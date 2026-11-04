import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from rna_gym.budget import BudgetLedger,BudgetDenied
from rna_gym.compute_guard import require_compute_lease


class ComputeGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name); (self.root/"configs").mkdir()
        self.path=self.root/"ledger.sqlite"
        self.ledger=BudgetLedger(self.path,"test",gpu_seconds=20,attempts=4,parallel=1)
        self.spec=dict(ledger="ledger.sqlite",gpu_seconds=20,attempts=4,parallel=1)
        self.write_policy(self.spec)
    def tearDown(self): self.tmp.cleanup()
    def write_policy(self,spec):
        (self.root/"configs/compute_budget_policy_v1.json").write_text(json.dumps(dict(authorized_scopes={"test":spec})))
    def env(self,token):
        return dict(RNA_GYM_BUDGET_SCOPE="test",RNA_GYM_BUDGET_TOKEN=token,RNA_GYM_BUDGET_LEDGER=str(self.path),RNA_GYM_SUPERVISED_PID=str(os.getpid()))
    def test_public_load_refuses_before_adapter_or_weight_access(self):
        from rna_gym import RNAHub
        with patch.dict(os.environ,{},clear=True),patch("tools.rnafm_adapter.RNAFMAdapter") as adapter:
            with self.assertRaises(BudgetDenied): RNAHub.load("RNA-FM")
            adapter.assert_not_called()
    def test_direct_adapter_cannot_bypass_public_guard(self):
        from tools.rnafm_adapter import RNAFMAdapter
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(BudgetDenied): RNAFMAdapter({})
    def test_adapter_encode_rechecks_before_forward(self):
        from tools.rnafm_adapter import RNAFMAdapter
        adapter=RNAFMAdapter.__new__(RNAFMAdapter)
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(BudgetDenied): adapter.encode([])
    def test_real_supervised_child_lease_passes_without_gpu(self):
        answer=self.root/"answer.json"
        code="import json; from pathlib import Path; from rna_gym.compute_guard import require_compute_lease; result=require_compute_lease(root=%r); Path(%r).write_text(json.dumps(result))" % (str(self.root),str(answer))
        rc=self.ledger.run_supervised([sys.executable,"-c",code],seconds=5,log_path=self.root/"child.log")
        self.assertEqual(rc,0,(self.root/"child.log").read_text()); self.assertEqual(json.loads(answer.read_text())["scope"],"test")
        self.assertEqual(self.ledger.snapshot()["reservations"][0]["state"],"SETTLED")
    def test_scope_and_ledger_binding_and_limits_fail_closed(self):
        token=self.ledger.reserve(5); env=self.env(token)
        for key,value,error in [("RNA_GYM_BUDGET_SCOPE","unapproved","NOT_AUTHORIZED"),("RNA_GYM_BUDGET_LEDGER",str(self.root/"other.sqlite"),"BINDING_MISMATCH"),("RNA_GYM_SUPERVISED_PID","0","SUPERVISED_CHILD")]:
            with patch.dict(os.environ,dict(env,**{key:value}),clear=True),patch("signal.getitimer",return_value=(1,0)):
                with self.assertRaisesRegex(BudgetDenied,error): require_compute_lease(root=self.root)
        spec=dict(self.spec,gpu_seconds=21); self.write_policy(spec)
        with patch.dict(os.environ,env,clear=True),patch("signal.getitimer",return_value=(1,0)):
            with self.assertRaisesRegex(BudgetDenied,"LIMITS_MISMATCH"): require_compute_lease(root=self.root)
    def test_no_timer_and_settled_lease_rejected_without_mutation(self):
        token=self.ledger.reserve(5); self.ledger.settle(token,0); env=self.env(token)
        before=self.path.read_bytes()
        with patch.dict(os.environ,env,clear=True),patch("signal.getitimer",return_value=(0,0)):
            with self.assertRaisesRegex(BudgetDenied,"WALL_TIMER_REQUIRED"): require_compute_lease(root=self.root)
        with patch.dict(os.environ,env,clear=True),patch("signal.getitimer",return_value=(1,0)):
            with self.assertRaisesRegex(BudgetDenied,"ACTIVE_PERSISTENT"): require_compute_lease(root=self.root)
        self.assertEqual(before,self.path.read_bytes())
    def test_expired_lease_cannot_be_reused(self):
        token=self.ledger.reserve(5)
        with self.ledger.transaction() as db: db.execute("UPDATE reservations SET created=?,pid=? WHERE token=?",(time.time()-10,os.getppid(),token))
        with patch.dict(os.environ,self.env(token),clear=True),patch("signal.getitimer",return_value=(1,0)):
            with self.assertRaisesRegex(BudgetDenied,"LEASE_EXPIRED"): require_compute_lease(root=self.root)
    def test_lease_owner_must_be_current_supervisor(self):
        token=self.ledger.reserve(5)
        with patch.dict(os.environ,self.env(token),clear=True),patch("signal.getitimer",return_value=(1,0)):
            with self.assertRaisesRegex(BudgetDenied,"SUPERVISOR_PID_MISMATCH"): require_compute_lease(root=self.root)
