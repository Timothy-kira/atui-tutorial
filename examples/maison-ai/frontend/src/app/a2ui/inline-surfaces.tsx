'use client';
import {createContext,useContext} from 'react';
import {A2UIRenderer} from '@copilotkit/a2ui-renderer';
import {SurfaceContext,SurfaceLoadContext} from './context';
import {Skeleton} from './skeleton';

export const InlineSurfaceContext=createContext<{
 byTool:Record<string,string[]>;surfaces:string[];loading:string[];failed:string[];
 retry:()=>void;busy:boolean;desktop:boolean;openTool:(id:string)=>void;collapsed:boolean;setCollapsed:(value:boolean)=>void;
}>({byTool:{},surfaces:[],loading:[],failed:[],retry:()=>{},busy:false,desktop:false,openTool:()=>{},collapsed:false,setCollapsed:()=>{}});

const uiTools=new Set(['render_a2ui','recommend_dishes','quote_order','place_order','get_cart','update_cart','calculate_total_calories','show_reservation','check_reservation','reserve_table','mock_show_menu','ui_action']);

export function InlineToolResponse({toolCallId,name,status,result}:{toolCallId:string;name:string;status:string;result?:string}){
 const feed=useContext(InlineSurfaceContext);
 const ids=(feed.byTool[toolCallId]||[]).filter(id=>feed.surfaces.includes(id));
 if(!ids.length){
  if(!uiTools.has(name)||status==='complete')return null;
  return <div className="inline-loading"><Skeleton variant="line"/></div>;
 }
 if(feed.desktop)return <button className="inline-a2ui-mini" onClick={()=>feed.openTool(toolCallId)} aria-label="Open dining cards">Dining cards <span className="card-open-arrow" aria-hidden="true"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M5 12h14m-6-6 6 6-6 6"/></svg></span></button>;
 return <SurfaceCards ids={ids}/>;
}

export function SurfaceCards({ids}:{ids:string[]}){
 const feed=useContext(InlineSurfaceContext);
 return <div className="inline-a2ui">{ids.map(id=>{
  const failed=feed.failed.includes(id),loading=feed.loading.includes(id);
  return <SurfaceContext.Provider key={id} value={id}><SurfaceLoadContext.Provider value={failed?'failed':loading?'loading':'ready'}>
   <div className="surface-shell" data-testid="a2ui-surface" data-surface-id={id} aria-busy={loading}><A2UIRenderer surfaceId={id}/>
    {failed&&<div className="stream-error" role="alert">Some content could not load.<button disabled={feed.busy} onClick={feed.retry}>Try again</button></div>}
   </div>
  </SurfaceLoadContext.Provider></SurfaceContext.Provider>;
 })}</div>;
}
