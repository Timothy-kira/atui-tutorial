import json
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

def get_menu(category: str='',dietary_preferences: list[str]|None=None,render_ui: bool=True) -> dict:
    """Browse actual dishes, automatically composing A2UI cards. Use category main and dietary_preferences ['vegetarian'] for vegetarian mains. Set render_ui=False ONLY for internal ID lookup during a cart mutation."""
    prefs=dietary_preferences or []
    dishes=[d for d in MENU if d['available'] and (not category or d['category']==category)]
    for p in prefs:
        if p in ('vegetarian','vegan'):dishes=[d for d in dishes if d[p]]
        elif p.startswith('no-'):dishes=[d for d in dishes if p[3:] not in d['allergens']]
    # Keep ordinary menu lookup compact; get_dish_details returns the full
    # recipe and safety notes on demand, avoiding a large prompt on every turn.
    summary=[{key:d[key] for key in MENU_SUMMARY_FIELDS} for d in dishes]
    return {'source':'backend/data/menu.json','currency':'SGD','dishes':summary,'render_ui':render_ui}

def get_dish_details(dish_id: str,render_ui: bool=True)->dict:
    """Show a dish as an automatically composed A2UI card with its trusted recipe, calories, servings, allergens and options. Set render_ui=False ONLY for internal validation during a cart mutation."""
    dish=BY_ID.get(dish_id)
    return {**dish,'render_ui':render_ui} if dish else {'error':'Unknown dish'}

def recommend_dishes(party_size: int=2,dietary_preferences: list[str]|None=None,budget: float=0,max_calories: int=0,excluded_allergens: list[str]|None=None)->dict:
    """Render editable A2UI filters and real dish cards, with photos, prices and suggested portions for 1–12 diners. max_calories is kcal/person for each dish at suggested quantity; budget caps that dish's group price. Zero means unlimited. Declared allergens only; cross-contact is unknown. This tool already renders UI; do not also call generate_a2ui."""
    try:
        result=candidates(party_size,dietary_preferences,budget,max_calories,excluded_allergens)
        return {'recommendation':{**result,'candidates':[]},'ui_request':'recommendation_filters'}
    except BusinessError as exc:return {'error':str(exc)}

def calculate_total_calories(tool_context: ToolContext,party_size: int=1)->dict:
    """Calculate this cart's recipe energy from actual quantities and render an A2UI breakdown, total kcal and an equal per-person split. Customizations are not included in menu calorie estimates."""
    if type(party_size) is not int or not 1<=party_size<=12:return {'error':'Choose 1–12 diners'}
    cart=sync(tool_context)
    return {'cart':cart,'party_size':party_size,'ui_request':'calorie_summary'}

def show_reservation(date: str='',start_time: str='18:00',end_time: str='20:00',party_size: int=2)->dict:
    """Show the A2UI reservation form for date, start/end time and guest count. This does not reserve a table. Times are Singapore restaurant time (UTC+08:00)."""
    if not 1<=party_size<=12:return {'error':'Choose 1–12 guests'}
    from datetime import datetime
    from .store import RESTAURANT_TIMEZONE
    return {'date':date or datetime.now(RESTAURANT_TIMEZONE).date().isoformat(),'start_time':start_time,'end_time':end_time,'party_size':party_size,'ui_request':'reservation_form'}

def check_reservation(date: str,start_time: str,end_time: str,party_size: int)->dict:
    """Check real demo table capacity and overlapping reservations. Render available tables with an explicit Confirm Reservation action. Does not create a reservation."""
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

def get_cart(tool_context: ToolContext)->dict:
    """Read this session's real cart and render its editable A2UI surface."""
    cart=sync(tool_context)
    return {'cart':cart,'ui_request':'cart'}

def quote_order(tool_context: ToolContext)->dict:
    """Validate cart and render a fixed A2UI order review. This DOES NOT place an order."""
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

def reply_to_guest():
    """Choose only for greetings or clarification needing no restaurant data or UI. Never use for menu, recommendations, budgets, reservations, calories, cart or orders. Then answer normally."""
    return {'reply_allowed':True}

BUSINESS_TOOLS=[reply_to_guest,get_menu,get_dish_details,recommend_dishes,calculate_total_calories,show_reservation,check_reservation,reserve_table,update_cart,get_cart,quote_order,place_order]
