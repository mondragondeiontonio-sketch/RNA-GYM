"""No dependency site checks. Optional real Chrome smoke: RNAGYM_BROWSER_TESTS=1.

All fixtures and browser profiles are temporary; no raw data or network downloads.
"""
from contextlib import redirect_stdout, redirect_stderr
import csv
import hashlib
import html
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('generate_site', ROOT / 'tools/generate_site.py')
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


class Document(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.tags = []
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class SiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.expected = generator.build_site()
        cls.tasks = json.loads(cls.expected['tasks.json'])
        cls.cards = json.loads(cls.expected['provenance.json'])
        cls.summary = json.loads(cls.expected['summary.json'])

    def fixture(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for rel in (generator.REGISTRY, generator.FAMILIES, generator.PACKAGES, generator.ASSETS):
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / rel, target)
        (root / 'data/audit').mkdir()
        return root

    def statuses(self, root, rows):
        columns = sorted(set().union(*(r.keys() for r in rows)))
        with (root / generator.AUDIT_TASKS).open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, delimiter='\t')
            writer.writeheader()
            writer.writerows(rows)

    def evidence(self, root, rows):
        (root / generator.AUDIT_ASSETS).write_text(json.dumps(rows), encoding='utf-8')

    def test_frozen_registry_counts_and_no_admission(self):
        self.assertEqual(self.summary['registered_task_rows'], 198)
        self.assertEqual(self.summary['source_families'], 123)
        self.assertEqual(self.summary['download_packages'], 47)
        self.assertEqual(self.summary['final_admitted_tasks'], 0)
        self.assertEqual(len({t['id'] for t in self.tasks}), 198)
        self.assertTrue(all(t['admission_status'] == 'NOT_ADMITTED' for t in self.tasks))
        self.assertTrue(all(t['actual_n'] is None for t in self.tasks))
        self.assertEqual(sum(self.summary['status_counts'].values()), 198)
        self.assertEqual(sum(self.summary['family_counts'].values()), 198)

    def test_all_outputs_byte_exact_and_deterministic(self):
        self.assertEqual(self.expected, generator.build_site())
        for name, content in self.expected.items():
            with self.subTest(name=name):
                self.assertEqual((ROOT / 'site/data' / name).read_bytes(), content)
        for name, digest in self.summary['data_sha256'].items():
            self.assertEqual(hashlib.sha256(self.expected[name]).hexdigest(), digest)

    def test_verify_detects_each_missing_or_stale_output_without_writes(self):
        root = self.fixture()
        output = root / 'site/data'
        output.mkdir(parents=True)
        with patch.object(generator, 'ROOT', root), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            # build_site's default is bound at definition; main passes ROOT explicitly.
            self.assertEqual(generator.main([]), 0)
            baseline = {p.name: p.read_bytes() for p in output.iterdir()}
            for name in generator.OUTPUTS:
                path = output / name
                path.write_bytes(b'{}\n')
                self.assertEqual(generator.main(['--verify']), 1)
                self.assertEqual(path.read_bytes(), b'{}\n')
                path.write_bytes(baseline[name])
                path.unlink()
                self.assertEqual(generator.main(['--verify']), 1)
                self.assertFalse(path.exists())
                path.write_bytes(baseline[name])
            self.assertEqual(generator.main(['--verify']), 0)

    def test_missing_optional_audit_snapshots_are_unknown_not_pass(self):
        result = generator.build_site(self.fixture())
        summary = json.loads(result['summary.json'])
        self.assertEqual(summary['review_ready_tasks'], 0)
        self.assertEqual(summary['raw_files_sha256_verified'], 0)
        self.assertTrue(all(t['stage'] is None for t in json.loads(result['tasks.json'])))
        for card in json.loads(result['provenance.json']):
            self.assertIsNone(card['canonical_assay_id'])
            self.assertIsNone(card['original_assay_doi'])
            self.assertIsNone(card['raw_file_sha256'])
            self.assertEqual(card['rights_status'], 'NOT_VERIFIED')
            self.assertEqual(card['files'], [])

    def test_reported_n_comes_only_from_registry_and_keeps_wording(self):
        rows = generator.read_csv(ROOT, generator.REGISTRY)
        originals = {r['task_id']: r for r in rows}
        for task in self.tasks:
            row = originals[task['id']]
            self.assertEqual(task['dataset_n']['reported'], generator.known(row['N(原登记)']))
            self.assertEqual(task['reported_n'], row['N(原登记)'])
            self.assertIsNone(task['actual_n'])
            if generator.known(task['reported_n']):
                self.assertEqual(task['reported_n_verification'], 'reported/unverified')
        self.assertIsNone(self.tasks[0]['dataset_n']['value'])  # 'task records', not sample N
        approximate = generator.dataset_size({'task_id': 'T', 'N(原登记)': '>1,000,000', 'N单位': 'variants'})
        self.assertIsNone(approximate['value'])
        self.assertEqual(approximate['reported'], '>1,000,000')
        unknown = generator.dataset_size({'task_id': 'T', 'N(原登记)': '未核实', 'N单位': 'sequences'})
        self.assertIsNone(unknown['reported'])
        self.assertEqual(unknown['status'], 'unknown')

    def test_non_sample_counts_never_become_sample_n(self):
        for unit in ('task records', 'assays', 'deep mutational scanning assays',
                     'datasets reused; not independent', 'suites', 'downstream tasks',
                     'targets / groups', 'algorithms / reads'):
            with self.subTest(unit=unit):
                result = generator.dataset_size({'task_id': 'T', 'N(原登记)': '198', 'N单位': unit})
                self.assertIsNone(result['value'])
                self.assertEqual(result['reported'], '198')

    def test_task_state_adapter_and_poc_counts_do_not_escalate(self):
        root = self.fixture()
        self.statuses(root, [{'task_id': 'T0001', 'package_group_id': 'BEACON_ALL',
                             'assay_id': '', 'state': 'HOLD_LICENSE',
                             'hold_reason': 'Original data license not verified',
                             'next_action': 'Verify data rights', 'reported_n': '99999999',
                             'reported_n_verification': 'PASS', 'actual_n': '42',
                             'actual_n_scope': 'PoC file only'}])
        result = generator.build_site(root)
        task = json.loads(result['tasks.json'])[0]
        self.assertEqual(task['status'], 'HOLD_LICENSE')
        self.assertIsNone(task['stage'])
        self.assertEqual(task['reported_n'], '13419')
        self.assertIsNone(task['actual_n'])
        self.assertEqual(task['next_action'], 'Verify data rights')
        self.assertEqual(json.loads(result['summary.json'])['review_ready_tasks'], 0)

    def test_hash_proof_is_explicit_not_a_link_or_git_sha(self):
        root = self.fixture()
        row = {'asset_id': 'A0001', 'state': 'HASHED', 'file_sha256': 'a' * 64,
               'file_size_bytes': 8, 'sha256_verified': True,
               'sample_count': 42, 'local_path': '/private/sequences.csv',
               'headers': {'Authorization': 'SECRET_DO_NOT_PUBLISH'},
               'reviewer': 'PRIVATE_PERSON'}
        self.evidence(root, [row])
        result = generator.build_site(root)
        self.assertEqual(json.loads(result['summary.json'])['raw_files_sha256_verified'], 1)
        for task in json.loads(result['tasks.json']):
            self.assertIsNone(task['actual_n'])
        for content in result.values():
            self.assertNotIn(b'SECRET_DO_NOT_PUBLISH', content)
            self.assertNotIn(b'PRIVATE_PERSON', content)
            self.assertNotIn(b'/private/', content)
        row['file_sha256'] = 'b' * 40
        self.evidence(root, [row])
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            generator.build_site(root)
        row['file_sha256'] = 'a' * 64
        row['file_size_bytes'] = None
        self.evidence(root, [row])
        with self.assertRaisesRegex(ValueError, 'positive bytes'):
            generator.build_site(root)

    def test_package_evidence_is_not_task_identity_or_verified_sha(self):
        root = self.fixture()
        self.evidence(root, [{'asset_id': 'A0001', 'stage': 'HASHED',
                             'file_sha256': 'c' * 64, 'file_size_bytes': 1}])
        result = generator.build_site(root)
        self.assertEqual(json.loads(result['summary.json'])['raw_files_sha256_verified'], 0)
        cards = [c for c in json.loads(result['provenance.json']) if c['files']]
        self.assertTrue(cards)
        for card in cards:
            self.assertIsNone(card['raw_file_sha256'])
            self.assertEqual(card['files'][0]['scope'], 'package_only')
            self.assertIsNone(card['original_assay_doi'])

    def test_hold_review_ready_and_admitted_are_separate(self):
        root = self.fixture()
        self.statuses(root, [{'task_id': 'T0001', 'state': 'REVIEW_READY'}])
        result = generator.build_site(root)
        self.assertEqual(json.loads(result['summary.json'])['review_ready_tasks'], 1)
        self.assertEqual(json.loads(result['summary.json'])['final_admitted_tasks'], 0)
        for field in ('state', 'stage', 'admission_status', 'final_status'):
            self.statuses(root, [{'task_id': 'T0001', field: 'ADMITTED_CORE'}])
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'admission lock'):
                generator.build_site(root)

    def test_invalid_task_mapping_and_duplicate_ids_fail_closed(self):
        root = self.fixture()
        self.statuses(root, [{'task_id': 'T9999', 'state': 'HOLD_SOURCE'}])
        with self.assertRaisesRegex(ValueError, 'unknown task'):
            generator.build_site(root)
        self.statuses(root, [{'task_id': 'T0001'}, {'task_id': 'T0001'}])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            generator.build_site(root)
        self.statuses(root, [{'task_id': 'T0001', 'package_group_id': 'WRONG'}])
        with self.assertRaisesRegex(ValueError, 'package mismatch'):
            generator.build_site(root)
        (root / generator.AUDIT_TASKS).unlink()
        self.evidence(root, [{'asset_id': 'A0001', 'task_ids': ['T0001']}])
        with self.assertRaisesRegex(ValueError, 'mapping'):
            generator.build_site(root)

    def test_new_asset_contract_keeps_qc_counts_and_identity_file_scoped(self):
        root = self.fixture()
        self.evidence(root, [{
            'asset_id': 'P0_MIR_TEST', 'package_group_id': 'MIR_BENCH',
            'state': 'QC_PASS_EXACT_ONLY_NOT_ADMITTED',
            'actual_sha256': 'd' * 64, 'sha256': 'd' * 64,
            'sha256_verified': True, 'raw_hash_verified': True,
            'verification_method': 'SHA-256 of actual downloaded raw bytes',
            'size_bytes': 200803, 'actual_n': 954, 'actual_n_scope': 'ONE_FILE_ONE_SPLIT',
            'dataset_alias': 'public_alias', 'original_split': 'test',
            'exact_qc_state': 'PASS_EXACT_PAIRED_QC_ONLY',
            'admitted': False, 'assay_identity_verified': False,
            'download_url': 'https://example.org/data.csv.gz',
            'license_evidence_url': 'https://example.org/license',
            'sequence': 'PRIVATE_SEQUENCE_DO_NOT_PUBLISH',
        }])
        result = generator.build_site(root)
        summary = json.loads(result['summary.json'])
        self.assertEqual(summary['raw_files_sha256_verified'], 1)
        self.assertEqual(summary['review_ready_tasks'], 0)
        self.assertEqual(summary['final_admitted_tasks'], 0)
        cards = [c for c in json.loads(result['provenance.json']) if c['package_group_id'] == 'MIR_BENCH']
        self.assertTrue(cards)
        for card in cards:
            file = card['files'][0]
            self.assertEqual(file['stage'], 'HASHED')
            self.assertEqual(file['evidence_state'], 'QC_PASS_EXACT_ONLY_NOT_ADMITTED')
            self.assertEqual(file['actual_n'], 954)
            self.assertEqual(file['actual_n_scope'], 'ONE_FILE_ONE_SPLIT')
            self.assertFalse(file['assay_identity_verified'])
            self.assertFalse(file['admitted'])
            self.assertEqual(file['rights_proof_url'], 'https://example.org/license')
            self.assertEqual(file['download_url'], 'https://example.org/data.csv.gz')
            self.assertEqual(card['identity_status'], 'NOT_VERIFIED')
            self.assertIsNone(card['raw_file_sha256'])
        self.assertTrue(all(t['actual_n'] is None for t in json.loads(result['tasks.json'])))
        self.assertTrue(all(b'PRIVATE_SEQUENCE_DO_NOT_PUBLISH' not in content for content in result.values()))

    def test_quarantined_hash_is_not_review_ready_or_identity_pass(self):
        root = self.fixture()
        self.evidence(root, [{
            'asset_id': 'P0_RNAGYM_TEST', 'package_group_id': 'RNAGYM_DMS',
            'state': 'HASHED_UNPINNED_QUARANTINED', 'actual_sha256': 'e' * 64,
            'sha256_verified': True, 'raw_hash_verified': True, 'size_bytes': 22491178,
            'admitted': False, 'assay_identity_verified': False,
        }])
        result = generator.build_site(root)
        summary = json.loads(result['summary.json'])
        self.assertEqual(summary['raw_files_sha256_verified'], 1)
        self.assertEqual(summary['review_ready_tasks'], 0)
        self.assertEqual(summary['final_admitted_tasks'], 0)
        for card in json.loads(result['provenance.json']):
            self.assertEqual(card['identity_status'], 'NOT_VERIFIED')
            self.assertIsNone(card['canonical_assay_id'])

    def test_conflicting_hash_aliases_or_admission_assertions_fail_closed(self):
        root = self.fixture()
        row = {'asset_id': 'A0001', 'state': 'HASHED', 'sha256': 'f' * 64,
               'actual_sha256': 'a' * 64, 'size_bytes': 10, 'sha256_verified': True}
        self.evidence(root, [row])
        with self.assertRaisesRegex(ValueError, 'conflicting actual raw SHA256'):
            generator.build_site(root)
        row['actual_sha256'] = row['sha256']
        row['admitted'] = True
        self.evidence(root, [row])
        with self.assertRaisesRegex(ValueError, 'admission lock'):
            generator.build_site(root)
        row['admitted'] = False
        row['raw_hash_verified'] = False
        self.evidence(root, [row])
        with self.assertRaisesRegex(ValueError, 'contradictory'):
            generator.build_site(root)
        row['raw_hash_verified'] = True
        row['actual_n'] = 42  # No scope: may never silently become task/sample N.
        self.evidence(root, [row])
        with self.assertRaisesRegex(ValueError, 'actual_n_scope'):
            generator.build_site(root)

    def test_rnagym_scientific_classification_is_file_scoped_and_not_admission(self):
        root = self.fixture()
        inventory = {'reference_count': 70, 'mrna_coding_fitness_proxy_candidates': 37,
                     'noncoding_or_splicing_candidate_files': 33, 'admitted': False,
                     'private_member_sequences': ['PRIVATE_RNA_DO_NOT_PUBLISH']}
        path = root / generator.AUDIT_RNAGYM_INVENTORY
        path.write_text(json.dumps(inventory))
        result = generator.build_site(root)
        classification = json.loads(result['summary.json'])['rnagym_reference_classification']
        self.assertEqual(classification['reference_count'], 70)
        self.assertEqual(classification['mrna_coding_fitness_proxy_candidates'], 37)
        self.assertEqual(classification['noncoding_or_splicing_candidate_files'], 33)
        self.assertEqual(classification['scope'], 'REFERENCE_FILES_NOT_VERIFIED_ASSAYS')
        self.assertEqual(classification['status'], 'ALL_HOLD_NOT_ADMITTED')
        for card in json.loads(result['provenance.json']):
            if card['package_group_id'] == 'RNAGYM_DMS':
                self.assertEqual(card['package_audit'], classification)
            else:
                self.assertIsNone(card['package_audit'])
        self.assertTrue(all(b'PRIVATE_RNA_DO_NOT_PUBLISH' not in content for content in result.values()))
        inventory['reference_count'] = 71
        path.write_text(json.dumps(inventory))
        with self.assertRaisesRegex(ValueError, 'do not sum'):
            generator.build_site(root)
        path.unlink()
        self.assertIsNone(json.loads(generator.build_site(root)['summary.json'])['rnagym_reference_classification'])

    def test_poc_aggregates_remain_scoped_and_match_file_byte_evidence(self):
        root = self.fixture()
        self.evidence(root, [{'asset_id': 'P0_TEST', 'package_group_id': 'MIR_BENCH',
                             'state': 'QC_PASS_EXACT_ONLY_NOT_ADMITTED',
                             'sha256': 'a' * 64, 'sha256_verified': True, 'size_bytes': 10,
                             'actual_n': 3, 'actual_n_scope': 'ONE_FILE_ONE_SPLIT'}])
        poc = {'files_downloaded_and_sha256_verified': 1, 'compressed_bytes_downloaded': 10,
               'paired_files_exact_qc_pass': 1, 'unique_paired_inputs_across_downloaded_mirbench': 3,
               'independent_assays_verified': 0, 'review_ready': 0, 'admitted': 0,
               'all_p0_dod_met': False, 'private_sequences': ['DO_NOT_PUBLISH_SEQUENCE']}
        path = root / generator.AUDIT_POC
        path.write_text(json.dumps(poc))
        result = generator.build_site(root)
        summary = json.loads(result['summary.json'])
        self.assertEqual(summary['poc_audit']['unique_paired_inputs_across_downloaded_mirbench'], 3)
        self.assertEqual(summary['poc_audit']['scope'], 'DOWNLOADED_POC_FILES_ONLY_NOT_TASK_N')
        self.assertTrue(all(t['actual_n'] is None for t in json.loads(result['tasks.json'])))
        self.assertTrue(all(b'DO_NOT_PUBLISH_SEQUENCE' not in content for content in result.values()))
        poc['compressed_bytes_downloaded'] = 11
        path.write_text(json.dumps(poc))
        with self.assertRaisesRegex(ValueError, 'file/byte counts disagree'):
            generator.build_site(root)
        poc['compressed_bytes_downloaded'] = 10
        poc['independent_assays_verified'] = 1
        path.write_text(json.dumps(poc))
        with self.assertRaisesRegex(ValueError, 'admission lock'):
            generator.build_site(root)

    def test_rnagym_ncrna_splicing_and_record_counts_never_fill_task_n(self):
        root = self.fixture()
        inventory = {'reference_count': 70, 'mrna_coding_fitness_proxy_candidates': 37,
                     'noncoding_or_splicing_candidate_files': 33,
                     'ncRNA_candidate_files': 31, 'mrna_splicing_candidate_files': 2,
                     'mrna_coding_proxy_candidate_files': 37,
                     'rna_candidate_files_safely_extracted': 33,
                     'rna_candidate_file_records': 862377, 'admitted': False}
        path = root / generator.AUDIT_RNAGYM_INVENTORY
        path.write_text(json.dumps(inventory))
        result = generator.build_site(root)
        audit = json.loads(result['summary.json'])['rnagym_reference_classification']
        self.assertEqual(audit['ncRNA_candidate_files'], 31)
        self.assertEqual(audit['mrna_splicing_candidate_files'], 2)
        self.assertEqual(audit['rna_candidate_file_records'], 862377)
        self.assertEqual(audit['record_count_scope'], 'PROCESSED_FILE_ROWS_NOT_DEDUPLICATED_NOT_TASK_N')
        self.assertTrue(all(t['actual_n'] is None for t in json.loads(result['tasks.json'])))
        inventory['mrna_splicing_candidate_files'] = 3
        path.write_text(json.dumps(inventory))
        with self.assertRaisesRegex(ValueError, 'do not sum'):
            generator.build_site(root)

    def test_public_links_reject_credentials_and_local_urls(self):
        for value in ('javascript:alert(1)', 'file:///private/data', 'http://example.org',
                      'https://user:password@example.org/data', 'https://localhost/data',
                      'https://127.0.0.1/data', 'https://10.0.0.1/data',
                      'https://example.org/data?token=SECRET',
                      'https://example.org/data?X-Amz-Signature=SECRET'):
            with self.subTest(value=value):
                self.assertIsNone(generator.public_url(value))
        self.assertEqual(generator.public_url('https://doi.org/10.1234/example'), 'https://doi.org/10.1234/example')

    def test_provenance_preserves_unknowns_and_benchmark_reference_separation(self):
        self.assertEqual([c['id'] for c in self.cards], [t['id'] for t in self.tasks])
        # Original benchmark reference is never automatically an assay DOI.
        self.assertIsNotNone(self.cards[0]['benchmark_reference_url'])
        self.assertIsNone(self.cards[0]['original_assay_doi'])

    def test_static_publication_allowlist_and_accessible_markup(self):
        allowed = {'.nojekyll', 'index.html', 'styles.css', 'app.js',
                   'data/tasks.json', 'data/provenance.json', 'data/summary.json',
                   'phase2.html', 'phase2.js', 'phase2.css',
                   'phase2-data/phase2-snapshot.json'}
        self.assertFalse(any(p.is_symlink() for p in (ROOT / 'site').rglob('*')), 'No symlinks into private files')
        actual = {p.relative_to(ROOT / 'site').as_posix() for p in (ROOT / 'site').rglob('*') if p.is_file()}
        self.assertEqual(actual, allowed, 'Only allowlisted static preview files may be published')
        document = Document((ROOT / 'site/index.html').read_text())
        ids = [attrs['id'] for _, attrs in document.tags if 'id' in attrs]
        self.assertEqual(len(ids), len(set(ids)))
        for section in ('home', 'datasets', 'provenance', 'method', 'baselines', 'leaderboard', 'governance', 'contribute'):
            self.assertIn(section, ids)
        labels = {attrs.get('for') for tag, attrs in document.tags if tag == 'label'}
        for tag, attrs in document.tags:
            if tag in ('input', 'select'):
                self.assertIn(attrs.get('id'), labels)
            if attrs.get('target') == '_blank':
                self.assertIn('noreferrer', attrs.get('rel', '').split())
            if tag in ('a', 'script', 'link'):
                target = attrs.get('href', attrs.get('src', ''))
                self.assertFalse(target.startswith(('http:', 'https:')), 'No external runtime dependencies')
                self.assertNotIn('docs/', target)
        app = (ROOT / 'site/app.js').read_text()
        self.assertNotIn('innerHTML', app)
        self.assertIn('noopener noreferrer', app)
        self.assertIn('Content-Security-Policy', (ROOT / 'site/index.html').read_text())

    def test_workflow_verifies_before_public_only_deploy(self):
        workflow = (ROOT / '.github/workflows/pages.yml').read_text()
        for required in ('pull_request:', 'python tools/generate_site.py --verify',
                         'python -m unittest discover -s tests -p test_site.py -v',
                         'needs: verify', 'path: site', 'tools/generate_site.py',
                         'data/audit/task_status.tsv', 'data/audit/asset_evidence.json',
                         'data/audit/rnagym_archive_inventory.json', 'data/audit/poc_summary.json'):
            self.assertIn(required, workflow)
        self.assertNotIn('npm ', workflow)
        self.assertIn("github.event_name != 'pull_request'", workflow)


