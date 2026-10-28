"""One command for both servers, persistent logs and a bounded service watchdog."""
import argparse,json,os,signal,subprocess,sys,time,urllib.request
from pathlib import Path
from jobs import ROOT,pnpm,command,FLAGS,write,event,notify

folder=ROOT/'.local/servers';folder.mkdir(parents=True,exist_ok=True)
URL='http://127.0.0.1:3008'
# A recognized network fault gets a few attempts inside a rolling window, so a
# long workshop session is not capped at one restart for the whole afternoon.
RESTART_LIMIT=3
RESTART_WINDOW=600
RECOVERABLE=('ECONNRESET','ECONNABORTED','ETIMEDOUT','EPIPE','Temporary failure')
ERROR_KEYWORDS=('Traceback','Error:','ERROR:','RUN_ERROR')

def size(name):return (folder/(name+'.log')).stat().st_size

def since(name,offset):
    with (folder/(name+'.log')).open('rb') as f:
        f.seek(offset);return f.read().decode('utf-8',errors='replace')

def start(name,cwd,argv,env):
    log=open(folder/(name+'.log'),'a',encoding='utf-8');log.flush()
    return subprocess.Popen(command(argv),cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=FLAGS)

def launch(mock=False):
    env={**os.environ,'NEXT_TELEMETRY_DISABLED':'1','PYTHONUTF8':'1'}
    if mock:env['MODEL_PROVIDER']='mock'
    commands=[('backend',ROOT,['uv','run','uvicorn','backend.app:app','--host','127.0.0.1','--port','8008']),('frontend',ROOT/'frontend',[pnpm(),'dev'])]
    processes={};launched={};restarts={name:[] for name,_,_ in commands};last_sizes={};down=set()
    for name,cwd,argv in commands:
        processes[name]=start(name,cwd,argv,env);launched[name]=size(name);last_sizes[name]=launched[name]
    live=lambda:{name:p.pid for name,p in processes.items() if name not in down and p.poll() is None}
    write(folder/'status.json',dict(status='starting',pid=os.getpid(),children=live(),url=URL))
    try:
        while True:
            time.sleep(5)
            healthy={}
            for name,cwd,argv in commands:
                if name in down:
                    healthy[name]=False
                    continue
                p=processes[name]
                if p.poll() is not None:
                    # Only this process's own output counts. The log is appended
                    # across every session, so its tail can name an hours-old fault.
                    fresh=since(name,launched[name])
                    restarts[name]=[stamp for stamp in restarts[name] if time.time()-stamp<RESTART_WINDOW]
                    if any(word in fresh for word in RECOVERABLE) and len(restarts[name])<RESTART_LIMIT:
                        restarts[name].append(time.time())
                        event(folder,'recovery',f'{name} network restart {len(restarts[name])}/{RESTART_LIMIT}')
                        processes[name]=start(name,cwd,argv,env);launched[name]=size(name);last_sizes[name]=launched[name]
                    else:
                        event(folder,'needs_attention',f'{name} exited ({p.returncode}); inspect its log')
                        notify(name+' stopped. See .local/servers logs.')
                        # The sibling keeps serving: one dead process should not
                        # take the rest of the demo down with it.
                        down.add(name)
                    healthy[name]=False
                    continue
                port=8008 if name=='backend' else 3008;path='/health' if name=='backend' else '/'
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}',timeout=3) as r:healthy[name]=r.status==200
                except Exception:healthy[name]=False
                if last_sizes.get(name)!=size(name):
                    fresh=since(name,last_sizes[name]);last_sizes[name]=size(name)
                    if any(word in fresh for word in ERROR_KEYWORDS):event(folder,'log_keyword',name+' logged an error; request failure is not silently retried')
            write(folder/'status.json',dict(status='ready' if all(healthy.values()) else 'degraded' if any(healthy.values()) else 'starting',
                pid=os.getpid(),healthy=healthy,children=live(),down=sorted(down),url=URL,updated=time.time()))
    except KeyboardInterrupt:pass
    finally:
        for p in processes.values():
            if p.poll() is None:
                if os.name=='nt':subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True)
                else:p.terminate()
        write(folder/'status.json',dict(status='stopped',pid=os.getpid()))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--mock',action='store_true');parser.add_argument('--background',action='store_true');parser.add_argument('--status',action='store_true');parser.add_argument('--stop',action='store_true');args=parser.parse_args()
    if args.status:print((folder/'status.json').read_text() if (folder/'status.json').exists() else 'Not running')
    elif args.stop:
        state=json.loads((folder/'status.json').read_text());
        if state.get('status')=='stopped':raise SystemExit('Already stopped')
        if os.name=='nt':
            pid=int(state['pid'])
            check=subprocess.run(['powershell','-NoProfile','-Command',f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}').CommandLine"],capture_output=True,text=True)
            if str(Path(__file__).resolve()).lower() not in check.stdout.lower():raise SystemExit('Refusing to stop a process that is not this project supervisor')
            subprocess.run(['taskkill','/PID',str(pid),'/T','/F'],capture_output=True)
        else:os.kill(state['pid'],signal.SIGTERM)
        write(folder/'status.json',dict(status='stopped'))
    elif args.background:
        subprocess.Popen([sys.executable,__file__,*(['--mock'] if args.mock else [])],cwd=ROOT,creationflags=FLAGS,stdout=open(folder/'supervisor.log','a'),stderr=subprocess.STDOUT)
        print('Servers starting at http://127.0.0.1:3008. Status: python scripts/dev.py --status')
    else:launch(args.mock)
