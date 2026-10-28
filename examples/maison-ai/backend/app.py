import asyncio,json,re,uuid,time,logging
from contextlib import asynccontextmanager
from fastapi import FastAPI,HTTPException
from fastapi.responses import StreamingResponse
from ag_ui.core import RunAgentInput
from ag_ui.encoder import EventEncoder
from pydantic import BaseModel,Field,StrictInt,ConfigDict
from typing import Literal
from .config import PROVIDER
from .agent import agent
from .tools import store,confirmed_action,confirmed_reservation
from .recommendations import candidates
from .store import MENU,BusinessError
from . import surfaces

app=FastAPI(title='Maison AI · ADK / AG-UI / A2UI')
logger=logging.getLogger('uvicorn.error')

class SessionLock:
    """A lock plus the number of coroutines currently inside or waiting for it."""
    def __init__(self):self.lock=asyncio.Lock();self.users=0
    async def __aenter__(self):
        self.users+=1
        await self.lock.acquire()
        return self
    async def __aexit__(self,*exc):
        self.lock.release();self.users-=1
        return False

run_locks:dict[str,SessionLock]={}
action_locks:dict[str,SessionLock]={}

@asynccontextmanager
async def session_lock(table,sid):
    """Serialize one kind of work per session and forget idle sessions.

    Agent runs and UI actions use separate tables on purpose: a run legitimately
    holds its lock for minutes, and a cart button must not queue behind it.
    """
    entry=table.get(sid)
    if entry is None:entry=table[sid]=SessionLock()
    try:
        async with entry:yield
    finally:
        # No await between the check and the pop, so a new caller cannot slip in.
        if entry.users==0 and table.get(sid) is entry:table.pop(sid,None)

def check_sid(sid):
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',sid):raise HTTPException(400,'Invalid session id')
    return sid

@app.get('/health')
def health():return {'status':'ok','provider':PROVIDER,'mock':PROVIDER=='mock','a2ui_version':'v0.9'}

@app.get('/menu')
def menu():return {'dishes':MENU,'source':'backend/data/menu.json'}

@app.get('/cart/{sid}')
def cart(sid:str):return store.cart(check_sid(sid))

@app.get('/orders/{sid}')
def orders(sid:str):return store.orders(check_sid(sid))

@app.get('/reservations/{sid}')
def reservations(sid:str):return store.reservations(check_sid(sid))

class ActionContext(BaseModel):
    model_config=ConfigDict(extra='forbid')
    dish_id:str=''
    item_id:str=''
    quantity:StrictInt=Field(default=1,ge=0,le=20)
    options:dict[str,str]=Field(default_factory=dict)
    confirmation_token:str=''
    idempotency_key:str=''
    party_size:StrictInt=Field(default=2,ge=1,le=12)
    dietary_preferences:list[str]=Field(default_factory=list,max_length=12)
    excluded_allergens:list[str]=Field(default_factory=list,max_length=20)
    max_calories:StrictInt=Field(default=0,ge=0,le=10000)
    budget:float=Field(default=0,ge=0,allow_inf_nan=False)
    date:str=''
    start_time:str='18:00'
    end_time:str='20:00'
    table_id:str=''

class UIActionInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:Literal['add_to_cart','update_item','remove_item','checkout','confirm_order','calculate_calories','recommend_dishes','open_reservation','check_reservation','confirm_reservation']
    context:ActionContext=Field(default_factory=ActionContext)

@app.post('/actions/{sid}')
async def ui_action(sid:str,action:UIActionInput):
    """Explicit UI operations update server state without a model round trip."""
    sid=check_sid(sid)
    async with session_lock(action_locks,sid):
        ctx=action.context
        try:
            if action.name in ('add_to_cart','update_item','remove_item'):
                operation={'add_to_cart':'add','update_item':'update','remove_item':'remove'}[action.name]
                updated=store.change(sid,operation,ctx.dish_id,ctx.quantity,ctx.options,ctx.item_id or None)
                return {'cart':updated,**surfaces.cart_view(updated)}
            if action.name=='checkout':
                quote=store.quote(sid)
                return {'cart':store.cart(sid),**surfaces.checkout(quote)}
            if action.name=='calculate_calories':
                current=store.cart(sid)
                return {'cart':current,**surfaces.calorie_summary(current,ctx.party_size)}
            if action.name=='recommend_dishes':
                result=candidates(ctx.party_size,ctx.dietary_preferences,ctx.budget,ctx.max_calories,ctx.excluded_allergens)
                lines=[]
                for dish in result['candidates']:
                    allergens=', '.join(dish['allergens']) or 'none listed'
                    lines.append(f"**{dish['name']}** — {dish['recommended_quantity']} portions for {result['party_size']} diners; approximately {dish['calories_per_person']} kcal per person, S$ {dish['group_price_cents']/100:.2f} for these portions. Declared allergens: {allergens}.")
                explanation=('Here are my recommendations based on your selected party size, budget and dietary filters. Each is an alternative choice:\n\n'+'\n\n'.join(lines)+'\n\nCalories are estimates. Kitchen cross-contact information is unavailable.') if lines else 'No dishes match all your filters. Please adjust your preferences and try again.'
                return {'recommendation':result,'assistant_message':explanation,**surfaces.recommendations(result,show_results=True)}
            if action.name=='open_reservation':return surfaces.reservation_form(ctx.date,ctx.start_time,ctx.end_time,ctx.party_size)
            if action.name=='check_reservation':
                result=store.availability(ctx.date,ctx.start_time,ctx.end_time,ctx.party_size)
                return {'availability':result,**surfaces.reservation_availability(result)}
            if action.name=='confirm_reservation':
                booking=store.reserve(sid,ctx.date,ctx.start_time,ctx.end_time,ctx.party_size,ctx.table_id,ctx.idempotency_key,explicit_confirm=True)
                return {'reservation':booking,**surfaces.reservation_success(booking)}
            order=store.place(sid,ctx.confirmation_token,ctx.idempotency_key,explicit_confirm=True)
            return {'cart':store.cart(sid),'order':order,**surfaces.success(order)}
        except BusinessError as exc:
            raise HTTPException(400,detail=str(exc)) from exc

