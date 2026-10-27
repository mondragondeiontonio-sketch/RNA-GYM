"""Dataset and capability rankings on a predeclared compatible common panel.

No heterogeneous overall score, absolute Spearman, post-hoc intersection,
missing-as-zero, best-head selection or mirror-as-independent-source weighting.
"""
from dataclasses import dataclass,field,asdict
import math
from pathlib import Path
from collections import defaultdict
from .datasets import DatasetHub

DIRECTIONS={'spearman':'higher','average_precision':'higher','decoded_pair_f1':'higher','masked_mae':'lower'}


@dataclass(frozen=True)
class RankingPanel:
    dataset_ids:tuple
    model_ids:tuple
    seeds:tuple
    protocol:str
    metric:str
    initialization:str='pretrained'
    label_budget:int=64
    split:str='official'
    input_context:str='sequence_only'
    source_groups:dict=field(default_factory=dict)
    assay_ids:dict=field(default_factory=dict)

    def __post_init__(self):
        for name in ('dataset_ids','model_ids','seeds'):
            values=getattr(self,name)
            if not values or len(set(values))!=len(values):raise ValueError('NONEMPTY_UNIQUE_FROZEN_PANEL_REQUIRED:'+name)
        if self.metric not in DIRECTIONS:raise ValueError('PRIMARY_METRIC_NOT_IMPLEMENTED_NO_MIXED_SCALE_AGGREGATE')
        if any(type(s) is not int or s<0 for s in self.seeds):raise ValueError('EXPLICIT_PANEL_SEEDS_REQUIRED')

    @property
    def sha256(self):
        from tools.evaluation_protocol import digest_json
        return digest_json(asdict(self))


def _mean_by_source(dataset_values,source_groups):
    """Pure numeric helper, caller must establish real source independence."""
    if set(dataset_values)!=set(source_groups):raise ValueError('FIXED_PANEL_COVERAGE_REQUIRED_NO_DATASET_DELETION')
    groups=defaultdict(list)
    for did,value in dataset_values.items():
        if not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError('FINITE_SAME_METRIC_VALUES_REQUIRED')
        groups[source_groups[did]].append(float(value))
    if any(not isinstance(g,str) or not g for g in groups):raise ValueError('EXPLICIT_SOURCE_CLUSTER_ID_REQUIRED')
    return math.fsum(math.fsum(v)/len(v) for v in groups.values())/len(groups)


def _ranks(scores,direction):
    order=sorted(scores,key=lambda key:scores[key],reverse=direction=='higher')
    result={};start=0
    while start<len(order):
        end=start+1
        while end<len(order) and scores[order[end]]==scores[order[start]]:end+=1
        for key in order[start:end]:result[key]=(start+1+end)/2
        start=end
    return result


