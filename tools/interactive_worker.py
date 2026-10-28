#!/usr/bin/env python3
"""Fixed API worker; clients cannot choose commands, paths or admission policy."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import evaluation_protocol as ep


def _parent_lifetime(pid):
    # Linux worker dies with the API dispatcher that owns it, not with a later
    # process reusing the same PID. A restart never kills an arbitrary PID.
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(1,signal.SIGTERM,0,0,0)!=0:
        raise OSError(ctypes.get_errno(),'PR_SET_PDEATHSIG_FAILED')
    if os.getppid()!=pid:
        raise InterruptedError('OWNING_API_PROCESS_ALREADY_EXITED')


def run_checks(suite,out):
    packet=ROOT.parent/'RNA_Gym_Research_Codex_Package_2026-10-26'
    commands=[]
    if suite in ('project','all'):
        commands.append(('project',[sys.executable,'-m','unittest','discover','-s','tests','-v']))
    if suite in ('site','all'):
        commands += [('site',[sys.executable,'tools/generate_site.py','--verify']),
                     ('task_bundles',[sys.executable,'tools/build_task_bundles.py','--verify'])]
    if suite in ('packet','all'):
        commands += [('packet',[sys.executable,str(packet/'scripts/validate_packet.py')]),
                     ('hold_contract',[sys.executable,str(packet/'scripts/validate_run_result.py'),str(packet/'examples/run_result.HOLD.json')]),
                     ('contract_guards',[sys.executable,str(packet/'scripts/test_contract_guards.py')])]
    if suite=='all':
        candidate=out/'public_candidate'
        commands += [('public_candidate',[sys.executable,'tools/prepare_public.py','--out',str(candidate)]),
                     ('public_candidate_tests',[sys.executable,'-m','unittest','discover','-s',str(candidate/'tests'),'-v'])]
    results=[]
    for name,argv in commands:
        started=time.monotonic()
        with (out/(name+'.stdout.log')).open('w') as stdout,(out/(name+'.stderr.log')).open('w') as stderr:
            proc=subprocess.Popen(argv,cwd=ROOT,stdout=stdout,stderr=stderr,
                                  env={**os.environ,'RNAGYM_BROWSER_TESTS':'1'})
            try:
                code=proc.wait(timeout=900)
            except BaseException:
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
                raise
        result={'name':name,'argv':argv,'exit_code':code,'wall_seconds':time.monotonic()-started,
                'stdout_sha256':ep.sha256_file(out/(name+'.stdout.log')),
                'stderr_sha256':ep.sha256_file(out/(name+'.stderr.log')),
                'environment':{'RNAGYM_BROWSER_TESTS':'1'}}
        ep.write_immutable(out/(name+'.command.json'),result)
        results.append(result)
    return {'schema_version':'rna_gym.api_software_checks.v1',
            'status':'EXECUTED' if all(r['exit_code']==0 for r in results) else 'FAILED',
            'scope':'SOFTWARE_AND_CONTRACT_CHECKS_NOT_SCIENTIFIC_ASSAY_EXECUTION',
            'commands':results,'rankable_real_result':False}


def execute(context,out,device):
    from interactive_api import verify_context,local_file
    verify_context(context)
    request=context['request'];kind=request['kind']
    if kind=='checks':return run_checks(request['suite'],out)
    if not device or not device.startswith('cuda:'):
        raise ep.ProtocolError('FM_REQUIRES_EXPLICIT_ALLOCATED_GPU_NO_CPU_FALLBACK')
    manifest=ep.read_json(local_file(ROOT,context['model_manifest']))
    if kind=='diagnostic':
        from rnafm_adapter import smoke
        return smoke(manifest,out/'diagnostic',device=device,
                     initialization=request['initialization'],seed=request['seed'])
    if kind=='encoder':
        from rnafm_adapter import RNAFMAdapter
        adapter=RNAFMAdapter(manifest,device=device,initialization=request['initialization'],seed=request['seed'])
        rows,cache=adapter.pooled(request['records'],out.parent.parent/'feature_cache',batch_size=request['batch_size'])
        records=[]
        for row in rows:
            length=row['length_nt']
            records.append({'observation_id':row['observation_id'],'length_nt':length,
                'sequence_sha256':row['sequence_sha256'],'pooled_embedding':row['pooled_embedding'],
                'valid_position_mask':[True]*length,
                'token_to_nucleotide':[None]*int(adapter.alphabet.prepend_bos)+list(range(length))+[None]*int(adapter.alphabet.append_eos)})
        return {'schema_version':'rna_gym.api_encoder_result.v1','status':'EXECUTED',
            'scope':'UNLABELED_REAL_FM_GPU_REPRESENTATION_NOT_FUNCTIONAL_PREDICTION',
            'output_kind':'frozen_nucleotide_masked_mean_representation',
            'records':records,'resources':adapter.resources(),'cache':cache,'contract':adapter.contract,
            'n_expected':len(request['records']),'n_encoded':len(records),'n_failed':0,
            'functional_labels_used':0,'functional_predictions_produced':0,'rankable_real_result':False}
    if kind=='assay':
        from frozen_pilot import run_pilot
        binding=context['binding']
        result=run_pilot(ep.read_json(local_file(ROOT,binding['config'])),local_file(ROOT,binding['input']),
                         local_file(ROOT,binding['splits']),manifest,out/'pilot',device=device)
        result['scope']='EXPLORATORY_ADMITTED_ASSAY_API_PILOT_NOT_MAIN_LEADERBOARD'
        return result
    raise ep.ProtocolError('UNKNOWN_FIXED_WORKER_KIND')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--parent-pid',type=int,required=True)
    parser.add_argument('--device')
    args=parser.parse_args()
    started=time.monotonic()
    def interrupted(_signum,_frame):raise InterruptedError('API_CANCEL_OR_PARENT_EXIT')
    signal.signal(signal.SIGTERM,interrupted)
    _parent_lifetime(args.parent_pid)
    args.out.mkdir(parents=True,exist_ok=False)
    try:
        context=ep.read_json(args.spec)
        if ep.digest_json(context['request'])!=context['request_sha256']:
            raise ep.ProtocolError('IMMUTABLE_REQUEST_HASH_MISMATCH')
        result=execute(context,args.out,args.device)
        if result['status']!='EXECUTED':
            ep.write_immutable(args.out/'checks_failed.json',result)
            raise ep.ProtocolError('SOFTWARE_CHECK_SUITE_FAILED_SEE_EXIT_CODES')
        result['worker_wall_seconds']=time.monotonic()-started
        ep.write_immutable(args.out/'result.json',result)
        inventory={str(p.relative_to(args.out)):ep.sha256_file(p)
                   for p in sorted(args.out.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}
        ep.write_immutable(args.out/'artifacts.json',inventory)
        print(json.dumps({'status':'EXECUTED','scope':result['scope'],'rankable_real_result':False}),flush=True)
        return 0
    except (Exception,KeyboardInterrupt) as exc:
        failure={'status':'FAILED','reason':str(exc),'exception_type':type(exc).__name__,
                 'wall_seconds':time.monotonic()-started,'rankable_real_result':False}
        ep.write_immutable(args.out/'failure.json',failure)
        print(json.dumps(failure),file=sys.stderr,flush=True)
        return 2


if __name__=='__main__':raise SystemExit(main())
