"""Real localhost HTTP contract tests; dispatcher disabled, no pretend FM runs.

Live GPU API checks are executed separately against the actual pinned backend.
All tested operations below cross a TCP/HTTP boundary, not direct route calls.
"""
import copy
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from interactive_api import Service,handler


class InteractiveHTTPTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'runs').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix='http_contract_',dir=ROOT/'runs')
        self.base=Path(self.temp.name)
        # Explicitly synthetic metadata for queue/state contracts, NEVER executed.
        (self.base/'environment.json').write_text(json.dumps({'executable':sys.executable}))
        (self.base/'model.json').write_text(json.dumps({'contract_fixture_only':True}))
        self.config={'cpu_python':'.venv-qc/bin/python',
            'gpu_environment_record':str((self.base/'environment.json').relative_to(ROOT)),
            'model_manifest':str((self.base/'model.json').relative_to(ROOT)),
            'gpu_devices':['cuda:0'], 'task_bindings':{'T0017':{
                'config':'configs/rnafm_frozen_pilot.json','input':None,'splits':None}}}
        self.service=Service(ROOT,self.config,self.base/'jobs',self.base/'state.sqlite',dispatch=False)
        self.start_http()
        self.addCleanup(self.cleanup)

    def start_http(self):
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.service))
        self.server.daemon_threads=True
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)

    def cleanup(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=5)
        self.service.close();self.temp.cleanup()

    def http(self,method,path,body=None,key=None,headers=None,raw=None):
        h={'Authorization':'Bearer '+self.service.token}
        if body is not None or raw is not None:h['Content-Type']='application/json'
        if key:h['Idempotency-Key']=key
        h.update(headers or {})
        content=raw if raw is not None else json.dumps(body).encode() if body is not None else None
        request=Request(self.url+path,data=content,headers=h,method=method)
        try:response=urlopen(request,timeout=120)
        except HTTPError as exc:response=exc
        with response:
            payload=response.read()
            return response.status,json.loads(payload) if response.headers['Content-Type'].startswith('application/json') else payload.decode()

    def encoder(self,**kwargs):
        request={'kind':'encoder','records':[{'observation_id':'contract_a','sequence':'ACGU'}]}
        request.update(kwargs)
        return request

    def test_auth_and_loopback_origin_enforcement(self):
        for h,status in (({'Authorization':''},401),({'Host':'evil.example'},403),({'Origin':'https://evil.example'},403)):
            got,_=self.http('GET','/v1/health',headers=h);self.assertEqual(got,status)
        code,health=self.http('GET','/v1/health')
        self.assertEqual(code,200);self.assertFalse(health['fm_cpu_fallback'])
        self.assertFalse(health['scheduler_enabled'])

    def test_console_and_openapi_are_served_locally_without_embedded_token(self):
        code,page=self.http('GET','/')
        self.assertEqual(code,200);self.assertIn('HTTP',page)
        self.assertNotIn(self.service.token,page)
        code,doc=self.http('GET','/openapi.json')
        self.assertEqual(code,200);self.assertEqual(doc['openapi'],'3.1.0')
        self.assertIn('/v1/runs/{run_id}/resume',doc['paths'])
        import re
        for path,methods in doc['paths'].items():
            for operation in methods.values():
                declared={p['name'] for p in operation.get('parameters',[]) if p['in']=='path' and p['required']}
                self.assertEqual(set(re.findall(r'\{([^}]+)\}',path)),declared)
        for name in ('api-console.js','api-console.css'):
            code,text=self.http('GET','/'+name);self.assertEqual(code,200);self.assertNotIn(self.service.token,text)

    def test_all_catalog_rows_preserved_with_honest_readiness(self):
        code,body=self.http('GET','/v1/tasks')
        self.assertEqual(code,200);self.assertEqual(len(body['tasks']),198)
        self.assertEqual(len({r['task_id'] for r in body['tasks']}),198)
        self.assertEqual(sum(r['status']=='NOT_APPLICABLE' for r in body['tasks']),9)
        self.assertFalse(any(r['status']=='READY' for r in body['tasks']))

    def test_all_198_api_pilot_submissions_never_bypass_gate(self):
        code,result=self.http('POST','/v1/tasks/pilots',{'task_ids':'all'},key='all-contract-tasks')
        self.assertEqual(code,207);self.assertEqual(result['requested'],198)
        self.assertEqual(result['states'],{'BLOCKED':189,'NOT_APPLICABLE':9})
        self.assertEqual(result['assay_executions_completed'],0)
        code,again=self.http('POST','/v1/tasks/pilots',{'task_ids':'all'},key='all-contract-tasks')
        self.assertEqual([r['run_id'] for r in result['runs']],[r['run_id'] for r in again['runs']])
        self.assertTrue(all(r['attempt']==0 for r in again['runs']))

    def test_invalid_bulk_is_validated_before_any_submission(self):
        code,_=self.http('POST','/v1/tasks/pilots',{'task_ids':['T0017','NO_SUCH_TASK']},key='bad-bulk')
        self.assertEqual(code,404)
        _,body=self.http('GET','/v1/runs');self.assertEqual(body['runs'],[])

    def test_real_task_hold_blocks_input_access_and_resumption(self):
        code,run=self.http('POST','/v1/tasks/T0017/pilot',{},key='real-task-hold')
        self.assertEqual(code,409);self.assertEqual(run['state'],'BLOCKED');self.assertEqual(run['attempt'],0)
        self.assertIn('REAL_HUMAN_REVIEW_PACKET_NOT_SUPPLIED',run['readiness']['issues'])
        code,_=self.http('POST','/v1/runs/'+run['run_id']+'/resume',{},key='bad-resume')
        self.assertEqual(code,409)
        code,_=self.http('GET','/v1/runs/'+run['run_id']+'/result');self.assertEqual(code,409)

    def test_idempotency_conflict_and_unchanged_request_identity(self):
        code,run=self.http('POST','/v1/runs',self.encoder(),key='same')
        self.assertEqual(code,202)
        code,again=self.http('POST','/v1/runs',self.encoder(),key='same')
        self.assertEqual(run['run_id'],again['run_id'])
        code,_=self.http('POST','/v1/runs',self.encoder(seed=23),key='same')
        self.assertEqual(code,409)
        code,_=self.http('POST','/v1/runs',self.encoder());self.assertEqual(code,400)

    def test_cancel_and_resume_preserve_seed_budget_request_and_attempt(self):
        _,run=self.http('POST','/v1/runs',self.encoder(seed=23),key='cancel-case')
        path='/v1/runs/'+run['run_id']
        code,cancelled=self.http('POST',path+'/cancel',{})
        self.assertEqual(code,200);self.assertEqual(cancelled['state'],'CANCELLED')
        code,resumed=self.http('POST',path+'/resume',{},key='resume-case')
        self.assertEqual(code,200);self.assertEqual(resumed['state'],'QUEUED')
        self.assertEqual(resumed['request_sha256'],run['request_sha256']);self.assertEqual(resumed['seed'],23)
        self.assertEqual(resumed['attempt'],0)
        _,repeat=self.http('POST',path+'/resume',{},key='resume-case')
        self.assertEqual(repeat['request_sha256'],run['request_sha256'])
        code,_=self.http('POST',path+'/resume',{'seed':11},key='change-protocol')
        self.assertEqual(code,400)
        code,events=self.http('GET',path+'/events')
        self.assertEqual(code,200);self.assertIn('RESUME_REQUESTED',[r['state'] for r in events])

    def test_forbid_arbitrary_commands_paths_approval_and_cpu_overrides(self):
        for field,value in (('device','cpu'),('command',['sh']),('checkpoint','/tmp/a'),('human_review_approved',True)):
            code,_=self.http('POST','/v1/runs',self.encoder(**{field:value}),key='forbid-'+field)
            self.assertEqual(code,400)
        code,_=self.http('POST','/v1/runs',{'kind':'checks','suite':'shell'},key='not-allowlisted')
        self.assertEqual(code,422)

    def test_no_normalization_truncation_or_fabricated_labels(self):
        for i,seq in enumerate(('ACGT','acgu','ACGUN','','A'*1023)):
            code,_=self.http('POST','/v1/runs',self.encoder(records=[{'observation_id':'a','sequence':seq}]),key='invalid-'+str(i))
            self.assertEqual(code,422)
        for records in ([{'observation_id':'a','sequence':'A','label':1}],
                        [{'observation_id':'a','sequence':'A'}]*2):
            code,_=self.http('POST','/v1/runs',self.encoder(records=records),key='no-labels')
            self.assertEqual(code,422)

    def test_strict_json_and_bounded_requests(self):
        for payload,expected in ((b'{"kind":"encoder","kind":"checks"}',400),
                                 (b'{"kind":"diagnostic","seed":NaN}',400),
                                 (b'{"kind":"diagnostic","seed":true}',422),
                                 (b'x'*65537,413)):
            code,_=self.http('POST','/v1/runs',raw=payload,key='json-contract')
            self.assertEqual(code,expected)

    def test_models_are_explicit_and_unsupported_model_is_not_substituted(self):
        code,body=self.http('GET','/v1/models')
        self.assertEqual(code,200);self.assertEqual(len(body['models']),6)
        self.assertEqual([m['model_id'] for m in body['models'] if m['api_encoder_implemented']],['RNA-FM'])
        code,_=self.http('POST','/v1/runs',self.encoder(model_id='RiNALMo'),key='no-substitution')
        self.assertEqual(code,422)

    def test_no_result_or_metric_replay_before_execution(self):
        _,run=self.http('POST','/v1/runs',self.encoder(),key='not-run')
        for method,suffix,body in (('GET','result',None),('GET','predictions',None),('POST','replay',{})):
            code,_=self.http(method,'/v1/runs/'+run['run_id']+'/'+suffix,body)
            self.assertEqual(code,409)
        code,logs=self.http('GET','/v1/runs/'+run['run_id']+'/logs')
        self.assertEqual(code,200);self.assertEqual(logs['attempt'],0)

    def test_state_persists_across_api_restart(self):
        _,run=self.http('POST','/v1/tasks/T0017/pilot',{},key='persistent-hold')
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=5);self.service.close()
        self.service=Service(ROOT,self.config,self.base/'jobs',self.base/'state.sqlite',dispatch=False)
        self.start_http()
        code,recovered=self.http('GET','/v1/runs/'+run['run_id'])
        self.assertEqual(code,200);self.assertEqual(recovered['state'],'BLOCKED')
        self.assertEqual(recovered['request_sha256'],run['request_sha256'])


if __name__=='__main__':unittest.main()
