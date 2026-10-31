import json
from typing import Literal
from contextvars import ContextVar
from google.adk.tools import ToolContext
from .store import Store,MENU,BY_ID,BusinessError
from . import surfaces
from .recommendations import candidates

store=Store()
confirmed_action=ContextVar('confirmed_action',default=None)
confirmed_reservation=ContextVar('confirmed_reservation',default=None)
MENU_SUMMARY_FIELDS=('id','name','category','description','price','currency','image','available','vegetarian','vegan','allergens','options','calories_kcal','servings')

def sid(ctx):return ctx.state['maison_thread']
def sync(ctx):
    cart=store.cart(sid(ctx));ctx.state['cart']=cart;return cart

def get_menu(category: Literal['','appetizer','main','pasta_pizza','dessert','drink']='',dietary_preferences: list[str]|None=None,render_ui: bool=True) -> dict:
    """Read actual menu records. render_ui=True returns model-composed interactive cards; choose False for internal lookup or text-only answers. Use category main and dietary_preferences ['vegetarian'] for vegetarian mains."""
    prefs=dietary_preferences or []
    if category not in {'','appetizer','main','pasta_pizza','dessert','drink'}:
        return {'error':'Unknown menu category. Use appetizer, main, pasta_pizza, dessert, drink or an empty string for all categories.','render_ui':False}
    unsupported=[p for p in prefs if p not in {'vegetarian','vegan'} and not p.startswith('no-')]
    if unsupported:
        return {'error':'Unsupported dietary preference. Use vegetarian, vegan or no-<declared allergen>.','render_ui':False}
    dishes=[d for d in MENU if d['available'] and (not category or d['category']==category)]
    for p in prefs:
        if p in ('vegetarian','vegan'):dishes=[d for d in dishes if d[p]]
        elif p.startswith('no-'):dishes=[d for d in dishes if p[3:] not in d['allergens']]
    # Keep ordinary menu lookup compact; get_dish_details returns the full
    # recipe and safety notes on demand, avoiding a large prompt on every turn.
    summary=[{key:d[key] for key in MENU_SUMMARY_FIELDS} for d in dishes]
    return {'source':'backend/data/menu.json','currency':'SGD','dishes':summary,'render_ui':render_ui}

def get_dish_details(dish_id: str,render_ui: bool=True)->dict:
    """Read a dish's actual recipe, calories, servings, allergens and options. render_ui=True returns a model-composed detail interface; choose False for internal lookup or text-only questions."""
    dish=BY_ID.get(dish_id)
    return {**dish,'render_ui':render_ui} if dish else {'error':'Unknown dish'}

def get_order_choices(dish_id:str)->dict:
    """Read actual dish options before adding. Returns a model-composed interface with editable selectors using these facts."""
    dish=BY_ID.get(dish_id)
    return {'dishes':[dish],'render_ui':True} if dish else {'error':'Unknown dish'}

def recommend_dishes(party_size: int=2,dietary_preferences: list[str]|None=None,budget: float=0,max_calories: int=0,excluded_allergens: list[str]|None=None)->dict:
    """Open interactive recommendation preferences immediately when the guest asks for meal/dinner recommendations. Pass known preferences; omit unspecified fields to use editable defaults. Do NOT ask a text questionnaire first: this tool returns a model-composed form collecting party_size, diet, allergies, budget and calories. Candidates appear only after Update recommendations. budget is each candidate's group cost, not a combined meal plan; max_calories is per person per candidate. Zero means unlimited."""
    try:
        result=candidates(party_size,dietary_preferences,budget,max_calories,excluded_allergens)
        from .config import UI_MODE,PROVIDER
        if UI_MODE=='dynamic' and PROVIDER!='mock':
            settings={key:value for key,value in result.items() if key!='candidates'}
            return {'recommendation':settings,'results_pending_user_submission':True,'next_step':'Compose an editable RecommendationFilters using these validated settings. No dish search results are expected until the guest submits Update recommendations.','ui_request':'recommendation_filters'}
        return {'recommendation':{**result,'candidates':[]},'ui_request':'recommendation_filters'}
    except BusinessError as exc:return {'error':str(exc)}

def calculate_total_calories(tool_context: ToolContext,party_size: int=1,render_ui: bool=True)->dict:
    """Calculate this cart's actual recipe energy and equal per-person split. render_ui=True returns an interactive breakdown; False returns facts for a text-only explanation. Customizations are not included in menu calorie estimates."""
    if type(party_size) is not int or not 1<=party_size<=12:return {'error':'Choose 1–12 diners'}
    cart=sync(tool_context)
    return {'cart':cart,'party_size':party_size,**({'ui_request':'calorie_summary'} if render_ui else {})}

def show_reservation(date: str='',start_time: str='18:00',end_time: str='20:00',party_size: int=2)->dict:
    """Get reservation form settings for date, start/end time and guest count. Returns an editable model-composed form. This does not reserve a table. Times are Singapore restaurant time (UTC+08:00)."""
    if not 1<=party_size<=12:return {'error':'Choose 1–12 guests'}
    from datetime import datetime
    from .store import RESTAURANT_TIMEZONE
    return {'date':date or datetime.now(RESTAURANT_TIMEZONE).date().isoformat(),'start_time':start_time,'end_time':end_time,'party_size':party_size,'ui_request':'reservation_form'}

def check_reservation(date: str,start_time: str,end_time: str,party_size: int)->dict:
    """Check real demo table capacity and overlapping reservations. Returns model-composed choices with server-issued Confirm Reservation fields. Does not create a reservation."""
    try:
        result=store.availability(date,start_time,end_time,party_size)
        return {'availability':result,'ui_request':'reservation_availability'}
    except BusinessError as exc:return {'error':str(exc)}

