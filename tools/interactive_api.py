#!/usr/bin/env python3
"""Authenticated loopback API over existing registries, StateDB and admission gate.

Requests cannot supply shell commands, local paths, approvals, device overrides or
model downloads. FM workers are isolated processes on explicitly allocated CUDA.
"""
import argparse
import contextlib
import csv
import fcntl
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit
import uuid

if __package__:
    from . import evaluation_protocol as ep
    from .rnagym import StateDB
    from .rnafm_adapter import validate_records
    from .frozen_pilot import prepare_pilot
else:
    import evaluation_protocol as ep
    from rnagym import StateDB
    from rnafm_adapter import validate_records
    from frozen_pilot import prepare_pilot

ROOT = Path(__file__).resolve().parents[1]
TERMINAL = {'EXECUTED', 'FAILED', 'BLOCKED', 'NOT_APPLICABLE', 'CANCELLED', 'INTERRUPTED'}
SOURCE_FILES = ['tools/interactive_api.py', 'tools/interactive_worker.py',
                'tools/rnafm_adapter.py', 'tools/evaluation_protocol.py',
                'tools/frozen_pilot.py', 'tools/paired_statistics.py', 'tools/admission_gate.py']


class APIError(Exception):
    def __init__(self, code, reason):
        self.code, self.reason = code, reason
        super().__init__(reason)


def local_file(root, value):
    """Only administrator configuration resolves filesystem paths, never clients."""
    path = (root/value).resolve()
    if not path.is_relative_to(root.resolve()) or path.is_symlink():
        raise APIError(400, 'CONFIGURED_PATH_OUTSIDE_PROJECT')
    return path


def verify_context(context, root=ROOT):
    for name, expected in context['source_hashes'].items():
        path = local_file(root, name)
        if not path.is_file() or ep.sha256_file(path) != expected:
            raise ep.ProtocolError('PINNED_SOURCE_OR_INPUT_CHANGED:'+name)


