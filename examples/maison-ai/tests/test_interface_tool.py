import pytest
from types import SimpleNamespace
from backend.interface_tool import RenderInterfaceTool

@pytest.fixture
def context(store,monkeypatch):
    from backend import tools
    monkeypatch.setattr(tools,'store',store)
    return SimpleNamespace(state={'maison_thread':'dynamic-interface-test'},invocation_id='turn-1')

@pytest.mark.asyncio
async def test_agent_graph_is_transported_without_selecting_a_template(context):
    graph=[{'id':'root','component':'Column','children':['warning','comparison']},
        {'id':'warning','component':'Notice','severity':'warning','message':'Choose another available time.'},
        {'id':'comparison','component':'DataTable','columns':['Time','Seats'],'rows':[['18:00',4],['19:00',2]]}]
    result=await RenderInterfaceTool().run_async(args={'components':graph},tool_context=context)
    assert result['ui_context']['agent_composed']
    assert result['a2ui_operations'][1]['updateComponents']['components']==graph
    assert context.state['_a2ui_rendered_invocation']=='turn-1'

@pytest.mark.asyncio
async def test_invalid_graph_returns_repairable_issues_and_no_false_display(context):
    for graph in ([{'id':'root','component':'Column','children':['missing']}],
                  [{'id':'root','component':'Column','children':['root']}],
                  [{'id':'root','component':'Script','src':'javascript:alert(1)'}],
                  [{'id':'root','component':'CartTotal','totalCents':123456}],
                  [{'id':'root','component':'Button','label':'Confirm','action':{'name':'confirm_order','context':{'confirmation_token':'invented','idempotency_key':'fake'}}}]):
        result=await RenderInterfaceTool().run_async(args={'components':graph},tool_context=context)
        assert result['error'] and result['retryable'] and result['issues']
        assert result['ui_context']['displayed'] is False and 'a2ui_operations' not in result

@pytest.mark.asyncio
async def test_surface_update_targets_a_real_generated_surface(context):
    tool=RenderInterfaceTool();initial=await tool.run_async(args={'components':[{'id':'root','component':'Text','text':'First'}]},tool_context=context)
    updated=await tool.run_async(args={'surface_id':initial['surface_id'],'components':[{'id':'root','component':'Notice','severity':'info','message':'Updated'}]},tool_context=context)
    assert len(updated['a2ui_operations'])==2
    assert updated['surface_id']==initial['surface_id']

@pytest.mark.asyncio
async def test_real_function_argument_json_and_code_fences(context):
    import json
    graph=[{'id':'root','component':'Card','title':'A composed section','child':'body'}, {'id':'body','component':'Text','text':'Choose an option.'}]
    for encoded in (json.dumps(graph),'```json\n'+json.dumps(graph)+'\n```'):
        result=await RenderInterfaceTool().run_async(args={'components_json':encoded},tool_context=context)
        assert result.get('a2ui_operations'),result

@pytest.mark.asyncio
async def test_nested_props_are_normalized_without_inventing_a_page(context):
    graph=[{'id':'root','component':'Column','props':{'children':['info']}},{'id':'info','component':{'Notice':{'message':'An actual error','severity':'error'}}}]
    result=await RenderInterfaceTool().run_async(args={'components':graph},tool_context=context)
    assert result.get('a2ui_operations'),result
    assert result['a2ui_operations'][1]['updateComponents']['components']==[{'id':'root','component':'Column','children':['info']},{'id':'info','component':'Notice','message':'An actual error','severity':'error'}]

@pytest.mark.asyncio
async def test_selected_business_tool_returns_model_graph_in_the_same_result(context,monkeypatch):
    from backend import agent
    from backend.tools import recommend_dishes
    from google.adk.models.base_llm import BaseLlm
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types
    import json
    from backend.interface_tool import GenerateInterfaceTool
    calls=[]
    graph=[{'id':'root','component':'Form','children':['guests'],'action':'recommend_dishes','submitLabel':'Find my choices'},
        {'id':'guests','component':'Field','name':'party_size','label':'Guests','type':'number','value':{'path':'/recommendation/party_size'}}]
    class Compositor(BaseLlm):
        async def generate_content_async(self,llm_request,stream=False):
            calls.append(llm_request)
            yield LlmResponse(content=types.Content(role='model',parts=[types.Part(text=json.dumps({'components':graph}))]),partial=False)
    monkeypatch.setattr(agent,'PROVIDER','dot');monkeypatch.setattr(agent,'UI_MODE','dynamic')
    monkeypatch.setattr(agent,'interface_tool',GenerateInterfaceTool(Compositor(model='compositor-test')))
    context.actions=SimpleNamespace(skip_summarization=True)
    result=await agent.finish_surface(SimpleNamespace(name='recommend_dishes'),{},context,recommend_dishes(party_size=2,budget=60))
    assert result.get('a2ui_operations'),result
    assert result['ui_context']['agent_composed'] and len(calls)==1
    assert context.state['_ui_records'][-1]['recommendation']==result['recommendation']
    nodes=result['a2ui_operations'][1]['updateComponents']['components']
    assert nodes[0]==graph[0] and nodes[1]['value']==2

@pytest.mark.asyncio
async def test_internal_fact_lookup_does_not_generate_ui(context,monkeypatch):
    from backend import agent
    from backend.tools import get_menu
    monkeypatch.setattr(agent,'PROVIDER','dot');monkeypatch.setattr(agent,'UI_MODE','dynamic')
    context.actions=SimpleNamespace(skip_summarization=True)
    result=await agent.finish_surface(SimpleNamespace(name='get_menu'),{},context,get_menu('main',render_ui=False))
    assert result['dishes'] and not result.get('a2ui_operations')
    assert not context.state.get('_a2ui_rendered_invocation')

