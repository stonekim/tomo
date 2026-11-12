"""Opt-in, two synthetic product calls through the configured real provider.
Run only with an authorized server environment; never prints key, prompt, or response text.
"""
import tempfile,json,sys
from pathlib import Path
from datetime import datetime,timedelta,timezone
from fastapi.testclient import TestClient
from tomo.app import create_product_app
from tomo.platform.config import Settings
from dataclasses import replace
ROOT=Path(__file__).resolve().parents[2]
out=ROOT/'.scratch/_tmp/release-qa';out.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='tomo-real-smoke-') as folder:
    cfg=replace(Settings.from_env(),database=str(Path(folder)/'qa.sqlite3'))
    if cfg.model_mode!='real':raise SystemExit('Requires explicit authorized real provider configuration')
    app=create_product_app(cfg);c=TestClient(app)
    diagnostics=[];original=app.state.models.adapter.complete
    def inspected(messages):
        result=original(messages)
        d={'fenced':result.text.strip().startswith('```'),'characters':len(result.text)}
        try:
            from tomo.platform.models import structured_json
            parsed=structured_json(result.text);d['top_keys']=list(parsed) if isinstance(parsed,dict) else None
            if 'short-cycle' in messages[0]['content']:
                from tomo.plans.service import Suggestions
                try:Suggestions.model_validate(parsed);d['schema_valid']=True
                except ValueError as e:d['schema_valid']=False;d['validation']=[{'location':v['loc'],'type':v['type']} for v in e.errors()]
                import re
                d['forbidden_probability_word']=bool(re.search(r'%|％|percent|probability|概率|成功率',json.dumps(parsed,ensure_ascii=False),re.I))
        except (ValueError,TypeError):d['json_valid']=False
        diagnostics.append(d);return result
    app.state.models.adapter.complete=inspected
    session=c.post('/api/v1/auth/register',json={'username':'real_smoke','password':'synthetic-password-123'}).json();h={'Authorization':'Bearer '+session['token']}
    game=c.post('/api/v1/game/saves',headers=h,json={'scenario':'A fictional programmer receives a job invitation.','engine':'model','idempotency_key':'real-game-create'}).json();s,b=game['save']['id'],game['branch']['id']
    action=c.post(f'/api/v1/game/saves/{s}/branches/{b}/actions',headers=h,json={'action':{'action':'wait'},'expected_revision':0,'idempotency_key':'real-game-turn-01'})
    now=datetime.now(timezone.utc)
    card={'goal':'Finish a synthetic portfolio outline','completion_criteria':'Three example sections and a reviewed outline','due_at':(now+timedelta(days=10)).isoformat(),'timezone':'UTC','facts':['An outline already exists'],'unknowns':['Reviewer availability'],'required_hours':8,'available_hours_per_week':10,'user_judgment':'uncertain'}
    plan=c.post('/api/v1/plans',headers=h,json={'title':'Synthetic provider QA','idempotency_key':'real-plan-create','card':card}).json();ps=plan['save']['id']
    suggestions=c.post(f'/api/v1/plans/{ps}/suggestions',headers=h,json={})
    audits=[*app.state.store.list_audit(session['user_id'],s),*app.state.store.list_audit(session['user_id'],ps)]
    data={'game_http':action.status_code,'game_mode':action.json().get('agent_mode'),'game_error':action.json().get('error'),'plan_http':suggestions.status_code,'plan_mode':suggestions.json().get('mode'),'plan_model_status':suggestions.json().get('model_status'),'audit':audits,'response_structure':diagnostics,'provider':cfg.model_name,'max_output_tokens':cfg.model_max_output_tokens,'scope':'Actual real-provider product calls, synthetic data and temporary DB; no retention/accuracy claim'}
    data['ok']=action.status_code==200 and data['game_mode']=='real' and suggestions.status_code==200 and data['plan_mode']=='real' and len(audits)==2 and all(x['mode']=='real' and x['status']=='ok' for x in audits)
    (out/'real-provider-smoke.json').write_text(json.dumps(data,ensure_ascii=False,indent=2));print(json.dumps(data,ensure_ascii=False,indent=2));raise SystemExit(0 if data['ok'] else 1)
