import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import admission_gate as gate


class AdmissionTests(unittest.TestCase):
    def test_empty_fails_closed(self):
        result = gate.evaluate({})
        self.assertEqual(result['state'], 'HOLD_REVIEW')
        self.assertFalse(result['admitted'])

    def test_sentinel_identity_and_boolean_string_rejected(self):
        result = gate.evaluate({'assay_doi_or_accession': 'NOT_VERIFIED',
                                'human_review_approved': 'true'})
        self.assertIn('MISSING_OR_UNVERIFIED:assay_doi_or_accession', result['issues'])
        self.assertIn('NOT_HUMAN_APPROVED', result['issues'])

    def test_exact_qc_cannot_pass_gate(self):
        import json
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'qc.json').write_text(json.dumps({'state': 'PASS_EXACT_QC_ONLY',
                 'admission_gate_pass': True, 'source_sha256': 'a' * 64,
                 'canonical_assay_id': 'assay_test'}))
            result = gate.evaluate({'canonical_assay_id': 'assay_test',
                'sha256': 'a' * 64, 'qc_report': 'qc.json'}, root)
            self.assertIn('EVIDENCE_NOT_FULL_PASS:qc_report', result['issues'])
            self.assertFalse(result['admitted'])

    def test_unrelated_pass_report_rejected(self):
        import json
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'qc.json').write_text(json.dumps({'state': 'PASS_ASSAY_QC',
                'admission_gate_pass': True, 'canonical_assay_id': 'other',
                'source_sha256': 'b' * 64}))
            result = gate.evaluate({'canonical_assay_id': 'expected',
                'sha256': 'a' * 64, 'qc_report': 'qc.json'}, root)
            self.assertIn('EVIDENCE_ASSAY_MISMATCH:qc_report', result['issues'])
            self.assertIn('EVIDENCE_HASH_MISMATCH:qc_report', result['issues'])
