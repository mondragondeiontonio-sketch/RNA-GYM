"""Fail-closed public FM entry guard. No reservation is created or reset here."""
import json
import os
from pathlib import Path
import signal
import sqlite3
import time
from .budget import BudgetDenied

ROOT=Path(__file__).resolve().parents[1]


def require_compute_lease(*, root=None):
    root=Path(root) if root is not None else ROOT
    scope=os.environ.get("RNA_GYM_BUDGET_SCOPE")
    token=os.environ.get("RNA_GYM_BUDGET_TOKEN")
    ledger_env=os.environ.get("RNA_GYM_BUDGET_LEDGER")
    if not all([scope,token,ledger_env]):
        raise BudgetDenied("PERSISTENT_APPROVED_COMPUTE_LEASE_REQUIRED")
    policy_path=root/"configs/compute_budget_policy_v1.json"
    if not policy_path.is_file(): raise BudgetDenied("COMPUTE_POLICY_MISSING")
    policy=json.loads(policy_path.read_text())
    spec=policy.get("authorized_scopes",{}).get(scope)
    if spec is None: raise BudgetDenied("COMPUTE_SCOPE_NOT_AUTHORIZED")
    expected=(root/spec["ledger"]).resolve()
    if Path(ledger_env).resolve()!=expected or not expected.is_file():
        raise BudgetDenied("APPROVED_LEDGER_BINDING_MISMATCH")
    if os.environ.get("RNA_GYM_SUPERVISED_PID")!=str(os.getpid()):
        raise BudgetDenied("SUPERVISED_CHILD_REQUIRED")
    if signal.getitimer(signal.ITIMER_REAL)[0]<=0:
        raise BudgetDenied("INDEPENDENT_CHILD_WALL_TIMER_REQUIRED")
    # Read-only connection: guard checks never initialize scopes or mutate receipts.
    uri=expected.as_uri()+"?mode=ro"
    try:
        db=sqlite3.connect(uri,uri=True,timeout=5)
        try:
            limits=db.execute("SELECT seconds,attempts,parallel FROM scopes WHERE scope=?",(scope,)).fetchone()
            row=db.execute("SELECT state,created,requested,pid FROM reservations WHERE scope=? AND token=?",(scope,token)).fetchone()
        finally: db.close()
    except sqlite3.Error as exc:
        raise BudgetDenied("APPROVED_LEDGER_UNREADABLE") from exc
    if limits!=(spec["gpu_seconds"],spec["attempts"],spec["parallel"]):
        raise BudgetDenied("APPROVED_SCOPE_LIMITS_MISMATCH")
    if row is None or row[0]!="ACTIVE":
        raise BudgetDenied("ACTIVE_PERSISTENT_RESERVATION_REQUIRED")
    if row[3]!=os.getppid(): raise BudgetDenied("LEASE_SUPERVISOR_PID_MISMATCH")
    age=time.time()-row[1]
    if age<0 or age>=row[2]: raise BudgetDenied("PERSISTENT_LEASE_EXPIRED")
    return {"scope":scope,"ledger":str(expected),"reserved_seconds":row[2]}