@app.post('/agent')
async def run(input:RunAgentInput):
    sid=check_sid(input.thread_id)
    last=input.messages[-1] if input.messages else None
    action=None
    if last and last.role=='user' and isinstance(last.content,str):
        if len(last.content)>16000:raise HTTPException(400,'Message too long')
        try:action=json.loads(last.content).get('a2uiAction')
        except (ValueError,AttributeError):pass
    if action:
        if action.get('name') not in ['add_to_cart','update_item','remove_item','checkout','confirm_order','calculate_calories','recommend_dishes','open_reservation','check_reservation','confirm_reservation']:raise HTTPException(400,'Unsupported UI action')
        if not isinstance(action.get('context',{}),dict):raise HTTPException(400,'Invalid action context')
    # Server state wins over all client-supplied business state.
    input=input.model_copy(update={'state':{'maison_thread':sid,'cart':store.cart(sid)}})
    encoder=EventEncoder()
    def failure(code,message):return 'data: '+json.dumps({'type':'RUN_ERROR','code':code,'message':message})+'\n\n'
    async def events():
        started=time.perf_counter();first_text=None;first_ui=None;first_content=None;text_deltas=0;tool_started={}
        async with session_lock(run_locks,sid):
            logger.info('maison_run run=%s queue_ms=%d',input.run_id,round((time.perf_counter()-started)*1000))
            token=confirmed_action.set(action.get('context') if action and action.get('name')=='confirm_order' else None)
            reservation_token=confirmed_reservation.set(action.get('context') if action and action.get('name')=='confirm_reservation' else None)
            try:
                async for event in agent.run(input):
                    kind=str(event.type.value if hasattr(event.type,'value') else event.type)
                    elapsed=round((time.perf_counter()-started)*1000)
                    if kind=='TEXT_MESSAGE_CONTENT':
                        text_deltas+=1
                        if first_text is None:
                            first_text=elapsed
                            logger.info('maison_run run=%s first_text_ms=%d',input.run_id,elapsed)
                    if kind=='TOOL_CALL_START':
                        tool_started[event.tool_call_id]=time.perf_counter()
                        logger.info('maison_tool run=%s tool=%s start_ms=%d',input.run_id,event.tool_call_name,elapsed)
                    elif kind=='TOOL_CALL_RESULT':
                        begin=tool_started.pop(event.tool_call_id,None)
                        logger.info('maison_tool run=%s complete_ms=%d',input.run_id,round((time.perf_counter()-(begin or started))*1000))
                        try:
                            payload=json.loads(event.content) if isinstance(event.content,str) else event.content
                        except (ValueError,TypeError):payload=None
                        if first_content is None and isinstance(payload,dict) and payload.get('a2ui_operations'):
                            first_content=elapsed
                            logger.info('maison_run run=%s first_ui_content_ms=%d',input.run_id,elapsed)
                    if kind=='CUSTOM' and getattr(event,'name',None)=='A2UI_STREAM':
                        phase=(event.value or {}).get('phase','progress')
                        if first_ui is None:
                            first_ui=elapsed
                            logger.info('maison_run run=%s first_ui_ms=%d',input.run_id,elapsed)
                        if first_content is None and phase=='progress':
                            first_content=elapsed
                            logger.info('maison_run run=%s first_ui_content_ms=%d',input.run_id,elapsed)
                        if phase in ('begin','commit','rollback'):
                            logger.info('maison_ui run=%s phase=%s elapsed_ms=%d',input.run_id,phase,elapsed)
                    yield encoder.encode(event)
            except asyncio.CancelledError:
                # ADK reports a failed model call by cancelling the run, and
                # CancelledError is not an Exception, so the handler below never
                # sees it. Record it here; the proxy closes the browser's stream
                # with a terminal frame when this one ends without one.
                logger.warning('maison_run run=%s aborted_ms=%d open_tools=%d',input.run_id,round((time.perf_counter()-started)*1000),len(tool_started))
                raise
            except Exception as exc:
                logger.error('maison_run run=%s failed_type=%s',input.run_id,type(exc).__name__)
                # Never send SDK exception strings: these can contain provider headers.
                yield failure('AGENT_FAILED','The agent could not finish. Check the backend log or try again.')
            finally:
                confirmed_action.reset(token);confirmed_reservation.reset(reservation_token)
                logger.info('maison_run run=%s complete_ms=%d text_deltas=%d first_text_ms=%s first_ui_ms=%s first_ui_content_ms=%s',input.run_id,round((time.perf_counter()-started)*1000),text_deltas,first_text,first_ui,first_content)
    return StreamingResponse(events(),media_type='text/event-stream',headers={'Cache-Control':'no-cache, no-transform','X-Accel-Buffering':'no'})
