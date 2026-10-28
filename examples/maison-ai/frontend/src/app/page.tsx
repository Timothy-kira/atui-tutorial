'use client';
import {useEffect,useMemo,useRef,useState} from 'react';
import {CopilotKit,CopilotChat,useAgent,useAgentContext,useHumanInTheLoop,useRenderTool} from '@copilotkit/react-core/v2';
import {HttpAgent} from '@ag-ui/client';
import {A2UIProvider,A2UIRenderer,useA2UI,extractCatalogComponentSchemas,A2UI_SCHEMA_CONTEXT_DESCRIPTION} from '@copilotkit/a2ui-renderer';
import {z} from 'zod';
import {catalog} from './a2ui/catalog';
import {DiningContext,SurfaceContext,SurfaceLoadContext,type Dish,type Selection,type UIAction} from './a2ui/context';
import {money} from './a2ui/renderers';
import {connectPresentation} from './presentation-bridge';
import {InlineSurfaceContext,InlineToolResponse,SurfaceCards} from './a2ui/inline-surfaces';
import {useSurfaceStream,type StreamUpdate,type SurfaceOperation} from './a2ui/use-surface-stream';

type CartItem={id:string;dish_id:string;name:string;quantity:number;options:Record<string,string>;line_total_cents:number};
type Cart={items:CartItem[];total_cents:number;count:number;revision:number;total_calories_kcal?:number};
type WireEvent=Record<string,unknown>&{type:string};
const emptyCart:Cart={items:[],total_cents:0,count:0,revision:-1};
const categories=[['all','All'],['appetizer','Starters'],['main','Mains'],['pasta_pizza','Pasta & pizza'],['dessert','Desserts'],['drink','Drinks']];
function DishDetails({dish,busy,onClose,onAdd}:{dish:Dish;busy:boolean;onClose:()=>void;onAdd:(selection:Selection)=>Promise<boolean>}){
 const dialog=useRef<HTMLDialogElement>(null);const [quantity,setQuantity]=useState(1);const [submitError,setSubmitError]=useState(false);
 const [options,setOptions]=useState<Record<string,string>>(()=>Object.fromEntries(Object.entries(dish.options).map(([name,values])=>[name,name==='doneness'?'':values[0]])));
 useEffect(()=>{dialog.current?.showModal();},[]);
 return <dialog ref={dialog} className="dish-dialog" onCancel={onClose} onClose={onClose} aria-labelledby="dish-name"><button className="dialog-close" aria-label="Close dish details" onClick={onClose}>×</button><img className="detail-photo" src={dish.image} alt={dish.name} onError={e=>{e.currentTarget.src='/images/placeholder.svg';}}/><div className="detail-body"><div className="menu-item-heading"><h2 id="dish-name">{dish.name}</h2><strong>{money(Math.round(dish.price*100))}</strong></div><p>{dish.description}</p><section className="detail-section"><h3>How it’s made</h3><p>{dish.preparation}</p></section><div className="dish-fact-grid detail-facts"><div><span>Energy · estimate</span><strong>{dish.calories_kcal} kcal</strong><small>per serving</small></div><div><span>Serving</span><strong>{dish.servings.people} {dish.servings.style}</strong><small>{dish.servings.note}</small></div></div><section className="detail-section allergen-section"><h3>Declared allergens</h3><p>{dish.allergens.length?dish.allergens.join(', '):'No major allergens declared in this demo recipe.'}</p><small>{dish.allergen_note}</small></section>{Object.entries(dish.options).map(([name,values])=><label className="option-control" key={name}><span>{name==='doneness'?'How would you like it?':name.replaceAll('_',' ')}</span><select value={options[name]} onChange={e=>setOptions({...options,[name]:e.target.value})}>{name==='doneness'&&<option value="" disabled>Choose doneness</option>}{values.map(v=><option key={v} value={v}>{v.replaceAll('-',' ')}</option>)}</select></label>)}<div className="detail-footer"><div className="menu-quantity"><button aria-label="Decrease quantity" disabled={quantity<=1} onClick={()=>setQuantity(quantity-1)}>−</button><output>{quantity}</output><button aria-label="Increase quantity" disabled={quantity>=20} onClick={()=>setQuantity(quantity+1)}>+</button></div><button className="primary-button" disabled={busy||Object.keys(dish.options).some(name=>!options[name])} onClick={async()=>{setSubmitError(false);if(await onAdd({quantity,options}))onClose();else setSubmitError(true);}}>{busy?'Adding…':'Add to table · '+money(Math.round(dish.price*100)*quantity)}</button></div>{submitError&&<p className="detail-error" role="alert">Could not add this dish. Please try again.</p>}<small className="nutrition-note">{dish.nutrition_basis}</small></div></dialog>;
}
function MenuBrowser({menu,cart,busy,onAdd}:{menu:Dish[];cart:Cart;busy:boolean;onAdd:(dish:Dish,selection:Selection)=>Promise<boolean>}){
 const [category,setCategory]=useState('all');const [selected,setSelected]=useState<Dish|null>(null);
 const known=categories.filter(([id])=>id==='all'||menu.some(d=>d.category===id));
 return <><nav className="menu-categories" aria-label="Menu categories">{known.map(([id,label])=><button key={id} aria-pressed={category===id} onClick={()=>setCategory(id)}>{label}</button>)}</nav><div className="menu-list">{known.filter(([id])=>id!=='all'&&(category==='all'||category===id)).map(([id,label])=><section className="menu-category" key={id} aria-label={label}><h2>{label}</h2>{menu.filter(d=>d.category===id).map(d=><button className="menu-item" key={d.id} disabled={!d.available} onClick={()=>setSelected(d)} aria-label={`Choose ${d.name}`}><img src={d.image} alt="" onError={e=>{e.currentTarget.src='/images/placeholder.svg';}}/><span className="menu-item-copy"><span className="menu-item-heading"><strong>{d.name}</strong><span>{money(Math.round(d.price*100))}</span></span><span className="menu-description">{d.description}</span><span className="menu-dietary">{!d.available?'Sold out':d.vegan?'Plant-based':d.vegetarian?'Vegetarian':''}</span></span><span className="menu-add" data-selected={cart.items.some(item=>item.dish_id===d.id)} aria-label={`${cart.items.filter(item=>item.dish_id===d.id).reduce((total,item)=>total+item.quantity,0)} at your table`}>{cart.items.filter(item=>item.dish_id===d.id).reduce((total,item)=>total+item.quantity,0)||<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>}</span></button>)}</section>)}</div>{!menu.length&&<p className="menu-loading" role="status">Loading the menu…</p>}{selected&&<DishDetails key={selected.id} dish={selected} busy={busy} onClose={()=>setSelected(null)} onAdd={selection=>onAdd(selected,selection)}/>}</>;
}
function Choice({question,options,respond}:{question:string;options:string[];respond?:((value:unknown)=>Promise<void>)}){const [choice,setChoice]=useState('');return <div className="choice-card"><h3>{question}</h3><div className="choice-options">{options.map(o=><button key={o} aria-pressed={choice===o} onClick={()=>setChoice(o)} disabled={!respond}>{o.replaceAll('-',' ')}</button>)}</div><div className="choice-actions"><button onClick={()=>respond?.({cancelled:true})} disabled={!respond}>Cancel</button><button className="primary-button" disabled={!choice||!respond} onClick={()=>respond?.({selection:choice})}>Confirm choice</button></div></div>;}

