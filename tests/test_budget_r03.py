import multiprocessing as mp
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from rna_gym.budget import BudgetLedger, BudgetDenied


def contender(path, queue):
    ledger = BudgetLedger(path, "shared", gpu_seconds=10, attempts=8, parallel=8)
    try:
        ledger.reserve(6)
        queue.put("RESERVED")
    except BudgetDenied:
        queue.put("DENIED")


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/"ledger.sqlite"
    def tearDown(self):
        self.tmp.cleanup()
    def make(self):
        return BudgetLedger(self.path, "one", gpu_seconds=10, attempts=3)
    def test_restart_crash_is_not_free(self):
        ledger = self.make()
        ledger.reserve(8)
        other = self.make()
        self.assertEqual(other.snapshot()["charged_seconds"], 8)
        with self.assertRaises(BudgetDenied): other.reserve(3)
        with self.assertRaises(BudgetDenied): other.reserve(1)
        self.assertEqual(self.make().snapshot()["events"], 3)
    def test_real_process_restart(self):
        code = ("from rna_gym.budget import BudgetLedger; import os; "
                "b=BudgetLedger(%r, \"one\", gpu_seconds=10, attempts=3); b.reserve(7); os._exit(9)" % str(self.path))
        self.assertEqual(subprocess.run([sys.executable, "-c", code]).returncode, 9)
        self.assertEqual(self.make().snapshot()["charged_seconds"], 7)
    def test_multiprocess_no_oversubscription(self):
        ctx = mp.get_context("spawn")
        queue = ctx.Queue()
        workers = [ctx.Process(target=contender, args=(str(self.path),queue)) for _ in range(8)]
        for p in workers: p.start()
        for p in workers: p.join(30); self.assertEqual(p.exitcode,0)
        answers = [queue.get(timeout=5) for _ in workers]
        self.assertEqual(answers.count("RESERVED"),1)
        self.assertEqual(answers.count("DENIED"),7)
    def test_settlement_and_immutable_caps(self):
        ledger = self.make(); token = ledger.reserve(5)
        ledger.settle(token,1)
        self.assertEqual(self.make().snapshot()["charged_seconds"],1)
        with self.assertRaises(BudgetDenied): ledger.settle(token,0)
        with self.assertRaises(BudgetDenied): BudgetLedger(self.path,"one",gpu_seconds=11,attempts=3)
    def test_failure_charges_cap_and_overrun_is_recorded(self):
        b=self.make(); t=b.reserve(4); b.settle(t,1,outcome="FAILED")
        self.assertEqual(b.snapshot()["charged_seconds"],4)
        t=b.reserve(5); b.settle(t,8)
        self.assertEqual(b.snapshot()["charged_seconds"],12)
        with self.assertRaises(BudgetDenied): b.reserve(1)
    def test_attempts_and_invalid_reservations(self):
        b=self.make()
        for _ in range(3):
            t=b.reserve(1); b.settle(t,0)
        with self.assertRaises(BudgetDenied): b.reserve(1)
        for n in [0,-1,float("nan"),float("inf")]:
            with self.assertRaises(ValueError): b.reserve(n)
    def test_supervisor_timeout(self):
        b=self.make()
        with self.assertRaises(subprocess.TimeoutExpired):
            b.run_supervised([sys.executable,"-c","import time; time.sleep(5)"],seconds=.15,log_path=Path(self.tmp.name)/"child.log")
        self.assertEqual(b.snapshot()["reservations"][0]["outcome"],"TIMEOUT")
        self.assertGreaterEqual(b.snapshot()["charged_seconds"],.15)

    def test_active_lease_and_direct_gpu_entrypoint_guard(self):
        from unittest.mock import patch
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("optional numpy unavailable")
        from tools.adaptation_smoke_v1 import train
        b=self.make(); t=b.reserve(1); b.assert_active(t); b.settle(t,0)
        with self.assertRaises(BudgetDenied): b.assert_active(t)
        with patch.dict("os.environ",{},clear=True):
            with self.assertRaisesRegex(BudgetDenied,"SUPERVISED_PERSISTENT_BUDGET_REQUIRED"): train("scratch")
