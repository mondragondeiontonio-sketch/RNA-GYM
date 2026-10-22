import csv
import json
import subprocess
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]


class TaskBundleTests(unittest.TestCase):
    def test_full_task_index_and_unverified_n(self):
        cards=[json.loads(p.read_text()) for p in sorted((ROOT/'data/task_bundles').glob('*.json'))]
        with (ROOT/'data/registries/search_level_task_crosswalk_198.csv').open(encoding='utf-8-sig') as f:
            tasks={r['row_id']:r for r in csv.DictReader(f)}
        self.assertEqual(len(cards),198)
        self.assertEqual({c['task_id'] for c in cards},set(tasks))
        for c in cards:
            self.assertEqual(c['reported_n'],tasks[c['task_id']]['reported_n'])
            self.assertIsNone(c['actual_task_n'])
            self.assertFalse(c['admitted'])
            self.assertFalse(c['task_download_completed'])
            self.assertTrue(all(a['identity_scope']=='PACKAGE_ONLY_NOT_PROVEN_TASK_INPUT' for a in c['assets']))

    def test_original_x_namespace_kept(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/task_download.py'),'plan','--task','XMRNA_mirna_target'],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(json.loads(p.stdout)['task_id'],'XMRNA_mirna_target')

    def test_plan_no_network_no_training(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/task_download.py'),'plan','--task','T0014'],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(json.loads(p.stdout)['task_id'],'T0014')

    def test_download_requires_explicit_package_scope(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/task_download.py'),'download','--task','T0014','--asset','P0_RNAGYM_PROCESSED'],capture_output=True,text=True)
        self.assertNotEqual(p.returncode,0)
        self.assertIn('package-evidence-only',p.stderr)
