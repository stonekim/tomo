"""Disposable nonroot container health, real HTTP auth and persisted restart check."""
import subprocess,json,time,uuid,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];out=ROOT/'.scratch/_tmp/release-qa';checks=[]
label='tomo-qa-'+uuid.uuid4().hex[:10];volume=label+'-data';active=None

def run(*args):return subprocess.check_output(['docker',*args],text=True).strip()
def request(base,path,body=None,token=None):
    data=json.dumps(body).encode() if body is not None else None
    headers={'Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    with urllib.request.urlopen(urllib.request.Request(base+path,data=data,headers=headers),timeout=5) as r:
        raw=r.read();return json.loads(raw) if r.headers.get_content_type()=='application/json' else raw

def start(name):
    global active
    active=name
    run('run','--rm','-d','--name',name,'--label','com.tomo.qa=true','--read-only','--tmpfs','/tmp:size=64m,mode=1777','--cap-drop','ALL','--security-opt','no-new-privileges:true','--health-interval','1s','--health-start-period','0s','-p','127.0.0.1::8000','--mount',f'type=volume,src={volume},dst=/data','tomo-integration-qa:20261113')
    base='http://'+run('port',name,'8000/tcp').splitlines()[0]
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        try:
            if request(base,'/healthz')['status']=='ok':return base
        except (OSError,ValueError):pass
        time.sleep(.1)
    raise RuntimeError('Container health endpoint not ready')

try:
    run('volume','create','--label','com.tomo.qa=true',volume)
    base=start(label)
    checks.append({'name':'nonroot image health and migration','pass':True})
    inspect=json.loads(run('inspect',label))[0]
    assert inspect['Config']['User']=='tomo' and inspect['HostConfig']['ReadonlyRootfs']
    checks.append({'name':'nonroot read-only application filesystem','pass':True})
    session=request(base,'/api/v1/auth/register',{'username':'container_qa','password':'synthetic-password-123'});token=session['token']
    game=request(base,'/api/v1/game/saves',{'scenario':'Synthetic container restart','idempotency_key':'container-create-01'},token);s,b=game['save']['id'],game['branch']['id']
    request(base,f'/api/v1/game/saves/{s}/branches/{b}/actions',{'action':{'action':'wait'},'expected_revision':0,'idempotency_key':'container-turn-01'},token)
    assert b'<title>Tomo' in request(base,'/') and b'createApi' in request(base,'/src/shared/api.js')
    checks.append({'name':'same-origin UI and actual authenticated game write','pass':True})
    run('stop',label);active=None
    base=start(label+'-restart')
    assert request(base,'/api/v1/me',token=token)['user_id']==session['user_id']
    assert request(base,f'/api/v1/game/saves/{s}/branches/{b}',token=token)['branch']['revision']==1
    checks.append({'name':'volume survives container replacement with account/session/event history','pass':True})
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        state=json.loads(run('inspect',active))[0]['State']['Health']['Status']
        if state=='healthy':break
        time.sleep(.2)
    assert state=='healthy'
    checks.append({'name':'configured Docker healthcheck becomes healthy','pass':True})
    result={'ok':True,'checks':checks,'image_id':run('image','inspect','--format','{{.Id}}','tomo-integration-qa:20261113'),'scope':'Disposable nonroot container, temporary named volume, synthetic user, provider disabled; not a public TLS launch'}
except BaseException as e:
    result={'ok':False,'checks':checks,'error':str(e)}
    raise
finally:
    if active:
        subprocess.run(['docker','stop',active],capture_output=True,text=True,timeout=30)
    subprocess.run(['docker','volume','rm',volume],capture_output=True,text=True,timeout=15)
    (out/'container-result.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
