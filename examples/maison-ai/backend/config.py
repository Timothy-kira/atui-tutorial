import os
from contextvars import ContextVar
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
PROVIDER = os.getenv('MODEL_PROVIDER','gemini').lower()
CATALOG_ID = 'copilotkit://maison-restaurant'
PROTOCOL_VERSION = 'v0.9'
UI_MODE=os.getenv('MAISON_UI_MODE','dynamic').lower()
if UI_MODE not in {'fixed','dynamic'}:raise RuntimeError('MAISON_UI_MODE must be fixed or dynamic')
# Dynamic-mode generation has distinct first-token and inter-chunk budgets.
# Fixed mode avoids a layout subagent. Conversation and function calls still
# stream normally, and the agent may make several model/tool steps.
FIRST_TOKEN_TIMEOUT=float(os.getenv('MAISON_FIRST_TOKEN_TIMEOUT','75'))
STREAM_IDLE_TIMEOUT=float(os.getenv('MAISON_STREAM_IDLE_TIMEOUT','25'))
MODEL_TIMEOUT=float(os.getenv('MAISON_MODEL_TIMEOUT','120'))
# Allow authored answers as well as function arguments; experimental free-form
# layout generation gets a larger output allowance.
MAX_OUTPUT_TOKENS=int(os.getenv('MAISON_MAX_OUTPUT_TOKENS','1024' if UI_MODE=='fixed' else '4096'))
JSON_OUTPUT=ContextVar('maison_json_output',default=False)

