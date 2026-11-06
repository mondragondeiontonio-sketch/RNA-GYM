"""Public fixtures only; scientific results never originate in these tests."""
import copy
import csv
import json
import random
import tempfile
import importlib.util
NUMERICAL = all(importlib.util.find_spec(m) is not None for m in ("numpy","scipy","sklearn"))
import unittest
from pathlib import Path
from rna_gym.research_v06.provenance import (ProtocolError, canonical_sequence, digest_json,
    validate_source, require_public_rights, immutable_text, overlap_graph, validate_features,
    public_scan, sha256_file)
from rna_gym.research_v06.therna import column_map, import_therna, iter_long
from rna_gym.research_v06.splits import make_split, audit_split
from rna_gym.research_v06.scoring import (regression, score_predictions, interaction_gain,
    require_admitted, source_macro)
from rna_gym.research_v06.polya import validate_polya, require_factorial
from rna_gym.research_v06.baselines import run_baselines
from tools.mrna_design.__main__ import synthetic_e2e, verify_receipt


def fixture_rows():
    rng = random.Random(6)
    result = []
    for i in range(40):
        seq = ''.join(rng.choices('ACGT', k=20))
        for j, c in enumerate(('A','B','C','D','E','F')):
            result.append({'observation_id':str(i)+'_'+c, 'sequence_id':digest_json(seq),
                'sequence':seq,'cell_id':c,'label_raw':seq.count('G')*.1+j*.2,
                'timepoint_value':str((i%3)*2),'assay_id':'test-assay',
                'readout_id':'synthetic','unit':'synthetic','missing_reason':'NOT_MISSING'})
    return result


