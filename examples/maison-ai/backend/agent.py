"""ADK owns conversation and tool choice; hooks enforce business boundaries."""
import json,logging
from google.adk.agents import LlmAgent
from google.adk.models.llm_response import LlmResponse
from ag_ui_adk import ADKAgent,AGUIToolset
from google.adk.apps import App
from google.adk.apps.app import ResumabilityConfig
from google.genai import types
from .config import make_model,PROVIDER,CATALOG_ID,UI_MODE
from .tools import BUSINESS_TOOLS,mock_show_menu,mock_show_workflow

INSTRUCTION="""You are Maison AI, a restaurant pickup assistant. Respond concisely in the guest's language. Answer the actual question; decide yourself whether to talk, clarify or call tools. Greetings/capability questions need no tool. Respect requests for text only.
Use business tools for menu facts, prices, recipes, availability and actual cart operations. Previous recommendations are not the whole menu. Never invent facts, dish IDs or completed operations. Use a few relevant choices and explain why they fit.
An affirmative answer to an offer of several different actions is NOT a choice of adding food. Ask which action the guest meant and stop; do not present imagined dishes or assume an operation. Keep clarification to a single short question.
For a clear recommendation request, CALL recommend_dishes to open editable preferences NOW, using known values and defaults. Missing diet, allergies, budget or calories are NOT prerequisites: the guest fills them in the interactive form. Do not replace that tool with a text questionnaire or an unfiltered menu. Candidates appear only after submission. A budget is the group cost of each candidate, not a combined meal plan. For an ambiguous reply to several offered actions, clarify which action instead of guessing.
Tools with render_ui=True return an interactive interface composed by a model from catalog components. Choose False for internal fact lookups or text-only questions. Other UI-producing tools return ui_context. Read it before saying an interface is displayed. Introduce actual forms with what to fill in; introduce recommendations with why they fit. Do not repeat whole cards in prose.
Checkout requires quote_order and an actual review interface. Do not merely promise to generate a confirmation. Only an explicit guest confirmation button may submit an order or reservation. These are local demo operations. Never submit through conversation alone.
Calories are estimates of base recipes times quantity; customizations do not change this demo's calculation. Declared allergens are from menu records; kitchen cross-contact is unknown.
"""
from .interface_tool import GenerateInterfaceTool
DYNAMIC_INSTRUCTION="""
CURRENT UI MODE: model-composed A2UI. UI-producing business tools already invoke a model to compose their interface and return it in the SAME result. Do not generate a duplicate after a successful display. You can call generate_a2ui independently to compose a comparison, repair a failed interface, show an actual error/correction, or change the layout using retrieved facts. No page template is selected. If ui_error occurs, the business operation may still have succeeded: do not repeat that operation. Repair the interface or explain the actual failure. Never claim a failed display succeeded.
"""

# These operations are exclusively dispatched from validated UI metadata.
# They are registered for ADK execution but never offered as model choices.
UI_ONLY_TOOLS={'handle_ui_action','place_order','reserve_table','reply_to_guest'}
UI_PAYLOAD_FIELDS={'a2ui_operations','assistant_message'}

def _has_ui_payload(value):
    if isinstance(value,dict):return any(key in UI_PAYLOAD_FIELDS for key in value) or any(_has_ui_payload(item) for item in value.values())
    if isinstance(value,list):return any(_has_ui_payload(item) for item in value)
    return False

def tool_facts(value):
    """Remove UI transport even inside serialized historical tool envelopes."""
    if isinstance(value,dict):return {key:tool_facts(item) for key,item in value.items() if key not in UI_PAYLOAD_FIELDS}
    if isinstance(value,list):return [tool_facts(item) for item in value]
    if isinstance(value,str):
        try:parsed=json.loads(value)
        except (ValueError,TypeError):return value
        if _has_ui_payload(parsed):return tool_facts(parsed)
    return value

