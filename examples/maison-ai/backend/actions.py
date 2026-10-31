"""Validated UI commands, executed by an ADK FunctionTool over AG-UI.

The model is not asked to reinterpret a user's explicit button click. These
fixed-schema surfaces and authoritative business results are still A2UI.
"""
from contextvars import ContextVar
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from .store import BusinessError
from .recommendations import candidates
from . import surfaces
from .config import UI_MODE,PROVIDER

def _presentation(result,build,*args,**kwargs):
    # Dynamic mode returns records; the Agent composes render_a2ui itself.
    if UI_MODE=='dynamic' and PROVIDER!='mock':return result
    displayed={'cart_view':'cart','recommendations':'recommendations'}.get(build.__name__,build.__name__)
    return {**result,'ui_context':{'displayed':displayed},**build(*args,**kwargs)}

active_ui_action = ContextVar('maison_ui_action', default=None)


class ActionContext(BaseModel):
    model_config = ConfigDict(extra='forbid')
    dish_id: str = ''
    item_id: str = ''
    quantity: StrictInt = Field(default=1, ge=0, le=20)
    options: dict[str, str] = Field(default_factory=dict)
    confirmation_token: str = ''
    idempotency_key: str = ''
    party_size: StrictInt = Field(default=2, ge=1, le=12)
    dietary_preferences: list[str] = Field(default_factory=list, max_length=12)
    excluded_allergens: list[str] = Field(default_factory=list, max_length=20)
    max_calories: StrictInt = Field(default=0, ge=0, le=10000)
    budget: float = Field(default=0, ge=0, allow_inf_nan=False)
    date: str = ''
    start_time: str = '18:00'
    end_time: str = '20:00'
    table_id: str = ''


class UIActionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: Literal['add_to_cart', 'update_item', 'remove_item', 'checkout',
                  'confirm_order', 'calculate_calories', 'recommend_dishes',
                  'open_reservation', 'check_reservation', 'confirm_reservation']
    context: ActionContext = Field(default_factory=ActionContext)

def perform_ui_action(sid, action):
    from .tools import store
    ctx=action.context
    if action.name in ('add_to_cart','update_item','remove_item'):
        operation={'add_to_cart':'add','update_item':'update','remove_item':'remove'}[action.name]
        cart=store.change(sid,operation,ctx.dish_id,ctx.quantity,ctx.options,ctx.item_id or None)
        return _presentation({'cart':cart,'operation':operation},surfaces.cart_view,cart)
    if action.name=='checkout':
        quote=store.quote(sid)
        return _presentation({'cart':store.cart(sid),'quote':quote,'requires_user_confirmation':True},surfaces.checkout,quote)
    if action.name=='calculate_calories':
        cart=store.cart(sid)
        return _presentation({'cart':cart,'party_size':ctx.party_size},surfaces.calorie_summary,cart,ctx.party_size)
    if action.name=='recommend_dishes':
        result=candidates(ctx.party_size,ctx.dietary_preferences,ctx.budget,ctx.max_calories,ctx.excluded_allergens)
        return _presentation({'recommendation':result,'candidates_are_alternatives':True},surfaces.recommendations,result,show_results=True)
    if action.name=='open_reservation':
        return _presentation({'date':ctx.date,'start_time':ctx.start_time,'end_time':ctx.end_time,'party_size':ctx.party_size,'requires_user_submission':True},surfaces.reservation_form,ctx.date,ctx.start_time,ctx.end_time,ctx.party_size)
    if action.name=='check_reservation':
        result=store.availability(ctx.date,ctx.start_time,ctx.end_time,ctx.party_size)
        return _presentation({'availability':result,'requires_user_confirmation':True},surfaces.reservation_availability,result)
    if action.name=='confirm_reservation':
        booking=store.reserve(sid,ctx.date,ctx.start_time,ctx.end_time,ctx.party_size,ctx.table_id,ctx.idempotency_key,explicit_confirm=True)
        return _presentation({'reservation':booking},surfaces.reservation_success,booking)
    order=store.place(sid,ctx.confirmation_token,ctx.idempotency_key,explicit_confirm=True)
    return _presentation({'cart':store.cart(sid),'order':order,'demo_only':True},surfaces.success,order)