def reserve_table(tool_context: ToolContext,date: str,start_time: str,end_time: str,party_size: int,table_id: str,idempotency_key: str)->dict:
    """Save a demo reservation ONLY after an explicit Confirm Reservation UI action, using its exact fields and idempotency key. Recheck capacity and time conflicts atomically."""
    fields=dict(date=date,start_time=start_time,end_time=end_time,party_size=party_size,table_id=table_id,idempotency_key=idempotency_key)
    action=confirmed_reservation.get()
    allowed=bool(action and all(action.get(key)==value for key,value in fields.items()))
    try:
        booking=store.reserve(sid(tool_context),date,start_time,end_time,party_size,table_id,idempotency_key,allowed)
        return {'reservation':booking,'ui_request':'reservation_success'}
    except BusinessError as exc:return {'error':str(exc)}

def update_cart(tool_context: ToolContext,action: str,dish_id: str,quantity: int=1,options: dict[str,str]|None=None,item_id: str='')->dict:
    """Add/update/remove a real cart line. Options must match get_dish_details. No client-supplied prices."""
    try:
        store.change(sid(tool_context),action,dish_id,quantity,options,item_id or None)
        cart=sync(tool_context)
        return {'cart':cart,'ui_request':'cart'}
    except BusinessError as e:return {'error':str(e),'cart':sync(tool_context)}

def get_cart(tool_context: ToolContext,render_ui: bool=True)->dict:
    """Read this session's actual cart. render_ui=True returns an editable model-composed cart; choose False for internal lookup or text-only answers."""
    cart=sync(tool_context)
    return {'cart':cart,**({'ui_request':'cart'} if render_ui else {})}

def quote_order(tool_context: ToolContext)->dict:
    """Validate the cart and create an actual expiring quote. Returns a model-composed review and Confirm Order button using server-issued fields. This DOES NOT place an order."""
    try:
        q=store.quote(sid(tool_context))
        return {'quote':q,'ui_request':'checkout'}
    except BusinessError as e:return {'error':str(e)}

def place_order(tool_context: ToolContext,confirmation_token: str,idempotency_key: str)->dict:
    """Place a Demo Order ONLY after a user Confirm Order action; requires a valid quote and idempotency key."""
    try:
        confirm=confirmed_action.get()
        allowed=bool(confirm and confirm.get('confirmation_token')==confirmation_token and confirm.get('idempotency_key')==idempotency_key)
        order=store.place(sid(tool_context),confirmation_token,idempotency_key,allowed)
        sync(tool_context)
        return {'order':order,'ui_request':'order_success'}
    except BusinessError as e:return {'error':str(e)}

def mock_show_menu(dish_ids: list[str],doneness: str='')->dict:
    """MOCK MODE ONLY: build a deterministic A2UI fixture, without claiming model-generated layout."""
    import uuid
    return surfaces.mock_menu([BY_ID[d] for d in dish_ids if d in BY_ID and BY_ID[d]['available']],sid='mock-'+uuid.uuid4().hex[:8],doneness=doneness or None)


def mock_show_workflow(tool_context: ToolContext)->dict:
    """MOCK MODE ONLY: render the last actual tool result using a fixed A2UI schema."""
    result=tool_context.state.get('_mock_last_result',{})
    kind=result.get('ui_request')
    if kind=='recommendation_filters':
        return {'assistant_message':'Please fill in your party size, budget, dietary preferences and any declared allergens to exclude, then select Update recommendations.',
                **surfaces.recommendations(result['recommendation'])}
    if kind=='checkout':return {'assistant_message':'Please review your pickup order, then select Confirm Order to submit it.',**surfaces.checkout(result['quote'])}
    if kind=='cart':return {'assistant_message':'Here is your current pickup order.',**surfaces.cart_view(result['cart'])}
    if kind=='calorie_summary':return {'assistant_message':'The panel shows the recipe energy for your selected portions. Calories are estimates.',**surfaces.calorie_summary(result['cart'],result['party_size'])}
    if kind=='reservation_form':return {'assistant_message':'Please fill in the date, time window and guest count, then check availability.',**surfaces.reservation_form(result['date'],result['start_time'],result['end_time'],result['party_size'])}
    if kind=='reservation_availability':return {'assistant_message':'Choose one of the available tables and confirm the reservation.',**surfaces.reservation_availability(result['availability'])}
    if result.get('id') in BY_ID:
        dish=BY_ID[result['id']]
        return {'assistant_message':f"**{dish['name']}**: {dish['description']} {dish['preparation']} Approximately {dish['calories_kcal']} kcal per serving. Declared allergens: "+(', '.join(dish['allergens']) or 'none listed')+'. '+dish['allergen_note'],**surfaces.dish_details(dish)}
    return {'error':'No supported business result is available to render.'}

def reply_to_guest():
    """Choose only for greetings or clarification needing no restaurant data or UI. Never use for menu, recommendations, budgets, reservations, calories, cart or orders. Then answer normally."""
    return {'reply_allowed':True}

def handle_ui_action(tool_context: ToolContext,name: str,context: dict)->dict:
    """Execute the exact validated UI command supplied by this AG-UI run, never a model-invented command."""
    from .actions import active_ui_action,perform_ui_action
    action=active_ui_action.get()
    if not action or name!=action.name or context!=action.context.model_dump(exclude_unset=True):
        return {'error':'No matching explicit UI action in this run.'}
    try:
        result=perform_ui_action(sid(tool_context),action)
        sync(tool_context)
        return result
    except BusinessError as exc:return {'error':str(exc)}

BUSINESS_TOOLS=[reply_to_guest,get_menu,get_dish_details,get_order_choices,recommend_dishes,calculate_total_calories,show_reservation,check_reservation,reserve_table,update_cart,get_cart,quote_order,place_order,handle_ui_action]
