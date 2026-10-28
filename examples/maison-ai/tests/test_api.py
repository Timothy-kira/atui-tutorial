import json,uuid

def request(text,thread=None,tools=None):
    return dict(threadId=thread or str(uuid.uuid4()),runId=str(uuid.uuid4()),state={},messages=[dict(id=str(uuid.uuid4()),role='user',content=text)],tools=tools or [],context=[],forwardedProps={})

def run(client,body):
    r=client.post('/agent',json=body);assert r.status_code==200
    events=[json.loads(line[5:]) for line in r.text.splitlines() if line.startswith('data:')]
    assert not any(e['type']=='RUN_ERROR' for e in events),events
    return events

def results(events):return [json.loads(e['content']) for e in events if e['type']=='TOOL_CALL_RESULT']

def test_real_adk_tools_and_a2ui_protocol(client):
    events=run(client,request('Show vegetarian dishes'))
    calls=[e['toolCallName'] for e in events if e['type']=='TOOL_CALL_START']
    assert 'get_menu' in calls and 'mock_show_menu' in calls
    out=results(events);menu=next(v for v in out if 'dishes' in v)
    assert all(d['vegetarian'] for d in menu['dishes'])
    ops=next(v['a2ui_operations'] for v in out if 'a2ui_operations' in v)
    assert ops[0]['version']=='v0.9'
    assert ops[0]['createSurface']['catalogId']=='copilotkit://maison-restaurant'
    assert any(c['component']=='DishImage' for c in ops[1]['updateComponents']['components'])

def test_action_cart_checkout_confirm_round_trip(client):
    sid=str(uuid.uuid4())
    def act(name,context):return run(client,request(json.dumps({'a2uiAction':{'name':name,'context':context}}),sid))
    act('add_to_cart',{'dish_id':'tiramisu','quantity':2})
    assert client.get('/cart/'+sid).json()['total_cents']==2400
    out=results(act('checkout',{}));q=next(v['quote'] for v in out if 'quote' in v)
    assert client.get('/orders/'+sid).json()==[]
    ctx={k:q[k] for k in ['confirmation_token','idempotency_key']}
    act('confirm_order',ctx);act('confirm_order',ctx)
    assert len(client.get('/orders/'+sid).json())==1
    assert client.get('/cart/'+sid).json()['count']==0

def test_missing_doneness_invokes_frontend_hitl(client):
    tools=[dict(name='ask_user',description='Ask the user for a required choice',parameters={'type':'object','properties':{'question':{'type':'string'},'options':{'type':'array','items':{'type':'string'}}},'required':['question','options']})]
    first=request("I'd like a steak.",tools=tools);events=run(client,first)
    call=next(e for e in events if e['type']=='TOOL_CALL_START' and e['toolCallName']=='ask_user')
    args=''.join(e['delta'] for e in events if e['type']=='TOOL_CALL_ARGS' and e['toolCallId']==call['toolCallId'])
    assert 'medium-rare' in args
    resumed={**first,'runId':str(uuid.uuid4()),'messages':first['messages']+[
      dict(id=str(uuid.uuid4()),role='assistant',toolCalls=[dict(id=call['toolCallId'],type='function',function=dict(name='ask_user',arguments=args))]),
      dict(id=str(uuid.uuid4()),role='tool',toolCallId=call['toolCallId'],content=json.dumps({'selection':'medium-rare'}))]}
    out=results(run(client,resumed))
    ops=next(v['a2ui_operations'] for v in out if 'a2ui_operations' in v)
    selectors=[c for c in ops[1]['updateComponents']['components'] if c['component']=='DishOptionSelector' and c['option']=='doneness']
    assert selectors[0]['value']=='medium-rare'

def test_rejects_unknown_action(client):
    r=client.post('/agent',json=request(json.dumps({'a2uiAction':{'name':'execute_js','context':{}}})))
    assert r.status_code==400
