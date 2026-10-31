"""Replay the reported ambiguous reply and checkout using an isolated demo cart."""
import json,time,uuid
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
sid=str(uuid.uuid4());messages=[]
report={'status':'running','thread':sid,'started':time.time(),'history_fixture':'User-reported multi-option cart reply; current cart is created through the actual UI action tool.','steps':[]}
def save():(ROOT/'.local/checkout-regression-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
def run(text=None,action=None):
    if text:messages.append({'id':str(uuid.uuid4()),'role':'user','content':text})
    payload={'threadId':sid,'runId':str(uuid.uuid4()),'messages':messages,'state':{},'tools':[],'context':[],'forwardedProps':{'a2uiAction':action} if action else {}}
    events=[];started=time.perf_counter()
    with httpx.stream('POST','http://127.0.0.1:8008/agent',json=payload,timeout=120) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.startswith('data:') and line[5:].strip() not in {'','[DONE]'}:events.append(json.loads(line[5:]))
    results=[]
    for event in events:
        if event['type']=='TOOL_CALL_RESULT':
            try:results.append(json.loads(event['content']))
            except (TypeError,ValueError):pass
    entry={'input':text or action['name'],'tools':[event['toolCallName'] for event in events if event['type']=='TOOL_CALL_START'],'reply':''.join(event.get('delta','') for event in events if event['type']=='TEXT_MESSAGE_CONTENT'),'elapsed_ms':round((time.perf_counter()-started)*1000),'ui_operations':sum(len(result.get('a2ui_operations',[])) for result in results)}
    report['steps'].append(entry);save()
    assert not any(event['type']=='RUN_ERROR' for event in events),'Agent run failed'
    assert any(event['type']=='RUN_FINISHED' for event in events),'Run did not finish'
    print(entry['input']+': '+','.join(entry['tools']),flush=True)
    return entry,results

if __name__=='__main__':
    save()
    try:
        report['phase']='startup';save();deadline=time.time()+60
        while True:
            try:
                response=httpx.get('http://127.0.0.1:8008/health',timeout=2);response.raise_for_status();health=response.json();break
            except (httpx.HTTPError,ValueError):
                if time.time()>deadline:raise RuntimeError('Backend startup timeout')
                time.sleep(2)
        assert not health['mock'],'A real provider is required'
        report['provider']=health['provider'];save()
        report['phase']='seed_cart';save()
        run(action={'name':'add_to_cart','context':{'dish_id':'caesar','quantity':1}})
        cart=httpx.get('http://127.0.0.1:8008/cart/'+sid).json()
        assert cart['count']==1 and cart['total_cents']==1400
        messages.extend([{'id':str(uuid.uuid4()),'role':'user','content':'检查下目前添加了什么商品'},
                         {'id':str(uuid.uuid4()),'role':'assistant','content':'您目前的购物车有凯撒沙拉1份，SGD14，390kcal。需要我帮您添加其他菜品、调整数量，或者直接进入结算吗？'}])
        report['phase']='ambiguous_reply';save();ambiguous,_=run('需要')
        assert not any(tool in ambiguous['tools'] for tool in ['update_cart','quote_order','place_order']),'Ambiguous consent was interpreted as a specific operation'
        assert ambiguous['ui_operations']==0
        categories=sum(any(word in ambiguous['reply'] for word in words) for words in [('添加','加菜','加点','加什么'),('调整','修改'),('结算','结账','结帐')])
        assert categories>=2 or any(word in ambiguous['reply'] for word in ['哪一步','哪一项','哪种操作','具体想','具体需要']),'Clarification still assumed adding dishes'
        report['phase']='checkout';save();checkout,results=run('直接结算')
        assert 'quote_order' in checkout['tools'],'Only a verbal promise was produced; quote_order was not executed'
        result=next((result for result in results if result.get('quote')),None)
        assert result and result['quote']['total_cents']==1400 and checkout['ui_operations'],'No real quote and confirmation interface'
        nodes=[node for response in results for op in response.get('a2ui_operations',[]) for node in op.get('updateComponents',{}).get('components',[])]
        assert any(node.get('action',{}).get('name')=='confirm_order' for node in nodes),'Missing explicit confirmation button'
        assert httpx.get('http://127.0.0.1:8008/orders/'+sid).json()==[],'Checkout placed an order without a button confirmation'
        report['phase']='recoverable_error';save();failure,failed_results=run(action={'name':'add_to_cart','context':{'dish_id':'nonexistent-test-dish','quantity':1}})
        assert any(response.get('error') for response in failed_results),'Invalid item did not produce an actual business error'
        error_ui,error_results=run('把刚才的错误和下一步操作显示在界面中，不要改动购物车。')
        assert error_ui['ui_operations'] and any(response.get('ui_context',{}).get('agent_composed') for response in error_results),'The agent did not compose an error/correction interface'
        assert httpx.get('http://127.0.0.1:8008/cart/'+sid).json()['total_cents']==1400
        report.update(status='complete',finished=time.time(),quote_total_cents=1400,orders_submitted=0);save()
    except Exception as exc:
        report.update(status='failed',error_type=type(exc).__name__,reason=str(exc)[:220] if isinstance(exc,AssertionError) else 'Inspect local backend logs.',finished=time.time());save()
        raise SystemExit('Checkout regression failed: '+report['reason'])
