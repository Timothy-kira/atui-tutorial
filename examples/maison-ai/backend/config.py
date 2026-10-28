import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
PROVIDER = os.getenv('MODEL_PROVIDER','mock').lower()
CATALOG_ID = 'copilotkit://maison-restaurant'
PROTOCOL_VERSION = 'v0.9'
# DOT regularly needs well over a minute for its first token, and the A2UI
# composition sub-agent streams a large JSON document. A single total budget
# cut healthy runs off mid-stream, so first-token latency and inter-chunk
# stalls are bounded separately instead.
FIRST_TOKEN_TIMEOUT=float(os.getenv('MAISON_FIRST_TOKEN_TIMEOUT','75'))
STREAM_IDLE_TIMEOUT=float(os.getenv('MAISON_STREAM_IDLE_TIMEOUT','25'))
MODEL_TIMEOUT=float(os.getenv('MAISON_MODEL_TIMEOUT','120'))
# Upper bound for one model call. This endpoint reached the previous 8192
# ceiling on a single turn and returned nothing usable after a minute, so the
# ceiling now bounds runaway generation instead of licensing it.
MAX_OUTPUT_TOKENS=int(os.getenv('MAISON_MAX_OUTPUT_TOKENS','2048'))

def make_model():
    if PROVIDER == 'mock':
        from .mock_model import WorkshopModel
        return WorkshopModel()
    if PROVIDER == 'gemini':
        if not os.getenv('GOOGLE_API_KEY'): raise RuntimeError('GOOGLE_API_KEY is required for Gemini mode')
        return os.getenv('GEMINI_MODEL','gemini-2.5-flash')
    if PROVIDER != 'dot': raise RuntimeError('MODEL_PROVIDER must be dot, gemini or mock')
    key = os.getenv('DOT_API_KEY')
    if not key: raise RuntimeError('DOT_API_KEY is required for DOT mode')
    from google.adk.models.lite_llm import LiteLlm, LiteLLMClient
    class StreamingClient(LiteLLMClient):
        async def acompletion(self, *args, **kwargs):
            from .streaming_a2ui import argument_observer
            observer = argument_observer.get()
            if kwargs.get('tool_choice')=='required' and len(kwargs.get('tools') or [])==1:
                kwargs['tool_choice']={'type':'function','function':{'name':kwargs['tools'][0]['function']['name']}}
            response = await super().acompletion(*args, **kwargs)
            if not kwargs.get('stream') or observer is None:
                return response
            async def chunks():
                names = {}
                try:
                    async for chunk in response:
                        choices = getattr(chunk, 'choices', None) or []
                        if choices:
                            delta = getattr(choices[0], 'delta', None)
                            for call in getattr(delta, 'tool_calls', None) or []:
                                index = getattr(call, 'index', 0) or 0
                                function = getattr(call, 'function', None)
                                if function is None:
                                    continue
                                name = getattr(function, 'name', None)
                                if name and name != names.get(index):
                                    names[index] = names.get(index, '') + name
                                arguments = getattr(function, 'arguments', None)
                                if names.get(index) == 'render_a2ui' and isinstance(arguments,str) and arguments:
                                    await observer(arguments)
                        yield chunk  # Original text/usage/finish chunks stay intact.
                finally:
                    close = getattr(response, 'aclose', None)
                    if close is not None:
                        await close()
            return chunks()
    class DotLlm(LiteLlm):
        async def generate_content_async(self,llm_request,stream=False):
            import asyncio,logging,time
            logger=logging.getLogger('uvicorn.error')
            # This preview model intermittently degenerates: it loops on repeated
            # tool calls until it burns the whole token ceiling and returns
            # nothing usable. Measured at this endpoint, that happens on roughly
            # half of all turns and the identical request succeeds moments later,
            # so one clean retry is worth more than the extra wait.
            for attempt in (1,2):
                started=time.perf_counter();chunks=0;text_chunks=0;partials=0;final=None
                request=llm_request.model_copy()
                request.config=llm_request.config.model_copy(deep=True)
                logger.info('maison_model attempt=%d tools=%s mode=%s payload_chars=%d',attempt,[fn.name for t in request.config.tools or [] for fn in t.function_declarations or []],getattr(getattr(request.config.tool_config,'function_calling_config',None),'mode',None),len(request.model_dump_json()))
                # The ADK A2UI factory declares stringified JSON for Gemini. DOT
                # supports native OpenAI function-argument arrays/objects instead.
                for tool in request.config.tools or []:
                    for fn in tool.function_declarations or []:
                        if fn.name=='render_a2ui':
                            fn.parameters=None
                            fn.parameters_json_schema={
                                'type':'object','properties':{
                                    'surfaceId':{'type':'string'},
                                    'components':{'type':'array','items':{'type':'object','properties':{'id':{'type':'string'},'component':{'type':'string'}},'required':['id','component'],'additionalProperties':True}},
                                    'data':{'type':'object','additionalProperties':True},
                                },'required':['surfaceId','components']}
                # Keep ADK's requested stream mode. Text becomes incremental Markdown
                # deltas; A2UI's structured subagent consumes the same stream.
                # Every await carries its own budget: the first token is allowed a
                # long wait, later chunks only have to keep arriving. One fixed
                # total deadline used to cancel healthy runs mid-stream.
                pending=super().generate_content_async(request,stream=stream).__aiter__()
                budget=FIRST_TOKEN_TIMEOUT if stream else MODEL_TIMEOUT
                while True:
                    try:
                        async with asyncio.timeout(budget):
                            response=await pending.__anext__()
                    except StopAsyncIteration:
                        break
                    except TimeoutError:
                        logger.error('maison_model attempt=%d timeout_ms=%d budget_ms=%d chunks=%d stage=%s',attempt,round((time.perf_counter()-started)*1000),round(budget*1000),chunks,'first_token' if not chunks else 'idle')
                        raise
                    budget=STREAM_IDLE_TIMEOUT if stream else MODEL_TIMEOUT
                    chunks+=1
                    if response.partial:partials+=1
                    if chunks==1:logger.info('maison_model first_chunk_ms=%d stream=%s attempt=%d',round((time.perf_counter()-started)*1000),stream,attempt)
                    if response.partial and response.content and any(part.text and not part.thought for part in response.content.parts or []):text_chunks+=1
                    if not response.partial:
                        final=response
                        usage=response.usage_metadata
                        logger.info('maison_model final_calls=%s error_code=%s tokens=%s/%s attempt=%d',[p.function_call.name for p in response.content.parts or [] if p.function_call] if response.content else [],response.error_code,
                            getattr(usage,'candidates_token_count',None),getattr(usage,'thoughts_token_count',None) or 0,attempt)
                    # Preserve partial deltas; only the consolidated final carries
                    # the terminal marker used by AG-UI to close the text stream.
                    if response.content and not response.partial and not any(part.function_call for part in response.content.parts or []):
                        response=response.model_copy(update={'turn_complete':True})
                    yield response
                logger.info('maison_model complete_ms=%d chunks=%d text_deltas=%d attempt=%d',round((time.perf_counter()-started)*1000),chunks,text_chunks,attempt)
                if attempt==1 and not partials and final is not None and 'MAX_TOKENS' in str(final.error_code or ''):
                    # Nothing was streamed and the turn died on the ceiling: the
                    # degenerate loop. A retry is safe because no output escaped.
                    logger.warning('maison_model degenerate_turn retrying attempt=2 tokens=%s',getattr(final.usage_metadata,'candidates_token_count',None))
                    continue
                return
    # DOT uses an api-key header, unlike the default OpenAI Bearer-only path.
    # timeout must outlast STREAM_IDLE_TIMEOUT, otherwise a stalled-but-open
    # stream is killed by the HTTP client before the stall itself is detected.
    return DotLlm(model='openai/'+os.getenv('DOT_MODEL','dots3-note-prev'),llm_client=StreamingClient(),
        api_base=os.getenv('DOT_BASE_URL','https://note3-prev-api.askdiandian.com/v1').rstrip('/'),
        api_key=key, extra_headers={'api-key':key},
        extra_body={'chat_template_kwargs':{'enable_thinking':False}},
        timeout=120, num_retries=1, max_tokens=MAX_OUTPUT_TOKENS)

