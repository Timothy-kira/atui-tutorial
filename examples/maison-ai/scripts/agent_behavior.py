"""Real-model autonomy checks. Synthetic prompts; no credentials/reasoning logged."""
import json,re,time,uuid,sys
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
thread=str(uuid.uuid4());messages=[]
report={'status':'running','thread':thread,'started':time.time(),'cases':[]}
def save():
    (ROOT/'.local/agent-behavior-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
def run(name,prompt,check,*,fresh=False):
    global thread,messages
    if len(sys.argv)>2 and sys.argv[1]=='--case' and sys.argv[2]!=name:return
    if fresh:thread=str(uuid.uuid4());messages=[]
    messages.append({'id':str(uuid.uuid4()),'role':'user','content':prompt})
    payload={'threadId':thread,'runId':str(uuid.uuid4()),'messages':messages,'state':{},'tools':[],'context':[],'forwardedProps':{}}
    started=time.perf_counter();events=[];first_text=None
    with httpx.stream('POST','http://127.0.0.1:8008/agent',json=payload,timeout=120) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line.startswith('data:'):continue
            if line[5:].strip() in {'','[DONE]'}:continue
            event=json.loads(line[5:]);events.append(event)
            if event['type']=='TEXT_MESSAGE_CONTENT' and first_text is None:first_text=round((time.perf_counter()-started)*1000)
    text=''.join(e.get('delta','') for e in events if e['type']=='TEXT_MESSAGE_CONTENT')
    calls=[e['toolCallName'] for e in events if e['type']=='TOOL_CALL_START']
    results=[]
    for e in events:
        if e['type']=='TOOL_CALL_RESULT':
            try:results.append(json.loads(e['content']))
            except (TypeError,ValueError):pass
    entry={'name':name,'thread':thread,'prompt':prompt,'reply':text,'tools':calls,'ui_count':sum(len(r.get('a2ui_operations',[])) for r in results),'first_text_ms':first_text,'elapsed_ms':round((time.perf_counter()-started)*1000)}
    entry['ui_errors']=[result.get('issues',result['error']) for result in results if result.get('error')]
    render_ids={event['toolCallId'] for event in events if event['type']=='TOOL_CALL_START' and event['toolCallName']=='render_a2ui'}
    entry['render_arguments']=[''.join(event.get('delta','') for event in events if event['type']=='TOOL_CALL_ARGS' and event['toolCallId']==key) for key in render_ids]
    report['cases'].append(entry);save()
    assert not any(e['type']=='RUN_ERROR' for e in events),'Actual agent run failed'
    assert text and any(e['type']=='RUN_FINISHED' for e in events),'No completed authored reply'
    check(entry,results)
    entry['passed']=True;save();print(name+': PASS; tools='+','.join(calls)+'; first_text_ms='+str(first_text),flush=True)

def plain_chinese(entry,results):
    assert entry['ui_count']==0,'Unrequested UI was opened'
    assert len(re.findall(r'[\u4e00-\u9fff]',entry['reply']))>=10,'Response did not follow the user language'

if __name__=='__main__':
    save()
    try:
        deadline=time.time()+60
        while True:
            try:
                response=httpx.get('http://127.0.0.1:8008/health',timeout=2);response.raise_for_status();health=response.json();break
            except (httpx.HTTPError,ValueError):
                if time.time()>deadline:raise RuntimeError('Backend startup timeout')
                time.sleep(2)
        assert not health['mock'],'A real model is required'
        report['provider']=health['provider'];report['ui_mode']=health.get('ui_mode');save()
        def recommendation(entry,results):
            assert entry['ui_count']>0,'Natural recommendation request produced text without an actual interface'
            assert any(result.get('recommendation') or result.get('dishes') for result in results),'Interface had no actual menu/settings source'
            nodes=[node for result in results for operation in result.get('a2ui_operations',[]) for node in operation.get('updateComponents',{}).get('components',[])]
            assert any(node.get('component') in {'Field','RecommendationFilters','DishImage','DishFacts','DataTable'} for node in nodes),'Only an error/notice was shown, not useful dining UI'
            settings=next((r['recommendation'] for r in results if 'recommendation' in r),None)
            if settings:assert not settings.get('candidates'),'Candidates appeared before the guest submitted preferences'
        run('natural_recommendation','Recommend dinner for two',recommendation,fresh=True)
        def budget_ui(entry,results):
            assert entry['ui_count']>0,'Budget request produced no actual interface'
            assert any(result.get('recommendation') or result.get('dishes') for result in results),'Interface was not grounded in actual business records'
            # A dynamic Agent may choose a preference form or an editable menu.
            # Do not require a predetermined function/page for this broad task.
            if any(result.get('recommendation') for result in results):
                assert not next(result['recommendation'] for result in results if result.get('recommendation')).get('candidates'),'Candidates appeared before preference submission'
        run('natural_budget_recommendation','Build a meal under S$60',budget_ui,fresh=True)
        def capabilities(entry,results):
            plain_chinese(entry,results)
            assert not entry['tools'],'A capability question was forced into business tools'
            assert sum(word in entry['reply'] for word in ['菜单','推荐','食材','过敏','热量','订单','点餐'])>=2,'Capability answer was off-topic'
        run('capabilities','你可以做什么',capabilities,fresh=True)
        def clarify(entry,results):
            plain_chinese(entry,results)
            assert entry['reply'].count('？')+entry['reply'].count('?')>=2,'Did not ask the requested two questions'
        run('clarify_without_ui','先别给我推荐菜，也不要打开卡片。请先问我两个问题，了解我想吃什么。',clarify)
        def menu(entry,results):
            assert entry['ui_count']>0 and 'get_menu' in entry['tools'],'Requested real menu cards did not appear'
            dishes=next(r['dishes'] for r in results if 'dishes' in r)
            assert dishes and all(d['vegetarian'] and d['category']=='main' for d in dishes),'Menu ignored the requested constraints'
        run('requested_menu_ui','现在请用卡片给我看素食主菜。',menu)
        def calorie_policy(entry,results):
            plain_chinese(entry,results)
            assert any(phrase in entry['reply'] for phrase in ['不会','不影响','不改变','不调整','不包含','不参与','不计入','没有']),'Answer contradicted the actual base-recipe calorie policy'
        run('general_reasoning_without_ui','不用卡片，说明每份菜和整单热量的区别；这个演示里去掉酱汁会改变工具算出的热量吗？',calorie_policy)
        report.update(status='complete',finished=time.time());save()
    except Exception as exc:
        report.update(status='failed',error_type=type(exc).__name__,reason=str(exc)[:220] if isinstance(exc,AssertionError) else 'See local backend logs.',finished=time.time());save()
        raise SystemExit('Agent behavior check failed: '+report['reason'])
