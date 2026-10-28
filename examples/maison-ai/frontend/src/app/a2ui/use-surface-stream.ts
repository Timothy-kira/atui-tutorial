'use client';
import {useCallback,useEffect,useRef,useState,type RefObject} from 'react';
import type {Selection} from './context';

export type SurfaceOperation=Record<string,unknown>;
export type StreamUpdate={phase?:string;streamId?:string;toolCallId?:string;surfaceId?:string;operations?:SurfaceOperation[];operation?:SurfaceOperation};
type Snapshot={create:SurfaceOperation;components:Map<string,SurfaceOperation>;data:Map<string,SurfaceOperation>};
const clone=(value:Snapshot):Snapshot=>({create:value.create,components:new Map(value.components),data:new Map(value.data)});
const SURFACE_KEYS=['createSurface','updateComponents','updateDataModel','deleteSurface'];
const ORPHAN_LIMIT=200;

function surfaceOf(op:SurfaceOperation):string|undefined{
 for(const key of SURFACE_KEYS){
  const value=op[key] as {surfaceId?:unknown}|undefined;
  if(value&&typeof value.surfaceId==='string')return value.surfaceId;
 }
 return undefined;
}

export function useSurfaceStream(processMessages:(ops:SurfaceOperation[])=>void,selections:RefObject<Record<string,Selection>>,onPaint:()=>void){
 const [surfaces,setSurfaces]=useState<string[]>([]),[operations,setOperations]=useState<SurfaceOperation[]>([]);
 const [loadingSurfaces,setLoadingSurfaces]=useState<string[]>([]),[failedSurfaces,setFailedSurfaces]=useState<string[]>([]);
 const failed=useRef(new Set<string>()),paint=useRef(onPaint);paint.current=onPaint;
 const cache=useRef(new Map<string,Snapshot>()),drafts=useRef(new Map<string,{sid:string;prior?:Snapshot}>());
 const queue=useRef<SurfaceOperation[]>([]),pending=useRef<{kind:'frame'|'timer';id:number}|null>(null),order=useRef<string[]>([]);
 const orphans=useRef(new Map<string,SurfaceOperation[]>());
 const flush=useCallback(()=>{
  const handle=pending.current;
  if(handle){if(handle.kind==='frame')cancelAnimationFrame(handle.id);else clearTimeout(handle.id);pending.current=null;}
  const batch=queue.current.splice(0);
  if(batch.length){processMessages(batch);setOperations(old=>[...old,...batch].slice(-200));setSurfaces([...order.current]);}
  setLoadingSurfaces([...drafts.current.values()].map(value=>value.sid));setFailedSurfaces([...failed.current]);paint.current();
 },[processMessages]);
 // requestAnimationFrame is paused while the tab is hidden, and a slow model
 // turn makes switching tabs routine. A timer keeps streamed surfaces landing.
 const paintSoon=useCallback(()=>{
  if(pending.current||!queue.current.length)return;
  if(typeof document!=='undefined'&&document.visibilityState==='hidden')
   pending.current={kind:'timer',id:setTimeout(flush,0) as unknown as number};
  else pending.current={kind:'frame',id:requestAnimationFrame(flush)};
 },[flush]);
 const apply=useCallback((ops:SurfaceOperation[])=>{
  const touched=new Set<string>();
  const ingest=(op:SurfaceOperation):void=>{
   const create=op.createSurface as {surfaceId:string}|undefined;
   const remove=op.deleteSurface as {surfaceId:string}|undefined;
   if(remove){cache.current.delete(remove.surfaceId);order.current=order.current.filter(id=>id!==remove.surfaceId);queue.current.push(op);return;}
   if(create){
    if(cache.current.has(create.surfaceId))return;
    cache.current.set(create.surfaceId,{create:op,components:new Map(),data:new Map()});
    order.current=[create.surfaceId,...order.current];queue.current.push(op);
    // Anything that arrived before this surface now has somewhere to land.
    const held=orphans.current.get(create.surfaceId);orphans.current.delete(create.surfaceId);
    for(const late of held??[])ingest(late);
    return;
   }
   const update=op.updateComponents as {surfaceId:string;components:SurfaceOperation[]}|undefined;
   if(update){
    touched.add(update.surfaceId);
    const state=cache.current.get(update.surfaceId);if(!state)return;
    const fresh=update.components.filter(node=>{
     const id=String(node.id);if(JSON.stringify(state.components.get(id))===JSON.stringify(node))return false;
     state.components.set(id,node);return true;
    });
    if(fresh.length)queue.current.push({...op,updateComponents:{...update,components:fresh}});
    return;
   }
   const data=op.updateDataModel as {surfaceId:string;path?:string;value:unknown}|undefined;
   if(data){
    const state=cache.current.get(data.surfaceId);if(!state)return;
    const path=data.path||'/';if(path==='/selections'||path.startsWith('/selections/'))return;
    const value=path==='/'&&data.value&&typeof data.value==='object'&&!Array.isArray(data.value)?{...data.value,selections:selections.current}:data.value;
    const next={...op,updateDataModel:{...data,value}};
    if(JSON.stringify(state.data.get(path))===JSON.stringify(next))return;
    // A parent write invalidates cached descendant writes, including prior runs.
    for(const key of state.data.keys())if(path==='/'||key.startsWith(path+'/'))state.data.delete(key);
    state.data.set(path,next);queue.current.push(next);
   }
  };
  for(const op of ops){
   const sid=surfaceOf(op);
   if(sid&&!op.deleteSurface&&!cache.current.has(sid)){
    // An update whose surface has not been announced yet is held, not dropped.
    const held=orphans.current.get(sid);
    if(held){if(held.length<ORPHAN_LIMIT)held.push(op);}
    else orphans.current.set(sid,[op]);
    continue;
   }
   ingest(op);
  }
  for(const id of touched)if(cache.current.has(id)&&!order.current.includes(id))order.current=[id,...order.current];
  paintSoon();
 },[paintSoon,selections]);
 const restore=useCallback((sid:string,prior?:Snapshot)=>{
  const ops:SurfaceOperation[]=[{version:'v0.9',deleteSurface:{surfaceId:sid}}];
  if(prior)ops.push(prior.create,{version:'v0.9',updateComponents:{surfaceId:sid,components:[...prior.components.values()]}},...prior.data.values());
  apply(ops);
 },[apply]);
 const stream=useCallback((value:StreamUpdate)=>{
  const {phase,streamId,surfaceId}=value;
  if(phase==='begin'&&streamId&&surfaceId){
   failed.current.delete(surfaceId);
   const existing=drafts.current.get(streamId);
   if(existing)restore(existing.sid,existing.prior);
   else {const prior=cache.current.get(surfaceId);drafts.current.set(streamId,{sid:surfaceId,prior:prior?clone(prior):undefined});}
  }
  if(phase==='rollback'&&streamId){
   const draft=drafts.current.get(streamId);if(draft)recover(draft.sid,draft.prior);
   drafts.current.delete(streamId);return;
  }
  apply(value.operations||(value.operation?[value.operation]:[]));
  if(phase==='commit'&&streamId){drafts.current.delete(streamId);if(surfaceId)failed.current.delete(surfaceId);}
 },[apply,restore]);
 function recover(sid:string,prior?:Snapshot){
  if(prior){restore(sid,prior);return;}
  const state=cache.current.get(sid);
  if(!state||![...state.components.values()].some(value=>value.component!=='Skeleton')){restore(sid);return;}
  failed.current.add(sid);
  const missing=[...state.components.values()].filter(value=>value.component==='Skeleton').map(value=>({...value,failed:true}));
  // Preserve validated fields and mark just the missing parts as failed.
  apply([{version:'v0.9',updateComponents:{surfaceId:sid,components:missing}}]);
 }
 const rollback=useCallback(()=>{
  const hadDrafts=drafts.current.size>0;
  for(const draft of drafts.current.values())recover(draft.sid,draft.prior);
  drafts.current.clear();return hadDrafts;
 },[restore]);
 useEffect(()=>{
  const wake=()=>{if(document.visibilityState==='visible'&&pending.current?.kind==='timer')flush();};
  document.addEventListener('visibilitychange',wake);return()=>document.removeEventListener('visibilitychange',wake);
 },[flush]);
 useEffect(()=>()=>{const handle=pending.current;if(handle){if(handle.kind==='frame')cancelAnimationFrame(handle.id);else clearTimeout(handle.id);}},[]);
 return {surfaces,operations,loadingSurfaces,failedSurfaces,apply,stream,rollback,flush};
}
