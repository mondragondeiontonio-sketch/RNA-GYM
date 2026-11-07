"""Release/figure contracts use approved metadata or explicit gaps, never fabricated scores."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from tools.mrna_design.export_figures import render
from tools.mrna_design.export_site import payload
from rna_gym.research_v06.provenance import ProtocolError
from rna_gym.research_v06.scoring import score_predictions

ROOT=Path(__file__).resolve().parents[2]


class ReleaseTests(unittest.TestCase):
    def test_all_six_figure_contracts_exist(self):
        for number in range(1,7):
            root=ROOT/'paper/figure_specs'/('fig'+str(number))
            for file in ('figure_spec.md','figure_input_schema.json','data_status.tsv','script.py'):
                self.assertTrue((root/file).is_file())
            self.assertEqual(json.loads((root/'figure_input_schema.json').read_text())['figure_id'],number)

    def test_missing_real_evidence_is_blocked_not_mock_score(self):
        with tempfile.TemporaryDirectory() as d:
            result=render(ROOT/'paper/figure_specs/fig3',Path(d)/'fig3')
            self.assertEqual(result['status'],'BLOCKED_DATA')
            self.assertFalse(result['experimental_scores_generated'])
            with self.assertRaises(ProtocolError):render(ROOT/'paper/figure_specs/fig3',Path(d)/'fig3')

    def test_public_site_has_no_ranking_or_private_stats(self):
        p=payload(ROOT)
        self.assertEqual(p['formal_admitted'],0)
        self.assertIsNone(p['universal_score'])
        self.assertEqual(p['real_statistics'],'LOCAL_ONLY_PENDING_PUBLICATION_RIGHTS')
        self.assertNotIn('prediction',p)

    @unittest.skipUnless(importlib.util.find_spec('scipy'),'Install research-v06 CPU extra')
    def test_undefined_cell_macro_not_silently_reweighted(self):
        rows=[{'cell_id':c,'sequence_id':str(i),'label':float(i) if c=='A' else 1.,
               'prediction':float(i)} for c in ('A','B') for i in range(4)]
        self.assertIsNone(score_predictions(rows)['cell_macro']['spearman'])

    def test_historical_scoring_v1_and_budget_are_not_changed(self):
        from tools.evaluation_protocol import sha256_file
        snap=json.loads((ROOT/'manifests/research_v06_source_snapshot.json').read_text())
        paths={r['path']:r['sha256'] for r in snap['files']}
        for path in ('configs/scoring_protocol_v1.yaml','configs/compute_budget_policy_v1.json',
                     'data/registries/utr_legacy_102.json','data/registries/utr_historical_result_status.json'):
            self.assertEqual(sha256_file(ROOT/path),paths[path])
