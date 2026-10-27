"""Native SDK contracts. Synthetic head/ranking arithmetic is not assay evidence."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from rna_gym import RNAHub,DatasetHub,RNABenchmark,ModelUnavailableError,DatasetResolutionError,RNALeaderboard,RankingPanel
from rna_gym.protocols import fit_readout,predict_readout
from rna_gym.rankings import _mean_by_source,_ranks


class CatalogTests(unittest.TestCase):
    def setUp(self):self.hub=DatasetHub(root=ROOT)

    def test_all_original_ids_types_and_label_vs_admission_are_separate(self):
        rows=self.hub.list();self.assertEqual(len(rows),198)
        self.assertEqual(sum(self.hub.catalog['task_type_counts'].values()),198)
        self.assertEqual(self.hub.catalog['task_type_counts']['RNA 2D'],13)
        self.assertEqual(self.hub.catalog['task_type_counts']['RNA 3D'],16)
        self.assertTrue(self.hub.records['T0021']['label_values_present_in_source_package'])
        self.assertFalse(self.hub.records['T0021']['admitted'])
        self.assertFalse(self.hub.records['T0017']['label_values_present_in_source_package'])

    def test_mrl_half_life_stays_two_targets_and_annotation_is_not_assay(self):
        record=self.hub.records['T0022']
        self.assertEqual(set(record['schema']['targets']),{'target_ribosome_load','target_in_cell_half_life'})
        self.assertIn('annotation',self.hub.records['T0023']['capability'])
        self.assertEqual(sum(r['is_excluded_non_assay'] for r in self.hub.list()),9)
        self.assertEqual(sum(r['registered_task_type']=='排除/仅方法学' for r in self.hub.list()),23)

    def test_collections_do_not_silently_choose_an_assay(self):
        runner=RNABenchmark(dataset='utr_translation',root=ROOT)
        self.assertEqual(runner.inspect()['task_ids'],['T0009','T0017'])
        with self.assertRaises(DatasetResolutionError):self.hub.get('utr_translation')

    def test_cluster_lookup_and_model_output_tables_are_not_ground_truth(self):
        cluster=self.hub.assets['HF_f8dd28395a17e62ed861']
        self.assertFalse(cluster['label_evidence'])
        for aid in ('HF_287b2797cface258321d','HF_51b53dab485ecb3d7409'):
            self.assertTrue(self.hub.assets[aid]['label_state'].startswith('EXCLUDED_MODEL_RESULT'))
            self.assertFalse(self.hub.assets[aid]['label_evidence'])

    def test_model_list_no_http_or_openai_key(self):
        with patch('socket.socket',side_effect=AssertionError('Native metadata must not call HTTP')):
            self.assertEqual(len(RNAHub.list(root=ROOT)),6)
            self.assertEqual(len(self.hub.list(task_type='scalar_regression')),23)
        with self.assertRaises(ModelUnavailableError):RNAHub.load('RiNALMo',root=ROOT)
        with self.assertRaises(ModelUnavailableError):RNAHub.load('RNA-FM',root=ROOT,device='cpu')

    def test_source_preview_is_bounded_preserves_raw_sequence_and_checks_hash(self):
        if not self.hub.private['assets'] or not importlib.util.find_spec('pyarrow'):
            self.skipTest('Private local data/PyArrow absent; no download or synthetic dataset substituted')
        dataset=self.hub.get('T0021')
        preview=dataset.preview(rows=2,asset_id='HF_214a7f32ac346e79b8b1')
        self.assertEqual(len(preview['records']),2)
        self.assertFalse(preview['labels_or_sequences_transformed'])
        self.assertIn('target',preview['records'][0])
        self.assertIn('T',preview['records'][0]['sequence'])
        self.assertFalse(preview['rankable_real_result'])
        with self.assertRaises(ValueError):dataset.preview(rows=9)

    def test_native_evaluate_reports_labels_present_but_no_scientific_admission(self):
        class ContractOnlyModel:
            model_id='RNA-FM';initialization='pretrained';initialization_seed=0
            def encode(self,**kwargs):raise AssertionError('Science HOLD must precede any FM inference')
        result=RNABenchmark(dataset='T0021',protocol='frozen_mlp',split='official',seed=42,root=ROOT).evaluate(ContractOnlyModel())
        self.assertEqual(result.status,'BLOCKED')
        self.assertTrue(result.runs[0]['data_readiness']['labels_present_in_linked_source'])
        self.assertIsNone(result.runs[0]['metrics'])
        self.assertIn('SCIENTIFIC_ADMISSION_REQUIRED_NOT_A_NO_DATA_CLAIM',result.runs[0]['reason_codes'])

    def test_no_silent_protocol_seed_or_label_budget_change(self):
        runner=RNABenchmark(dataset='T0021',seed=42,root=ROOT)
        self.assertEqual(runner.inspect()['seed'],42)
        self.assertEqual(runner.inspect()['formal_five_seed_protocol_unchanged'],[11,23,47,71,101])
        with self.assertRaises(NotImplementedError):RNABenchmark(dataset='T0021',label_budget=256,root=ROOT)
        with self.assertRaises(NotImplementedError):RNABenchmark(dataset='T0021',protocol='native_pair',root=ROOT)


@unittest.skipUnless(importlib.util.find_spec('numpy') and importlib.util.find_spec('sklearn'),'optional numeric dependencies absent')
class FrozenReadoutTests(unittest.TestCase):
    def fixture(self):
        return [[0,1],[1,3],[2,2],[9,9]], [{'observation_id':str(i),'label':float(i)} for i in range(4)], {str(i):'train' if i<3 else 'test' for i in range(4)}

    def test_ridge_fit_is_heldout_blind_and_budget_union_explicit(self):
        x,rows,splits=self.fixture();a=fit_readout(x,rows,splits,['0','1','2'],protocol='frozen_ridge',problem='regression',seed=42)
        other=copy.deepcopy(rows);other[3]['label']=-1e8;x[3]=[1e9,-1e9]
        b=fit_readout(x,other,splits,['0','1','2'],protocol='frozen_ridge',problem='regression',seed=42)
        self.assertEqual(a,b)
        self.assertEqual(a['label_budget']['total_unique'],3)
        self.assertEqual(a['label_budget']['tune_unique'],0)
        self.assertEqual(a['label_budget']['test_selection_labels'],0)
        self.assertEqual(len(predict_readout(a,x)),4)

    @unittest.skipUnless(importlib.util.find_spec('torch'),'optional torch absent')
    def test_mlp_uses_exact_fixed_defaults_no_heldout_epoch_selection(self):
        x,rows,splits=self.fixture()
        a=fit_readout(x,rows,splits,['0','1','2'],protocol='frozen_mlp',problem='regression',seed=42,device='cpu')
        changed=copy.deepcopy(rows);changed[3]['label']=1000000
        b=fit_readout(x,changed,splits,['0','1','2'],protocol='frozen_mlp',problem='regression',seed=42,device='cpu')
        self.assertEqual(a,b);self.assertEqual(a['epochs'],100)
        self.assertEqual(a['hidden_width'],128);self.assertEqual(a['dropout'],0.2)
        self.assertFalse(a['early_stopping']);self.assertEqual(a['label_budget']['hpo_candidates'],0)
        self.assertEqual(len(predict_readout(a,x)),4)

    def test_no_test_labels_or_redraw_to_obtain_binary_support(self):
        x,rows,splits=self.fixture()
        with self.assertRaises(ValueError):fit_readout(x,rows,splits,['0','3'],protocol='frozen_ridge',problem='regression',seed=42)
        for r in rows[:3]:r['label']=1
        with self.assertRaisesRegex(ValueError,'NO_LABEL_BASED_REDRAW'):
            fit_readout(x,rows,splits,['0','1','2'],protocol='frozen_mlp',problem='binary_classification',seed=42)


class RankingContracts(unittest.TestCase):
    def test_signed_scores_and_ties_not_absolute_or_best_head(self):
        self.assertEqual(_ranks({'inverse':-0.8,'positive':0.2},'higher'),{'positive':1.0,'inverse':2.0})
        self.assertEqual(_ranks({'a':0.2,'b':0.2},'higher'),{'a':1.5,'b':1.5})
        self.assertEqual(_ranks({'a':0.2,'b':0.1},'lower'),{'b':1.0,'a':2.0})

    def test_source_cluster_weighting_is_not_file_weighting(self):
        score=_mean_by_source({'a1':0.5,'a2':0.5,'b1':-0.5},{'a1':'sourceA','a2':'sourceA','b1':'sourceB'})
        self.assertEqual(score,0.0)
        with self.assertRaises(ValueError):_mean_by_source({'a1':0.5},{'a1':'sourceA','missing':'sourceB'})

    def test_frozen_panel_no_zero_fill_or_posthoc_intersection(self):
        class MetadataOnlyModel:model_id='RNA-FM';initialization='pretrained';initialization_seed=0
        result=RNABenchmark(dataset='T0021',seed=42,root=ROOT).evaluate(MetadataOnlyModel())
        panel=RankingPanel(dataset_ids=('T0021',),model_ids=('RNA-FM','RiNALMo'),seeds=(42,),protocol='frozen_mlp',metric='spearman')
        board=RNALeaderboard(root=ROOT,scope='exploratory').add(result).by_dataset(panel=panel)
        self.assertEqual(board['status'],'INCOMPLETE_FIXED_PANEL_NO_RANKS')
        self.assertTrue(all(r['score'] is None and r['rank'] is None for r in board['rows']))
        self.assertEqual({r['state'] for r in board['cells']},{'BLOCKED','NOT_RUN'})

    def test_synthetic_results_cannot_enter_real_rankings(self):
        fake={'dataset_id':'T0021','model_id':'RNA-FM','seed':42,'protocol':'frozen_mlp','model_initialization':'pretrained',
              'label_budget_declared':64,'split_requested':'official','input_context':'sequence_only','status':'EXECUTED','run_kind':'synthetic'}
        panel=RankingPanel(dataset_ids=('T0021',),model_ids=('RNA-FM',),seeds=(42,),protocol='frozen_mlp',metric='spearman')
        board=RNALeaderboard(root=ROOT,scope='exploratory').add(fake).by_dataset(panel=panel)
        self.assertEqual(board['cells'][0]['state'],'SYNTHETIC_NOT_A_REAL_RANKING')
        self.assertIsNone(board['rows'][0]['rank'])

    def test_no_heterogeneous_capability_or_unresolved_source_aggregation(self):
        board=RNALeaderboard(root=ROOT,scope='exploratory')
        panel=RankingPanel(dataset_ids=('T0020','T0021'),model_ids=('RNA-FM',),seeds=(42,),protocol='frozen_mlp',metric='spearman')
        with self.assertRaisesRegex(ValueError,'NO_GLOBAL_MIX'):board.by_capability(panel=panel)
        panel=RankingPanel(dataset_ids=('T0021',),model_ids=('RNA-FM',),seeds=(42,),protocol='frozen_mlp',metric='spearman')
        with self.assertRaisesRegex(ValueError,'SOURCE_GROUPS'):board.by_capability(panel=panel)


if __name__=='__main__':unittest.main()