class ProvenanceTests(unittest.TestCase):
    def test_ut_equivalent_and_invalid(self):
        self.assertEqual(canonical_sequence(' auG '),'ATG')
        with self.assertRaises(ProtocolError): canonical_sequence('ACNT')

    def test_immutable_conflict(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'file';immutable_text(p,'one');immutable_text(p,'one')
            with self.assertRaises(ProtocolError): immutable_text(p,'two')

    def test_public_rights_license_is_not_authorization(self):
        with self.assertRaises(ProtocolError):
            require_public_rights({'license':'CC0','rights_aggregate':True,
                                 'rights_review_status':'APPROVED','local_only':True})

    def test_hash_missing_and_rights(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'raw.csv';p.write_text('raw')
            c={k:'x' for k in ('source_id','source_release','assay_id','readout_id',
                              'label_raw_unit','label_direction','label_formula')}
            c.update(rights_research=True,rights_evaluate=True,rights_redistribute=False,
                     rights_aggregate=False,raw_files=[{'path':'raw.csv','sha256':sha256_file(p)}])
            self.assertEqual(len(validate_source(c,d)),1)
            c['raw_files'][0]['sha256']='0'*64
            with self.assertRaises(ProtocolError): validate_source(c,d)
            c['raw_files'][0]['path']='missing.csv'
            with self.assertRaises(ProtocolError): validate_source(c,d)
            c['rights_research']=False
            with self.assertRaises(ProtocolError): validate_source(c,d)

    def test_overlap_keeps_conditions(self):
        rows=[{'observation_id':'a','sequence_id':'same','cell_id':'A'},
              {'observation_id':'b','sequence_id':'same','cell_id':'B'}]
        edges=overlap_graph(rows)
        self.assertEqual(edges[0]['members'],['a','b'])
        self.assertFalse(edges[0]['independent_assay_evidence'])

    def test_feature_leak_canaries(self):
        for feature in [{'fit_role':'test','uses_target':False,'available_at_design':True},
                        {'fit_role':'train','uses_target':True,'available_at_design':True},
                        {'fit_role':'independent','uses_target':False,'available_at_design':False}]:
            with self.assertRaises(ProtocolError): validate_features([feature],protocol='S-OUT')

    def test_public_hidden_labels_and_paths(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'metadata.json'
            for value in [{'hidden_test_labels':[1]}, {'sequence':'ACG','label_raw':1},
                          {'path':'/'+'home'+'/private/data'}]:
                p.write_text(json.dumps(value))
                with self.assertRaises(ProtocolError): public_scan([p])
            p.write_text(json.dumps({'formal_admitted':0,'views':102}))
            self.assertEqual(public_scan([p])['status'],'PASS')


class SplitTests(unittest.TestCase):
    def test_deterministic_label_blind_sout(self):
        rows=fixture_rows();a,m=make_split(rows)
        altered=copy.deepcopy(rows)
        for r in altered: r['label_raw']=999
        self.assertEqual((a,m),make_split(altered))
        self.assertEqual(audit_split(a,'S-OUT')['status'],'PASS')

    def test_ut_and_construct_grouped(self):
        rows=fixture_rows();rows[0]['construct_id']='matched';rows[-1]['construct_id']='matched'
        a,_=make_split(rows)
        self.assertEqual(a[0]['role'],a[-1]['role'])

    def test_overlap_refused(self):
        a,_=make_split(fixture_rows());a[1]['role']='test' if a[0]['role']!='test' else 'train'
        with self.assertRaises(ProtocolError): audit_split(a,'S-OUT')

    def test_unseen_id_no_descriptor(self):
        for protocol in ('C-OUT-DESC','SC-OUT'):
            with self.assertRaises(ProtocolError): make_split(fixture_rows(),protocol=protocol)
        _,m=make_split(fixture_rows(),protocol='C-OUT-ID')
        self.assertEqual(m['input_contract'],'CELL_AGNOSTIC_ONLY')

    def test_sc_out_quarantines_cross_rectangles(self):
        descriptor={'source_sha256':'a'*64,'uses_target':False,'available_at_design':True,
                    'fit_role':'independent','values':{c:[i] for i,c in enumerate('ABCDEF')}}
        a,m=make_split(fixture_rows(),protocol='SC-OUT',cell_descriptor=descriptor)
        self.assertGreater(m['no_leakage_report']['counts']['quarantine'],0)
        self.assertEqual(audit_split(a,'SC-OUT')['status'],'PASS')

    def test_time_order_and_two_time_stop(self):
        rows=fixture_rows();a,_=make_split(rows,protocol='TIME-OUT')
        for r,s in zip(rows,a):
            self.assertEqual(s['role'],{'0':'train','2':'val','4':'test'}[r['timepoint_value']])
        for r in rows:r['timepoint_value']='24'
        with self.assertRaises(ProtocolError):make_split(rows,protocol='TIME-OUT')

    def test_duplicate_observation_rejected(self):
        rows=fixture_rows();rows.append(rows[0])
        with self.assertRaises(ProtocolError):make_split(rows)


class ThernaTests(unittest.TestCase):
    def test_column_alias_and_bad_time(self):
        with self.assertRaises(ProtocolError):
            column_map(['sequence','a__24h','a__36h','b__24h','b__36h'],'penta',
                       {'expected_cells':1,'cell_aliases':{'a':'A','b':'A'}})
        with self.assertRaises(ProtocolError):
            column_map(['sequence','a__25h'],'penta',{'expected_cells':1})

    def test_missing_time_grid_rejected(self):
        with self.assertRaises(ProtocolError):
            column_map(['sequence','a__24h'],'penta',{'expected_cells':1})

    @unittest.skipUnless(NUMERICAL, "Install research-v06 CPU extra")
    def test_synthetic_e2e_replay_and_receipt_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'e2e';s=synthetic_e2e(out)
            self.assertEqual(s['metrics_replayed'],5)
            self.assertFalse(s['formal_admitted'])
            verify_receipt(out/'import')
            (out/'import/qc.json').chmod(0o600)
            (out/'import/qc.json').write_text('{}')
            with self.assertRaises(ProtocolError):verify_receipt(out/'import')

    def test_zero_missing_negative_no_fill(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'raw.csv';p.write_text('sequence,A__24h,A__36h\nACG,0,NaN\nACT,-2,1\n')
            cfg={'kind':'penta','expected_cells':1,'source_id':'s','source_release':'v',
              'assay_id':'a','readout_id':'GEX_NORMALIZED_REPORTER','label_raw_unit':'x',
              'label_direction':'UNKNOWN','label_formula':'RAW','rights_research':True,
              'rights_evaluate':True,'rights_redistribute':False,'rights_aggregate':False,
              'raw_files':[{'path':p.name,'sha256':sha256_file(p)}]}
            import_therna(cfg,root,root/'out');rows=list(iter_long(root/'out/long.tsv.gz'))
            self.assertEqual([r['label_raw'] for r in rows],['0','','-2','1'])
            self.assertEqual(rows[1]['missing_reason'],'SOURCE_MISSING')
            self.assertEqual(rows[0]['biological_replicate'],'REPLICATES_NOT_AVAILABLE')


@unittest.skipUnless(NUMERICAL, "Install research-v06 CPU extra")
class ModelScoreTests(unittest.TestCase):
    def test_constant_na_and_cell_macro(self):
        self.assertIsNone(regression([1,1,1],[1,2,3])['spearman'])
        rows=[{'cell_id':c,'sequence_id':str(i),'label':y,'prediction':p}
              for c in ('A','B') for i,(y,p) in enumerate([(1,1),(2,2),(3,3)])]
        self.assertAlmostEqual(score_predictions(rows)['cell_macro']['spearman'],1)

    def test_test_targets_cannot_change_model(self):
        rows=fixture_rows();a,m=make_split(rows)
        config={'seed':6,'max_k':1,'interaction_rank':1,'ridge_alphas':[1.], 'bootstrap_replicates':2}
        p,s=run_baselines(rows,a,m,config)
        changed=copy.deepcopy(rows)
        for r,role in zip(changed,a):
            if role['role']=='test':r['label_raw']+=100
        q,t=run_baselines(changed,a,m,config)
        self.assertEqual(s['training_statistics_hash'],t['training_statistics_hash'])
        for name in p:
            self.assertEqual([r['prediction'] for r in p[name]],[r['prediction'] for r in q[name]])

    def test_mixed_readouts_refused_and_split_tamper(self):
        rows=fixture_rows();a,m=make_split(rows);rows[0]['readout_id']='OTHER'
        with self.assertRaises(ProtocolError):run_baselines(rows,a,m,{'seed':6})
        a[0]['role']='test'
        with self.assertRaises(ProtocolError):run_baselines(fixture_rows(),a,m,{'seed':6})

    def test_paired_gain_sign_and_alignment(self):
        a=[{'observation_id':str(i),'sequence_id':str(i),'cell_id':'A','label':float(i),
            'prediction':0.,'split_hash':'s'} for i in range(8)]
        b=copy.deepcopy(a)
        for r in b:r['prediction']=r['label']
        g=interaction_gain(a,b,replicates=5)
        self.assertGreater(g['delta_error_mae'],0)
        self.assertIsNone(g['delta_int_spearman'])
        with self.assertRaises(ProtocolError):interaction_gain(a,b[:-1],replicates=5)

    def test_formal_hold_and_duplicate_votes(self):
        with self.assertRaises(ProtocolError):require_admitted({'scientific_review_status':'SCIENTIFIC_HOLD'})
        r={'scientific_review_status':'ADMITTED','reviewer_evidence':'fixture-not-real',
           'assay_review':'APPROVED','label_review':'APPROVED','split_review':'APPROVED',
           'rights_review':'APPROVED','source_family':'s','assay_id':'a','score':1}
        with self.assertRaises(ProtocolError):source_macro([r,r])

    def test_polya_no_expression_pseudolabels(self):
        for task in ('APA_USAGE','TAIL_LENGTH_DYNAMICS','TAIL_DESIGN_FUNCTION'):
            with self.assertRaises(ProtocolError):validate_polya({'task_id':task,'label_origin':'THERNA_EXPRESSION'})
        with self.assertRaises(ProtocolError):validate_polya({'task_id':'TAIL_LENGTH_DYNAMICS','label_origin':'REAL'})
        with self.assertRaises(ProtocolError):require_factorial({})

class ImmutableIdentityTests(unittest.TestCase):
    @unittest.skipUnless(NUMERICAL, 'Install research-v06 CPU extra')
    def test_mutated_cell_or_sequence_identity_rejected(self):
        rows=fixture_rows();a,m=make_split(rows)
        for key,value in [('cell_id','UNKNOWN_NEW_CELL'),('sequence','ACGT')]:
            corrupted=copy.deepcopy(rows);corrupted[0][key]=value
            with self.assertRaises(ProtocolError):run_baselines(corrupted,a,m,{'seed':6})
