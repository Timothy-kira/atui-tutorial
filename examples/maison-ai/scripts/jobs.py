"""Persistent background task runner and independent log/process monitor."""
import argparse, json, os, re, shutil, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.local' / 'tasks'
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

def pnpm():
    found = shutil.which('pnpm')
    if found: return found
    candidates = list((Path.home()/'.cache/codex-runtimes').glob('*/dependencies/bin/fallback/pnpm.cmd'))
    if candidates: return str(candidates[0])
    raise RuntimeError('Install pnpm first: https://pnpm.io/installation')

def command(args):
    if os.name == 'nt' and str(args[0]).endswith('.cmd'):
        return ['cmd.exe', '/d', '/c', *map(str,args)]
    return list(map(str,args))

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,indent=2),encoding='utf-8');temp.replace(path)

def event(folder, kind, detail):
    with (folder/'events.jsonl').open('a',encoding='utf-8') as out:
        out.write(json.dumps(dict(time=time.time(),kind=kind,detail=detail))+'\n')

def notify(message):
    # Local notification only; this does not claim to wake an AI conversation.
    if os.name=='nt':
        code="Add-Type -AssemblyName System.Windows.Forms; $n=New-Object System.Windows.Forms.NotifyIcon; $n.Icon=[System.Drawing.SystemIcons]::Information; $n.Visible=$true; $n.ShowBalloonTip(5000,'Maison AI',"+"'"+message.replace("'","''")+"'"+",[System.Windows.Forms.ToolTipIcon]::Info); Start-Sleep -Seconds 6; $n.Dispose()"
        subprocess.Popen(['powershell','-NoProfile','-WindowStyle','Hidden','-Command',code],creationflags=FLAGS,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def alive(pid):
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:return False
        exit_code=wintypes.DWORD()
        try:return bool(kernel.GetExitCodeProcess(handle,ctypes.byref(exit_code))) and exit_code.value==259
        finally:kernel.CloseHandle(handle)
    try:os.kill(pid,0);return True
    except OSError:return False

def worker(kind):
    folder=STATE/kind;folder.mkdir(parents=True,exist_ok=True)
    status=dict(status='running',kind=kind,pid=os.getpid(),started=time.time(),phase='starting')
    write(folder/'status.json',status)
    if kind=='install':commands=[(ROOT,['uv','sync']),(ROOT/'frontend',[pnpm(),'install','--no-frozen-lockfile'])]
    elif kind=='live':commands=[(ROOT/'frontend',['node','scripts/export-catalog.mjs']),(ROOT,['uv','run','python','scripts/live_smoke.py'])]
    elif kind=='e2e':commands=[(ROOT/'frontend',[pnpm(),'test:e2e'])]
    elif kind=='build':commands=[(ROOT/'frontend',[pnpm(),'build'])]
    elif kind=='assets':commands=[(ROOT,['python','scripts/refine_photos.py'])]
    else:commands=[(ROOT,['uv','run','pytest','-q']),(ROOT/'frontend',[pnpm(),'check']),(ROOT/'frontend',[pnpm(),'build'])]
    with (folder/'output.log').open('a',encoding='utf-8',buffering=1) as log:
        for cwd, argv in commands:
            status.update(phase=' '.join(argv),updated=time.time());write(folder/'status.json',status)
            log.write('\nPHASE '+status['phase']+'\n');log.flush()
            for attempt in range(2 if kind=='install' else 1):
                proc=subprocess.Popen(command(argv),cwd=cwd,stdout=log,stderr=subprocess.STDOUT,creationflags=FLAGS)
                status['child_pid']=proc.pid;write(folder/'status.json',status)
                try: code=proc.wait(timeout=900)
                except subprocess.TimeoutExpired:
                    if os.name=='nt': subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True)
                    else: proc.kill()
                    code=124
                if code==0: break
                recent=(folder/'output.log').read_text(encoding='utf-8',errors='replace')[-12000:]
                transient=bool(re.search('ECONNRESET|ETIMEDOUT|EAI_AGAIN|TLS|timed out|connection reset|download failed',recent,re.I))
                if kind=='install' and attempt==0 and transient:
                    event(folder,'recovery','One retry for transient dependency download failure');continue
                status.update(status='needs_attention',exit_code=code,finished=time.time());write(folder/'status.json',status)
                event(folder,'failure',status['phase']);notify('Task failed. See .local/tasks/'+kind+'/output.log');return
        status.update(status='complete',exit_code=0,finished=time.time());write(folder/'status.json',status)
        event(folder,'complete',kind);notify(kind+' completed')

def monitor(kind):
    folder=STATE/kind;last_size=0;last_change=time.time();reported=False;seen=set()
    for _ in range(360):
        time.sleep(5)
        path=folder/'status.json'
        if not path.exists(): continue
        status=json.loads(path.read_text())
        if status['status']!='running': event(folder,'monitor_finished',status['status']);return
        if not alive(status['pid']):
            status.update(status='needs_attention',reason='worker exited unexpectedly');write(path,status);event(folder,'process_dead',status['pid']);notify('Task process exited unexpectedly');return
        log=folder/'output.log'
        if log.exists():
            size=log.stat().st_size
            if size!=last_size:
                with log.open('rb') as f: f.seek(last_size);fresh=f.read().decode('utf-8',errors='replace')
                last_size=size;last_change=time.time();reported=False
                for line in fresh.splitlines():
                    if re.search(r'error|failed|traceback|exception',line,re.I) and line not in seen:
                        seen.add(line);event(folder,'log_keyword',line[:500])
            if time.time()-last_change>180 and not reported:
                event(folder,'stall','No new log output for 180s');notify('Task may be stalled. Check status.');reported=True
    event(folder,'monitor_timeout','30 minute limit');notify('Task monitor reached its timeout')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['start','worker','monitor','status']);p.add_argument('kind',choices=['install','verify','live','e2e','build','assets'],default='install',nargs='?');a=p.parse_args()
    folder=STATE/a.kind;folder.mkdir(parents=True,exist_ok=True)
    if a.action=='start':
        current=folder/'status.json'
        if current.exists() and json.loads(current.read_text()).get('status')=='running': raise SystemExit('Already running; use status.')
        subprocess.Popen([sys.executable,__file__,'worker',a.kind],cwd=ROOT,creationflags=FLAGS,stdout=subprocess.DEVNULL,stderr=open(folder/'worker.log','a'))
        subprocess.Popen([sys.executable,__file__,'monitor',a.kind],cwd=ROOT,creationflags=FLAGS,stdout=subprocess.DEVNULL,stderr=open(folder/'monitor.log','a'))
        print('Started. Inspect with: python scripts/jobs.py status '+a.kind)
    elif a.action=='worker': worker(a.kind)
    elif a.action=='monitor': monitor(a.kind)
    elif (folder/'status.json').exists(): print((folder/'status.json').read_text());print('Log:',folder/'output.log')
    else: print('Not started')
