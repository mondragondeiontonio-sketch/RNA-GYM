"""Work allocation preserves task IDs and scientific evidence boundaries."""
import fnmatch
import json
from pathlib import Path
import tempfile
import unittest

from tools import build_workstream_index as index

ROOT = Path(__file__).resolve().parents[1]


class WorkstreamTests(unittest.TestCase):
    def test_all_198_original_rows_appear_exactly_once(self):
        actual = index.build()
        source = json.loads((ROOT / index.CATALOG).read_text())
        ids = [tid for group in actual['workstreams'] for tid in group['task_ids']]
        self.assertEqual(len(ids), 198)
        self.assertEqual(len(set(ids)), 198)
        self.assertEqual(set(ids), {r['task_id'] for r in source['tasks']})
        self.assertIn('XMRNA_rnahl_saluki_mouse', ids)
        self.assertEqual(len(actual['workstreams']), 10)

    def test_registered_row_counts_not_samples_or_independent_assays(self):
        expected = {'sequence': 68, 'secondary': 13, 'tertiary': 16, 'variant': 9,
                    'probing': 10, 'rna_pair': 6, 'ligand': 15, 'design': 34,
                    'signal': 4, 'methodology': 23}
        actual = index.build()
        self.assertEqual({g['workstream_id']: g['registered_task_rows']
                          for g in actual['workstreams']}, expected)
        self.assertEqual(actual['admitted_task_rows'], 0)
        self.assertIn('WORK_ALLOCATION_ONLY', actual['scope'])
        self.assertTrue(all(row['task_level_sample_n'] is None
                            for g in actual['workstreams'] for row in g['tasks']))

    def test_controls_and_protected_holds_are_not_promoted(self):
        actual = index.build()
        rows = {r['task_id']: r for g in actual['workstreams'] for r in g['tasks']}
        for tid in ('T0021', 'T0022'):
            self.assertFalse(rows[tid]['admitted'])
            self.assertTrue(rows[tid]['scientific_state'].startswith('HOLD'))
        self.assertTrue(rows['T0063']['is_excluded_non_assay'])
        self.assertFalse(rows['T0063']['admitted'])
        self.assertEqual(sum(r['is_excluded_non_assay'] for r in rows.values()), 9)

    def test_deterministic_index_and_readme_are_not_stale(self):
        value = index.build()
        self.assertEqual(index.canonical(value), (ROOT / index.OUTPUT).read_bytes())
        self.assertEqual(value, index.build())
        text = (ROOT / 'README.md').read_text()
        section = text[text.index(index.START):text.index(index.END) + len(index.END)]
        self.assertEqual(section, index.readme_table(value))

    def test_unknown_task_type_requires_explicit_mapping(self):
        data = json.loads((ROOT / index.CATALOG).read_text())
        data['tasks'][0]['registered_task_type'] = 'NEW_UNREVIEWED_MODALITY'
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / index.CATALOG
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'UNASSIGNED_TASK_TYPES'):
                index.build(Path(temp))

    def test_catalog_and_workstream_only_changes_trigger_both_ci_events(self):
        text = (ROOT / '.github/workflows/pages.yml').read_text()
        sections = [text.split('  push:', 1)[1].split('  pull_request:', 1)[0],
                    text.split('  pull_request:', 1)[1].split('  workflow_dispatch:', 1)[0]]
        for section in sections:
            patterns = [line.strip().split("'", 2)[1] for line in section.splitlines()
                        if "- '" in line]
            for name in [index.CATALOG, index.OUTPUT]:
                self.assertTrue(any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns), name)
        self.assertIn('python tools/build_workstream_index.py --verify', text)

    def test_metadata_and_doc_have_explicit_public_selection(self):
        from tools.prepare_public import selected_files, scan_file
        selected = selected_files(ROOT)
        for name in (index.OUTPUT, 'docs/TASK_WORKSTREAMS.md'):
            self.assertIn(name, selected)
            self.assertEqual(scan_file(ROOT / name), [])


if __name__ == '__main__':
    unittest.main()
