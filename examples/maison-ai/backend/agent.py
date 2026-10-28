import re,uuid
from google.adk.agents import LlmAgent
from google.adk.models.llm_response import LlmResponse
from ag_ui_adk import ADKAgent,AGUIToolset,get_a2ui_tool
from google.adk.apps import App
from google.adk.apps.app import ResumabilityConfig
from google.genai import types
from .config import make_model,PROVIDER,CATALOG_ID
from .tools import BUSINESS_TOOLS,mock_show_menu
from .streaming_a2ui import streaming_a2ui_tool

INSTRUCTION='''You are Maison AI, a dining assistant for a fictional Western restaurant. Reply in English, with SGD prices.
Select the appropriate business tool for every request. For recommendations or building a meal with a budget, use recommend_dishes and extract supplied budget, party size, diets and allergens. This returns filter settings; show the editable filter form before recommendations. The user clicks Update recommendations to obtain real matching dishes.
Every new dish or drink question needs a fresh lookup. A previous recommendation is not the full menu. For "What's in the lemonade?", call get_menu(category='drink',render_ui=False), locate House Lemonade, then call get_dish_details with its actual id. Never claim an item is absent merely because it was not among previous recommendations.
For browsing use get_menu; for ingredients, calories, allergens or dish explanations use get_dish_details. Use returned data; never remembered or invented dishes, prices, images or availability. For internal ID lookups during mutations set render_ui=False.
Business tools return trusted data, not layouts. After a result requests UI, call generate_a2ui to assemble components from the catalog. After generation, provide a short explanation based only on trusted results. Per-person calories, group portion totals and declared allergens belong in chat text, not dish cards. Calories are estimates and kitchen cross-contact is unknown.
Every UI response MUST include a matching conversational paragraph. For recommendation filters say: "Please fill in your party size, budget, dietary preferences and any declared allergens to exclude, then select Update recommendations." For a reservation form ask the guest to fill in date, start/end times and party size. For actual dish recommendations say what you recommend and why, using actual returned facts. For checkout ask the guest to review their choices and explicitly confirm. Never end a UI turn with no text explanation.
For calories use calculate_total_calories. For checkout use quote_order. Only explicit confirm_order UI actions with exact server confirmation_token and idempotency_key may place an order. Never confirm an order from conversation alone.
For reservations use show_reservation, or check_reservation if date, start/end times and party size are supplied. Only an explicit confirm_reservation UI action may reserve a table. Times are Singapore restaurant time. Preserve backend confirmation gates.
For cart reads use get_cart; for mutations use update_cart with real dish and line IDs. Ask for missing steak doneness with ask_user before adding. Never claim success without the real tool result.
Use reply_to_guest only for greetings or clarification needing no restaurant data or UI, then answer normally. Actual dining requests must use business tools. Never expose credentials or reasoning. Orders are local Demo Orders with no payment or external restaurant connection.
'''
COMPOSITION='''Compose A2UI v0.9 using the host catalog and latest trusted tool result. Root ID is root. You choose layout, child IDs, bindings and combinations.
For ui_request recommendation_filters: render only RecommendationFilters with returned settings. Do not show dishes until the user submits. The host submit action then returns real recommendations.
For menu dishes compose a Column with a Row of Cards, each containing DishImage, PriceBadge, QuantitySelector, optional DietaryBadge/DishOptionSelector and add_to_cart Button. Use actual dishId, options and names. No descriptions, kcal, allergens or group totals inside dish cards. ServingInfo is only for portion count. Facts go in Agent chat text.
For calorie_summary compose NutritionTotal and CalorieControls from actual cart totals and party_size. For cart compose Cards with PriceBadge and CartItemControls using exact item IDs, options and quantities, plus CartTotal.
For reservation_form use ReservationForm with returned date, times and party size. For reservation_availability show actual available table choices with confirm_reservation Buttons using exact table IDs, date, times, party size and a unique idempotency_key. Never invent availability.
For checkout use CartTotal, NutritionTotal, and Confirm Order Button with the EXACT quote confirmation_token and idempotency_key. Never generate replacement tokens. Use OrderStatus/ReservationStatus for successful confirmations with actual facts only.
Use bound Text/Card fields where useful and fill data incrementally. Never invent HTML, JavaScript, monetary values, image URLs, recipe facts or user selections.'''

