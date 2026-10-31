from types import SimpleNamespace
import json,uuid
import pytest
from backend.store import MENU

def request(text):
    return {'threadId':str(uuid.uuid4()),'runId':str(uuid.uuid4()),'messages':[{'id':'question','role':'user','content':text}],'state':{},'tools':[],'context':[],'forwardedProps':{}}

def runtime(monkeypatch,model,tools):
    from google.adk.agents import LlmAgent
    from google.adk.apps import App
    from ag_ui_adk import ADKAgent
    from backend import agent,app as app_module
    monkeypatch.setattr(agent,'PROVIDER','dot')
    monkeypatch.setattr(agent,'UI_MODE','fixed')
    root=LlmAgent(name='autonomous_test',model=model,tools=tools,before_model_callback=agent.prepare_response,after_tool_callback=agent.finish_surface)
    monkeypatch.setattr(app_module,'agent',ADKAgent.from_app(App(name='autonomous_test',root_agent=root),user_id='test',use_thread_id_as_session_id=True))

def test_natural_turn_is_free_to_answer_without_tools(monkeypatch):
    from backend import agent
    from google.adk.models.llm_request import LlmRequest
    from google.genai import types
    monkeypatch.setattr(agent,'PROVIDER','dot')
    value=LlmRequest(contents=[types.Content(role='user',parts=[types.Part(text='你可以做什么？')])],config=types.GenerateContentConfig())
    assert agent.prepare_response(SimpleNamespace(state={},invocation_id='new'),value) is None
    assert value.config.tool_config.function_calling_config.mode=='AUTO'
    assert value.contents[0].parts[0].text=='你可以做什么？'

@pytest.mark.asyncio
async def test_surface_hook_does_not_choose_or_write_the_answer(monkeypatch):
    from backend import agent
    from backend.tools import get_menu
    monkeypatch.setattr(agent,'PROVIDER','dot');monkeypatch.setattr(agent,'UI_MODE','fixed')
    context=SimpleNamespace(state={},actions=SimpleNamespace(skip_summarization=True))
    result=get_menu('main',['vegetarian'])
    rendered=await agent.finish_surface(SimpleNamespace(name='get_menu'),{},context,result)
    assert rendered['dishes']==result['dishes'] and rendered['a2ui_operations']
    assert 'assistant_message' not in rendered and '_response_message' not in context.state
    assert context.actions.skip_summarization is False

def test_model_authors_the_response_after_actual_tool_result(client,monkeypatch):
    from google.adk.models.base_llm import BaseLlm
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types
    from backend.tools import get_menu
    calls=[]
    class AutonomousModel(BaseLlm):
        async def generate_content_async(self,llm_request,stream=False):
            calls.append(1)
            if len(calls)==1:
                part=types.Part(function_call=types.FunctionCall(id='read-menu',name='get_menu',args={'category':'main','dietary_preferences':['vegetarian']}))
            else:
                facts=[p.function_response.response for c in llm_request.contents for p in c.parts or [] if p.function_response]
                assert facts and facts[-1]['dishes']
                assert 'a2ui_operations' not in facts[-1]
                part=types.Part(text='这两道主菜都符合素食要求。你更想吃米饭，还是蔬菜？')
            yield LlmResponse(content=types.Content(role='model',parts=[part]),partial=False)
    runtime(monkeypatch,AutonomousModel(model='test-autonomous'),[get_menu])
    response=client.post('/agent',json=request('想看看素食主菜。'))
    events=[json.loads(line[5:]) for line in response.text.splitlines() if line.startswith('data:')]
    assert not any(e['type']=='RUN_ERROR' for e in events)
    assert [e['toolCallName'] for e in events if e['type']=='TOOL_CALL_START']==['get_menu']
    assert any(e['type']=='TOOL_CALL_RESULT' and json.loads(e['content']).get('a2ui_operations') for e in events)
    text=''.join(e['delta'] for e in events if e['type']=='TEXT_MESSAGE_CONTENT')
    assert text=='这两道主菜都符合素食要求。你更想吃米饭，还是蔬菜？' and len(calls)==2

def test_capability_answer_crosses_adk_without_menu_or_cards(client,monkeypatch):
    from google.adk.models.base_llm import BaseLlm
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types
    from backend.tools import get_menu
    class DirectModel(BaseLlm):
        async def generate_content_async(self,llm_request,stream=False):
            yield LlmResponse(content=types.Content(role='model',parts=[types.Part(text='我可以帮你浏览菜单、按预算推荐、解释食材和过敏原，也能协助你检查取餐订单。')]),partial=False)
    runtime(monkeypatch,DirectModel(model='test-direct'),[get_menu])
    events=[json.loads(line[5:]) for line in client.post('/agent',json=request('你可以做什么？')).text.splitlines() if line.startswith('data:')]
    assert not any(e['type'] in {'RUN_ERROR','TOOL_CALL_START','TOOL_CALL_RESULT'} for e in events)
    assert any(e['type']=='TEXT_MESSAGE_CONTENT' and '我可以' in e['delta'] for e in events)