def make_model():
    if PROVIDER == 'mock':
        from .mock_model import WorkshopModel
        return WorkshopModel()
    if PROVIDER == 'gemini':
        if not os.getenv('GOOGLE_API_KEY'): raise RuntimeError('GOOGLE_API_KEY is required for Gemini mode')
        return os.getenv('GEMINI_MODEL','gemini-3.8-flash')
    if PROVIDER != 'dot': raise RuntimeError('MODEL_PROVIDER must be dot, gemini or mock')
    key = os.getenv('DOT_API_KEY')
    if not key: raise RuntimeError('DOT_API_KEY is required for DOT mode')
    from google.adk.models.lite_llm import LiteLlm, LiteLLMClient
    class StreamingClient(LiteLLMClient):
        async def acompletion(self, *args, **kwargs):
            # LiteLLM forwards constructor and per-request limits separately.
            # Keep the ADK request's limit when present; never send both names.
            if kwargs.get('max_completion_tokens') is not None:kwargs.pop('max_tokens',None)
            if kwargs.get('tools'):
                kwargs['parallel_tool_calls']=False
                if kwargs.get('tool_choice') is None:kwargs['tool_choice']='auto'
            elif JSON_OUTPUT.get():
                kwargs['response_format']={'type':'json_object'}
            if UI_MODE=='dynamic' and kwargs.get('tool_choice')=='required' and len(kwargs.get('tools') or [])==1:
                kwargs['tool_choice']={'type':'function','function':{'name':kwargs['tools'][0]['function']['name']}}
            response = await super().acompletion(*args, **kwargs)
            if not kwargs.get('stream'):
                return response
            async def chunks():
                import asyncio
                names = {}
                source=response.__aiter__()
                budget=FIRST_TOKEN_TIMEOUT
                # Some compatible providers buffer structured tool arguments.
                # Keep a bounded layout budget distinct from chat idle time.
                layout=any(t.get('function',{}).get('name')=='render_a2ui' for t in kwargs.get('tools') or [] if isinstance(t,dict))
                idle_budget=max(FIRST_TOKEN_TIMEOUT,STREAM_IDLE_TIMEOUT) if layout else STREAM_IDLE_TIMEOUT
                try:
                    while True:
                        try:
                            async with asyncio.timeout(budget):chunk=await source.__anext__()
                        except StopAsyncIteration:break
                        choices = getattr(chunk, 'choices', None) or []
                        if choices:
                            delta = getattr(choices[0], 'delta', None)
                            if getattr(delta,'content',None):budget=idle_budget
                            for call in getattr(delta, 'tool_calls', None) or []:
                                index = getattr(call, 'index', 0) or 0
                                function = getattr(call, 'function', None)
                                if function is None:
                                    continue
                                name = getattr(function, 'name', None)
                                if name and name != names.get(index):
                                    names[index] = names.get(index, '') + name
                                arguments = getattr(function, 'arguments', None)
                                if isinstance(arguments,str) and arguments:budget=idle_budget
                        yield chunk  # Original text/usage/finish chunks stay intact.
                finally:
                    close = getattr(response, 'aclose', None)
                    if close is not None:
                        await close()
            return chunks()
    class DotLlm(LiteLlm):
        async def generate_content_async(self,llm_request,stream=False):
            token=JSON_OUTPUT.set(llm_request.config.response_mime_type=='application/json')
            try:
                async for response in self._generate(llm_request,stream):yield response
            finally:JSON_OUTPUT.reset(token)

        async def _generate(self,llm_request,stream=False):
            import asyncio,logging,time
            logger=logging.getLogger('uvicorn.error')
            # A failed request is not silently replaced with another decision.
            # Dynamic mode retains one bounded retry before any partial output.
            for attempt in ((1,) if UI_MODE=='fixed' else (1,2)):
                started=time.perf_counter();chunks=0;text_chunks=0;partials=0;final=None
                request=llm_request.model_copy()
                request.config=llm_request.config.model_copy(deep=True)
                logger.info('maison_model attempt=%d tools=%s mode=%s payload_chars=%d',attempt,[fn.name for t in request.config.tools or [] for fn in t.function_declarations or []],getattr(getattr(request.config.tool_config,'function_calling_config',None),'mode',None),len(request.model_dump_json()))
                # The ADK A2UI factory declares stringified JSON for Gemini. DOT
                # supports native OpenAI function-argument arrays/objects instead.
                for tool in request.config.tools or []:
                    for fn in tool.function_declarations or []:
                        if fn.name=='render_a2ui' and fn.parameters_json_schema is None:
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
                actual_stream=stream
                pending=super().generate_content_async(request,stream=actual_stream).__aiter__()
                # Raw wire chunks above enforce first-token and idle budgets.
                # ADK may buffer tool arguments until they form valid JSON;
                # absence of an ADK response is not absence of network progress.
                budget=MODEL_TIMEOUT
                while True:
                    try:
                        async with asyncio.timeout(budget):
                            response=await pending.__anext__()
                    except StopAsyncIteration:
                        break
                    except TimeoutError:
                        logger.error('maison_model attempt=%d timeout_ms=%d budget_ms=%d chunks=%d stage=%s',attempt,round((time.perf_counter()-started)*1000),round(budget*1000),chunks,'first_token' if not chunks else 'idle')
                        raise
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
                    # An empty truncated response must not look like a clean
                    # completed turn to ADK / AG-UI. Retry only before output;
                    # otherwise propagate an actual failure to the browser.
                    if not response.partial and 'MAX_TOKENS' in str(response.error_code or ''):
                        continue
                    yield response
                logger.info('maison_model complete_ms=%d chunks=%d text_deltas=%d attempt=%d',round((time.perf_counter()-started)*1000),chunks,text_chunks,attempt)
                if UI_MODE=='dynamic' and attempt==1 and not partials and final is not None and 'MAX_TOKENS' in str(final.error_code or ''):
                    # Nothing was streamed and the turn died on the ceiling: the
                    # degenerate loop. A retry is safe because no output escaped.
                    logger.warning('maison_model degenerate_turn retrying attempt=2 tokens=%s',getattr(final.usage_metadata,'candidates_token_count',None))
                    continue
                if final is not None and 'MAX_TOKENS' in str(final.error_code or ''):
                    raise RuntimeError('The provider exhausted its output limit before completing the response.')
                if not chunks:
                    raise RuntimeError('The provider returned an empty response.')
                return
    # DOT uses an api-key header, unlike the default OpenAI Bearer-only path.
    # timeout must outlast STREAM_IDLE_TIMEOUT, otherwise a stalled-but-open
    # stream is killed by the HTTP client before the stall itself is detected.
    return DotLlm(model='openai/'+os.getenv('DOT_MODEL','dots3-note-prev'),llm_client=StreamingClient(),
        api_base=os.getenv('DOT_BASE_URL','https://note3-prev-api.askdiandian.com/v1').rstrip('/'),
        api_key=key, extra_headers={'api-key':key},
        extra_body={'chat_template_kwargs':{'enable_thinking':False}},
        timeout=20 if UI_MODE=='fixed' else 120, num_retries=0 if UI_MODE=='fixed' else 1, max_tokens=MAX_OUTPUT_TOKENS)

