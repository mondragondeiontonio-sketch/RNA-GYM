import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import prepare_public as public


class PublicationTests(unittest.TestCase):
    def test_no_private_paths_selected(self):
        names = public.selected_files(ROOT)
        self.assertNotIn('docs/ORIGINAL_PHASE1_AUDIT.md', names)
        self.assertFalse(any(n.endswith('.xlsx') or 'raw_cache/' in n or '/runs/' in n for n in names))
        self.assertIn('data/audit/task_status.tsv', names)

    def test_token_sequence_and_identity_detection(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'data.txt'
            for value in ['ghp_' + 'A' * 32, 'A' * 50,
                          '/home/' + 'private-person/private-data',
                          'https://cdn.example/a?X-Amz-Signature=' + 'a' * 30]:
                p.write_text(value)
                self.assertTrue(public.scan_file(p))
            p.write_text('Public metadata only; actual_n=954, admitted=false.')
            self.assertEqual(public.scan_file(p), [])

    def test_new_output_required(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                public.build(ROOT, Path(temp))
