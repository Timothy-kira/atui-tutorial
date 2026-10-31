"""Bounded synthetic transport probes. No credentials or hidden reasoning saved."""
import asyncio,json,os,time,uuid,sys
from pathlib import Path
import httpx
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
load_dotenv(ROOT/'.env')
REPORT=ROOT/'.local/dot-diagnostics.json'
report={'started':time.time(),'status':'running','cases':[]}
def save():REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

async def main():
    from google.adk.tools import FunctionTool
    from backend.agent import INSTRUCTION,DYNAMIC_INSTRUCTION,UI_ONLY_TOOLS
    from backend.tools import BUSINESS_TOOLS
    from backend.config import make_model
    from backend.interface_tool import GenerateInterfaceTool,catalog_instructions,parse_argument
    from google.genai import types
    from google.adk.models.llm_request import LlmRequest
    from google.adk.models.lite_llm import LiteLLMClient
    model=make_model()
    declarations=[FunctionTool(fn)._get_declaration() for fn in BUSINESS_TOOLS if fn.__name__ not in UI_ONLY_TOOLS]+[GenerateInterfaceTool(model)._get_declaration()]
    tool_specs=[{'type':'function','function':{'name':fn.name,'description':fn.description,'parameters':fn.parameters_json_schema or (fn.parameters.model_dump(exclude_none=True) if fn.parameters else {'type':'object','properties':{}})}} for fn in declarations]
    # Convert Google's schema type enum values to ordinary JSON types.
    def lower(value):
        if isinstance(value,dict):return {key:(str(item).lower() if key=='type' and isinstance(item,str) else lower(item)) for key,item in value.items()}
        if isinstance(value,list):return [lower(item) for item in value]
        return value
    tool_specs=lower(json.loads(json.dumps(tool_specs,default=str)))
    headers={'api-key':os.environ['DOT_API_KEY'],'Authorization':'Bearer '+os.environ['DOT_API_KEY']}
    base=os.environ.get('DOT_BASE_URL','https://note3-prev-api.askdiandian.com/v1').rstrip('/')+'/chat/completions'
    base_payload={'model':os.environ.get('DOT_MODEL','dots3-note-prev'),'temperature':0,'chat_template_kwargs':{'enable_thinking':False}}
    async with httpx.AsyncClient(timeout=30) as client:
        for style,system in [('current',INSTRUCTION+DYNAMIC_INSTRUCTION),('concise','You are a restaurant Agent. Answer ordinary chat normally. Use actual business tools for facts. For a requested interface, set render_ui=true. Never say a UI is displayed without successful tool output. Do not ask a text questionnaire when recommend_dishes can collect editable preferences.')]:
            for stream in (False,True):
                entry={'name':style+('_stream' if stream else '_batch'),'started':time.time()};started=time.perf_counter()
                payload={**base_payload,'messages':[{'role':'system','content':system},{'role':'user','content':'Recommend dinner for two'}],'tools':tool_specs,'tool_choice':'auto','parallel_tool_calls':False,'max_tokens':256,'stream':stream}
                try:
                    calls={};text=[];finish=None
                    async with client.stream('POST',base,headers=headers,json=payload) as response:
                        entry['http_status']=response.status_code;response.raise_for_status()
                        if stream:
                            async for line in response.aiter_lines():
                                if not line.startswith('data:') or line[5:].strip() in {'','[DONE]'}:continue
                                chunk=json.loads(line[5:]);choice=(chunk.get('choices') or [{}])[0];delta=choice.get('delta') or {}
                                if delta.get('content'):text.append(delta['content'])
                                for call in delta.get('tool_calls') or []:
                                    item=calls.setdefault(call.get('index',0),{'name':'','arguments':''});fn=call.get('function') or {}
                                    item['name']+=fn.get('name') or '';item['arguments']+=fn.get('arguments') or ''
                                finish=choice.get('finish_reason') or finish
                        else:
                            value=json.loads(await response.aread());choice=(value.get('choices') or [{}])[0];message=choice.get('message') or {};finish=choice.get('finish_reason')
                            text=[message.get('content') or ''];calls={n:{'name':call['function']['name'],'arguments':call['function']['arguments']} for n,call in enumerate(message.get('tool_calls') or [])}
                    entry.update(tools=list(calls.values()),visible_text=''.join(text)[:500],finish=finish)
                except Exception as exc:entry['error_type']=type(exc).__name__
                entry['elapsed_ms']=round((time.perf_counter()-started)*1000);report['cases'].append(entry);save();print(entry['name']+' finished',flush=True)
        entry={'name':'sdk_recommendation'};started=time.perf_counter()
        original=LiteLLMClient.acompletion
        async def tapped_root(self,*args,**kwargs):
            entry['wire_options']={key:kwargs.get(key) for key in ('stream','max_tokens','max_completion_tokens','tool_choice','response_format')}
            entry['wire_messages']=kwargs.get('messages')
            return await original(self,*args,**kwargs)
        LiteLLMClient.acompletion=tapped_root
        try:
            request=LlmRequest(contents=[types.Content(role='user',parts=[types.Part(text='Recommend dinner for two')])],config=types.GenerateContentConfig(system_instruction=INSTRUCTION+DYNAMIC_INSTRUCTION,tools=[types.Tool(function_declarations=declarations)],temperature=0,max_output_tokens=1024,tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode='AUTO'))))
            async with asyncio.timeout(30):
                async for result in model.generate_content_async(request,stream=True):
                    if not result.partial and result.content:
                        entry['tools']=[{'name':part.function_call.name,'arguments':part.function_call.args} for part in result.content.parts or [] if part.function_call]
                        entry['visible_text']=''.join(part.text for part in result.content.parts or [] if part.text and not part.thought)[:500]
        except Exception as exc:entry['error_type']=type(exc).__name__
        finally:LiteLLMClient.acompletion=original
        entry['elapsed_ms']=round((time.perf_counter()-started)*1000);report['cases'].append(entry);save();print(entry['name']+' finished',flush=True)
        prompt='Compose two compact interactive dish cards for actual dishes risotto (Truffle Mushroom Risotto) and cauliflower (Roasted Cauliflower). Each needs a photo, price badge, quantity control and add_to_cart action with exact dish_id. Root id root. Return ONLY {"components":[...],"data":{}}. Flat component props; Row/Column children are string IDs; Card child is a Column ID and footerChildren are quantity/button IDs.\nCatalog:\n'+catalog_instructions()
        for mode in ('raw_json','sdk_json'):
            entry={'name':mode};started=time.perf_counter();chunks=[]
            try:
                if mode=='raw_json':
                    response=await client.post(base,headers=headers,json={**base_payload,'messages':[{'role':'user','content':prompt}],'response_format':{'type':'json_object'},'max_tokens':2048,'stream':False});response.raise_for_status()
                    value=response.json();choice=value['choices'][0];entry['finish']=choice['finish_reason'];chunks=[choice['message'].get('content') or '']
                else:
                    original=LiteLLMClient.acompletion
                    async def tapped(self,*args,**kwargs):
                        entry['wire_options']={key:kwargs.get(key) for key in ('stream','max_tokens','max_completion_tokens','tool_choice','response_format')}
                        return await original(self,*args,**kwargs)
                    LiteLLMClient.acompletion=tapped
                    try:
                        request=LlmRequest(contents=[types.Content(role='user',parts=[types.Part(text=prompt)])],config=types.GenerateContentConfig(temperature=0,max_output_tokens=2048,response_mime_type='application/json'))
                        async with asyncio.timeout(35):
                            async for result in model.generate_content_async(request,stream=False):
                                if result.content:chunks.extend(part.text for part in result.content.parts or [] if part.text and not part.thought)
                    finally:LiteLLMClient.acompletion=original
                document=parse_argument(''.join(chunks),'dict');entry['document']=document
                entry['component_count']=len(document.get('components',[]))
            except Exception as exc:entry['error_type']=type(exc).__name__
            entry['elapsed_ms']=round((time.perf_counter()-started)*1000);report['cases'].append(entry);save();print(mode+' finished',flush=True)
    report.update(status='complete',finished=time.time());save()

if __name__=='__main__':
    save()
    try:asyncio.run(main())
    except Exception as exc:
        report.update(status='failed',error_type=type(exc).__name__,setup_detail=str(exc)[:180] if isinstance(exc,(AttributeError,ModuleNotFoundError)) else None,finished=time.time());save();raise SystemExit('Diagnostic setup failed; inspect local report.')