def test_context_preserves_tool_facts_and_only_removes_ui_transport(monkeypatch):
    from backend import agent
    from google.adk.models.llm_request import LlmRequest
    from google.genai import types
    monkeypatch.setattr(agent,'PROVIDER','dot')
    facts={'dishes':[{'id':'chicken','price':28}],'a2ui_operations':[{'huge':'tree'}],'assistant_message':'a canned answer'}
    original=types.Content(role='user',parts=[types.Part(function_response=types.FunctionResponse(name='get_menu',response=facts))])
    value=LlmRequest(contents=[original],config=types.GenerateContentConfig())
    assert agent.prepare_response(SimpleNamespace(state={},invocation_id='new'),value) is None
    actual=value.contents[0].parts[0].function_response.response
    assert actual=={'dishes':[{'id':'chicken','price':28}]}
    assert 'a2ui_operations' in original.parts[0].function_response.response

def test_serialized_tool_history_retains_facts_without_ui_or_canned_answers():
    from backend.agent import tool_facts
    original={'result':json.dumps({'cart':{'count':1,'total_cents':1400},'a2ui_operations':[{'large':'tree'}],'assistant_message':'a canned promise'})}
    assert tool_facts(original)=={'result':{'cart':{'count':1,'total_cents':1400}}}
    assert isinstance(original['result'],str)
    assert tool_facts({'preparation':'Fresh lemon juice.'})=={'preparation':'Fresh lemon juice.'}

def test_dynamic_business_call_emits_real_ui_and_then_authored_text(client,monkeypatch):
    from backend import agent
    from backend.interface_tool import GenerateInterfaceTool
    from backend.tools import recommend_dishes
    from google.adk.models.base_llm import BaseLlm
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types
    calls=[]
    class Model(BaseLlm):
        async def generate_content_async(self,llm_request,stream=False):
            calls.append(llm_request.config.response_mime_type or 'conversation')
            if llm_request.config.response_mime_type=='application/json':
                part=types.Part(text=json.dumps({'components':[{'id':'root','component':'Form','action':'recommend_dishes','submitLabel':'Find dishes','children':['guests']},{'id':'guests','component':'Field','name':'party_size','label':'Guests','type':'number','value':{'path':'/recommendation/party_size'}}]}))
            elif len(calls)==1:
                wire=llm_request.model_dump_json()
                assert 'huge-catalog-sentinel' not in wire
                part=types.Part(function_call=types.FunctionCall(id='preferences',name='recommend_dishes',args={'party_size':2}))
            else:
                facts=[p.function_response.response for c in llm_request.contents for p in c.parts or [] if p.function_response]
                assert facts[-1]['ui_context']['displayed'] is True
                assert 'a2ui_operations' not in facts[-1]
                part=types.Part(text='请在表单中填写人数、预算与饮食偏好。')
            yield LlmResponse(content=types.Content(role='model',parts=[part]),partial=False)
    model=Model(model='test-dynamic-integration')
    runtime(monkeypatch,model,[recommend_dishes])
    monkeypatch.setattr(agent,'UI_MODE','dynamic');monkeypatch.setattr(agent,'interface_tool',GenerateInterfaceTool(model))
    from backend import app as app_module
    original=app_module.agent;received=[]
    class CapturedAgent:
        async def run(self,input):
            received.append(input)
            async for event in original.run(input):yield event
    monkeypatch.setattr(app_module,'agent',CapturedAgent())
    payload=request('Recommend dinner for two')
    payload['context']=[{'description':'A2UI Component Schema','value':'huge-catalog-sentinel'},{'description':'Guest context','value':'Synthetic local context'}]
    response=client.post('/agent',json=payload)
    events=[json.loads(line[5:]) for line in response.text.splitlines() if line.startswith('data:')]
    assert not any(e['type']=='RUN_ERROR' for e in events),events
    results=[json.loads(e['content']) for e in events if e['type']=='TOOL_CALL_RESULT']
    assert len(received[0].context)==1 and received[0].context[0].value=='Synthetic local context'
    assert len(results)==1 and results[0]['recommendation'] and results[0]['ui_context']['agent_composed']
    assert len(results[0]['a2ui_operations'])==3
    assert calls==['conversation','application/json','conversation']
    assert ''.join(e['delta'] for e in events if e['type']=='TEXT_MESSAGE_CONTENT')=='请在表单中填写人数、预算与饮食偏好。'