const suggestedPrompts=['Recommend dinner for two','Show me vegetarian mains','What’s in the lemonade?','Build a meal under S$60'];

function Restaurant({thread}:{thread:string}){
 const {agent}=useAgent({agentId:'maison',throttleMs:0});const actionPending=useRef(false);
 const {processMessages}=useA2UI();
 const [toolSurfaces,setToolSurfaces]=useState<Record<string,string[]>>({});
 const [surfacesCollapsed,setSurfacesCollapsed]=useState(false);
 const [activeTool,setActiveTool]=useState('');
 const [desktop,setDesktop]=useState(false);
 useEffect(()=>{const media=window.matchMedia('(min-width: 1000px)');const update=()=>setDesktop(media.matches);update();media.addEventListener('change',update);return()=>media.removeEventListener('change',update);},[]);
 const surfaceOwners=useRef(new Map<string,string>());
 function scopeOperations(ops:SurfaceOperation[],owner:string,source?:string){
  return ops.map(op=>{
   const key=['createSurface','updateComponents','updateDataModel','deleteSurface'].find(key=>op[key]);
   if(!key)return op;
   const value=op[key] as Record<string,unknown>,base=String(value.surfaceId);
   const sid=source||(surfaceOwners.current.has(base)||base.startsWith('generated-')?base:base+'--'+owner);
   if(!surfaceOwners.current.has(sid)){
    surfaceOwners.current.set(sid,owner);
    setActiveTool(owner);setSurfacesCollapsed(false);
    setToolSurfaces(current=>({...current,[owner]:[...new Set([...(current[owner]||[]),sid])]}));
   }
   return {...op,[key]:{...value,surfaceId:sid}};
  });
 }
 useRenderTool({name:'*',render:props=><InlineToolResponse {...props}/>},[]);
 const [menu,setMenu]=useState<Dish[]>([]);const [cart,setCart]=useState<Cart>(emptyCart);
 const [provider,setProvider]=useState('connecting');
 const [events,setEvents]=useState<WireEvent[]>([]);
 const [pendingSurface,setPendingSurface]=useState<'card'|'cards'|null>(null);
 const [retryable,setRetryable]=useState(false);
 const [busy,setBusy]=useState(false);const [activity,setActivity]=useState('Working…');const [error,setError]=useState('');const [inspector,setInspector]=useState(false);const [raw,setRaw]=useState(false);
 const [view,setView]=useState<'menu'|'agent'>('menu');const [cartOpen,setCartOpen]=useState(false);const cartDialog=useRef<HTMLDialogElement>(null);
 useEffect(()=>{window.scrollTo({top:0,behavior:'instant'});},[view]);
 useEffect(()=>{if(cartOpen)cartDialog.current?.showModal();else cartDialog.current?.close();},[cartOpen]);
 const [selections,setSelections]=useState<Record<string,Selection>>({});const selectionRef=useRef(selections);const seen=useRef(new Set<string>());
 const {surfaces,operations,loadingSurfaces,failedSurfaces,apply,stream,rollback,flush}=useSurfaceStream(processMessages,selectionRef,()=>setPendingSurface(null));
 const schema=useMemo(()=>JSON.stringify(extractCatalogComponentSchemas(catalog)),[]);
 useAgentContext({description:A2UI_SCHEMA_CONTEXT_DESCRIPTION,value:schema});
 useHumanInTheLoop({name:'ask_user',description:'Ask a required single-choice question. A cancelled response means stop this choice.',parameters:z.object({question:z.string(),options:z.array(z.string())}),render:({args,respond})=><Choice question={args.question||'One quick question'} options={args.options||[]} respond={respond}/>},[]);
 const acceptCart=(incoming:Cart)=>{if(!incoming||!Array.isArray(incoming.items))return;const next={...incoming,count:incoming.items.reduce((n,item)=>n+item.quantity,0),revision:Number.isFinite(incoming.revision)?incoming.revision:0};setCart(current=>next.revision<current.revision?current:next);};
 function acceptRecommendation(value:{candidates?:{id:string;recommended_quantity:number}[]}){
  if(!Array.isArray(value?.candidates))return;
  const next={...selectionRef.current};
  value.candidates.forEach(dish=>{next[dish.id]={...next[dish.id],quantity:next[dish.id]?.quantity??dish.recommended_quantity};});
  selectionRef.current=next;setSelections(next);
 }
 const refreshCart=()=>fetch('/api/demo/cart/'+thread,{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('Could not load cart');return r.json();}).then(acceptCart);
 useEffect(()=>{Promise.all([fetch('/api/demo/menu').then(r=>r.json()).then(d=>setMenu(d.dishes)),fetch('/api/demo/health').then(r=>r.json()).then(d=>setProvider(d.provider)),refreshCart()]).catch(()=>setError('The dining assistant is offline. Start the Python backend.'));},[thread]);
 useEffect(()=>{
   const sub=agent.subscribe({onEvent:({event})=>{
     const e=event as unknown as WireEvent;
     // Keep actual protocol events, without displaying model reasoning content.
     if(!e.type.startsWith('REASONING'))setEvents(old=>[...old.slice(-199),e]);
     if(e.type==='RUN_STARTED'){setBusy(true);setActivity('Working on your request…');setError('');setRetryable(false);}
     if(e.type==='TOOL_CALL_START'){const labels:Record<string,string>={get_cart:'Checking your table…',get_menu:'Reading the menu…',get_dish_details:'Checking dish details…',update_cart:'Updating your table…',recommend_dishes:'Finding dishes for you…',calculate_total_calories:'Calculating recipe energy…',show_reservation:'Preparing your reservation…',check_reservation:'Checking available tables…',reserve_table:'Confirming your table…',generate_a2ui:'Preparing your dining options…',ask_user:'Waiting for your choice…'};setActivity(labels[String(e.toolCallName)]||'Preparing your response…');}
     if(e.type==='TOOL_CALL_RESULT')setActivity('Preparing your response…');
     if(e.type==='TOOL_CALL_START'&&['recommend_dishes','generate_a2ui','quote_order','calculate_total_calories','show_reservation','check_reservation'].includes(String(e.toolCallName)))setPendingSurface(['recommend_dishes','generate_a2ui'].includes(String(e.toolCallName))?'cards':'card');
     if(e.type==='TEXT_MESSAGE_CONTENT')setActivity('Writing your response…');
     if(e.type==='RUN_ERROR'){rollback();flush();setPendingSurface(null);setError(String(e.message||'Something went wrong'));setBusy(false);}
     if(e.type==='RUN_FINISHED'){if(rollback()){setError('The interface could not finish loading. Your previous choices are saved.');setRetryable(true);}flush();setPendingSurface(null);setBusy(false);void refreshCart().catch(()=>{});}
     // Read the cart from SQLite; an older ADK snapshot must not replace it.
     if(e.type==='CUSTOM'&&e.name==='A2UI_STREAM'){
       const payload=e.value as StreamUpdate|undefined;
       if(payload){const ops=scopeOperations(payload.operations||[],payload.toolCallId||payload.streamId||'ui',payload.surfaceId);stream({...payload,operations:ops});if(payload.phase==='rollback'){setError('The interface could not finish loading. Your previous choices are saved.');setRetryable(true);}}
     }
     if(e.type==='TOOL_CALL_RESULT'){
       const id=String(e.toolCallId);if(seen.current.has(id))return;
       try{const value=typeof e.content==='string'?JSON.parse(e.content):e.content;
         if(value?.a2ui_operations){seen.current.add(id);apply(scopeOperations(value.a2ui_operations,id));}
         if(value?.cart)acceptCart(value.cart);
         if(value?.recommendation)acceptRecommendation(value.recommendation);
         if(value?.error){setError(String(value.error));setPendingSurface(null);}
       }catch{/* Non-JSON tool results remain available in Inspector. */}
     }
   }});return ()=>sub.unsubscribe();
 },[agent,processMessages,thread,apply,stream,rollback,flush]);
 async function sendAction(action:UIAction):Promise<boolean>{
   if(actionPending.current)return false;
   let context={...action.context};
   if(action.name==='add_to_cart'){
     const id=String(context.dish_id);const dish=menu.find(d=>d.id===id);const choice=selectionRef.current[id];
     const defaults=Object.fromEntries(Object.entries(dish?.options||{}).filter(([name])=>name!=='doneness').map(([name,values])=>[name,values[0]]));
     context={...context,quantity:choice?.quantity??context.quantity??1,options:{...defaults,...(context.options as Record<string,string>||{}),...choice?.options}};
   }
   actionPending.current=true;setBusy(true);setActivity('Updating your table…');setError('');setRetryable(false);
   let paintQueued=false;
   if(['recommend_dishes','checkout','calculate_calories','open_reservation','check_reservation'].includes(action.name))setPendingSurface(action.name==='recommend_dishes'?'cards':'card');
   try{
     const response=await fetch('/api/demo/actions/'+thread,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:action.name,context})});
     const value=await response.json();
     if(!response.ok)throw Error(typeof value.detail==='string'?value.detail:'Could not update your table. Please try again.');
     acceptCart(value.cart);
     if(value.recommendation)acceptRecommendation(value.recommendation);
     if(typeof value.assistant_message==='string')agent.addMessage({id:crypto.randomUUID(),role:'assistant',content:value.assistant_message});
     if(value.a2ui_operations){
       const owner=action.surfaceId?surfaceOwners.current.get(action.surfaceId)||crypto.randomUUID():crypto.randomUUID();
       if(!action.surfaceId){
         agent.addMessage({id:crypto.randomUUID(),role:'assistant',toolCalls:[{id:owner,type:'function',function:{name:'ui_action',arguments:JSON.stringify({name:action.name})}}]});
         agent.addMessage({id:crypto.randomUUID(),role:'tool',toolCallId:owner,content:JSON.stringify({ok:true})});
       }
       apply(scopeOperations(value.a2ui_operations,owner,action.surfaceId));paintQueued=true;
       if(action.name==='recommend_dishes'){
         setActiveTool(owner);setSurfacesCollapsed(false);
         requestAnimationFrame(()=>document.querySelector('.dining-workspace-body')?.scrollTo({top:0,behavior:'smooth'}));
       }
     }
     if(['checkout','confirm_order','calculate_calories','recommend_dishes','open_reservation','check_reservation','confirm_reservation'].includes(action.name)){setView('agent');setCartOpen(false);}
     return true;
   }catch(cause){setError(cause instanceof Error?cause.message:'Could not update your table. Please try again.');return false;}
   finally{actionPending.current=false;setBusy(false);if(paintQueued)flush();else setPendingSurface(null);}
 }
 // Remove legacy UI-operation turns created by the old chat-based action handler.
 useEffect(()=>{
   let internalTurn=false;
   const messages=agent.messages.filter(message=>{
     if(message.role==='user'){
       internalTurn=false;
       if(typeof message.content==='string')try{internalTurn=!!JSON.parse(message.content)?.a2uiAction;}catch{}
     }
     return !internalTurn;
   });
   if(messages.length!==agent.messages.length)agent.setMessages(messages);
 },[agent]);
 useEffect(()=>{const listener=(e:Event)=>{void sendAction((e as CustomEvent<UIAction>).detail);};window.addEventListener('maison-action',listener);return()=>window.removeEventListener('maison-action',listener);},[menu,agent,processMessages,thread]);
 function change(id:string,patch:Selection,surfaceId:string){const existing=selectionRef.current[id]||{};const value={...existing,...patch,options:{...existing.options,...patch.options}};selectionRef.current={...selectionRef.current,[id]:value};setSelections(selectionRef.current);if(surfaceId)processMessages([{version:'v0.9',updateDataModel:{surfaceId,path:'/selections/'+id,value}}]);}
 function askSuggestedPrompt(prompt:string){
   if(busy||agent.isRunning)return;
   setError('');
   agent.addMessage({id:crypto.randomUUID(),role:'user',content:prompt});
   void agent.runAgent().catch(()=>{rollback();flush();setBusy(false);setError('Connection interrupted. Your cart is saved. Please send your message again.');});
 }
 const toolEvents=events.filter(e=>e.type==='TOOL_CALL_START');
 function retryResponse(){const last=[...agent.messages].reverse().find(message=>message.role==='user'&&typeof message.content==='string');if(last&&typeof last.content==='string')askSuggestedPrompt(last.content);}
 return <DiningContext.Provider value={{menu,selections,change:change,send:sendAction,busy}}><InlineSurfaceContext.Provider value={{byTool:toolSurfaces,surfaces,loading:loadingSurfaces,failed:failedSurfaces,retry:retryResponse,busy,collapsed:surfacesCollapsed,setCollapsed:setSurfacesCollapsed,desktop,openTool:(id:string)=>{setActiveTool(id);setSurfacesCollapsed(false);}}}>
   <header className="view-navigation"><div className="view-tabs" role="tablist" aria-label="Dining view" onKeyDown={e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const next=e.key==='Home'?'menu':e.key==='End'?'agent':view==='menu'?'agent':'menu';setView(next);document.getElementById(next+'-tab')?.focus();}}}>
     <span className="view-tab-indicator" style={{transform:`translateX(${view==='agent'?'100%':'0'})`}} aria-hidden="true"/>
     <button id="menu-tab" role="tab" aria-selected={view==='menu'} aria-controls="menu-view" tabIndex={view==='menu'?0:-1} onClick={()=>setView('menu')}>Menu</button>
     <button id="agent-tab" role="tab" aria-selected={view==='agent'} aria-controls="agent-view" tabIndex={view==='agent'?0:-1} onClick={()=>setView('agent')}>Agent</button>
   </div><button className="table-toggle" aria-label={`Your table, ${cart.count} items`} aria-haspopup="dialog" onClick={()=>setCartOpen(true)}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" width="21" height="21" aria-hidden="true"><path d="M5 7h14l1 14H4L5 7Z"/><path d="M8 8V6a4 4 0 0 1 8 0v2"/></svg><span>{cart.count}</span></button></header>
   {(provider==='mock'||error)&&<div className="app-notices">
     {provider==='mock'&&<div className="mode-notice">Mock Mode · scripted agent and UI fixtures. No live model generation.</div>}
     {error&&<div className="error-notice" role="alert">{error}</div>}
   </div>}
   <main className="tab-layout">
     <section id="menu-view" role="tabpanel" aria-labelledby="menu-tab" hidden={view!=='menu'} className="menu-view">
       <MenuBrowser menu={menu} cart={cart} busy={busy} onAdd={(dish,selection)=>{change(dish.id,selection,'');return sendAction({name:'add_to_cart',context:{dish_id:dish.id}});}}/>
       {busy&&<div className="menu-progress" role="status">Updating your table…</div>}
       <p className="demo-note">A fictional restaurant for DevFest. All orders are demo orders.</p>
     </section>
     <section id="agent-view" role="tabpanel" aria-labelledby="agent-tab" hidden={view!=='agent'} className="agent-view">
       <div className={`agent-content${desktop&&activeTool&&!surfacesCollapsed?' has-surfaces':''}`}>
         <section id="dining-chat" className="conversation" aria-label="Dining assistant">
           <div className="chat-stage">{agent.messages.length===0&&<section className="chat-welcome" aria-labelledby="chat-welcome-title"><div className="chat-welcome-copy"><p className="chat-welcome-eyebrow">MAISON DINING ASSISTANT</p><h1 id="chat-welcome-title">Good evening. What sounds good?</h1><p>I can recommend dishes, check ingredients and allergens, or help you build a meal for your table.</p></div><div className="suggested-prompts" aria-label="Suggested questions">{suggestedPrompts.map(prompt=><button className="suggested-prompt" key={prompt} disabled={busy} onClick={()=>askSuggestedPrompt(prompt)}><span>{prompt}</span><kbd aria-hidden="true">↵</kbd></button>)}</div></section>}{busy&&view==='agent'&&<div className="agent-activity" role="status"><span className="activity-spinner" aria-hidden="true"/>{activity}</div>}<CopilotChat agentId="maison" threadId={thread} autoScroll="none" throttleMs={0} welcomeScreen={false} className="maison-chat" labels={{chatInputPlaceholder:'What sounds good tonight?'}} onError={()=>{setBusy(false);setError('Connection interrupted. Your cart is saved. Please send your message again.');}}/></div>
         </section>
         {desktop&&activeTool&&!surfacesCollapsed&&<aside className="dining-workspace" aria-label="Dining cards"><header className="dining-workspace-header"><span>Dining cards</span><button aria-label="Collapse dining cards" onClick={()=>setSurfacesCollapsed(true)}>×</button></header><div className="dining-workspace-body"><SurfaceCards ids={(toolSurfaces[activeTool]||[]).filter(id=>surfaces.includes(id))}/></div></aside>}
       </div>
     </section>
   </main>
   <dialog ref={cartDialog} className="table-dialog" aria-label="Your table" onCancel={()=>setCartOpen(false)} onClose={()=>setCartOpen(false)}><button className="dialog-close" aria-label="Close your table" onClick={()=>setCartOpen(false)}>×</button>
     <section className="cart-panel" aria-label="Your cart"><div className="panel-heading"><h2>Your table</h2><span>{cart.count} items</span></div>{cart.items.length===0?<p className="empty-cart">Something delicious will go here.</p>:<div className="cart-lines">{cart.items.map(item=><div className="cart-line" key={item.id}><div><strong>{item.name}</strong><small>{Object.values(item.options).join(' · ').replaceAll('-',' ')}</small><div className="cart-stepper"><button aria-label={'Decrease '+item.name} disabled={busy||item.quantity<=1} onClick={()=>sendAction({name:'update_item',context:{dish_id:item.dish_id,item_id:item.id,quantity:item.quantity-1,options:item.options}})}>−</button><span>{item.quantity}</span><button aria-label={'Increase '+item.name} disabled={busy||item.quantity>=20} onClick={()=>sendAction({name:'update_item',context:{dish_id:item.dish_id,item_id:item.id,quantity:item.quantity+1,options:item.options}})}>+</button><button className="remove-item" disabled={busy} onClick={()=>sendAction({name:'remove_item',context:{dish_id:item.dish_id,item_id:item.id}})}>Remove</button></div></div><b>{money(item.line_total_cents)}</b></div>)}</div>}<div className="cart-total"><span>Total</span><strong>{money(cart.total_cents)}</strong></div><button className="primary-button" disabled={busy||!cart.items.length} onClick={()=>sendAction({name:'checkout'})}>Checkout</button></section>
   </dialog>
   {inspector&&<section className="inspector" aria-label="Developer Inspector"><div className="panel-heading"><h2>Developer Inspector</h2><button onClick={()=>setInspector(false)}>Close</button></div><p>Actual captured events · A2UI v0.9 · menu.json + SQLite demo orders · {provider} mode</p><div className="inspector-grid"><div><h3>ADK tool calls</h3><pre>{toolEvents.map(e=>String(e.toolCallName)).join('\n')||'No tool calls yet.'}</pre></div><div><h3>AG-UI events</h3><pre>{JSON.stringify(events,null,2)}</pre></div><div><h3>Latest A2UI operations</h3><pre>{JSON.stringify(operations,null,2)}</pre></div><div><h3>Server cart</h3><pre>{JSON.stringify(cart,null,2)}</pre></div></div></section>}
 </InlineSurfaceContext.Provider></DiningContext.Provider>;
}

function App({thread}:{thread:string}){
 const agents=useMemo(()=>({maison:new HttpAgent({url:'/api/demo/agent',agentId:'maison',threadId:thread})}),[thread]);
 return <CopilotKit selfManagedAgents={agents} agentId="maison" enableInspector={false} showIntelligenceIndicator={false}><A2UIProvider catalog={catalog} onAction={message=>{if(message.userAction)window.dispatchEvent(new CustomEvent('maison-action',{detail:message.userAction}));}}><Restaurant thread={thread}/></A2UIProvider></CopilotKit>;
}
export default function Page(){const [thread,setThread]=useState('');useEffect(connectPresentation,[]);useEffect(()=>{const id=sessionStorage.getItem('maison-thread')||crypto.randomUUID();sessionStorage.setItem('maison-thread',id);setThread(id);},[]);return thread?<App thread={thread}/>:<div className="boot-screen">Maison <span>AI</span></div>;}
