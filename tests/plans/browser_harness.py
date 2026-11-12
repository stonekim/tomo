"""Local synthetic browser QA. No production DB, provider, credentials or public server."""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import httpx
import uvicorn
from starlette.responses import HTMLResponse
from starlette.staticfiles import StaticFiles
from tomo.plans import create_plan_app
from tomo.platform.config import Settings

ROOT = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='tomo-plans-browser-') as folder:
    app = create_plan_app(Settings(database=str(Path(folder) / 'qa.sqlite')))
    app.mount('/assets/plans', StaticFiles(directory=ROOT / 'web/src/plans'))
    @app.get('/')
    def page():
        return HTMLResponse('''<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Plan synthetic QA</title><body style="background:#081a14;margin:0"><main id="root"></main><script type="module">
import {mountPlans} from '/assets/plans/index.js';
let token=sessionStorage.getItem('qa-token');
if(!token){const session=await fetch('/api/v1/auth/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'browser_qa',password:'synthetic-test-password'})}).then(r=>r.json());token=session.token;sessionStorage.setItem('qa-token',token);}
window.testContext={saveId:localStorage.getItem('test-plan-id'),async api(path,options={}){const response=await fetch(path,{method:options.method||'GET',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:options.body?JSON.stringify(options.body):undefined});const data=await response.json();if(!response.ok){const e=new Error('API failure');e.status=response.status;e.code=data.error?.code;throw e;}return data;},onSaveCreated(save){window.testContext.saveId=save.id;localStorage.setItem('test-plan-id',save.id);}};
window.cleanup=mountPlans(document.getElementById('root'),window.testContext);
</script></body></html>''')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error'))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            try:
                if httpx.get(f'http://127.0.0.1:{port}/healthz', trust_env=False).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(.05)
        result = subprocess.run(['node', str(ROOT / 'tests/plans/browser_check.cjs')], env=dict(os.environ, PLAN_QA_ORIGIN=f'http://127.0.0.1:{port}'), capture_output=True, text=True, timeout=120)
        print(result.stdout)
        if result.stderr:
            print(result.stderr)
        raise SystemExit(result.returncode)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
