"""Native benchmark composition over the existing task/data/science contracts."""
from dataclasses import dataclass
from pathlib import Path
import time
import uuid
from .datasets import DatasetHub
from .protocols import fit_readout,predict_readout


@dataclass
class BenchmarkResults:
    runs:list
    @property
    def status(self):
        if self.runs and all(r['status']=='EXECUTED' for r in self.runs):return 'EXECUTED'
        if self.runs and all(r['status']=='NOT_APPLICABLE' for r in self.runs):return 'NOT_APPLICABLE'
        if any(r['status']=='EXECUTED' for r in self.runs):return 'PARTIAL'
        if any(r['status']=='FAILED' for r in self.runs):return 'FAILED'
        return 'BLOCKED'
    def as_dict(self):return {'schema_version':'rna_gym.native_benchmark_results.v1','status':self.status,'runs':self.runs,'formal_leaderboard_eligible':False}
    def save(self,path):
        from tools.evaluation_protocol import write_immutable
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);write_immutable(path,self.as_dict())


class RNABenchmark:
    def __init__(self,*,dataset,protocol='frozen_mlp',split='official',seed=42,target=None,
                 label_budget=64,root=None,batch_size=4,output=None):
        if protocol not in ('frozen_ridge','frozen_linear','frozen_mlp'):raise NotImplementedError('PROTOCOL_REQUIRES_A_SEPARATE_NATIVE_TOKEN_PAIR_OR_GENERATION_ADAPTER')
        if type(seed) is not int or seed<0:raise ValueError('Explicit nonnegative seed required')
        if type(label_budget) is not int or not 1<=label_budget<=64:raise NotImplementedError('Only declared strict <=64 fixed-default label budget is implemented; larger budgets require grouped HPO')
        if type(batch_size) is not int or not 1<=batch_size<=4:raise ValueError('Batch size must remain within profiled 1..4')
        self.hub=DatasetHub(root=root);self.root=self.hub.root
        self.dataset_ids=self.hub.resolve(dataset);self.dataset_name=dataset
        self.protocol,self.split,self.seed=protocol,split,seed
        self.target,self.label_budget,self.batch_size=target,label_budget,batch_size
        self.output=None
        if output is not None:
            path=Path(output).expanduser()
            path=(path if path.is_absolute() else self.root/path).resolve()
            if not path.is_relative_to(self.root/'runs'):
                raise ValueError('OUTPUT_MUST_BE_INSIDE_CHECKOUT_RUNS')
            self.output=path

    def inspect(self):
        return {'dataset':self.dataset_name,'task_ids':list(self.dataset_ids),
            'collection_not_single_assay':len(self.dataset_ids)>1,'protocol':self.protocol,
            'split_requested':self.split,'seed':self.seed,'label_budget':self.label_budget,
            'tasks':[self.hub.records[i] for i in self.dataset_ids],
            'formal_five_seed_protocol_unchanged':self.hub.config['formal_training_seeds_unchanged']}

    def evaluate(self,model):
        results=[]
        for tid in self.dataset_ids:
            try:results.append(self._evaluate_one(tid,model))
            except Exception as exc:
                results.append({'schema_version':'rna_gym.native_run.v1','dataset_id':tid,
                    'model_id':getattr(model,'model_id',None),'status':'FAILED',
                    'reason_codes':[type(exc).__name__+':'+str(exc)],'metrics':None,
                    'protocol':self.protocol,'seed':self.seed,'formal_leaderboard_eligible':False})
        return BenchmarkResults(results)

    def _evaluate_one(self,tid,model):
        from tools import evaluation_protocol as ep
        task=self.hub.records[tid]
        base={'schema_version':'rna_gym.native_run.v1','dataset_id':tid,'model_id':getattr(model,'model_id',None),
            'capability':task['capability'],'source_family_id':task['source_family_id'],
            'protocol':self.protocol,'split_requested':self.split,'seed':self.seed,
            'input_context':'sequence_only','target_column':self.target,
            'label_budget_declared':self.label_budget,'run_kind':'real',
            'evaluation_phase':'exploratory','formal_leaderboard_eligible':False,
            'model_initialization':getattr(model,'initialization',None),
            'model_initialization_seed':getattr(model,'initialization_seed',None),
            'data_readiness':{'local_package_files':task['local_package_files'],
                'label_files_in_package':task['label_files_in_package'],
                'labels_present_in_linked_source':task['label_values_present_in_source_package'],
                'exact_assay_mapping_verified':task['exact_assay_mapping_verified']},
            'metrics':None,'reason_codes':[]}
        def blocked(*reasons,status='BLOCKED'):
            return {**base,'status':status,'reason_codes':list(reasons),'functional_labels_used_for_fit':0}
        if task['is_excluded_non_assay']:return blocked('EXCLUDED_NON_ASSAY',status='NOT_APPLICABLE')
        # HOLD is not NO_LABELS. Never hide available target evidence behind the
        # scientific gate, and never promote it to scientific approval either.
        if not task['admitted']:return blocked('SCIENTIFIC_ADMISSION_REQUIRED_NOT_A_NO_DATA_CLAIM',task['scientific_state'])
        cfg=ep.read_json(self.root/self.hub.config['execution_bindings_source'])
        binding=cfg.get(self.hub.config['execution_bindings_key'],{}).get(tid)
        if not binding or not all(binding.get(k) for k in ('config','input','splits')):
            return blocked('FROZEN_EXECUTION_BINDING_REQUIRED')
        configuration=ep.read_json(self.root/binding['config'])
        contract=dict(configuration.get('task',configuration))
        if contract.get('admission_evidence'):
            contract['admission_evidence']=str((self.root/contract['admission_evidence']).resolve())
        if contract.get('task_id')!=tid:return blocked('TASK_BINDING_ID_MISMATCH')
        if configuration.get('split_id')!=self.split:return blocked('EXPLICIT_OFFICIAL_OR_GROUPED_SPLIT_ID_NOT_BOUND')
        targets=(task.get('schema') or {}).get('targets',{})
        if len(targets)>1 and not self.target:return blocked('MULTIPLE_BIOLOGICAL_READOUTS_REQUIRE_ENDPOINT_SELECTION')
        if self.target and contract.get('source_target_column')!=self.target:return blocked('TARGET_COLUMN_NOT_BOUND_TO_REVIEWED_LABEL_DEFINITION')
        if contract.get('input_mode')!='sequence' or contract.get('alphabet')!='ACGU':
            return blocked('EXPLICIT_MODEL_COMPATIBLE_INPUT_RECIPE_REQUIRED_NO_SILENT_DNA_CONVERSION')
        input_path=self.root/binding['input'];split_path=self.root/binding['splits']
        prepared=ep.prepare(contract,input_path,split_path)  # Original human gate and exact input/split/label binding.
        if prepared['config']['problem_type'] not in ('regression','binary_classification'):
            return blocked('SCALAR_HEAD_NOT_A_MULTILABEL_TOKEN_PAIR_OR_3D_PREDICTOR')
        if not hasattr(model,'encode') or not hasattr(model,'contract') or not getattr(model,'device','').startswith('cuda:'):
            return blocked('VERIFIED_LOCAL_GPU_MODEL_ADAPTER_REQUIRED')
        inference_group=configuration.get('inference_group_field')
        if not isinstance(inference_group,str) or any(not isinstance(r.get(inference_group),str) or not r[inference_group]
                for r in prepared['rows'] if prepared['splits'][r['observation_id']]!='train'):
            return blocked('REVIEWED_INDEPENDENT_INFERENCE_GROUPS_REQUIRED')
        ids=[r['observation_id'] for r in prepared['rows'] if prepared['splits'][r['observation_id']]=='train']
        if len(ids)<self.label_budget:return blocked('INSUFFICIENT_TRAIN_LABELS_NO_BUDGET_REDUCTION')
        selected=sorted(ids,key=lambda oid:ep.digest_json({'sample_selection_seed':self.seed,'observation_id':oid}))[:self.label_budget]
        out=self.output/tid if self.output else self.root/'runs/native_sdk_evaluations'/('SDK_'+uuid.uuid4().hex)
        out=out.resolve()
        if not out.is_relative_to(self.root/'runs'):raise ValueError('Real predictions/labels must stay in ignored runs/')
        out.mkdir(parents=True,exist_ok=False);started=time.monotonic()
        resolved={**base,'task_contract':contract,'model_contract':model.contract,
                  'selected_train_ids':selected,'input_sha256':ep.sha256_file(input_path),
                  'split_sha256':ep.sha256_file(split_path),'layer':'last','pooling':'masked_mean',
                  'hpo_candidates':0,'head_epochs':100 if self.protocol=='frozen_mlp' else None}
        ep.write_immutable(out/'resolved_config.json',resolved)
        try:
            features=model.encode(sequences=[r['sequence'] for r in prepared['rows']],layer='last',pooling='masked_mean',batch_size=self.batch_size)
            head=fit_readout(features,prepared['rows'],prepared['splits'],selected,
                             protocol=self.protocol,problem=contract['problem_type'],seed=self.seed,device=model.device)
            values=predict_readout(head,features,device=model.device)
            predictions=[{'observation_id':r['observation_id'],'split':prepared['splits'][r['observation_id']],
                'input_sha256':ep.input_key(r,'sequence'),'prediction':value}
                for r,value in zip(prepared['rows'],values) if prepared['splits'][r['observation_id']]!='train']
            p={**prepared,'config':{**contract,'baseline_id':model.model_id+'_'+self.protocol}}
            metrics=ep.evaluate(p,predictions)
            metrics.update(gpu_used=True,fm_inference_device=model.device,metric_computation_device='cpu')
            ep.write_immutable(out/'head.json',head);ep.write_immutable(out/'predictions.json',predictions)
            ep.write_immutable(out/'metrics.json',metrics)
            from tools.paired_statistics import paired_group_bootstrap
            subset={**prepared,'rows':[r for r in prepared['rows'] if prepared['splits'][r['observation_id']]!='train' or r['observation_id'] in selected]}
            baselines=('mean_null','sequence_stats_ridge','sequence_kmer_ridge') if contract['problem_type']=='regression' else ('prevalence_null','sequence_kmer_logistic')
            baseline_results={}
            for baseline in baselines:
                pbaseline={**subset,'config':{**contract,'baseline_id':baseline,'alpha':1.0,'C':1.0,'kmer_k':3}}
                result_baseline=ep.run(pbaseline)
                directory=out/'baselines'/baseline;directory.mkdir(parents=True)
                for name,value in (('head.json',result_baseline['model']),('predictions.json',result_baseline['predictions']),
                                   ('metrics.json',ep.evaluate(pbaseline,result_baseline['predictions']))):
                    ep.write_immutable(directory/name,value)
                baseline_results[baseline]=result_baseline
            reference=baselines[-1]
            bp={r['observation_id']:r for r in baseline_results[reference]['predictions']}
            fp={r['observation_id']:r for r in predictions}
            heldout=[r for r in prepared['rows'] if prepared['splits'][r['observation_id']]=='test']
            metric='spearman' if contract['problem_type']=='regression' else 'average_precision'
            uncertainty=paired_group_bootstrap([r['label'] for r in heldout],
                [fp[r['observation_id']]['prediction'] for r in heldout],
                [bp[r['observation_id']]['prediction'] for r in heldout],
                [r[inference_group] for r in heldout],problem=contract['problem_type'],metric=metric,
                replicates=2000,seed=20261026)
            uncertainty['formal_comparison']=False
            uncertainty['inference_group_field']=inference_group
            ep.write_immutable(out/'paired_statistics.json',uncertainty)
            if ep.sha256_file(input_path)!=resolved['input_sha256'] or ep.sha256_file(split_path)!=resolved['split_sha256']:
                raise ValueError('FROZEN_INPUT_CHANGED_DURING_EXECUTION')
            ep._approval(contract,resolved['input_sha256'],resolved['split_sha256'])
            result={**base,'status':'EXECUTED','reason_codes':[],'metrics':metrics['metrics'],
                'problem_type':contract['problem_type'],'label_budget':head['label_budget'],
                'model_initialization':model.initialization,'model_initialization_seed':model.initialization_seed,
                'model_contract':model.contract,'assay_id':contract['canonical_assay_id'],
                'resources':model.resources(),'wall_seconds':time.monotonic()-started,
                'artifacts':{name:ep.sha256_file(out/name) for name in ('head.json','predictions.json','metrics.json','resolved_config.json','paired_statistics.json')},
                'output_directory':str(out.relative_to(self.root)),
                'formal_result_review':'NOT_PERFORMED_PILOT_IS_NOT_MAIN_LEADERBOARD'}
            ep.write_immutable(out/'native_result.json',result)
            return result
        except Exception as exc:
            failure={**base,'status':'FAILED','reason_codes':[type(exc).__name__+':'+str(exc)],
                     'wall_seconds':time.monotonic()-started,'output_directory':str(out.relative_to(self.root))}
            ep.write_immutable(out/'failure.json',failure)
            raise
