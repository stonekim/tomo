"""Actual product UI + HTTP/SQLite browser QA, disposable synthetic users; no provider."""
import sys,os,json,socket,threading,tempfile,subprocess,time
from pathlib import Path
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
import uvicorn
from dataclasses import replace
from tomo.app import create_product_app
from tomo.platform.config import Settings
ROOT=Path(__file__).resolve().parents[2]
prefix=os.environ.get('TOMO_QA_PREFIX','').rstrip('/')
label=os.environ.get('TOMO_QA_LABEL') or ('prefix' if prefix else '')
out=ROOT/'.scratch/_tmp/release-qa'/label;out.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='tomo-product-browser-') as folder:
    clock=[datetime.now(timezone.utc)]
    with patch('tomo.plans.service.utc_now',side_effect=lambda:clock[0]),patch('tomo.platform.store.timestamp',side_effect=lambda:clock[0].isoformat()),patch('tomo.platform.auth.time.time',side_effect=lambda:clock[0].timestamp()):
        settings=replace(Settings.from_env(),database=str(Path(folder)/'qa.sqlite3')) if os.environ.get('TOMO_QA_REAL')=='1' else Settings(database=str(Path(folder)/'qa.sqlite3'))
        app=create_product_app(settings)
        app.state.auth.clock=lambda:clock[0].timestamp()
        @app.post('/__qa__/advance')
        def advance():
            clock[0]+=timedelta(days=9)
            return {'now':clock[0].isoformat()}
        app.router.routes.insert(0, app.router.routes.pop())
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(app,log_level='warning'))
        thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
        deadline=time.monotonic()+10
        while not server.started:
            if time.monotonic()>deadline:raise RuntimeError('QA server failed to start')
            time.sleep(.05)
        proxy=None
        origin=f'http://127.0.0.1:{port}'
        if prefix:
            import http.server,http.client
            class Proxy(http.server.BaseHTTPRequestHandler):
                def log_message(self,*args):pass
                def forward(self):
                    if not self.path.startswith(prefix+'/'):
                        self.send_error(404);return
                    upstream=http.client.HTTPConnection('127.0.0.1',port,timeout=60)
                    body=self.rfile.read(int(self.headers.get('Content-Length','0'))) if self.command=='POST' else None
                    headers={k:v for k,v in self.headers.items() if k.lower() not in ('host','connection','content-length')}
                    upstream.request(self.command,self.path[len(prefix):],body=body,headers=headers)
                    r=upstream.getresponse();payload=r.read();self.send_response(r.status)
                    for k,v in r.getheaders():
                        if k.lower() not in ('connection','content-length','transfer-encoding'):self.send_header(k,v)
                    self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload);upstream.close()
                do_GET=forward
                do_POST=forward
            proxy=http.server.ThreadingHTTPServer(('127.0.0.1',0),Proxy)
            threading.Thread(target=proxy.serve_forever,daemon=True).start()
            origin=f'http://127.0.0.1:{proxy.server_port}'+prefix
        try:
            node_env={k:os.environ[k] for k in ('PATH','HOME','LANG','TOMO_PLAYWRIGHT_MODULE','TOMO_CHROMIUM_PATH') if k in os.environ}
            node_env.update(TOMO_PRODUCT_ORIGIN=origin,TOMO_PRODUCT_OUT=str(out))
            script=ROOT/os.environ.get('TOMO_BROWSER_SCRIPT','tests/system/browser.cjs')
            r=subprocess.run(['node',str(script)],env=node_env,text=True,capture_output=True,timeout=180)
            (out/'browser-run.json').write_text(json.dumps({'exit_code':r.returncode,'stdout':r.stdout,'stderr':r.stderr},indent=2))
            print(r.stdout);print(r.stderr if r.returncode else '');raise SystemExit(r.returncode)
        finally:
            if proxy:proxy.shutdown();proxy.server_close()
            server.should_exit=True;thread.join(timeout=5);sock.close()
