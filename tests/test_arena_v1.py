import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from rna_gym.arena import aggregate, joint_score, leaf_weights, normalize_score
from rna_gym.submissions import SubmissionStore
from tools.build_arena_v1 import ROOT, datasets, load, old_mapping, taxonomy, table


class ArenaV1Tests(unittest.TestCase):
    def setUp(self):
        self.config = load(ROOT/'configs/scoring_protocol_v1.yaml')

    def leaf(self, tid='SSP', version='v1', cell='c1'):
        t = next(t for t in taxonomy()['tasks'] if t['task_id'] == tid)
        return dict(cell_id=cell, macro_domain=t['macro_domain'], level2_category=t['level2_category'],
            canonical_task_id=tid, source_family_id='source1', assay_id='assay1', dataset_version=version,
            primary_metric=t['primary_metric'], human_admitted=True, scientific_role='CORE', baseline=0.1)

    def test_exact_28_tasks_and_five_domains(self):
        t = taxonomy()
        self.assertEqual(len(t['tasks']), 28)
        self.assertEqual(len({r['task_id'] for r in t['tasks']}), 28)
        self.assertEqual(len(t['registry_level1_domains']), 5)
        self.assertEqual({r['macro_domain'] for r in t['tasks']}, {'Structure','Function','Engineering'})

    def test_higher_normalization(self):
        self.assertEqual(normalize_score('Spearman', -0.5, self.config), 0)
        self.assertAlmostEqual(normalize_score('AUROC', 0.75, self.config), 0.5)
        self.assertEqual(normalize_score('F1', 2, self.config), 1)

    def test_auprc_prevalence_required(self):
        with self.assertRaises(ValueError): normalize_score('AUPRC', 0.6, self.config)
        self.assertAlmostEqual(normalize_score('AUPRC', 0.55, self.config, baseline=0.1), 0.5)
        for b in [0, 1, -1]:
            with self.assertRaises(ValueError): normalize_score('AUPRC', .6, self.config, baseline=b)

    def test_lower_and_nonfinite(self):
        self.assertAlmostEqual(normalize_score('MAE', 2, self.config, baseline=4), .5)
        for x in [None, float('nan'), float('inf'), True]:
            with self.assertRaises(ValueError): normalize_score('Spearman', x, self.config)
        with self.assertRaises(ValueError): normalize_score('RMSE', 1, self.config, baseline=0)

    def test_joint_normalized_only(self):
        self.assertAlmostEqual(joint_score({'MRL': .4, 'Half-life': .8}), .6)
        with self.assertRaises(ValueError): joint_score({'MRL': 3, 'Half-life': .8})

    def test_macro_and_capability_weights(self):
        self.assertAlmostEqual(leaf_weights([self.leaf()], self.config)['c1'], 1/9)
        self.assertAlmostEqual(leaf_weights([self.leaf('CMP')], self.config)['c1'], 1/18)

    def test_release_does_not_add_weight(self):
        a, b = self.leaf(), self.leaf(version='v2', cell='c2')
        self.assertAlmostEqual(sum(leaf_weights([a,b], self.config).values()), 1/9)
        b['dataset_version']='v1'
        with self.assertRaises(ValueError): leaf_weights([a,b], self.config)

    def test_missing_status_keeps_na(self):
        for state in ('UNSUPPORTED','NOT_RUN','FAILED','INCOMPATIBLE','REPORTED_ONLY'):
            result = aggregate([self.leaf()], [dict(cell_id='c1', evaluation_status=state,
                result_source='PAPER_REPORTED' if state == 'REPORTED_ONLY' else 'RNA_GYM_REPRODUCED', raw_score=None)], self.config)
            self.assertIsNone(result['cells'][0]['raw_score'])
            self.assertIsNone(result['performance'])
            self.assertEqual(result['coverage'], 0)
            self.assertEqual(result['universal_score'], 0)

    def test_reported_value_preserved_but_not_scored(self):
        a=aggregate([self.leaf()], [dict(cell_id='c1', evaluation_status='REPORTED_ONLY',
            result_source='PAPER_REPORTED', raw_score=.95)], self.config)
        self.assertEqual(a['cells'][0]['raw_score'], .95)
        self.assertIsNone(a['cells'][0]['normalized_score'])
        self.assertEqual(a['coverage'], 0)

    def test_sdk_exposes_canonical_catalog_without_private_labels(self):
        from rna_gym import DatasetHub
        hub=DatasetHub(root=ROOT)
        self.assertEqual(len(hub.arena_tasks()),28)
        views=hub.arena_dataset_views(task_id='MRL_PROXY')
        self.assertTrue(views)
        self.assertFalse(any('labels' in r or 'records' in r or 'label_json' in r for r in views))

    def test_private_quota_is_atomic_under_concurrency(self):
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as tmp:
            req=dict(scope='public',model_id='m',model_version='v',code_version='abc',
                **{k:'a'*64 for k in ['checkpoint_hash','adapter_hash','prompt_hash','protocol_hash']})
            store=SubmissionStore(Path(tmp)/'q.sqlite', {'max_private_submissions_per_team_per_week':2},
                verified_public_receipts=[dict(req,principal='team',status='PUBLIC_BENCHMARK_COMPLETED',verification_status='SERVER_VERIFIED')])
            req['scope']='private'
            def submit(_):
                try: store.submit('team',req); return 1
                except ValueError: return 0
            with ThreadPoolExecutor(max_workers=4) as pool:
                self.assertEqual(sum(pool.map(submit,range(8))),2)

    def test_non_evaluated_zero_raw_rejected(self):
        with self.assertRaises(ValueError):
            aggregate([self.leaf()], [dict(cell_id='c1', evaluation_status='UNSUPPORTED',
                result_source='RNA_GYM_REPRODUCED', raw_score=0)], self.config)

    def test_partial_coverage_and_eligibility(self):
        r=dict(cell_id='c1', evaluation_status='EVALUATED', raw_score=.8, raw_metric='F1',
            result_source='RNA_GYM_REPRODUCED', formal_leaderboard_eligible=True)
        a=aggregate([self.leaf()], [r], self.config)
        self.assertAlmostEqual(a['performance'], (.8-.1)/.9)
        self.assertAlmostEqual(a['coverage'], 1/9)
        self.assertFalse(a['universal_rank_eligible'])

    def test_exploratory_or_paper_cannot_promote(self):
        for source, eligible in [('PAPER_REPORTED',True),('RNA_GYM_REPRODUCED',False)]:
            with self.assertRaises(ValueError):
                aggregate([self.leaf()], [dict(cell_id='c1', evaluation_status='EVALUATED', raw_score=.8,
                    raw_metric='F1', result_source=source, formal_leaderboard_eligible=eligible)], self.config)

    def test_no_automatic_human_admission(self):
        leaf=self.leaf(); leaf['human_admitted']=False
        with self.assertRaises(ValueError):
            aggregate([leaf], [dict(cell_id='c1', evaluation_status='EVALUATED', raw_score=.8,
                raw_metric='F1', result_source='RNA_GYM_REPRODUCED', formal_leaderboard_eligible=True)], self.config)

    @unittest.skipUnless((ROOT/'data/processed').is_dir(), 'Local processed evidence is intentionally not published')
    def test_mapping_reconciles_198(self):
        r, _ = datasets(ROOT, taxonomy()); mapped=old_mapping(ROOT,r)
        self.assertEqual(len(mapped),198)
        byid={x['old_task_id']:x for x in mapped}
        self.assertEqual(byid['T0009']['mapping_status'],'MAPPED')
        self.assertEqual(byid['T0009']['canonical_task_id'],'MRL_EXACT')
        self.assertEqual(byid['T0021']['canonical_task_id'],'MRL_PROXY')
        self.assertEqual(byid['T0035']['mapping_status'],'TAXONOMY_REVIEW_REQUIRED')
        self.assertEqual(byid['T0028']['mapping_status'],'TAXONOMY_REVIEW_REQUIRED')
        self.assertFalse(any(x['canonical_task_id']=='SSI' for x in r))
        self.assertTrue(all(x['scientific_role']=='SECONDARY_PROXY' for x in r if x['source_category']=='variant.protein_proxy'))

    def test_leaderboards_are_empty_no_fake_scores(self):
        self.assertEqual(table(ROOT/'results/leaderboards/public/universal.tsv'), [])
        private = ROOT/'results/leaderboards/private/universal.tsv'
        if private.exists():
            self.assertEqual(table(private), [])
        else:
            self.assertFalse(load(ROOT/'configs/private_protocol_v1.yaml')['labels_in_api'])

    def test_actual_splits_leakage_zero(self):
        for p in (ROOT/'data/splits/RNAGYM_SPLIT_V1').glob('*/manifest.json'):
            m=load(p)
            self.assertEqual(m['difficulty'],'D2_GENERALIZATION')
            self.assertFalse(any(m['leakage'].values()))
            self.assertFalse(m['formal_admitted'])


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.request=dict(scope='private', model_id='m', model_version='v', code_version='abc',
            **{k:'a'*64 for k in ['checkpoint_hash','adapter_hash','prompt_hash','protocol_hash']})
        self.receipt=dict(self.request, principal='team',status='PUBLIC_BENCHMARK_COMPLETED',verification_status='SERVER_VERIFIED')
        self.store=SubmissionStore(Path(self.tmp.name)/'intake.sqlite',
            {'max_private_submissions_per_team_per_week':2}, verified_public_receipts=[self.receipt])
    def tearDown(self): self.tmp.cleanup()
    def test_gate_not_score_threshold(self):
        self.assertTrue(self.store.qualified('team',self.request))
        with self.assertRaises(ValueError): self.store.submit('stranger', self.request)
    def test_persistent_weekly_quota(self):
        now=datetime(2026,10,30,tzinfo=timezone.utc)
        self.store.submit('team',self.request,now=now)
        self.store.submit('team',self.request,now=now)
        with self.assertRaisesRegex(ValueError,'QUOTA'): self.store.submit('team',self.request,now=now)
        other=SubmissionStore(self.store.database,self.store.config,verified_public_receipts=[self.receipt])
        with self.assertRaisesRegex(ValueError,'QUOTA'): other.submit('team',self.request,now=now)
        self.store.submit('team',self.request,now=datetime(2026,11,2,tzinfo=timezone.utc))
    def test_version_binding(self):
        with self.assertRaises(ValueError): self.store.submit('team',dict(self.request,model_version='different'))
    def test_owner_and_hidden_labels(self):
        r=self.store.submit('team',self.request)
        self.assertEqual(set(self.store.get('team',r['id'])), {'id','submission_hash','status','scope'})
        with self.assertRaises(KeyError): self.store.get('other',r['id'])
        with self.assertRaises(ValueError): self.store.submit('team',dict(self.request,labels=[1]))


if __name__ == '__main__': unittest.main()
