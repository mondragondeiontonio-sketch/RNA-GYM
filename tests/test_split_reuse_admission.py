"""Synthetic contracts for the explicitly user-authorized upstream reuse tier."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.audit_dataset_splits import POLICY_ID, assess, scan_table, split_key, verify


def fixture():
    return {'protocol_id':'SYNTHETIC_CONTRACT_ONLY', 'source_hashes_verified':True,
            'workflow':{'commit':'1'*40,'sha256':'2'*64,'url':'https://github.com/example/source/blob/'+'1'*40+'/README.md'},
            'partitions':[{'split':role,'sha256':'3'*64,'n_rows':2,
                           'input_columns':['sequence'],'target_column':'label','invalid_rows':0}
                          for role in ['train','test']],
            'cross_partition_key_overlap':0,'overlap_key_basis':'EXACT_RAW_SEQUENCE_BYTES',
            'usage_recipe':{'resplitting':False,'rows_dropped':0}}


class ReusePolicyTests(unittest.TestCase):
    def test_audit_integrity_checks_survive_python_optimization(self):
        import ast
        import tools.audit_dataset_splits as module
        tree=ast.parse(Path(module.__file__).read_text())
        self.assertFalse(any(isinstance(node,ast.Assert) for node in ast.walk(tree)))

    def test_scoped_reuse_pass_never_fabricates_formal_admission_or_rights(self):
        value=assess(fixture())
        self.assertTrue(value['admitted_upstream_reuse'])
        self.assertEqual(value['policy_id'],POLICY_ID)
        for key in ['formal_core_admitted','formal_leaderboard_eligible','human_signature_generated','rights_approval_generated']:
            self.assertFalse(value[key])

    def test_names_without_a_real_partition_or_recipe_do_not_pass(self):
        for change in [{'partitions':[]},{'usage_recipe':{}},{'workflow':{}},
                       {'source_hashes_verified':False},{'cross_partition_key_overlap':None},
                       {'overlap_key_basis':None},{'missing_reference_release':True}]:
            with self.subTest(change=change):
                self.assertFalse(assess({**fixture(),**change})['admitted_upstream_reuse'])

    def test_missing_labels_bad_hash_or_invalid_rows_are_not_approved(self):
        for key,value in [('target_column',None),('input_columns',[]),('sha256','unknown'),
                          ('n_rows',0),('invalid_rows',1)]:
            item=fixture();item['partitions'][0][key]=value
            with self.subTest(key=key):self.assertFalse(assess(item)['admitted_upstream_reuse'])

    def test_cross_partition_overlap_and_ambiguous_roles_do_not_pass(self):
        item=fixture();item['cross_partition_key_overlap']=1
        self.assertFalse(assess(item)['admitted_upstream_reuse'])
        item=fixture();item['partitions'].append(copy.deepcopy(item['partitions'][0]))
        self.assertFalse(assess(item)['admitted_upstream_reuse'])

    def test_empty_released_validation_is_retained_not_invented(self):
        item=fixture();part=copy.deepcopy(item['partitions'][0]);part.update(split='validation',n_rows=0)
        item['partitions'].append(part)
        self.assertTrue(assess(item)['admitted_upstream_reuse'])
        self.assertEqual(item['partitions'][2]['n_rows'],0)

    def test_validation_holdout_is_not_silently_renamed_test(self):
        item=fixture();item['partitions'][1]['split']='validation'
        value=assess(item)
        self.assertTrue(value['admitted_upstream_reuse'])
        self.assertEqual(value['evaluation_partition'],'validation')
        self.assertEqual(value['evaluation_claim'],'DEVELOPMENT_HOLDOUT_ONLY_NOT_TEST')

    def test_editor_checkpoints_are_not_blessed_as_author_protocols(self):
        item=fixture();item['partitions'][0]['member']='data/.ipynb_checkpoints/train.csv'
        self.assertFalse(assess(item)['admitted_upstream_reuse'])

    def test_split_tokens_are_explicit_and_strategy_identity_preserved(self):
        self.assertEqual(split_key('CV/min_similarity/train/toy_train.csv'),('CV/min_similarity/toy','train'))
        self.assertEqual(split_key('CV/min_similarity/test/toy_test.csv'),('CV/min_similarity/toy','test'))
        self.assertNotEqual(split_key('CV/random/train/toy_train.csv')[0],split_key('CV/min_similarity/train/toy_train.csv')[0])
        self.assertIsNone(split_key('dataset/training_results.pkl'))
        self.assertIsNone(split_key('dataset/train/test.csv'))

    def test_reader_preserves_case_dna_duplicates_and_all_rows(self):
        raw=b'sequence,label\nAcgT,1\nAcgT,2\n'
        part,keys=scan_table(raw,'train.csv')
        self.assertEqual(part['n_rows'],2)
        self.assertEqual(part['repeated_exact_inputs_within_partition'],1)
        self.assertEqual(keys,{hashlib.sha256(b'AcgT').digest()})
        self.assertEqual(part['sequence_transformation'],'NONE')

    def test_ambiguous_unidentified_target_not_guessed(self):
        part,_=scan_table(b'sequence,readout_A,readout_B\nACGU,1,2\n','train.csv')
        self.assertIsNone(part['target_column'])

    def test_changed_member_bytes_fail_closed(self):
        with self.assertRaisesRegex(ValueError,'PRIOR_MEMBER_HASH_MISMATCH'):
            scan_table(b'sequence,label\nACGU,1\n','train.csv',{'member_sha256':'0'*64})

    def test_registry_decisions_are_replayable_and_cannot_be_silently_promoted(self):
        value=assess(fixture())
        report={'policy_id':POLICY_ID,'formal_core_admitted_by_this_audit':0,
                'protocols':[value],'summary':{'protocols_admitted_upstream_reuse':1}}
        verify(report)
        report['protocols'][0]['formal_leaderboard_eligible']=True
        with self.assertRaisesRegex(ValueError,'STALE_ADMISSION_DECISION'):verify(report)


class ProtocolAPITests(unittest.TestCase):
    def test_native_protocol_api_is_metadata_only_and_keeps_formal_gate_distinct(self):
        from rna_gym import DatasetHub
        hub=DatasetHub()
        import socket
        from unittest.mock import patch
        with patch.object(socket,'socket',side_effect=AssertionError('No network in metadata API')):
            values=hub.protocols(admitted=True)
            dms=hub.protocols(package='RNAGYM_DMS',admitted=True)
        self.assertTrue(values)
        self.assertTrue(all(v['admission_scope']=='UPSTREAM_PROTOCOL_REUSE' for v in values))
        self.assertTrue(all(not v['formal_leaderboard_eligible'] for v in values))
        self.assertTrue(all(not v['automatic_dataset_or_model_download'] for v in values))
        self.assertTrue(all(v['evaluation_partition']=='validation' for v in dms))
        self.assertFalse(hub.get('T0021').describe()['admitted'])

    def test_public_readme_counts_match_the_frozen_registry(self):
        root=Path(__file__).resolve().parents[1]
        report=json.loads((root/'data/registries/upstream_split_audit.json').read_text())
        verify(report)
        text=(root/'README.md').read_text()
        total=report['summary']['protocols_admitted_upstream_reuse']
        self.assertIn(str(total)+' upstream split protocols',text)
        self.assertEqual(len(report['inventory']),50)

    def test_claim_role_cannot_be_promoted_by_editing_only_registry_metadata(self):
        value=assess(fixture());value['evaluation_claim']='FORMAL_TEST'
        report={'policy_id':POLICY_ID,'formal_core_admitted_by_this_audit':0,
                'protocols':[value],'summary':{'protocols_admitted_upstream_reuse':1}}
        with self.assertRaisesRegex(ValueError,'STALE_ADMISSION_DECISION'):verify(report)


if __name__=='__main__':unittest.main()