class Service:
    def __init__(self, root, config, run_root, state_db, *, dispatch=True):
        self.root, self.config = Path(root).resolve(), config
        self.run_root, self.state_db = Path(run_root).resolve(), Path(state_db).resolve()
        if not self.run_root.is_relative_to(self.root/'runs'):
            raise ValueError('API_ARTIFACTS_MUST_STAY_IN_IGNORED_PROJECT_RUNS')
        self.run_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.run_root.chmod(0o700)
        self.state_db.parent.mkdir(parents=True, exist_ok=True)
        self.guard = threading.RLock()
        self.stop = threading.Event()
        self.processes = {}
        self.scheduler_error = None
        self.last_disk_check = 0.0
        self.dispatch_enabled = dispatch
        self.orphans = {}
        self.token_file = self.run_root/'api_token'
        if not self.token_file.exists():
            fd = os.open(self.token_file, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as handle:
                handle.write(secrets.token_hex(32)+'\n')
        if self.token_file.is_symlink() or self.token_file.stat().st_mode & 0o077:
            raise PermissionError('API_TOKEN_MUST_BE_PRIVATE_REGULAR_FILE')
        self.token = self.token_file.read_text().strip()
        if not re.fullmatch('[0-9a-f]{64}', self.token):
            raise ValueError('INVALID_API_TOKEN_FILE')
        self.owner = open(str(self.state_db)+'.interactive-api.lock', 'a')
        try:
            fcntl.flock(self.owner, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.owner.close()
            raise RuntimeError('API_SCHEDULER_ALREADY_RUNNING_FOR_THIS_STATE_DB')
        self._initialize()
        self.gpu_python = None
        record = config.get('gpu_environment_record')
        if record:
            path = local_file(self.root, record)
            if path.is_file():
                candidate = Path(ep.read_json(path)['executable'])
                if candidate.is_file():
                    self.gpu_python = str(candidate)
        self.devices = list(config.get('gpu_devices', ['cuda:0']))
        if any(not re.fullmatch('cuda:[0-9]+', x) for x in self.devices) or len(set(self.devices)) != len(self.devices):
            raise ValueError('EXPLICIT_UNIQUE_CUDA_DEVICES_REQUIRED')
        visible = os.getenv('CUDA_VISIBLE_DEVICES')
        if visible is not None:
            count = len([v for v in visible.split(',') if v and v != '-1'])
            if any(int(x.split(':')[1]) >= count for x in self.devices):
                raise ValueError('GPU_DEVICE_EXCEEDS_VISIBLE_ALLOCATION')
        self.dispatcher = threading.Thread(target=self._schedule, daemon=True)
        if dispatch:
            self.dispatcher.start()

    @contextlib.contextmanager
    def db(self):
        state = StateDB(self.state_db)
        try:
            yield state
        finally:
            state.db.close()

    def _initialize(self):
        with self.db() as s, s.transaction():
            s.db.executescript('''
              CREATE TABLE IF NOT EXISTS eval_api_runs (
                run_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL,
                request_sha256 TEXT NOT NULL, spec_json TEXT NOT NULL,
                state TEXT NOT NULL, reason TEXT, attempt INTEGER NOT NULL DEFAULT 0,
                device TEXT, pid INTEGER, exit_code INTEGER, created TEXT NOT NULL,
                updated TEXT NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0,
                resume_key TEXT, wall_seconds REAL NOT NULL DEFAULT 0,
                gpu_wall_seconds REAL NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS eval_api_budget_reservations (
                run_id TEXT NOT NULL, attempt INTEGER NOT NULL, seconds REAL NOT NULL,
                reason TEXT NOT NULL, PRIMARY KEY(run_id,attempt));
              CREATE TABLE IF NOT EXISTS eval_api_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                at_utc TEXT NOT NULL, state TEXT NOT NULL, detail_json TEXT NOT NULL);
            ''')
            for row in s.db.execute("SELECT * FROM eval_api_runs WHERE state='RUNNING'").fetchall():
                self.orphans[row['run_id']] = row['pid']
                # Resource telemetry lost in a crash is UNKNOWN, never zero.
                # Reserve the full per-attempt cap against the remaining budget
                # separately from observed wall time; do not invent usage.
                if json.loads(row['spec_json'])['request']['kind']!='checks':
                    s.db.execute('INSERT OR IGNORE INTO eval_api_budget_reservations VALUES(?,?,?,?)',
                        (row['run_id'],row['attempt'],1800.0,'CRASH_INTERVAL_UNOBSERVED_CONSERVATIVE_CAP_NOT_MEASUREMENT'))
                s.db.execute("UPDATE eval_api_runs SET state='INTERRUPTED',reason=?,updated=? WHERE run_id=?",
                             ('API_PROCESS_RESTARTED_REQUIRES_EXPLICIT_RESUME', ep.utc_now(), row['run_id']))
                self._event(s, row['run_id'], 'INTERRUPTED', {'previous_pid':row['pid']})

    def _event(self, s, run_id, state, detail):
        s.db.execute('INSERT INTO eval_api_events(run_id,at_utc,state,detail_json) VALUES(?,?,?,?)',
                     (run_id, ep.utc_now(), state, json.dumps(detail)))

    def _row(self, run_id):
        if not re.fullmatch('RUN_[0-9a-f]{32}', run_id):
            raise APIError(404, 'RUN_NOT_FOUND')
        with self.db() as s:
            row = s.db.execute('SELECT * FROM eval_api_runs WHERE run_id=?', (run_id,)).fetchone()
        if row is None:
            raise APIError(404, 'RUN_NOT_FOUND')
        return dict(row)

    def view(self, run_id):
        row = self._row(run_id)
        spec = json.loads(row.pop('spec_json'))
        row.pop('resume_key')
        row.update(kind=spec['request']['kind'], task_id=spec['request'].get('task_id'),
                   initialization=spec['request'].get('initialization'),
                   seed=spec['request'].get('seed'), rankable_real_result=False,
                   n_records=len(spec['request'].get('records', [])))
        missing=[]
        for attempt in range(1,row['attempt']+1):
            path=self.run_root/run_id/f'attempt_{attempt:04d}'/'exit.json'
            if not path.exists() and not (row['state']=='RUNNING' and attempt==row['attempt']):missing.append(attempt)
        row['unmeasured_attempts']=missing
        row['resource_observation_complete']=not missing and row['state']!='RUNNING'
        if spec.get('readiness'):
            row['readiness'] = spec['readiness']
        return row

    def runs(self):
        with self.db() as s:
            ids = [r[0] for r in s.db.execute('SELECT run_id FROM eval_api_runs ORDER BY created DESC LIMIT 1024')]
        return [self.view(i) for i in ids]

    def tasks(self):
        with (self.root/'data/audit/task_master.tsv').open(encoding='utf-8-sig') as handle:
            return list(csv.DictReader(handle, delimiter='\t'))

    def readiness(self, task_id):
        rows = {r['task_id']:r for r in self.tasks()}
        if task_id not in rows:
            raise APIError(404, 'UNREGISTERED_TASK_ID')
        row = rows[task_id]
        bundle_path = self.root/'data/task_bundles'/(task_id+'.json')
        bundle = ep.read_json(bundle_path)
        issues = []
        state = row['state']
        result = {'task_id':task_id, 'registered_state':state,
                  'task':bundle.get('task'), 'input_modality':bundle.get('input_modality'),
                  'source_family_id':row.get('source_family_id'),
                  'canonical_assay_id':bundle.get('canonical_assay_id'),
                  'issues':issues, 'next_action':bundle.get('next_action'),
                  'functional_labels_used':0, 'rankable_real_result':False}
        if state.startswith('EXCLUDED_'):
            return {**result, 'status':'NOT_APPLICABLE', 'issues':['EXCLUDED_NON_ASSAY_NOT_A_FAILED_MODEL']}
        if not state.startswith('ADMITTED') or not bundle.get('admitted'):
            issues.append('TASK_REGISTRY_NOT_SCIENTIFICALLY_ADMITTED')
        if not bundle.get('canonical_assay_id'):
            issues.append('CANONICAL_ASSAY_BINDING_UNRESOLVED')
        binding = self.config.get('task_bindings', {}).get(task_id)
        if not binding:
            issues.append('NO_RESOLVED_EXECUTION_BINDING')
        else:
            try:
                config = ep.read_json(local_file(self.root, binding['config']))
                if config['task']['task_id'] != task_id:
                    issues.append('TASK_CONFIG_ID_MISMATCH')
                if not config['task'].get('enabled'):
                    issues.append('REAL_TASK_DISABLED_PENDING_ADMISSION')
                if not config['task'].get('admission_evidence'):
                    issues.append('REAL_HUMAN_REVIEW_PACKET_NOT_SUPPLIED')
                for key in ('input', 'splits'):
                    if not binding.get(key) or not local_file(self.root, binding[key]).is_file():
                        issues.append('MISSING_FROZEN_'+key.upper())
                if not issues:
                    prepare_pilot(config, local_file(self.root, binding['input']), local_file(self.root, binding['splits']))
            except (KeyError, OSError, ValueError, ep.ProtocolError) as exc:
                issues.append('BINDING_OR_GATE_REJECTED:'+str(exc))
        result['status'] = 'BLOCKED' if issues else 'READY'
        return result

    def _request(self, request):
        if not isinstance(request, dict):
            raise APIError(400, 'JSON_OBJECT_REQUIRED')
        kind = request.get('kind')
        fields = {'encoder':{'kind','records','initialization','seed','batch_size','model_id'},
                  'diagnostic':{'kind','initialization','seed','model_id'},
                  'assay':{'kind','task_id'}, 'checks':{'kind','suite'}}
        if kind not in fields or set(request)-fields[kind]:
            raise APIError(400, 'UNKNOWN_KIND_OR_FIELDS_NO_COMMAND_PATH_APPROVAL_OR_DEVICE_OVERRIDES')
        request = dict(request)
        if kind in ('encoder','diagnostic'):
            if request.get('model_id', 'RNA-FM') != 'RNA-FM':
                raise APIError(422, 'MODEL_ADAPTER_NOT_VERIFIED')
            request.setdefault('model_id','RNA-FM')
            request.setdefault('initialization','pretrained')
            request.setdefault('seed',11)
            if request['initialization'] not in ('pretrained','random') or type(request['seed']) is not int or request['seed'] < 0:
                raise APIError(422, 'INVALID_INITIALIZATION_OR_SEED')
            if kind == 'encoder':
                records = request.get('records')
                if not isinstance(records,list) or not 1 <= len(records) <= 16 or any(
                        not isinstance(r,dict) or set(r) != {'observation_id','sequence'} for r in records):
                    raise APIError(422, 'ONE_TO_SIXTEEN_UNLABELED_RECORDS_REQUIRED')
                try:
                    validate_records(records, 1022)
                except ep.ProtocolError as exc:
                    raise APIError(422,str(exc)) from exc
                request.setdefault('batch_size',4)
                if type(request['batch_size']) is not int or not 1 <= request['batch_size'] <= 4:
                    raise APIError(422,'BATCH_SIZE_OUTSIDE_PROFILED_SCOPE')
        if kind == 'checks' and request.get('suite') not in ('project','packet','site','all'):
            raise APIError(422,'CHECK_SUITE_NOT_ALLOWLISTED')
        if kind == 'assay' and not isinstance(request.get('task_id'),str):
            raise APIError(422,'REGISTERED_TASK_ID_REQUIRED')
        return request

    def submit(self, request, key):
        if not isinstance(key,str) or not re.fullmatch('[A-Za-z0-9_.:-]{1,128}',key):
            raise APIError(400,'IDEMPOTENCY_KEY_REQUIRED_1_TO_128_SAFE_CHARACTERS')
        request = self._request(request)
        digest = ep.digest_json(request)
        with self.guard, self.db() as s:
            if self.scheduler_error:
                raise APIError(503,'SCHEDULER_FAILED_CLOSED:'+self.scheduler_error)
            old = s.db.execute('SELECT run_id,request_sha256 FROM eval_api_runs WHERE idempotency_key=?',(key,)).fetchone()
            if old:
                if old['request_sha256'] != digest:
                    raise APIError(409,'IDEMPOTENCY_KEY_CONTENT_CONFLICT')
                return self.view(old['run_id']), False
            if s.db.execute('SELECT count(*) FROM eval_api_runs').fetchone()[0] >= 1024:
                raise APIError(429,'BOUNDED_RUN_COUNT_EXCEEDED')
            context = {'request':request, 'request_sha256':digest, 'source_hashes':{},
                       'configuration_sha256':ep.digest_json(self.config),
                       'created':ep.utc_now(), 'rankable_real_result':False}
            state, reason = 'QUEUED', None
            if request['kind'] == 'assay':
                ready = self.readiness(request['task_id'])
                context['readiness'] = ready
                if ready['status'] != 'READY':
                    state, reason = ready['status'], ';'.join(ready['issues'])
                else:
                    context['binding'] = self.config['task_bindings'][request['task_id']]
                    for name in context['binding'].values():
                        if name:
                            context['source_hashes'][name] = ep.sha256_file(local_file(self.root,name))
            if request['kind'] in ('encoder','diagnostic','assay') and state == 'QUEUED':
                manifest = self.config.get('model_manifest')
                if not self.gpu_python or not manifest or not local_file(self.root,manifest).is_file():
                    state, reason = 'BLOCKED','PINNED_GPU_BACKEND_OR_MANIFEST_NOT_AVAILABLE'
                else:
                    context['model_manifest'] = manifest
                    context['source_hashes'][manifest] = ep.sha256_file(local_file(self.root,manifest))
            if state == 'QUEUED':
                if s.db.execute("SELECT count(*) FROM eval_api_runs WHERE state='QUEUED'").fetchone()[0] >= 8:
                    raise APIError(429,'BOUNDED_QUEUE_FULL')
                for name in SOURCE_FILES:
                    context['source_hashes'][name] = ep.sha256_file(self.root/name)
            run_id = 'RUN_'+uuid.uuid4().hex
            directory = self.run_root/run_id
            directory.mkdir(mode=0o700)
            # Preserve actual code/input bytes as well as hashes for audit after
            # future edits; workers still require the current bytes to match.
            for name,expected in context['source_hashes'].items():
                source=local_file(self.root,name)
                payload=source.read_bytes()
                if hashlib.sha256(payload).hexdigest()!=expected:
                    raise APIError(409,'SOURCE_CHANGED_DURING_REQUEST_FREEZE')
                target=directory/'source_snapshot'/name
                target.parent.mkdir(parents=True,exist_ok=True)
                with target.open('xb') as handle:handle.write(payload)
                target.chmod(0o400)
            ep.write_immutable(directory/'request.json',context)
            with s.transaction():
                s.db.execute('''INSERT INTO eval_api_runs(run_id,idempotency_key,request_sha256,spec_json,
                  state,reason,created,updated) VALUES(?,?,?,?,?,?,?,?)''',
                  (run_id,key,digest,json.dumps(context),state,reason,ep.utc_now(),ep.utc_now()))
                self._event(s,run_id,state,{'reason':reason,'scope':'NO_SCIENTIFIC_ADMISSION_GRANTED'})
            return self.view(run_id), True

    def action(self, run_id, action, key=None):
        with self.guard, self.db() as s:
            row = self._row(run_id)
            if action == 'cancel':
                if row['state'] in TERMINAL:
                    return self.view(run_id)
                state = 'CANCELLED' if row['state']=='QUEUED' else row['state']
                with s.transaction():
                    s.db.execute('UPDATE eval_api_runs SET cancel_requested=1,state=?,updated=? WHERE run_id=?',(state,ep.utc_now(),run_id))
                    self._event(s,run_id,'CANCEL_REQUESTED',{'no_seed_or_protocol_change':True})
            elif action == 'resume':
                if not key or not re.fullmatch('[A-Za-z0-9_.:-]{1,128}',key):
                    raise APIError(400,'RESUME_IDEMPOTENCY_KEY_REQUIRED')
                if row['resume_key']==key:
                    return self.view(run_id)
                if row['state'] not in ('FAILED','CANCELLED','INTERRUPTED') or row['attempt'] >= 2:
                    raise APIError(409,'NOT_RESUMABLE_OR_BOUNDED_ATTEMPTS_EXHAUSTED')
                context = json.loads(row['spec_json'])
                try:
                    verify_context(context,self.root)
                except ep.ProtocolError as exc:
                    raise APIError(409,str(exc)) from exc
                with s.transaction():
                    s.db.execute("UPDATE eval_api_runs SET state='QUEUED',reason=NULL,cancel_requested=0,resume_key=?,updated=? WHERE run_id=?",(key,ep.utc_now(),run_id))
                    self._event(s,run_id,'RESUME_REQUESTED',{'same_request_sha256':row['request_sha256']})
            else:
                raise APIError(404,'UNKNOWN_ACTION')
            return self.view(run_id)

    def _output(self, row):
        return self.run_root/row['run_id']/f"attempt_{row['attempt']:04d}"/'output'

    def result(self, run_id):
        row = self._row(run_id)
        if row['state'] != 'EXECUTED':
            raise APIError(409,'NO_EXECUTED_RESULT:'+row['state'])
        return ep.read_json(self._output(row)/'result.json')

    def logs(self, run_id):
        row=self._row(run_id)
        if not row['attempt']:
            return {'state':row['state'],'attempt':0,'reason':row['reason'],'logs':{}}
        output=self._output(row)
        names=[output.parent/'stdout.log',output.parent/'stderr.log']
        names += [output/(name+'.stderr.log') for name in ('project','site','task_bundles','packet','hold_contract','contract_guards','public_candidate','public_candidate_tests')]
        logs={}
        for path in names:
            if path.is_file() and not path.is_symlink():
                with path.open('rb') as handle:
                    handle.seek(max(0,path.stat().st_size-32768))
                    logs[str(path.relative_to(output.parent))]=handle.read(32768).decode('utf-8',errors='replace')
        return {'state':row['state'],'attempt':row['attempt'],'reason':row['reason'],'logs':logs}

    def predictions(self, run_id):
        row=self._row(run_id)
        context=json.loads(row['spec_json'])
        if row['state']!='EXECUTED' or context['request']['kind']!='assay':
            raise APIError(409,'NO_EXECUTED_ASSAY_PREDICTIONS_EMBEDDINGS_ARE_NOT_FUNCTIONAL_SCORES')
        output=self._output(row)
        return {'run_id':run_id,'rankable_real_result':False,
                'cells':[{'cell':str(path.parent.relative_to(output/'pilot')),
                          'predictions':ep.read_json(path)}
                         for path in sorted((output/'pilot').glob('seed_*/*/predictions.json'))]}

    def replay(self, run_id):
        row = self._row(run_id)
        if row['state'] != 'EXECUTED':
            raise APIError(409,'ONLY_EXECUTED_OUTPUT_CAN_BE_REPLAYED')
        context = json.loads(row['spec_json'])
        try:
            snapshots=self.run_root/run_id/'source_snapshot'
            for name,expected in context['source_hashes'].items():
                snapshot=(snapshots/name).resolve()
                if not snapshot.is_relative_to(snapshots.resolve()) or ep.sha256_file(snapshot)!=expected:
                    raise ep.ProtocolError('FROZEN_SOURCE_SNAPSHOT_MISMATCH:'+name)
            # Integrity replay survives unrelated transport/UI upgrades. Numerical
            # assay replay still requires unchanged current scorer and bindings.
            if context['request']['kind']=='assay':
                scoring={'tools/evaluation_protocol.py','tools/paired_statistics.py',
                         'tools/frozen_pilot.py','tools/admission_gate.py'}
                required={k:v for k,v in context['source_hashes'].items()
                          if k in scoring or k in context['binding'].values()}
                verify_context({'source_hashes':required},self.root)
            output = self._output(row)
            inventory = ep.read_json(output/'artifacts.json')
            for name, expected in inventory.items():
                path = (output/name).resolve()
                if not path.is_relative_to(output.resolve()) or ep.sha256_file(path) != expected:
                    raise ep.ProtocolError('ARTIFACT_HASH_MISMATCH:'+name)
            kind = context['request']['kind']
            if kind == 'assay':
                binding = context['binding']
                prepared = prepare_pilot(ep.read_json(local_file(self.root,binding['config'])),
                                         local_file(self.root,binding['input']),local_file(self.root,binding['splits']))
                for path in sorted((output/'pilot').glob('seed_*/*/predictions.json')):
                    metrics = ep.read_json(path.parent/'metrics.json')
                    p = {**prepared,'config':{**prepared['config'],'baseline_id':metrics['baseline_id']}}
                    recomputed = ep.evaluate(p,ep.read_json(path))
                    if recomputed['metrics'] != metrics['metrics']:
                        raise ep.ProtocolError('REPLAY_METRICS_MISMATCH')
            result = {'status':'VERIFIED','scope':'ARTIFACT_INTEGRITY_AND_SAVED_PREDICTION_METRIC_REPLAY' if kind=='assay' else 'ARTIFACT_INTEGRITY_ONLY_NO_FUNCTIONAL_METRICS',
                      'run_id':run_id,'artifacts_checked':len(inventory),'source_snapshots_checked':len(context['source_hashes']),'new_fm_forward_passes':0,
                      'scientific_admission_granted':False,'rankable_real_result':False}
        except (ValueError,OSError,ep.ProtocolError) as exc:
            raise APIError(409,'REPLAY_REJECTED:'+str(exc)) from exc
        with self.db() as s, s.transaction():
            self._event(s,run_id,'REPLAY_VERIFIED',result)
        return result

    def events(self, run_id):
        self._row(run_id)
        with self.db() as s:
            return [dict(r) for r in s.db.execute('SELECT * FROM eval_api_events WHERE run_id=? ORDER BY seq',(run_id,))]

    def health(self):
        with self.db() as s:
            counts = dict(s.db.execute('SELECT state,count(*) FROM eval_api_runs GROUP BY state'))
        return {'status':'DEGRADED' if self.scheduler_error else 'READY','transport':'authenticated_loopback_http','fm_cpu_fallback':False,
                'gpu_devices':self.devices,'cuda_visible_devices':os.getenv('CUDA_VISIBLE_DEVICES'),
                'slurm_job_id':os.getenv('SLURM_JOB_ID'),'gpu_backend_configured':bool(self.gpu_python),
                'task_count':len(self.tasks()),'run_states':counts,'rankable_real_result':False,
                'scheduler_enabled':self.dispatch_enabled,'scheduler_error':self.scheduler_error,
                'gpu_budget':self.gpu_budget()}

    def gpu_budget(self):
        with self.db() as s:
            observed=s.db.execute('SELECT COALESCE(sum(gpu_wall_seconds),0) FROM eval_api_runs').fetchone()[0]
            reserved=s.db.execute('SELECT COALESCE(sum(seconds),0) FROM eval_api_budget_reservations').fetchone()[0]
        return {'observed_completed_stage_seconds':observed,
                'unobserved_crash_conservative_reserved_seconds':reserved,
                'cap_seconds':self.config.get('gpu_stage_wall_seconds_cap',7200),
                'reserved_is_not_measured_usage':True,'billing_hours_inferred':False}

    def _set(self, run_id, state, **values):
        values.update(state=state,updated=ep.utc_now())
        with self.db() as s, s.transaction():
            s.db.execute('UPDATE eval_api_runs SET '+','.join(k+'=?' for k in values)+' WHERE run_id=?',(*values.values(),run_id))
            self._event(s,run_id,state,values)

    def _schedule(self):
        while not self.stop.wait(0.2):
            try:
                self._tick()
            except Exception as exc:
                self.scheduler_error = type(exc).__name__+':'+str(exc)
                # Fail closed instead of reporting a healthy but dead scheduler.
                (self.run_root/'scheduler_failure.json').write_text(json.dumps({
                    'reason':self.scheduler_error,'at':ep.utc_now()}))
                return

    def _tick(self):
        with self.guard:
            for slot, record in list(self.processes.items()):
                proc, run_id, started, handles = record
                row = self._row(run_id)
                timed_out = time.monotonic()-started > (1800 if slot=='CPU' else 1800)
                if proc.poll() is None and (row['cancel_requested'] or timed_out):
                    proc.terminate()
                    try: proc.wait(timeout=5)
                    except subprocess.TimeoutExpired: proc.kill()
                if proc.poll() is not None:
                    for h in handles:h.close()
                    state = 'CANCELLED' if row['cancel_requested'] else 'FAILED' if timed_out or proc.returncode else 'EXECUTED'
                    output = self._output(row)
                    reason = 'WALL_BUDGET_EXCEEDED' if timed_out else None
                    if state=='FAILED' and (output/'failure.json').is_file():
                        reason = ep.read_json(output/'failure.json').get('reason')
                    if state=='EXECUTED' and not all((output/name).is_file() for name in ('result.json','artifacts.json')):
                        state,reason='FAILED','SUCCESS_EXIT_WITHOUT_VERIFIABLE_RESULT'
                    elapsed=time.monotonic()-started
                    ep.write_immutable(output.parent/'exit.json',{'exit_code':proc.returncode,
                        'state':state,'wall_seconds':elapsed,'device':row['device'],'finished_at':ep.utc_now()})
                    self._set(run_id,state,exit_code=proc.returncode,reason=reason,pid=None,
                              wall_seconds=row['wall_seconds']+elapsed,
                              gpu_wall_seconds=row['gpu_wall_seconds']+(elapsed if slot!='CPU' else 0))
                    self.processes.pop(slot)
            # A parent-death signal normally stops old workers. Never kill a
            # stale PID or schedule over a surviving orphan after restart.
            alive = []
            for run_id,pid in self.orphans.items():
                try:
                    cmdline = Path(f'/proc/{pid}/cmdline').read_bytes()
                    if b'interactive_worker.py' in cmdline and run_id.encode() in cmdline:alive.append(pid)
                except OSError:pass
            if alive:return
            with self.db() as s:
                gpu_used=s.db.execute('SELECT COALESCE(sum(gpu_wall_seconds),0) FROM eval_api_runs').fetchone()[0]
                gpu_used+=s.db.execute('SELECT COALESCE(sum(seconds),0) FROM eval_api_budget_reservations').fetchone()[0]
            gpu_used += sum(time.monotonic()-v[2] for slot,v in self.processes.items() if slot!='CPU')
            output_over_budget=False
            if self.processes and time.monotonic()-self.last_disk_check>5:
                self.last_disk_check=time.monotonic()
                output_over_budget=sum(p.stat().st_size for p in self.run_root.rglob('*') if p.is_file())>self.config.get('new_output_bytes_cap',5000000000)
            if output_over_budget or gpu_used>=self.config.get('gpu_stage_wall_seconds_cap',7200):
                for slot,(proc,run_id,_,_) in self.processes.items():
                    if output_over_budget or slot!='CPU':
                        if proc.poll() is None:proc.terminate()
                with self.db() as s:
                    waiting=[r[0] for r in s.db.execute("SELECT run_id FROM eval_api_runs WHERE state='QUEUED'")]
                for run_id in waiting:self._set(run_id,'BLOCKED',reason='FINITE_EXECUTION_SCOPE_BUDGET_EXCEEDED')
                return
            with self.db() as s:
                queued = [dict(r) for r in s.db.execute("SELECT * FROM eval_api_runs WHERE state='QUEUED' ORDER BY created")]
            for row in queued:
                request = json.loads(row['spec_json'])['request']
                cpu = request['kind']=='checks'
                slots = ['CPU'] if cpu else self.devices
                slot = next((x for x in slots if x not in self.processes),None)
                if slot is None:continue
                attempt = row['attempt']+1
                directory = self.run_root/row['run_id']/f'attempt_{attempt:04d}'
                directory.mkdir(exist_ok=False)
                # Virtualenv python is intentionally a symlink to an existing
                # interpreter outside the checkout. Only trusted server config
                # selects it; request paths remain confined by local_file().
                interpreter=(self.root/self.config.get('cpu_python','.venv-qc/bin/python')).absolute()
                if cpu and (not interpreter.is_relative_to(self.root) or not interpreter.is_file() or not os.access(interpreter,os.X_OK)):
                    raise APIError(503,'CONFIGURED_CPU_INTERPRETER_UNAVAILABLE')
                python = str(interpreter) if cpu else self.gpu_python
                command = [python,str(self.root/'tools/interactive_worker.py'),
                           '--spec',str(self.run_root/row['run_id']/'request.json'),
                           '--out',str(directory/'output'),'--parent-pid',str(os.getpid())]
                if not cpu:command += ['--device',slot]
                env = {**os.environ,'OMP_NUM_THREADS':'6','MKL_NUM_THREADS':'6','OPENBLAS_NUM_THREADS':'6',
                       'PYTHONDONTWRITEBYTECODE':'1','TOKENIZERS_PARALLELISM':'false'}
                handles = [(directory/n).open('w') for n in ('stdout.log','stderr.log')]
                try:
                    proc = subprocess.Popen(command,cwd=self.root,env=env,stdout=handles[0],stderr=handles[1],start_new_session=True)
                except OSError as exc:
                    for h in handles:h.close()
                    self._set(row['run_id'],'FAILED',reason=str(exc),attempt=attempt,exit_code=127)
                    continue
                ep.write_immutable(directory/'command.json',{'argv':command,'cwd':str(self.root),
                    'environment':{k:env[k] for k in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','PYTHONDONTWRITEBYTECODE')},
                    'started_at':ep.utc_now(),'device':None if cpu else slot})
                self._set(row['run_id'],'RUNNING',attempt=attempt,device=None if cpu else slot,pid=proc.pid)
                self.processes[slot] = (proc,row['run_id'],time.monotonic(),handles)

    def close(self):
        self.stop.set()
        if self.dispatcher.is_alive():self.dispatcher.join(timeout=10)
        for slot,(proc,run_id,_,handles) in self.processes.items():
            if proc.poll() is None:
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
            for h in handles:h.close()
            self._set(run_id,'INTERRUPTED',reason='API_SHUTDOWN_EXPLICIT_RESUME_REQUIRED',pid=None,exit_code=proc.returncode)
        self.owner.close()


def openapi():
    paths = {p:{m:{'responses':{'200':{'description':'JSON result'},'400':{'description':'Invalid request'},
        '401':{'description':'Missing bearer token'},'409':{'description':'Blocked/conflicting request'}}}}
        for p,m in [('/v1/health','get'),('/v1/tasks','get'),('/v1/models','get'),('/v1/tasks/pilots','post'),
                    ('/v1/tasks/{task_id}/readiness','get'),('/v1/tasks/{task_id}/pilot','post'),
                    ('/v1/runs','get'),('/v1/runs/{run_id}','get'),('/v1/runs/{run_id}/result','get'),
                    ('/v1/runs/{run_id}/events','get'),('/v1/runs/{run_id}/logs','get'),('/v1/runs/{run_id}/predictions','get'),('/v1/runs/{run_id}/cancel','post'),
                    ('/v1/runs/{run_id}/resume','post'),('/v1/runs/{run_id}/replay','post')]}
    paths['/v1/runs']['post']={'summary':'Submit encoder, diagnostic, assay or allowlisted checks',
        'parameters':[{'name':'Idempotency-Key','in':'header','required':True,'schema':{'type':'string'}}],
        'requestBody':{'required':True,'content':{'application/json':{'schema':{'type':'object','required':['kind'],
            'properties':{'kind':{'enum':['encoder','diagnostic','assay','checks']},
                'records':{'type':'array','maxItems':16,'items':{'type':'object','required':['observation_id','sequence'],
                    'properties':{'observation_id':{'type':'string'},'sequence':{'type':'string','pattern':'^[ACGU]+$','maxLength':1022}}}},
                'initialization':{'enum':['pretrained','random']},'seed':{'type':'integer','minimum':0},
                'batch_size':{'type':'integer','minimum':1,'maximum':4},'task_id':{'type':'string'},
                'suite':{'enum':['project','packet','site','all']}}}}}},
        'responses':{'202':{'description':'Queued'},'409':{'description':'Scientifically blocked; persisted run'},'422':{'description':'Invalid or unsupported inputs'}}}
    for path,methods in paths.items():
        for method,operation in methods.items():
            params=operation.setdefault('parameters',[])
            params += [{'name':name,'in':'path','required':True,'schema':{'type':'string'}}
                       for name in re.findall(r'\{([^}]+)\}',path)]
            if method=='post' and (path.endswith('/pilot') or path.endswith('/resume') or path.endswith('/pilots')):
                params.append({'name':'Idempotency-Key','in':'header','required':True,'schema':{'type':'string'}})
            if method=='post' and path!='/v1/runs':
                schema={'type':'object','additionalProperties':False}
                if path.endswith('/pilots'):
                    schema.update(required=['task_ids'],properties={'task_ids':{'oneOf':[
                        {'const':'all'},{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':198,'uniqueItems':True}]}})
                operation['requestBody']={'required':True,'content':{'application/json':{'schema':schema}}}
    run_schema=paths['/v1/runs']['post']['requestBody']['content']['application/json']['schema']
    props=run_schema['properties']
    props['records']['minItems']=1
    props['records']['items']['additionalProperties']=False
    props['records']['items']['properties']['observation_id']['minLength']=1
    allowed={'encoder':['kind','records','initialization','seed','batch_size'],
             'diagnostic':['kind','initialization','seed'],
             'assay':['kind','task_id'],'checks':['kind','suite']}
    required={'encoder':['kind','records'],'diagnostic':['kind'],'assay':['kind','task_id'],'checks':['kind','suite']}
    variants=[]
    for kind,keys in allowed.items():
        item={key:props[key] for key in keys}
        item['kind']={'const':kind}
        if kind in ('encoder','diagnostic'):item['model_id']={'const':'RNA-FM'}
        variants.append({'type':'object','required':required[kind],'additionalProperties':False,'properties':item})
    paths['/v1/runs']['post']['requestBody']['content']['application/json']['schema']={'oneOf':variants}
    return {'openapi':'3.1.0','info':{'title':'RNA Gym local interactive API','version':'1.0.0'},
        'servers':[{'url':'/'}],'security':[{'bearerAuth':[]}],
        'components':{'securitySchemes':{'bearerAuth':{'type':'http','scheme':'bearer'}}},'paths':paths}


def handler(service):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'RNA-Gym-local/1'
        def log_message(self,*args):pass  # Never log tokens or raw sequence bodies.
        def send(self,status,value,content_type='application/json'):
            body = ep.canonical_bytes(value) if content_type=='application/json' else value
            self.send_response(status)
            self.send_header('Content-Type',content_type+'; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            try:self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError):pass
        def _security(self,path):
            hosts = self.headers.get_all('Host',[])
            if len(hosts)!=1 or urlsplit('//'+hosts[0]).hostname not in ('localhost','127.0.0.1'):
                raise APIError(403,'LOOPBACK_HOST_REQUIRED')
            origin = self.headers.get('Origin')
            if origin and origin not in ('http://'+hosts[0],'https://'+hosts[0]):
                raise APIError(403,'CROSS_ORIGIN_REQUEST_FORBIDDEN')
            if path.startswith('/v1/'):
                token = self.headers.get('Authorization','')
                if not hmac.compare_digest(token.encode(),('Bearer '+service.token).encode()):
                    raise APIError(401,'BEARER_TOKEN_REQUIRED')
        def _body(self):
            if self.headers.get('Transfer-Encoding'):
                raise APIError(400,'CHUNKED_REQUESTS_NOT_SUPPORTED')
            try:length=int(self.headers.get('Content-Length','0'))
            except ValueError:raise APIError(400,'INVALID_CONTENT_LENGTH')
            if not 0 <= length <= 65536:raise APIError(413,'BOUNDED_REQUEST_BODY_EXCEEDED')
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':
                raise APIError(415,'APPLICATION_JSON_REQUIRED')
            try:body=ep.strict_json_loads(self.rfile.read(length).decode())
            except (ValueError,UnicodeError,ep.ProtocolError):raise APIError(400,'STRICT_JSON_OBJECT_REQUIRED')
            if not isinstance(body,dict):raise APIError(400,'JSON_OBJECT_REQUIRED')
            return body
        def do_GET(self):self._dispatch('GET')
        def do_POST(self):self._dispatch('POST')
        def _dispatch(self,method):
            path=urlsplit(self.path).path
            try:
                self.connection.settimeout(20)
                self._security(path)
                if method=='GET':
                    if path in ('/','/docs'):
                        return self.send(200,(service.root/'tools/api_console/api-console.html').read_bytes(),'text/html')
                    if path in ('/api-console.css','/api-console.js'):
                        suffix='text/css' if path.endswith('.css') else 'application/javascript'
                        return self.send(200,(service.root/'tools/api_console'/path[1:]).read_bytes(),suffix)
                    if path=='/openapi.json':return self.send(200,openapi())
                    if path=='/v1/health':return self.send(200,service.health())
                    if path=='/v1/tasks':return self.send(200,{'tasks':[service.readiness(r['task_id']) for r in service.tasks()]})
                    if path=='/v1/models':
                        registry=ep.read_json(service.root/'configs/model_adapter_registry.yaml')
                        return self.send(200,{'models':[{'model_id':m['model_id'],
                            'api_encoder_implemented':m['model_id']=='RNA-FM',
                            'scientific_admission_required':True,'runtime_loadability':m['runtime_loadability']} for m in registry['models']]})
                    if path=='/v1/runs':return self.send(200,{'runs':service.runs()})
                    match=re.fullmatch('/v1/tasks/([^/]+)/readiness',path)
                    if match:return self.send(200,service.readiness(match[1]))
                    match=re.fullmatch('/v1/runs/(RUN_[0-9a-f]{32})(?:/(result|events|logs|predictions))?',path)
                    if match:
                        name=match[2]
                        methods={'result':service.result,'events':service.events,'logs':service.logs,'predictions':service.predictions}
                        return self.send(200,methods[name](match[1]) if name else service.view(match[1]))
                else:
                    body=self._body();key=self.headers.get('Idempotency-Key')
                    if path=='/v1/tasks/pilots':
                        if set(body)!={'task_ids'}:raise APIError(400,'EXPLICIT_TASK_IDS_REQUIRED')
                        ids=[r['task_id'] for r in service.tasks()] if body['task_ids']=='all' else body['task_ids']
                        if not isinstance(ids,list) or not ids or len(ids)>198 or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids):
                            raise APIError(400,'UNIQUE_REGISTERED_TASK_LIST_REQUIRED')
                        if set(ids)-{r['task_id'] for r in service.tasks()}:
                            raise APIError(404,'UNREGISTERED_TASK_ID_NO_PARTIAL_BULK_SUBMISSION')
                        if not key or len(key)>100:raise APIError(400,'BULK_IDEMPOTENCY_KEY_REQUIRED_MAX_100')
                        runs=[service.submit({'kind':'assay','task_id':i},key+'.'+i)[0] for i in ids]
                        counts={state:sum(r['state']==state for r in runs) for state in sorted({r['state'] for r in runs})}
                        return self.send(207,{'runs':runs,'states':counts,'requested':len(ids),
                            'assay_executions_completed':sum(r['state']=='EXECUTED' for r in runs),'rankable_real_result':False})
                    match=re.fullmatch('/v1/tasks/([^/]+)/pilot',path)
                    if match:
                        if body:raise APIError(400,'NO_CLIENT_TASK_PROTOCOL_OVERRIDES')
                        body={'kind':'assay','task_id':match[1]}
                    if path=='/v1/runs' or match:
                        run,created=service.submit(body,key)
                        return self.send(409 if run['state']=='BLOCKED' else 202 if run['state']=='QUEUED' else 200,run)
                    match=re.fullmatch('/v1/runs/(RUN_[0-9a-f]{32})/(cancel|resume|replay)',path)
                    if match:
                        if body:raise APIError(400,'ACTION_CANNOT_CHANGE_PINNED_PROTOCOL')
                        return self.send(200,service.replay(match[1]) if match[2]=='replay' else service.action(match[1],match[2],key))
                raise APIError(404,'ROUTE_NOT_FOUND')
            except APIError as exc:self.send(exc.code,{'status':'REJECTED','reason':exc.reason,'rankable_real_result':False})
            except (ValueError,TypeError,KeyError,ep.ProtocolError) as exc:self.send(400,{'status':'REJECTED','reason':str(exc),'rankable_real_result':False})
            except Exception as exc:self.send(500,{'status':'FAILED','reason':type(exc).__name__,'rankable_real_result':False})
    return Handler


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=ROOT/'configs/interactive_api.json')
    parser.add_argument('--run-root',type=Path,default=ROOT/'runs/interactive_api')
    parser.add_argument('--state-db',type=Path,default=ROOT/'run-state.sqlite')
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    service=Service(ROOT,ep.read_json(args.config),args.run_root,args.state_db)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),handler(service));server.daemon_threads=True
    info={'url':f'http://127.0.0.1:{server.server_port}','pid':os.getpid(),
          'token_file':str(service.token_file),'state_db':str(service.state_db),
          'bind_scope':'LOOPBACK_ONLY','all_fm_forward_requires_cuda':True}
    (service.run_root/'runtime.json').write_text(json.dumps(info,indent=2)+'\n')
    print(json.dumps(info),flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();service.close()


if __name__=='__main__':main()
