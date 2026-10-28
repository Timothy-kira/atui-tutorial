// Enabled only for the embedded DevFest presentation. No agent request is sent.
export function connectPresentation(){
 if(window.parent===window||new URLSearchParams(window.location.search).get('presentation')!=='devfest')return;
 const channel='devfest-maison-presentation';
 const parentOrigin=document.referrer?new URL(document.referrer).origin:null;
 let frame:number|null=null,sequence=0,runId=0,disposed=false;
 const waits=new Set<()=>void>();
 const send=(type:string,detail:Record<string,unknown>={})=>window.parent.postMessage({channel,type,runId,...detail},parentOrigin&&parentOrigin!=='null'?parentOrigin:'*');
 const stop=()=>{if(frame!==null)cancelAnimationFrame(frame);frame=null;document.documentElement.classList.remove('devfest-pointer');};
 const cursorStyle=document.createElement('style');
 cursorStyle.textContent='html.devfest-pointer,html.devfest-pointer *{cursor:none!important}';
 document.head.append(cursorStyle);
 function ready():Promise<boolean>{
  const exists=()=>!!document.querySelector('#menu-view .menu-item')&&!!document.getElementById('agent-tab');
  if(exists())return Promise.resolve(true);
  return new Promise(resolve=>{
   const finish=(ok:boolean)=>{clearTimeout(timer);observer.disconnect();waits.delete(cancel);resolve(ok);};
   const cancel=()=>finish(false);
   const observer=new MutationObserver(()=>{if(exists())finish(true);});
   const timer=setTimeout(()=>finish(false),30000);
   waits.add(cancel);observer.observe(document.body,{childList:true,subtree:true});
  });
 }
 const nextPaint=()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve())));
 function agentRect(){
  const box=document.getElementById('agent-tab')?.getBoundingClientRect();
  return box?{x:box.x,y:box.y,width:box.width,height:box.height}:null;
 }
 async function receive(event:MessageEvent){
  if(event.source!==window.parent||(parentOrigin&&event.origin!==parentOrigin)||event.data?.channel!==channel)return;
  const data=event.data;
  if(typeof data.runId!=='number')return;
  runId=data.runId;
  if(data.action==='stop'){sequence++;stop();return;}
  if(data.action==='pointer'){document.documentElement.classList.add('devfest-pointer');return;}
  if(data.action==='locate-agent'){
   const token=++sequence;stop();
   if(!await ready()||disposed||token!==sequence)return;
   window.scrollTo({top:0,behavior:'instant'});
   await nextPaint();
   if(!disposed&&token===sequence)send('agent-position',{agentRect:agentRect()});
   return;
  }
  if(data.action==='prepare'){
   const token=++sequence;stop();
   if(!await ready()||disposed||token!==sequence)return;
   document.getElementById('menu-tab')?.click();
   await document.fonts.ready;
   await Promise.all([...document.querySelectorAll<HTMLImageElement>('#menu-view img')].map(image=>image.decode().catch(()=>{})));
   if(disposed||token!==sequence)return;
   await nextPaint();
   if(disposed||token!==sequence)return;
   window.scrollTo({top:0,behavior:'instant'});
   send('prepared');return;
  }
  if(data.action==='explore'){
   const token=++sequence;stop();
   if(!await ready()||disposed||token!==sequence)return;
   const scroller=document.scrollingElement;
   if(!scroller)return;
   const speed=Math.max(20,Math.min(150,Number(data.speed)||70));
   let position=scroller.scrollTop,previous:number|null=null;
   function scroll(now:number){
    if(disposed||token!==sequence)return;
    if(document.hidden){previous=null;frame=requestAnimationFrame(scroll);return;}
    if(previous!==null)position+=speed*(now-previous)/1000;
    previous=now;
    const bottom=Math.max(0,scroller!.scrollHeight-window.innerHeight);
    window.scrollTo({top:Math.min(position,bottom),behavior:'instant'});
    if(position>=bottom-1){window.scrollTo({top:bottom,behavior:'instant'});frame=null;send('explore-complete',{agentRect:agentRect()});return;}
    frame=requestAnimationFrame(scroll);
   }
   frame=requestAnimationFrame(scroll);return;
  }
  if(data.action==='recommend'){
   const token=++sequence;stop();
   if(!await ready()||disposed||token!==sequence)return;
   document.getElementById('agent-tab')?.click();
   await nextPaint();
   if(!disposed&&token===sequence)send('recommend-ready');
  }
 }
 const interrupted=()=>{if(frame!==null){sequence++;stop();send('interrupted');}};
 const navigate=(event:KeyboardEvent)=>{
  if(event.defaultPrevented||event.altKey||event.ctrlKey||event.metaKey||event.shiftKey)return;
  if(event.target instanceof HTMLElement&&event.target.closest('input,textarea,select,[contenteditable="true"]'))return;
  if(['ArrowRight','ArrowLeft','PageDown','PageUp',' '].includes(event.key)){event.preventDefault();send(['ArrowLeft','PageUp'].includes(event.key)?'navigate-back':'navigate-next');}
 };
 window.addEventListener('message',receive);
 window.addEventListener('wheel',interrupted,{passive:true});
 window.addEventListener('pointerdown',interrupted,{passive:true});
 window.addEventListener('keydown',navigate);
 send('ready');
 return()=>{disposed=true;sequence++;stop();waits.forEach(cancel=>cancel());cursorStyle.remove();window.removeEventListener('message',receive);window.removeEventListener('wheel',interrupted);window.removeEventListener('pointerdown',interrupted);window.removeEventListener('keydown',navigate);};
}
