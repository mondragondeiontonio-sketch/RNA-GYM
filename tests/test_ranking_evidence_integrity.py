"""R01/R02 synthetic receipts only: never real admission or model evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rna_gym import RNALeaderboard, RankingPanel
from tools import evaluation_protocol as ep


class RankingEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.out=self.root/'runs/cell';self.out.mkdir(parents=True)
        self.write('configs/model_adapter_registry.yaml',{'models':[]})
        self.write('configs/native_sdk.json',{'dataset_catalog':'data/catalog.json','private_assets_manifest':'runs/private.json','dataset_aliases':{},'execution_bindings_source':'configs/bindings.json','execution_bindings_key':'task_bindings'})
        self.write('data/catalog.json',{'assets':[],'tasks':[{'task_id':'FIXTURE_ONLY','asset_ids':[],'local_package_files':0,'admitted':False,'is_excluded_non_assay':False}]})
        self.contract={'task_id':'TOY_ONLY','baseline_id':'mean_null','synthetic':True,
            'problem_type':'regression','input_mode':'sequence','alphabet':'ACGU',
            'label_definition':'SYNTHETIC_ONLY','label_unit':'synthetic','split_source':'SYNTHETIC_ONLY',
            'canonical_assay_id':'NOT_A_REAL_ASSAY'}
        self.rows=[{'observation_id':str(i),'sequence':s,'label':float(i)}
                   for i,s in enumerate(['AAA','AAC','AAG','CCA','CCC','CCG'])]
        self.splits={str(i):'train' if i<3 else 'test' for i in range(6)}
        (self.root/'data/input.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in self.rows))
        self.write('data/splits.json',self.splits)
        self.write('configs/task.json',{'task':self.contract})
        self.write('configs/bindings.json',{'task_bindings':{'FIXTURE_ONLY':{'config':'configs/task.json','input':'data/input.jsonl','splits':'data/splits.json'}}})
        self.prepared=ep.prepare(self.contract,self.root/'data/input.jsonl',self.root/'data/splits.json')
        selected=sorted(['0','1','2'],key=lambda i:ep.digest_json({'sample_selection_seed':11,'observation_id':i}))[:2]
        ledger={'fit_unique':2,'tune_unique':0,'calibration_unique':0,'total_unique':2,'test_selection_labels':0,'hpo_candidates':0}
        self.head={'fit_observation_ids':selected,'protocol':'frozen_ridge','kind':'linear','problem_type':'regression','label_budget':ledger}
        mc={'checkpoint_sha256':'a'*64,'initialization':'pretrained','initialization_seed':0}
        self.result={'dataset_id':'FIXTURE_ONLY','status':'EXECUTED','run_kind':'real',
            'model_id':'RNA-FM','protocol':'frozen_ridge','seed':11,'model_initialization':'pretrained',
            'model_initialization_seed':0,'label_budget_declared':2,'label_budget':ledger,
            'split_requested':'official','input_context':'sequence_only','target_column':None,
            'output_directory':'runs/cell','model_contract':mc,'assay_id':'NOT_A_REAL_ASSAY'}
        self.resolved={**self.result,'input_sha256':ep.sha256_file(self.root/'data/input.jsonl'),
            'split_sha256':ep.sha256_file(self.root/'data/splits.json'),'selected_train_ids':selected,'hpo_candidates':0}
        predictions=[{'observation_id':r['observation_id'],'split':'test','input_sha256':ep.input_key(r,'sequence'),'prediction':r['label']} for r in self.rows[3:]]
        p={**self.prepared,'config':{**self.contract,'baseline_id':'RNA-FM_frozen_ridge'}}
        self.metrics=ep.evaluate(p,predictions);self.result['metrics']=self.metrics['metrics']
        for name,value in [('head.json',self.head),('resolved_config.json',self.resolved),
                           ('predictions.json',predictions),('metrics.json',self.metrics),('paired_statistics.json',{'scope':'SYNTHETIC_CONTRACT_ONLY'})]:
            self.write('runs/cell/'+name,value)
        self.seal()
        self.board=RNALeaderboard(root=self.root,scope='exploratory')
        # Synthetic in-memory validator precondition, not a scientific approval.
        self.board.hub.records['FIXTURE_ONLY']['admitted']=True

    def write(self,name,value):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))

    def seal(self):
        self.result['artifacts']={name:ep.sha256_file(self.out/name) for name in
            ['resolved_config.json','head.json','predictions.json','metrics.json','paired_statistics.json']}
        self.write('runs/cell/native_result.json',self.result)

    def validate(self,value=None):
        value=value or self.result
        panel=RankingPanel(dataset_ids=('FIXTURE_ONLY',),model_ids=(value['model_id'],),seeds=(11,),
            protocol=value['protocol'],metric='spearman',label_budget=2,initialization=value['model_initialization'])
        with patch.object(ep,'prepare',return_value=self.prepared):
            return self.board._validated(value,panel)

    def test_complete_receipt_positive_control(self):
        self.assertEqual(self.validate(),('VERIFIED',1.0))

    def test_external_model_protocol_and_initialization_relabel_rejected(self):
        for edit in [{'model_id':'RiNALMo'},{'protocol':'frozen_mlp'},
                     {'model_initialization':'random'},{'model_initialization_seed':9}]:
            with self.subTest(edit=edit):self.assertTrue(self.validate({**self.result,**edit})[0].startswith('EVIDENCE_REJECTED'))

    def test_rewriting_receipt_does_not_override_resolved_model_binding(self):
        self.result['model_id']='RiNALMo';self.write('runs/cell/native_result.json',self.result)
        self.assertTrue(self.validate()[0].startswith('EVIDENCE_REJECTED'))

    def test_receipt_and_resolved_relabel_cannot_override_encoder_initialization(self):
        self.result['model_initialization']='random'
        self.resolved['model_initialization']='random'
        self.write('runs/cell/resolved_config.json',self.resolved);self.seal()
        self.assertTrue(self.validate()[0].startswith('EVIDENCE_REJECTED'))

    def test_empty_or_incomplete_artifact_manifest_rejected(self):
        for artifacts in [{},{k:v for k,v in self.result['artifacts'].items() if k!='paired_statistics.json'}]:
            item={**self.result,'artifacts':artifacts};self.write('runs/cell/native_result.json',item)
            self.assertTrue(self.validate(item)[0].startswith('EVIDENCE_REJECTED'))

    def test_missing_original_receipt_rejected(self):
        (self.out/'native_result.json').unlink()
        self.assertTrue(self.validate()[0].startswith('EVIDENCE_REJECTED'))

    def test_inconsistent_or_nonzero_tuning_ledger_rejected_after_rehash(self):
        for edit in [{'tune_unique':100},{'calibration_unique':40},{'hpo_candidates':9},
                     {'fit_unique':1},{'total_unique':True}]:
            head=copy.deepcopy(self.head);head['label_budget'].update(edit)
            self.write('runs/cell/head.json',head);self.seal()
            with self.subTest(edit=edit):self.assertTrue(self.validate()[0].startswith('EVIDENCE_REJECTED'))

    def test_unknown_training_uid_and_resolved_hpo_rejected(self):
        head=copy.deepcopy(self.head);head['fit_observation_ids']=['UNKNOWN','0']
        self.write('runs/cell/head.json',head);self.seal()
        self.assertTrue(self.validate()[0].startswith('EVIDENCE_REJECTED'))
        self.write('runs/cell/head.json',self.head)
        self.resolved['hpo_candidates']=9;self.write('runs/cell/resolved_config.json',self.resolved);self.seal()
        self.assertTrue(self.validate()[0].startswith('EVIDENCE_REJECTED'))


if __name__=='__main__':unittest.main()