BROWSER_SCRIPT = r"""
(async () => {
 const result = document.getElementById('result');
 const frame = document.getElementById('preview');
 const checks = [];
 const wait = async test => {
   for (let i = 0; i < 150; i++) {if (test()) return; await new Promise(r => setTimeout(r, 50));}
   throw new Error('timeout waiting for site');
 };
 const assert = (value, name) => {if (!value) throw new Error(name); checks.push(name);};
 try {
  await wait(() => frame.contentDocument && frame.contentDocument.getElementById('nTasks')?.textContent === '198');
  const doc = frame.contentDocument;
  const get = id => doc.getElementById(id);
  const change = (id, value, type = 'change') => {get(id).value = value; get(id).dispatchEvent(new frame.contentWindow.Event(type, {bubbles:true}));};
  assert(get('nFamilies').textContent === '123' && get('nPackages').textContent === '47', 'registry counts 198/123/47');
  assert(get('nAdmitted').textContent === '0', 'zero final admitted');
  assert(get('taskbody').rows.length === 12, 'first page 12 rows');
  get('next').click(); assert(get('pageLabel').textContent === '2 / 17', 'next page');
  get('prev').click(); assert(get('pageLabel').textContent === '1 / 17', 'previous page');
  change('search', 'T0001', 'input'); assert(get('taskbody').rows.length === 1 && get('taskbody').textContent.includes('T0001'), 'Task ID search');
  get('taskbody').querySelector('a.id').click(); assert(get('assayCard').textContent.includes('T0001'), 'open assay provenance card');
  assert(get('assayCard').textContent.includes('unknown') && get('assayCard').textContent.includes('NOT_ADMITTED'), 'unknown evidence not admitted');
  change('search', '突变', 'input'); assert(!get('filteredCount').textContent.startsWith('显示 0 /'), 'Chinese keyword search');
  get('reset').click(); change('family', 'RNA 2D'); assert([...get('taskbody').rows].every(row => row.cells[1].textContent.includes('RNA 2D')), 'family filter');
  change('package', 'BEACON_ALL'); assert(!get('filteredCount').textContent.startsWith('显示 0 /'), 'package filter');
  get('reset').click(); const status = get('status').options[1].value; change('status', status);
  assert([...get('taskbody').rows].every(row => row.cells[3].textContent.includes(status)), 'status filter');
  change('search', 'NO_SUCH_TASK_zzzz', 'input'); assert(get('pageLabel').textContent === '0 / 0' && get('next').disabled, 'empty results and disabled pagination');
  get('reset').click(); change('pageSize', '24'); assert(get('taskbody').rows.length === 24, 'page size 24');
  const lastId = get('cardSelect').options[get('cardSelect').options.length - 1].value;
  change('cardSelect', lastId); assert(get('assayCard').textContent.includes(lastId), 'last registered task provenance and baseline');
  change('cardSelect', get('cardSelect').options[0].value);
  frame.contentWindow.location.hash = '#assay-' + encodeURIComponent(lastId);
  await wait(() => get('cardSelect').value === lastId);
  assert(get('cardSelect').value === lastId, 'non-numeric Task ID deep link');
  assert([...doc.querySelectorAll('a[target="_blank"]')].every(a => a.rel.includes('noreferrer')), 'safe external links');
  const publicTasks = await (await fetch('/data/tasks.json')).json();
  const publicCards = await (await fetch('/data/provenance.json')).json();
  const publicSummary = await (await fetch('/data/summary.json')).json();
  assert(get('snapshot').textContent.includes('SHA256-verified files: ' + publicSummary.raw_files_sha256_verified), 'verified file count displayed without admission');
  assert(get('auditSummary').textContent.includes(publicSummary.excluded_task_rows + ' EXCLUDED / ' + publicSummary.held_task_rows + ' HOLD'), 'registered task HOLD/exclusion summary');
  if (publicSummary.poc_audit) {
    const poc = publicSummary.poc_audit;
    assert(get('auditSummary').textContent.includes(poc.compressed_bytes_downloaded + ' 压缩字节'), 'PoC actual compressed byte count');
    assert(get('auditSummary').textContent.includes('paired 输入：' + poc.unique_paired_inputs_across_downloaded_mirbench), 'exact unique paired inputs scoped to PoC');
    assert(get('auditSummary').textContent.includes('不是任务 N'), 'PoC counts never represented as task N');
  }
  const mirTask = publicTasks.find(task => task.package === 'MIR_BENCH');
  if (mirTask) {
    change('cardSelect', mirTask.id);
    const mirCard = publicCards.find(card => card.id === mirTask.id);
    for (const file of mirCard.files) {
      assert(get('assayCard').textContent.includes(file.file_sha256), 'actual raw SHA256 displayed');
      if (file.actual_n !== null) assert(get('assayCard').textContent.includes('File/split N: ' + file.actual_n), 'counts explicitly file/split scoped');
    }
    assert(mirTask.actual_n === null && get('assayCard').textContent.includes('NOT_VERIFIED / NOT_VERIFIED'), 'file exact QC does not verify task identity or split');
  }
  const rnaTask = publicTasks.find(task => task.package === 'RNAGYM_DMS');
  if (rnaTask && publicSummary.rnagym_reference_classification) {
    change('cardSelect', rnaTask.id);
    const audit = publicSummary.rnagym_reference_classification;
    assert(get('assayCard').textContent.includes(audit.mrna_coding_fitness_proxy_candidates + ' 个 mRNA-coding'), 'RNAGym protein-fitness proxy warning');
    assert(get('assayCard').textContent.includes(audit.noncoding_or_splicing_candidate_files + ' 个仅为 RNA-readout 候选'), 'RNAGym remaining files only candidates');
    assert(get('assayCard').textContent.includes('全部 HOLD / NOT_ADMITTED'), 'RNAGym inventory not assay admission');
    if (audit.ncRNA_candidate_files !== undefined) {
      assert(get('assayCard').textContent.includes(audit.ncRNA_candidate_files + ' ncRNA / ' + audit.mrna_splicing_candidate_files + ' mRNA-splicing'), 'RNA candidate file subclasses');
      assert(get('assayCard').textContent.includes('候选文件行数 ' + audit.rna_candidate_file_records), 'processed file row count explicitly not task N');
    }

  }
  const mobileFrame = document.getElementById('mobile');
  await wait(() => mobileFrame.contentDocument && mobileFrame.contentDocument.getElementById('nTasks')?.textContent === '198');
  const mobileDoc = mobileFrame.contentDocument;
  assert(mobileFrame.contentWindow.innerWidth === 375 && mobileDoc.documentElement.scrollWidth <= 375, '375px no document overflow (inner=' + mobileFrame.contentWindow.innerWidth + ', client=' + mobileDoc.documentElement.clientWidth + ', scroll=' + mobileDoc.documentElement.scrollWidth + ')');
  const menu = mobileDoc.querySelector('.navigation');
  assert(!menu.open, 'mobile navigation initially collapsed'); menu.querySelector('summary').click();
  assert(menu.open && menu.querySelector('nav').getBoundingClientRect().width > 0, 'mobile navigation operable');
  const desktopMenu = doc.querySelector('.navigation');
  assert(desktopMenu.open && desktopMenu.querySelector('nav').getBoundingClientRect().width > 0, 'desktop navigation visible');
  result.dataset.status = 'pass'; result.textContent = JSON.stringify(checks);
 } catch (error) {result.dataset.status = 'fail'; result.textContent = error.stack || error.message;}
})();
"""