@pytest.mark.asyncio
async def test_render_failure_preserves_successful_cart_mutation(context,monkeypatch):
    from backend import agent
    from backend.tools import update_cart
    class FailedRenderer:
        async def run_async(self,**kwargs):return {'error':'Invalid graph','issues':['Missing root']}
    monkeypatch.setattr(agent,'PROVIDER','dot');monkeypatch.setattr(agent,'UI_MODE','dynamic')
    monkeypatch.setattr(agent,'interface_tool',FailedRenderer())
    context.actions=SimpleNamespace(skip_summarization=True)
    result=await agent.finish_surface(SimpleNamespace(name='update_cart'),{},context,update_cart(context,'add','caesar',1))
    assert result['cart']['total_cents']==1400
    assert 'error' not in result and result['ui_error']['retryable']
    assert result['ui_context']['displayed'] is False

@pytest.mark.asyncio
async def test_compositor_output_limit_is_a_bounded_repair_not_a_network_crash(context):
    from backend.interface_tool import GenerateInterfaceTool
    from google.adk.models.base_llm import BaseLlm
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types
    calls=[]
    class BudgetModel(BaseLlm):
        async def generate_content_async(self,llm_request,stream=False):
            calls.append(1)
            if len(calls)==1:raise RuntimeError('The provider exhausted its output limit before completing the response.')
            yield LlmResponse(content=types.Content(role='model',parts=[types.Part(text='{"components":[{"id":"root","component":"Notice","severity":"info","message":"Please adjust your preferences."}]}')]),partial=False)
    result=await GenerateInterfaceTool(BudgetModel(model='test-budget')).run_async(args={'request':'Show the actual issue'},tool_context=context)
    assert result['a2ui_operations'] and len(calls)==2

@pytest.mark.asyncio
async def test_server_bindings_protect_quote_values_and_never_send_tokens_to_model(context,store):
    import json
    from google.adk.models.base_llm import BaseLlm
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types
    from backend.interface_tool import GenerateInterfaceTool
    session=context.state['maison_thread']
    store.change(session,'add','caesar',1)
    quote=store.quote(session);context.state['_ui_records']=[{'quote':quote}]
    class QuoteModel(BaseLlm):
        async def generate_content_async(self,llm_request,stream=False):
            prompt=llm_request.contents[0].parts[0].text
            assert quote['confirmation_token'] not in prompt
            document={'data':{'quote':{'total_cents':1,'confirmation_token':'fake','idempotency_key':'fake'}},'components':[
                {'id':'root','component':'Column','children':['total','confirm']},
                {'id':'total','component':'CartTotal','totalCents':{'path':'/quote/total_cents'}},
                {'id':'confirm','component':'Button','label':'Confirm','action':{'name':'confirm_order','context':{key:{'path':'/quote/'+key} for key in ('confirmation_token','idempotency_key')}}}]}
            yield LlmResponse(content=types.Content(role='model',parts=[types.Part(text=json.dumps(document))]),partial=False)
    result=await GenerateInterfaceTool(QuoteModel(model='quote-test')).run_async(args={'request':'Review my actual quote'},tool_context=context)
    assert result.get('a2ui_operations'),result
    nodes=result['a2ui_operations'][1]['updateComponents']['components']
    assert nodes[1]['totalCents']==1400
    assert nodes[2]['action']['context']=={key:quote[key] for key in ('confirmation_token','idempotency_key')}
    assert not store.orders(session)

@pytest.mark.asyncio
async def test_invalid_dish_repair_keeps_the_full_id_map(context):
    result=await RenderInterfaceTool().run_async(args={'components':[{'id':'root','component':'DishImage','dishId':'truffle-risotto'}]},tool_context=context)
    assert result['error'] and result['repair_data']['allowed_dishes']
    assert any(d['id']=='risotto' for d in result['repair_data']['allowed_dishes'])

def test_successful_records_clear_a_previous_error(context):
    from backend.interface_tool import trusted_data
    context.state['_ui_records']=[{'error':'Unknown dish'},{'dishes':[]}]
    data=trusted_data(context)
    assert 'error' not in data and data['latest_result']=={'dishes':[]}

@pytest.mark.asyncio
async def test_form_does_not_render_a_second_submit_button(context):
    graph=[{'id':'root','component':'Form','action':'recommend_dishes','submitLabel':'Update','children':['extra']},
        {'id':'extra','component':'Button','label':'Update again','action':{'name':'recommend_dishes'}}]
    result=await RenderInterfaceTool().run_async(args={'components':graph},tool_context=context)
    assert result['error'] and result['repair_data']['remove_component']=='extra'

@pytest.mark.asyncio
async def test_network_failure_returns_a_ui_error_not_a_business_crash(context):
    import httpx
    from backend.interface_tool import GenerateInterfaceTool
    class OfflineModel:
        async def generate_content_async(self,*args,**kwargs):
            raise httpx.ReadTimeout('Synthetic connection interruption')
            yield
    result=await GenerateInterfaceTool(OfflineModel()).run_async(args={'request':'Show cart'},tool_context=context)
    assert result['retryable'] and result['ui_context']['displayed'] is False
    assert 'a2ui_operations' not in result
