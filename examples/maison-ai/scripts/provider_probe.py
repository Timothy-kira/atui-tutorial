"""Two bounded, synthetic tool-choice checks. Never logs credentials or content."""
import json,os,time
from pathlib import Path
import httpx
from dotenv import load_dotenv

ROOT=Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env')
report={'checks':[],'started':time.time()}
for choice in ('auto','required'):
    started=time.perf_counter()
    entry={'tool_choice':choice}
    try:
        key=os.environ['DOT_API_KEY']
        response=httpx.post(os.environ.get('DOT_BASE_URL','https://note3-prev-api.askdiandian.com/v1').rstrip('/')+'/chat/completions',
            headers={'api-key':key,'Authorization':'Bearer '+key},timeout=20,
            json={'model':os.environ.get('DOT_MODEL','dots3-note-prev'),
                  'messages':[{'role':'system','content':'Use the provided function for restaurant requests.'},{'role':'user','content':'Show vegetarian mains.'}],
                  'tools':[{'type':'function','function':{'name':'get_menu','description':'Read restaurant menu.','parameters':{'type':'object','properties':{'category':{'type':'string'},'vegetarian':{'type':'boolean'}},'required':['category','vegetarian']}}}],
                  'tool_choice':choice,'max_tokens':128,'temperature':0.3,'stream':False,'chat_template_kwargs':{'enable_thinking':False}})
        entry['http_status']=response.status_code
        if response.is_success:
            value=response.json();result=value.get('choices',[{}])[0]
            entry.update(finish=result.get('finish_reason'),tools=[c.get('function',{}).get('name') for c in result.get('message',{}).get('tool_calls',[])],tokens=value.get('usage',{}).get('completion_tokens'))
            entry['message_fields']={key:(len(item) if isinstance(item,(str,list)) else type(item).__name__) for key,item in result.get('message',{}).items()}
    except Exception as exc:entry['error_type']=type(exc).__name__
    entry['elapsed_ms']=round((time.perf_counter()-started)*1000)
    report['checks'].append(entry)
    (ROOT/'.local/provider-probe.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(entry),flush=True)
if not all(check.get('http_status')==200 and check.get('tools') for check in report['checks']):
    raise SystemExit('Provider transport check failed; inspect .local/provider-probe.json')