class RNALeaderboard:
    def __init__(self,*,root=None,scope='formal'):
        if scope not in ('formal','exploratory'):raise ValueError('Rank scope must be explicit formal or exploratory')
        self.hub=DatasetHub(root=root);self.root=self.hub.root;self.scope=scope
        self.results=[]

    def add(self,result):
        from tools.evaluation_protocol import read_json
        if hasattr(result,'as_dict'):value=result.as_dict()
        elif isinstance(result,(str,Path)):value=read_json(result)
        elif isinstance(result,dict):value=result
        else:raise TypeError('Native results, result path or result mapping required')
        rows=value.get('runs',[value])
        self.results.extend(rows)
        return self

    def _validated(self,result,panel):
        from tools import evaluation_protocol as ep
        if result.get('status')!='EXECUTED':return result.get('status','NOT_RUN'),None
        if result.get('run_kind')!='real':return 'SYNTHETIC_NOT_A_REAL_RANKING',None
        if self.scope=='formal' and (result.get('evaluation_phase')!='confirmatory' or not result.get('formal_leaderboard_eligible')):
            return 'EXPLORATORY_NOT_FORMAL',None
        task=self.hub.records[result['dataset_id']]
        if not task.get('admitted'):return 'SCIENTIFIC_ADMISSION_REQUIRED',None
        try:
            out=(self.root/result['output_directory']).resolve()
            if not out.is_relative_to(self.root/'runs'):raise ValueError('PRIVATE_PREDICTION_ARTIFACT_PATH_REQUIRED')
            for name,digest in result['artifacts'].items():
                path=(out/name).resolve()
                if not path.is_relative_to(out) or ep.sha256_file(path)!=digest:raise ValueError('RESULT_ARTIFACT_HASH_MISMATCH')
            resolved=ep.read_json(out/'resolved_config.json')
            cfg=ep.read_json(self.root/self.hub.config['execution_bindings_source'])
            binding=cfg[self.hub.config['execution_bindings_key']][result['dataset_id']]
            task_config=ep.read_json(self.root/binding['config'])
            contract=dict(task_config.get('task',task_config))
            if contract.get('admission_evidence'):contract['admission_evidence']=str((self.root/contract['admission_evidence']).resolve())
            prepared=ep.prepare(contract,self.root/binding['input'],self.root/binding['splits'])
            if (prepared['metadata']['input_sha256']!=resolved['input_sha256'] or
                prepared['metadata']['split_sha256']!=resolved['split_sha256']):raise ValueError('FROZEN_DATA_OR_SPLIT_CHANGED')
            expected_ids=sorted([r['observation_id'] for r in prepared['rows'] if prepared['splits'][r['observation_id']]=='train'],
                key=lambda oid:ep.digest_json({'sample_selection_seed':result['seed'],'observation_id':oid}))[:panel.label_budget]
            head=ep.read_json(out/'head.json')
            if sorted(head['fit_observation_ids'])!=sorted(expected_ids) or sorted(resolved['selected_train_ids'])!=sorted(expected_ids):
                raise ValueError('UNMATCHED_OR_LABEL_SELECTED_TRAINING_OBSERVATIONS')
            if resolved['model_contract']!=result['model_contract']:raise ValueError('MODEL_CONTRACT_CHANGED')
            if panel.assay_ids and panel.assay_ids.get(result['dataset_id'])!=result['assay_id']:raise ValueError('PANEL_CANONICAL_ASSAY_MISMATCH')
            if panel.source_groups and panel.source_groups.get(result['dataset_id'])!=result['source_family_id']:raise ValueError('PANEL_SOURCE_GROUP_MISMATCH')
            if self.scope=='formal':
                review_path=result.get('result_review_path')
                if not review_path:raise ValueError('REAL_HUMAN_RESULT_REVIEW_REQUIRED')
                review=ep.read_json(self.root/review_path)
                if (review.get('approved') is not True or not isinstance(review.get('reviewer'),str) or
                    review['reviewer'].strip().upper() in ('','UNKNOWN','PENDING','NONE') or
                    review.get('result_sha256')!=ep.sha256_file(out/'native_result.json') or
                    review.get('panel_sha256')!=panel.sha256):raise ValueError('RESULT_REVIEW_NOT_BOUND_TO_RESULT_AND_PANEL')
            if head['label_budget']['total_unique']!=panel.label_budget or head['label_budget']['test_selection_labels']!=0:
                raise ValueError('UNMATCHED_LABEL_BUDGET_OR_TEST_SELECTION')
            metrics=ep.read_json(out/'metrics.json')
            p={**prepared,'config':{**contract,'baseline_id':metrics['baseline_id']}}
            recalculated=ep.evaluate(p,ep.read_json(out/'predictions.json'))['metrics']
            if recalculated!=result['metrics'] or recalculated!=metrics['metrics']:raise ValueError('METRICS_DO_NOT_REPLAY_FROM_PREDICTIONS')
            if result.get('assay_id')!=contract['canonical_assay_id']:raise ValueError('ASSAY_ID_NOT_BOUND')
            value=recalculated['test'][panel.metric]
            if value is None:return 'UNDEFINED_METRIC',None
            if not math.isfinite(value):raise ValueError('NONFINITE_PRIMARY_METRIC')
            return 'VERIFIED',value
        except (KeyError,ValueError,OSError,ep.ProtocolError) as exc:
            return 'EVIDENCE_REJECTED:'+str(exc),None

    def _matrix(self,panel):
        if not isinstance(panel,RankingPanel):raise ValueError('EXPLICIT_FROZEN_RANKING_PANEL_REQUIRED')
        if set(panel.dataset_ids)-set(self.hub.records):raise ValueError('UNREGISTERED_PANEL_DATASET')
        if any(self.hub.records[d]['is_excluded_non_assay'] for d in panel.dataset_ids):raise ValueError('NON_ASSAY_CANNOT_ENTER_SCIENTIFIC_RANKING_PANEL')
        lookup=defaultdict(list)
        for result in self.results:
            if (result.get('dataset_id') in panel.dataset_ids and result.get('model_id') in panel.model_ids and
                result.get('seed') in panel.seeds and result.get('protocol')==panel.protocol and
                result.get('model_initialization')==panel.initialization and
                result.get('label_budget_declared')==panel.label_budget and result.get('split_requested')==panel.split and
                result.get('input_context')==panel.input_context):
                lookup[(result['dataset_id'],result['model_id'],result['seed'])].append(result)
        cells=[]
        for did in panel.dataset_ids:
            for model in panel.model_ids:
                for seed in panel.seeds:
                    matches=lookup[(did,model,seed)]
                    if len(matches)>1:state,value='DUPLICATE_RUN_NO_BEST_SEED_OR_HEAD_SELECTION',None
                    elif not matches:state,value='NOT_RUN',None
                    else:state,value=self._validated(matches[0],panel)
                    cells.append({'dataset_id':did,'model_id':model,'seed':seed,'state':state,'score':value})
        return cells

    def by_dataset(self,*,panel):
        cells=self._matrix(panel);rows=[]
        for did in panel.dataset_ids:
            scores={};group=[]
            for model in panel.model_ids:
                selected=[r for r in cells if r['dataset_id']==did and r['model_id']==model]
                valid=[r['score'] for r in selected if r['state']=='VERIFIED']
                score=math.fsum(valid)/len(valid) if len(valid)==len(panel.seeds) else None
                row={'dataset_id':did,'model_id':model,'score':score,'rank':None,
                     'n_expected_seeds':len(panel.seeds),'n_verified_seeds':len(valid),
                     'states':[r['state'] for r in selected]}
                group.append(row)
                if score is not None:scores[model]=score
            if len(scores)==len(panel.model_ids):
                rank=_ranks(scores,DIRECTIONS[panel.metric])
                for row in group:row['rank']=rank[row['model_id']]
            rows.extend(group)
        return {'scope':self.scope,'panel_sha256':panel.sha256,'metric':panel.metric,
                'direction':DIRECTIONS[panel.metric],'score_transform':'identity_never_absolute',
                'status':'RANKED' if rows and all(r['rank'] is not None for r in rows) else 'INCOMPLETE_FIXED_PANEL_NO_RANKS',
                'rows':rows,'cells':cells,'formal_leaderboard_eligible':False}

    def by_capability(self,*,panel):
        capabilities={self.hub.records[d]['capability'] for d in panel.dataset_ids}
        if len(capabilities)!=1:raise ValueError('CAPABILITY_PANEL_MUST_BE_HOMOGENEOUS_NO_GLOBAL_MIX')
        if set(panel.source_groups)!=set(panel.dataset_ids):raise ValueError('REVIEWED_SOURCE_GROUPS_REQUIRED_FOR_EVERY_PANEL_DATASET')
        if set(panel.assay_ids)!=set(panel.dataset_ids) or len(set(panel.assay_ids.values()))!=len(panel.dataset_ids):
            raise ValueError('UNIQUE_CANONICAL_ASSAYS_REQUIRED_MIRRORS_ARE_NOT_REPLICATES')
        for did,assay in panel.assay_ids.items():
            if not isinstance(assay,str) or not assay or assay.startswith(('TMP_','UNKNOWN')):
                raise ValueError('REVIEWED_CANONICAL_ASSAY_ID_REQUIRED')
        dataset_view=self.by_dataset(panel=panel)
        rows=[];scores={}
        for model in panel.model_ids:
            values={r['dataset_id']:r['score'] for r in dataset_view['rows'] if r['model_id']==model and r['score'] is not None}
            score=_mean_by_source(values,panel.source_groups) if len(values)==len(panel.dataset_ids) else None
            rows.append({'model_id':model,'capability':next(iter(capabilities)),'score':score,'rank':None,
                         'n_expected_datasets':len(panel.dataset_ids),'n_scored_datasets':len(values),
                         'source_clusters':len(set(panel.source_groups.values()))})
            if score is not None:scores[model]=score
        if len(scores)==len(panel.model_ids):
            rank=_ranks(scores,DIRECTIONS[panel.metric])
            for row in rows:row['rank']=rank[row['model_id']]
        return {'scope':self.scope,'capability':next(iter(capabilities)),'metric':panel.metric,
                'panel_sha256':panel.sha256,'weighting':'SOURCE_CLUSTER_EQUAL_THEN_ASSAY_EQUAL_SAME_METRIC',
                'status':'RANKED' if rows and all(r['rank'] is not None for r in rows) else 'INCOMPLETE_FIXED_PANEL_NO_RANKS',
                'rows':rows,'coverage':dataset_view['cells'],'formal_leaderboard_eligible':False}