def complete_cart_lookup(callback_context,llm_request):
    """A read-only cart intent always executes the real ADK get_cart tool.

    Format its authoritative result directly so a provider's verbal promise
    cannot prematurely finish this particular operation.
    """
    contents=llm_request.contents or []
    start=next((index for index in range(len(contents)-1,-1,-1)
        if contents[index].role=='user' and any(part.text for part in contents[index].parts or [])),None)
    if start is None:return None
    text=' '.join(part.text for part in contents[start].parts or [] if part.text).lower()
    if 'a2uiaction' in text:return None
    if re.search(r'calori|kcal|热量|熱量|卡路里|reserv|book.*table|recommend|推荐|预订|预定|預訂',text):return None
    cart_words=re.search(r'cart|basket|购物车|購物車|加购|加購|已点|已點',text)
    question=re.search(r'what|show|view|check|list|see|current|看看|查看|什么|哪些|多少|目前|现在|看下',text)
    implicit=re.search(r'what.*(?:added|ordered|selected)|(?:点|點)了什么',text)
    mutation=re.search(r'\b(?:add|remove|delete|clear|checkout|increase|decrease)\b|加入|添加|删除|刪除|移除|清空|结账|結帳',text)
    if mutation or not ((cart_words and question) or implicit):return None
    result=next((part.function_response.response for content in reversed(contents[start+1:])
        for part in content.parts or [] if part.function_response and part.function_response.name=='get_cart'),None)
    if result is None:
        return LlmResponse(content=types.Content(role='model',parts=[types.Part(function_call=types.FunctionCall(
            id='cart-'+uuid.uuid4().hex[:12],name='get_cart',args={}))]),partial=False)
    cart=result.get('cart',result)
    items=cart.get('items',[])
    if not items:
        answer='Your table is empty. Open Menu to choose a dish, or ask me for a recommendation.'
    else:
        answer=f"Here’s your table — **{cart['count']} items**, totaling **S$ {cart['total_cents']/100:.2f}**. You can adjust quantities in the dish cards."
    return LlmResponse(content=types.Content(role='model',parts=[types.Part(text=answer)]),partial=False,turn_complete=True)

def prepare_response(callback_context,llm_request):
    if PROVIDER=='mock':return None
    state=callback_context.state
    if state.get('_ui_invocation')!=callback_context.invocation_id:
        state['_ui_invocation']=callback_context.invocation_id
        state['_dining_tool_used']=False
        state['_needs_ui']=False
        state['_ui_completed']=False
    if state.get('_needs_ui'):
        allowed={'generate_a2ui'};mode='ANY'
    elif not state.get('_dining_tool_used'):
        # The model chooses the intent; no keyword routing or synthetic calls.
        allowed={name for name in llm_request.tools_dict if name!='generate_a2ui'};mode='ANY'
    else:
        allowed=None;mode='NONE' if state.get('_ui_completed') else 'AUTO'
    if allowed is not None:
        groups=[]
        for group in llm_request.config.tools or []:
            declarations=[fn.model_copy(deep=True) for fn in group.function_declarations or [] if fn.name in allowed]
            for fn in declarations:
                if fn.name=='generate_a2ui':
                    fn.parameters_json_schema=None
                    fn.parameters=types.Schema(type=types.Type.OBJECT,properties={'intent':types.Schema(type=types.Type.STRING,enum=['create'])},required=['intent'])
            if declarations:groups.append(types.Tool(function_declarations=declarations))
        if groups:llm_request.config.tools=groups
    llm_request.config.tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode=mode))
    return None

def finish_surface(tool,args,tool_context,tool_response):
    state=tool_context.state
    state['_dining_tool_used']=True
    if tool.name=='generate_a2ui':
        state['_needs_ui']=False;state['_ui_completed']=True
        tool_context.actions.skip_summarization=False
    elif isinstance(tool_response,dict) and not tool_response.get('error'):
        state['_needs_ui']=bool(tool_response.get('ui_request') or tool_response.get('render_ui'))
        state['_ui_kind']=tool_response.get('ui_request') or 'dishes'
    return None

root_agent=LlmAgent(name='MaisonRestaurantAgent',model=make_model(),instruction=INSTRUCTION,
    tools=[*BUSINESS_TOOLS,AGUIToolset(),*([mock_show_menu] if PROVIDER=='mock' else [])],
    before_model_callback=prepare_response,after_tool_callback=finish_surface,generate_content_config=types.GenerateContentConfig(temperature=0.3))
if PROVIDER!='mock':
    root_agent.tools.append(streaming_a2ui_tool(get_a2ui_tool({'model':root_agent.canonical_model,
        'default_catalog_id':CATALOG_ID,'guidelines':{'composition_guide':COMPOSITION},
        'recovery':{'maxAttempts':2}})))
adk_app=App(name='maison_ai',root_agent=root_agent,resumability_config=ResumabilityConfig(is_resumable=True))
# A run can make several model calls, each allowed its own first-token wait.
# The outer bound has to outlast those, or a legitimately slow turn is aborted
# before it produced anything.
agent=ADKAgent.from_app(adk_app,user_id='workshop',use_thread_id_as_session_id=True,execution_timeout_seconds=300)