def prepare_response(callback_context,llm_request):
    from .actions import active_ui_action
    action=active_ui_action.get()
    action_complete=False
    if action:
        call_id='ui-'+callback_context.invocation_id
        result=next((part.function_response.response for content in reversed(llm_request.contents or [])
            for part in content.parts or [] if part.function_response and part.function_response.id==call_id),None)
        if result is None:
            # A click already carries intent. Execute exactly that command once.
            return LlmResponse(content=types.Content(role='model',parts=[types.Part(function_call=types.FunctionCall(
                id=call_id,name='handle_ui_action',args={'name':action.name,'context':action.context.model_dump(exclude_unset=True)}))]),partial=False)
        action_complete=True
    if PROVIDER=='mock':return None

    # Keep actual calls, tool facts, and conversational context. Only remove UI
    # transport payloads / canned hints; they are not instructions for the LLM.
    contents=[]
    for original in llm_request.contents or []:
        content=original.model_copy(deep=True)
        for part in content.parts or []:
            response=part.function_response
            if response and isinstance(response.response,dict):
                response.response=tool_facts(response.response)
        contents.append(content)
    llm_request.contents=contents

    groups=[]
    for group in llm_request.config.tools or []:
        declarations=[fn for fn in group.function_declarations or [] if fn.name not in UI_ONLY_TOOLS and (not action_complete or UI_MODE!='dynamic' or fn.name in {'generate_a2ui','get_menu','get_dish_details'})]
        if declarations:groups.append(types.Tool(function_declarations=declarations))
    llm_request.config.tools=groups or None
    # AUTO permits both normal conversation and autonomous function calling.
    # After an explicit click the model narrates its actual outcome; it cannot
    # repeat that click as another side effect in the same confirmation run.
    llm_request.config.tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(
        mode='NONE' if action_complete and UI_MODE!='dynamic' else 'AUTO'))
    return None


async def finish_surface(tool,args,tool_context,tool_response):
    if PROVIDER=='mock':
        if isinstance(tool_response,dict) and tool.name not in ('mock_show_menu','mock_show_workflow'):
            tool_context.state['_mock_last_result']=tool_response
        return None
    if not isinstance(tool_response,dict):return None
    tool_context.actions.skip_summarization=False

    if UI_MODE=='dynamic':
        if tool.name in {'render_a2ui','generate_a2ui'}:return None
        facts=tool_facts(tool_response)
        tool_context.state['_ui_records']=[*tool_context.state.get('_ui_records',[]),facts][-8:]
        wants_ui=(tool_response.get('ui_request') or tool_response.get('render_ui') is True or tool.name=='handle_ui_action')
        if not wants_ui:return facts
        interface=await interface_tool.run_async(args={'request':
            'Compose an interactive interface for the latest '+tool.name+' result ('+str(tool_response.get('ui_request') or 'requested display')+'). Follow the latest guest request and actual latest_result. If it is an error, show that error and useful correction controls. If preferences await submission, show editable fields, not candidates.'},tool_context=tool_context)
        if interface.get('error'):
            # A presentation failure does not roll back a successful mutation.
            return {**facts,'ui_error':{'message':interface['error'],'issues':interface.get('issues',[]),'retryable':True},'ui_context':{'displayed':False}}
        return {**facts,**interface}

    if UI_MODE=='fixed' and not tool_response.get('error') and tool.name!='handle_ui_action':
        from .presentation import present_result
        presentation=present_result(tool_response)
        if presentation:
            # Compose the UI, not the answer. The agent reads the underlying
            # business facts and writes its own response on the next model step.
            operations=presentation.get('a2ui_operations')
            if operations:
                kind=tool_response.get('ui_request') or ('menu' if 'dishes' in tool_response else 'dish_details')
                return {**tool_response,'a2ui_operations':operations,'ui_context':{
                    'displayed':kind,'requires_user_submission':kind in {'recommendation_filters','checkout','reservation_form','reservation_availability'}}}
    return None

model=make_model()
interface_tool=GenerateInterfaceTool(model)
root_agent=LlmAgent(name='MaisonRestaurantAgent',model=model,instruction=INSTRUCTION+(DYNAMIC_INSTRUCTION if UI_MODE=='dynamic' and PROVIDER!='mock' else ''),
    tools=[*BUSINESS_TOOLS,AGUIToolset(),*([mock_show_menu,mock_show_workflow] if PROVIDER=='mock' else []),*([interface_tool] if UI_MODE=='dynamic' and PROVIDER!='mock' else [])],
    before_model_callback=prepare_response,after_tool_callback=finish_surface,
    generate_content_config=types.GenerateContentConfig(temperature=0.3))
adk_app=App(name='maison_ai',root_agent=root_agent,resumability_config=ResumabilityConfig(is_resumable=True))
agent=ADKAgent.from_app(adk_app,user_id='workshop',use_thread_id_as_session_id=True,execution_timeout_seconds=180)

