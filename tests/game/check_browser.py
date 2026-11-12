"""Disposable localhost game/browser QA. No production user or provider is accessed."""
import json,os,pathlib,socket,subprocess,tempfile,threading
import uvicorn
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from tomo.platform.api import create_app
from tomo.platform.rules import RuleRegistry
from tomo.platform.config import Settings
from tomo.game import router,register_game_rules
ROOT=pathlib.Path(__file__).resolve().parents[2]
out=pathlib.Path(os.environ.get('GAME_QA_OUT',ROOT/'.scratch/_tmp/game-browser'));out.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory() as temp:
 rules=RuleRegistry();register_game_rules(rules)
 app=create_app(Settings(database=str(pathlib.Path(temp)/'game.sqlite3')),rule_registry=rules,domain_routers=[router])
 app.mount('/assets',StaticFiles(directory=ROOT/'web/src'),name='assets')
 @app.get('/',response_class=HTMLResponse)
 def harness():
  return '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Isolated game QA</title><style>body{margin:0;padding:20px;background:#0b1921;color:#dbe8ed}</style></head><body><main id="app"></main><script type="module">import {mountGame} from '/assets/game/index.js';mountGame(document.getElementById('app'),{saveId:new URL(location).searchParams.get('save'),async api(path,options={}){const r=await fetch(path,{method:options.method||'GET',headers:{Authorization:'Bearer '+window.qaToken,'Content-Type':'application/json'},body:options.body?JSON.stringify(options.body):undefined});const body=await r.json();if(!r.ok){const e=new Error(body.error?.message||'Request failed');e.status=r.status;throw e}return body},onSaveCreated(save){history.replaceState(null,'','?save='+save.id)}});</script></body></html>'''
 sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.listen()
 server=uvicorn.Server(uvicorn.Config(app,log_level='error'));thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
 try:
  env=os.environ.copy();env.update(GAME_QA_ORIGIN=f'http://127.0.0.1:{port}',GAME_QA_OUT=str(out))
  r=subprocess.run(['node',str(ROOT/'tests/game/browser_game.cjs')],env=env,capture_output=True,text=True,timeout=120)
  (out/'run.json').write_text(json.dumps({'exit_code':r.returncode,'stdout':r.stdout,'stderr':r.stderr},indent=2));print(r.stdout);print(r.stderr if r.returncode else '')
  if r.returncode:raise SystemExit(r.returncode)
 finally:server.should_exit=True;thread.join(timeout=10);sock.close()