@unittest.skipUnless(os.environ.get('RNAGYM_BROWSER_TESTS') == '1', 'set RNAGYM_BROWSER_TESTS=1 for local Chrome UI smoke')
class BrowserSmokeTests(unittest.TestCase):
    def test_real_browser_search_filters_pagination_cards_mobile(self):
        chrome = shutil.which('google-chrome') or shutil.which('chromium')
        if not chrome:
            self.skipTest('Chrome/Chromium not installed; no dependency downloaded')
        harness = ('<!doctype html><html><body><pre id="result" data-status="pending"></pre>'
                   '<iframe id="preview" src="/index.html" style="width:1280px;height:900px;border:0"></iframe>'
                   '<iframe id="mobile" src="/index.html" style="width:375px;height:900px;border:0"></iframe>'
                   '<script>' + BROWSER_SCRIPT + '</script></body></html>').encode()

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(ROOT / 'site'), **kwargs)

            def do_GET(self):
                if self.path == '/__test__.html':
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('Content-Length', str(len(harness)))
                    self.end_headers()
                    self.wfile.write(harness)
                else:
                    super().do_GET()

            def log_message(self, *_):
                pass

        with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server, tempfile.TemporaryDirectory() as profile:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f'http://127.0.0.1:{server.server_port}'
                for file in ('index.html', 'app.js', 'styles.css', 'data/tasks.json', 'data/summary.json', 'data/provenance.json'):
                    with urlopen(f'{base}/{file}', timeout=10) as response:
                        self.assertEqual(response.status, 200)
                        response.read()
                result = subprocess.run([chrome, '--headless', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
                                         '--no-proxy-server', '--disable-background-networking',
                                         f'--user-data-dir={profile}', '--virtual-time-budget=20000',
                                         '--dump-dom', f'{base}/__test__.html'],
                                        text=True, capture_output=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr[-3000:])
                document = Document(result.stdout)
                status = next((attrs.get('data-status') for _, attrs in document.tags if attrs.get('id') == 'result'), None)
                self.assertEqual(status, 'pass', html.unescape(result.stdout.split('</pre>', 1)[0]))
            finally:
                server.shutdown()
                thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
