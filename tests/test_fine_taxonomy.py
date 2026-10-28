"""Fine endpoints and UTR binding are metadata/data access, not admission."""
import copy
import csv
import gzip
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tools import build_fine_taxonomy as fine
from tools import prepare_public
from rna_gym import DatasetHub
from rna_gym.utr import UTRDataset,dataset_views

ROOT=Path(__file__).resolve().parents[1]


class FineTaxonomyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog=json.loads((ROOT/fine.OUTPUT).read_text())

    def test_original_registry_is_not_expanded_to_300_tasks(self):
        hub=DatasetHub(root=ROOT)
        self.assertEqual(len(hub.list()),198)
        self.assertEqual(self.catalog['summary']['tasks_covered'],198)
        self.assertEqual(len({r['task_id'] for r in self.catalog['registered_task_category_relations']}),198)

    def test_277_views_not_364_independent_experiments(self):
        ds=self.catalog['datasets'];self.assertEqual(len(ds),277)
        self.assertEqual(len({r['dataset_id'] for r in ds}),277)
        self.assertEqual(sum(r['source_collection']=='RNAGYM_QC' for r in ds),175)
        self.assertEqual(sum(r['source_collection']=='UTR_LEGACY_102' for r in ds),102)
        self.assertEqual(self.catalog['summary']['utr_revised_metadata_only_views'],87)
        self.assertTrue(all(r['formal_admitted'] is False for r in ds))
        self.assertEqual(self.catalog['summary']['formal_admitted'],0)

    def test_local_utr_family_counts_and_no_false_te(self):
        categories={r['category_id']:r for r in self.catalog['categories']}
        expected={'seq.mrl.native':8,'seq.mrl.log2':4,'seq.half_life.native':1,
                  'seq.half_life.log':4,'seq.stability.retention':2,'seq.stability.log_retention':2,
                  'seq.reporter.rna_dna':12,'seq.reporter.protein_com':21,'seq.reporter.protein_yfp':1,
                  'seq.rna_abundance':16,'seq.decay.transformed':30,'variant.growth_proxy':1}
        self.assertEqual(sum(expected.values()),102)
        for cat,n in expected.items():self.assertEqual(categories[cat]['utr_local_dataset_views'],n)
        self.assertEqual(categories['seq.te.measured']['utr_local_dataset_views'],0)
        self.assertEqual(categories['seq.te.measured']['rnagym_qc_dataset_units'],0)

    def test_metric_types_and_source_metrics_are_distinct(self):
        categories={r['category_id']:r for r in self.catalog['categories']}
        self.assertEqual(categories['seq.mrl.native']['primary_metric'],'spearman')
        self.assertIn('r2',categories['seq.mrl.native']['secondary_metrics'])
        self.assertEqual(categories['struct.secondary_pair']['primary_metric'],'pair_f1')
        self.assertEqual(categories['ann.family']['primary_metric'],'macro_f1')
        self.assertEqual(categories['interaction.rbp_binding']['primary_metric'],'auprc')
        for r in self.catalog['datasets']:
            if r['source_collection']=='UTR_LEGACY_102':
                self.assertEqual(set(r['source_metrics_at_snapshot']),{'spearman','mse','mae'})
        history=json.loads((ROOT/'data/registries/utr_historical_result_status.json').read_text())
        self.assertEqual(history['matrix_rows'],96)
        self.assertIn('r2',history['fold_metrics_available'])
        self.assertEqual(history['raw_pooled_scores_present'],0)

    def test_revised_geisberg_hours_does_not_relabel_old_minutes(self):
        old=[r for r in self.catalog['datasets'] if r.get('source_family')=='geisberg']
        new=json.loads((ROOT/'data/registries/utr_revised_87_metadata.json').read_text())
        entry=next(r for r in new['datasets'] if r['family']=='geisberg')
        self.assertEqual(old[0]['label_unit'],'min');self.assertTrue(entry['label_unit'].startswith('h '))
        self.assertFalse(new['data_bytes_bound'])

    def test_te_token_not_protein_or_site_substring(self):
        with (ROOT/'data/registries/search_level_task_crosswalk_198.csv').open(encoding='utf-8-sig') as handle:
            rows=list(csv.DictReader(handle))
        row=copy.deepcopy(rows[0]);row.update(row_id='TEST',output_taxonomy='SEQUENCE_SITE_REGRESSION',
             task='icSHAPE reactivity',dataset='chemical probing',scoring_family='Chemical probing')
        self.assertNotIn('seq.te.measured',fine.registered_categories(row))

    def test_generated_catalog_and_readme_are_current(self):
        actual=fine.build(ROOT)
        self.assertEqual(actual,self.catalog)
        text=(ROOT/'README.md').read_text()
        self.assertEqual(text[text.index(fine.START):text.index(fine.END)+len(fine.END)],fine.render(actual))

    def test_offline_public_projection_needs_no_processed_data(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            files=['search_level_task_crosswalk_198.csv','utr_legacy_102.json','utr_revised_87_metadata.json',
                   'curated_endpoint_units.json']
            for name in files:
                dest=root/'data/registries'/name;dest.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(ROOT/'data/registries'/name,dest)
            self.assertEqual(fine.build(root),self.catalog)

    def test_new_metadata_is_public_selected_and_safe(self):
        selected=prepare_public.selected_files(ROOT)
        for name in [fine.OUTPUT,'data/registries/utr_legacy_102.json','data/registries/utr_revised_87_metadata.json',
                     'data/registries/utr_historical_result_status.json','data/registries/curated_endpoint_units.json',
                     'rna_gym/utr.py','tools/integrate_utr_bench.py','tools/build_fine_taxonomy.py']:
            self.assertIn(name,selected)
            self.assertEqual(prepare_public.scan_file(ROOT/name),[],name)


class UTRBindingTests(unittest.TestCase):
    def fixture(self,root):
        data=root/'external_data';data.mkdir();p=data/'fold_0.csv.gz'
        rows=[['sequence','raw_label','zscore_label','set','fold'],['ACGT','2','-1','train','0'],['TGCA','4','1','test','0']]
        with gzip.open(p,'wt',newline='') as f:csv.writer(f).writerows(rows)
        public=root/'data/registries/fine_task_catalog.json';public.parent.mkdir(parents=True)
        record={'dataset_id':'UTR102:test','source_collection':'UTR_LEGACY_102','unit_id':'test','category_ids':['seq.mrl.native'],'formal_admitted':False}
        public.write_text(json.dumps({'categories':[{'category_id':'seq.mrl.native'}],'datasets':[record]}))
        private=root/'private.json';st=p.stat()
        binding={'local_verified':True,'folds':{'0':{'path':str(p),'bytes':st.st_size,'mtime_ns':st.st_mtime_ns,
                                                   'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}}}
        private.write_text(json.dumps({'allowed_data_root':str(data),'datasets':{'test':binding}}))
        hub=SimpleNamespace(root=root,config={'fine_task_registry':'data/registries/fine_task_catalog.json','utr_private_manifest':'private.json'})
        return hub,p,private

    def test_existing_columns_and_split_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            hub,p,_=self.fixture(Path(td));before=p.read_bytes();dataset=UTRDataset(hub,'UTR102:test')
            row=dataset.preview(fold=0,split='test',rows=1)[0]
            self.assertEqual(row,{'sequence':'TGCA','raw_label':4.0,'zscore_label':1.0,'set':'test','fold':0})
            self.assertEqual(p.read_bytes(),before)

    def test_invalid_fold_split_and_bounds_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            hub,_,_=self.fixture(Path(td));dataset=UTRDataset(hub,'UTR102:test')
            for fold in [-1,10,True]:
                with self.assertRaises(ValueError):dataset.preview(fold=fold)
            with self.assertRaises(ValueError):dataset.preview(fold=0,split='validation')
            with self.assertRaises(ValueError):dataset.preview(rows=100)

    def test_changed_bytes_refused(self):
        with tempfile.TemporaryDirectory() as td:
            hub,p,_=self.fixture(Path(td));dataset=UTRDataset(hub,'UTR102:test');p.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'CHANGED'):dataset.preview(fold=0)

    def test_path_traversal_refused(self):
        with tempfile.TemporaryDirectory() as td:
            hub,p,private=self.fixture(Path(td));info=json.loads(private.read_text());info['allowed_data_root']=str(p.parent/'other')
            private.write_text(json.dumps(info))
            with self.assertRaisesRegex(ValueError,'ESCAPED'):UTRDataset(hub,'UTR102:test').preview(fold=0)

    def test_no_binding_does_not_download(self):
        with tempfile.TemporaryDirectory() as td:
            hub,_,private=self.fixture(Path(td));private.unlink()
            with self.assertRaisesRegex(FileNotFoundError,'NO_DOWNLOAD'):UTRDataset(hub,'UTR102:test').preview(fold=0)
            self.assertFalse(dataset_views(hub)[0]['bytes_available_now'])

if __name__=='__main__':unittest.main()
