"""Opt-in live-provider flow. No keys or provider reasoning are written to logs."""
import json,time,uuid
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
SID=str(uuid.uuid4());messages=[];report={'status':'running','thread':SID,'started':time.time(),'steps':[]}
CATALOG=(ROOT/'.local/catalog.json').read_text(encoding='utf-8')
SCHEMA_DESCRIPTION='A2UI Component Schema — available components for generating UI surfaces. Use these component names and properties when creating A2UI operations.'
def persist(): (ROOT/'.local/live-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
def run(text):
    messages.append(dict(id=str(uuid.uuid4()),role='user',content=text))
    payload=dict(threadId=SID,runId=str(uuid.uuid4()),state={},messages=messages,tools=[],context=[{'description':SCHEMA_DESCRIPTION,'value':CATALOG}],forwardedProps={})
    events=[]
    with httpx.stream('POST','http://127.0.0.1:8008/agent',json=payload,timeout=210) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.startswith('data:'):
                event=json.loads(line[5:]);events.append(event)
                if event['type']=='TOOL_CALL_START':print('ADK tool:',event['toolCallName'],flush=True)
    errors=[e for e in events if e['type']=='RUN_ERROR']
    results=[];calls=[]
    for e in events:
        if e['type']=='TOOL_CALL_START':calls.append(e['toolCallName'])
        if e['type']=='TOOL_CALL_RESULT':
            try:results.append(json.loads(e['content']))
            except (TypeError,ValueError):pass
    report['last_tool_results']=results
    report['render_args']=[e.get('delta') for e in events if e['type']=='TOOL_CALL_ARGS' and str(e.get('toolCallId','')).startswith('a2ui-render')]
    report['steps'].append(dict(tool_calls=calls,operation_count=sum(len(r.get('a2ui_operations',[])) for r in results)));persist()
    if errors:
        import re
        report['agent_errors']=[re.sub(r'(?:ak_|sk-)[A-Za-z0-9_-]+','[REDACTED]',str(e.get('message','')))[:300] for e in errors];persist()
        raise RuntimeError('Agent returned RUN_ERROR')
    print('Completed phase; tools:',','.join(calls),flush=True)
    return results,calls

if __name__=='__main__':
    persist()
    try:
        deadline=time.time()+90
        while True:
            try:health=httpx.get('http://127.0.0.1:8008/health',timeout=2).json();break
            except httpx.HTTPError:
                if time.time()>deadline:raise RuntimeError('Backend startup timeout')
                time.sleep(2)
        if health['mock']:raise RuntimeError('Live verification requires DOT or Gemini mode')
        report['provider']=health['provider'];persist()
        results,calls=run('Show two vegetarian dinner dishes using generate_a2ui. Read get_menu first. Use a new composed surface with dish photos, PriceBadge, descriptions and Add to cart buttons.')
        assert 'get_menu' in calls and 'generate_a2ui' in calls,'Missing real ADK/A2UI tools'
        ops=next(r['a2ui_operations'] for r in results if r.get('a2ui_operations'))
        (ROOT/'.local/live-operations.json').write_text(json.dumps(ops,indent=2),encoding='utf-8')
        assert any(op.get('updateComponents',{}).get('components') for op in ops),'No component tree'
        action=lambda name,context:json.dumps({'a2uiAction':{'name':name,'context':context}})
        run(action('add_to_cart',{'dish_id':'tiramisu','quantity':2,'options':{}}))
        cart=httpx.get('http://127.0.0.1:8008/cart/'+SID).json();assert cart['total_cents']==2400
        results,_=run(action('checkout',{}));quote=next(r['quote'] for r in results if 'quote' in r)
        assert httpx.get('http://127.0.0.1:8008/orders/'+SID).json()==[]
        run(action('confirm_order',{k:quote[k] for k in ['confirmation_token','idempotency_key']}))
        orders=httpx.get('http://127.0.0.1:8008/orders/'+SID).json();assert len(orders)==1
        report.update(status='complete',order_id=orders[0]['order_id'],finished=time.time());persist();print('Live provider → ADK → AG-UI → A2UI → cart → confirmed demo order: PASS',flush=True)
    except Exception as e:
        report.update(status='failed',error_type=type(e).__name__,reason=str(e)[:160] if isinstance(e,AssertionError) else 'See backend/provider logs; no credentials are included in this report.',finished=time.time());persist();raise SystemExit('Live flow failed: '+type(e).__name__)
