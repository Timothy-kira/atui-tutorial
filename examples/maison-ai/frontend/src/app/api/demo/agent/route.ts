export const runtime='nodejs';
export const dynamic='force-dynamic';

const encoder=new TextEncoder();
const frame=(payload:unknown)=>encoder.encode('data: '+JSON.stringify(payload)+'\n\n');
const interrupted=(code='CONNECTION_INTERRUPTED',message='Connection interrupted. Your cart and completed cards are saved. Please try your request again.')=>frame({type:'RUN_ERROR',code,message});

// AG-UI frames are separated by a blank line and JSON escapes newlines, so a
// frame body can never contain one. Reading the forwarded bytes back is enough
// to tell a run that finished from one whose body was cut off mid-flight.
const TERMINAL=new Set(['RUN_FINISHED','RUN_ERROR']);
function createRunWatch(){
  let pending='',terminal=false;
  return {
    push(chunk:Uint8Array){
      pending+=Buffer.from(chunk).toString('utf8');
      let cut=pending.indexOf('\n\n');
      while(cut>=0){
        const block=pending.slice(0,cut);pending=pending.slice(cut+2);cut=pending.indexOf('\n\n');
        for(const line of block.split('\n')){
          if(!line.startsWith('data:'))continue;
          try{if(TERMINAL.has(JSON.parse(line.slice(5)).type))terminal=true;}catch{/* Incomplete frame. */}
        }
      }
      // An oversized single frame is never a terminal one, so resync instead of
      // holding an unbounded buffer.
      if(pending.length>1048576){const at=pending.lastIndexOf('\n\n');pending=at<0?'':pending.slice(at+2);}
    },
    mark(){terminal=true;},
    get terminal(){return terminal;},
  };
}

export async function POST(request:Request){
 const controller=new AbortController();
 const abort=()=>controller.abort();
 request.signal.addEventListener('abort',abort,{once:true});
 if(request.signal.aborted)controller.abort();
 try{
  const upstream=await fetch('http://127.0.0.1:8008/agent',{
   method:'POST',headers:{'Content-Type':'application/json',Accept:'text/event-stream'},
   body:await request.text(),signal:controller.signal,cache:'no-store',
  });
  if(!upstream.ok||!upstream.body){
   request.signal.removeEventListener('abort',abort);
   await upstream.body?.cancel();
   return Response.json({error:'The dining assistant is unavailable. Please try again.'},{status:upstream.status>=400?upstream.status:502});
  }
  const reader=upstream.body.getReader();
  const watch=createRunWatch();
  let closed=false;
  let heartbeat:ReturnType<typeof setInterval>|undefined;
  const cleanup=()=>{closed=true;if(heartbeat)clearInterval(heartbeat);request.signal.removeEventListener('abort',abort);};
  const body=new ReadableStream<Uint8Array>({
   async start(output){
    // The browser must see a terminal frame, otherwise it parses a truncated
    // stream and reports the whole run as a network error.
    const write=(bytes:Uint8Array)=>{if(closed)return;try{output.enqueue(bytes);}catch{/* The browser already disconnected. */}};
    // SSE comments keep idle model/tool connections alive without producing chat events.
    heartbeat=setInterval(()=>write(encoder.encode(': keepalive\n\n')),10000);
    try{
     while(!closed){const {done,value}=await reader.read();if(done)break;watch.push(value);write(value);}
    }catch(error){
     if(!closed&&!controller.signal.aborted){
      console.error('Maison stream interrupted:',error instanceof Error?error.name:'UnknownError');
      watch.mark();write(interrupted());
     }
    }finally{
     if(!watch.terminal){watch.mark();write(interrupted('RUN_TRUNCATED','The agent stopped before it finished. Your cart and completed cards are saved. Please try your request again.'));}
     if(!closed){cleanup();try{output.close();}catch{/* The runtime already closed the stream. */}}
     reader.releaseLock();
    }
   },
   async cancel(){cleanup();controller.abort();try{await reader.cancel();}catch{/* Client has already disconnected. */}},
  });
  return new Response(body,{headers:{'Content-Type':'text/event-stream','Cache-Control':'no-cache, no-transform','X-Accel-Buffering':'no'}});
 }catch(error){
  request.signal.removeEventListener('abort',abort);
  if(!controller.signal.aborted)console.error('Maison connection failed:',error instanceof Error?error.name:'UnknownError');
  return Response.json({error:'The dining assistant is unavailable. Please try again.'},{status:503});
 }
}
