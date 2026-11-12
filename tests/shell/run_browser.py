"""Serve actual platform API and shell with a disposable DB for browser QA only."""
import sys,pathlib,tempfile,threading,socket,subprocess,os,json
ROOT=pathlib.Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
import uvicorn
from fastapi.staticfiles import StaticFiles
from tomo.platform.api import create_app
from tomo.platform.config import Settings
from tomo.platform.rules import RuleRegistry
with tempfile.TemporaryDirectory(prefix='tomo-shell-') as directory:
 rules=RuleRegistry();rules.register('game',lambda *args:None);rules.register('plan',lambda *args:None)
 app=create_app(Settings(database=str(pathlib.Path(directory)/'qa.sqlite3')),rule_registry=rules)
 app.mount('/',StaticFiles(directory=ROOT/'web',html=True))
 sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 server=uvicorn.Server(uvicorn.Config(app,log_level='warning'));thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
 import time
 deadline=time.monotonic()+10
 while not server.started:
  if time.monotonic()>deadline:raise RuntimeError('QA server did not start')
  time.sleep(.05)
 out=ROOT/'.scratch/_tmp/shell-qa';out.mkdir(parents=True,exist_ok=True)
 env=os.environ.copy();env.update(TOMO_SHELL_ORIGIN=f'http://127.0.0.1:{port}',TOMO_SHELL_OUT=str(out))
 try:
  result=subprocess.run(['node',str(ROOT/'tests/shell/browser.cjs')],env=env,text=True,capture_output=True,timeout=120)
  (out/'run.json').write_text(json.dumps({'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr},indent=2));print(result.stdout);print(result.stderr if result.returncode else '');sys.exit(result.returncode)
 finally:server.should_exit=True;thread.join(timeout=5);sock.close()
