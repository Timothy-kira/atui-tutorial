import asyncio,json,re,uuid,time,logging
from contextlib import asynccontextmanager
from fastapi import FastAPI,HTTPException
from fastapi.responses import StreamingResponse
from ag_ui.core import RunAgentInput,UserMessage
from ag_ui.encoder import EventEncoder
from pydantic import ValidationError
from .actions import UIActionInput,active_ui_action
from .config import PROVIDER,UI_MODE
from .agent import agent
from .tools import store,confirmed_action,confirmed_reservation
from .store import MENU

app=FastAPI(title='Maison AI · ADK / AG-UI / A2UI')
logger=logging.getLogger('uvicorn.error')

class SessionLock:
    """A lock plus the number of coroutines currently inside or waiting for it."""
    def __init__(self):self.lock=asyncio.Lock();self.users=0
    async def __aenter__(self):
        self.users+=1
        try:await self.lock.acquire()
        except BaseException:
            self.users-=1
            raise
        return self
    async def __aexit__(self,*exc):
        self.lock.release();self.users-=1
        return False

run_locks:dict[str,SessionLock]={}
@asynccontextmanager
async def session_lock(table,sid):
    """Serialize chat and explicit UI runs per session and forget idle sessions."""
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
def health():return {'status':'ok','provider':PROVIDER,'mock':PROVIDER=='mock','a2ui_version':'v0.9','ui_mode':UI_MODE}

@app.get('/menu')
def menu():return {'dishes':MENU,'source':'backend/data/menu.json'}

@app.get('/cart/{sid}')
def cart(sid:str):return store.cart(check_sid(sid))

@app.get('/orders/{sid}')
def orders(sid:str):return store.orders(check_sid(sid))

@app.get('/reservations/{sid}')
def reservations(sid:str):return store.reservations(check_sid(sid))

@app.post('/agent')
async def run(input:RunAgentInput):
    sid=check_sid(input.thread_id)
    last=input.messages[-1] if input.messages else None
    if last and last.role=='user' and isinstance(last.content,str) and len(last.content)>16000:
        raise HTTPException(400,'Message too long')
    props=input.forwarded_props if isinstance(input.forwarded_props,dict) else {}
    action=None
    if props.get('a2uiAction') is not None:
        try:action=UIActionInput.model_validate(props['a2uiAction'])
        except ValidationError as exc:raise HTTPException(422,'Invalid A2UI action or parameters') from exc
        # Give ADK a new user turn even when this click follows an assistant
        # response. The wire metadata, not a JSON string typed into chat, is
        # the authorization source for this explicit command.
        input=input.model_copy(update={'messages':[*input.messages,UserMessage(
            id='ui-request-'+uuid.uuid4().hex,role='user',content=f'The user clicked {action.name}.')]})
    # Server state wins over all client-supplied business state.
    guest=next((message.content for message in reversed(input.messages) if message.role=='user' and isinstance(message.content,str)), '')
    input=input.model_copy(update={'state':{'maison_thread':sid,'cart':store.cart(sid),'maison_guest_request':guest}})
    # The dedicated compositor reads the authoritative server catalog. Sending
    # its full schema again to the conversational planner duplicates thousands
    # of tokens and exposes low-level layout syntax to the wrong model step.
    # Other guest/application context remains intact in both UI modes.
    input=input.model_copy(update={'context':[entry for entry in input.context if not entry.description.startswith('A2UI Component Schema')]})
    encoder=EventEncoder()
    def failure(code,message):return 'data: '+json.dumps({'type':'RUN_ERROR','code':code,'message':message})+'\n\n'
    async def events():
        started=time.perf_counter();first_text=None;first_ui=None;first_content=None;text_deltas=0;tool_started={}
        async with session_lock(run_locks,sid):
            logger.info('maison_run run=%s queue_ms=%d',input.run_id,round((time.perf_counter()-started)*1000))
            ui_token=active_ui_action.set(action)
            token=confirmed_action.set(action.context.model_dump() if action and action.name=='confirm_order' else None)
            reservation_token=confirmed_reservation.set(action.context.model_dump() if action and action.name=='confirm_reservation' else None)
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
                active_ui_action.reset(ui_token);confirmed_action.reset(token);confirmed_reservation.reset(reservation_token)
                logger.info('maison_run run=%s complete_ms=%d text_deltas=%d first_text_ms=%s first_ui_ms=%s first_ui_content_ms=%s',input.run_id,round((time.perf_counter()-started)*1000),text_deltas,first_text,first_ui,first_content)
    return StreamingResponse(events(),media_type='text/event-stream',headers={'Cache-Control':'no-cache, no-transform','X-Accel-Buffering':'no'})
