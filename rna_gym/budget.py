"""R03: transactional, durable, conservative compute reservations.

A crashed worker keeps its ENTIRE reservation and its concurrency slot. Only an
explicit settlement can release it; restarting never resets limits or usage.
Use run_supervised for hard wall-time enforcement; accounting alone is not a timer.
"""
import contextlib
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import uuid


class BudgetDenied(RuntimeError):
    pass


class BudgetLedger:
    def __init__(self, path, scope, *, gpu_seconds, attempts, parallel=1):
        if not scope or not math.isfinite(gpu_seconds) or gpu_seconds <= 0:
            raise ValueError("FINITE_POSITIVE_SCOPE_REQUIRED")
        if type(attempts) is not int or attempts < 1 or type(parallel) is not int or parallel < 1:
            raise ValueError("POSITIVE_INTEGER_LIMITS_REQUIRED")
        self.path, self.scope = Path(path).resolve(), scope
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS scopes (scope TEXT PRIMARY KEY, seconds REAL NOT NULL, attempts INTEGER NOT NULL, parallel INTEGER NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS reservations (token TEXT PRIMARY KEY, scope TEXT NOT NULL, requested REAL NOT NULL, charged REAL NOT NULL, state TEXT NOT NULL, pid INTEGER NOT NULL, created REAL NOT NULL, elapsed REAL, outcome TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL, at REAL NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL)")
            limits = (float(gpu_seconds), attempts, parallel)
            old = db.execute("SELECT seconds,attempts,parallel FROM scopes WHERE scope=?", (scope,)).fetchone()
            if old and tuple(old) != limits:
                raise BudgetDenied("IMMUTABLE_SCOPE_LIMITS")
            db.execute("INSERT OR IGNORE INTO scopes VALUES(?,?,?,?)", (scope,) + limits)

    @contextlib.contextmanager
    def transaction(self):
        db = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA busy_timeout=30000")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _event(self, db, kind, detail):
        db.execute("INSERT INTO events(scope,at,kind,detail) VALUES(?,?,?,?)",
                   (self.scope, time.time(), kind, json.dumps(detail, sort_keys=True)))

    def reserve(self, seconds):
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("FINITE_POSITIVE_RESERVATION_REQUIRED")
        reason = None
        token = uuid.uuid4().hex
        with self.transaction() as db:
            cap, attempts, parallel = db.execute("SELECT seconds,attempts,parallel FROM scopes WHERE scope=?", (self.scope,)).fetchone()
            used, count, active = db.execute("SELECT COALESCE(SUM(charged),0),COUNT(*),COALESCE(SUM(state='ACTIVE'),0) FROM reservations WHERE scope=?", (self.scope,)).fetchone()
            if used + seconds > cap:
                reason = "GPU_SECONDS_EXHAUSTED"
            elif count >= attempts:
                reason = "ATTEMPTS_EXHAUSTED"
            elif active >= parallel:
                reason = "CONCURRENCY_EXHAUSTED_OR_UNSETTLED_CRASH"
            if reason:
                self._event(db, "DENIED", dict(reason=reason, seconds=seconds))
            else:
                db.execute("INSERT INTO reservations VALUES(?,?,?,?,?,?,?,?,?)",
                           (token, self.scope, seconds, seconds, "ACTIVE", os.getpid(), time.time(), None, None))
                self._event(db, "RESERVED", dict(token=token, seconds=seconds))
        if reason:
            raise BudgetDenied(reason)
        return token

    def settle(self, token, elapsed, *, outcome="SUCCESS"):
        if not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError("FINITE_NONNEGATIVE_ELAPSED_REQUIRED")
        with self.transaction() as db:
            row = db.execute("SELECT requested,state FROM reservations WHERE token=? AND scope=?", (token, self.scope)).fetchone()
            if row is None or row[1] != "ACTIVE":
                raise BudgetDenied("UNKNOWN_OR_ALREADY_SETTLED_RESERVATION")
            # Failed/crashed intervals are never interpreted as zero usage.
            charge = elapsed if outcome == "SUCCESS" else max(row[0], elapsed)
            db.execute("UPDATE reservations SET charged=?,state=?,elapsed=?,outcome=? WHERE token=?",
                       (charge, "SETTLED", elapsed, outcome, token))
            self._event(db, "SETTLED", dict(token=token, elapsed=elapsed, charged=charge, outcome=outcome))

    def assert_active(self, token):
        with self.transaction() as db:
            row = db.execute("SELECT state FROM reservations WHERE token=? AND scope=?", (token, self.scope)).fetchone()
            if row is None or row[0] != "ACTIVE":
                raise BudgetDenied("ACTIVE_PERSISTENT_RESERVATION_REQUIRED")

    def snapshot(self):
        with self.transaction() as db:
            keys = [d[0] for d in db.execute("SELECT * FROM reservations LIMIT 0").description]
            rows = [dict(zip(keys, row)) for row in db.execute("SELECT * FROM reservations WHERE scope=? ORDER BY created", (self.scope,))]
            events = db.execute("SELECT COUNT(*) FROM events WHERE scope=?", (self.scope,)).fetchone()[0]
            return dict(scope=self.scope, reservations=rows, charged_seconds=sum(r["charged"] for r in rows), events=events)

    def run_supervised(self, command, *, seconds, log_path, cwd=None, env=None):
        """Single-GPU child only; no daemonized grandchildren. Parent crash is conservative.

        Wall enforcement kills ONLY the child started here, never other processes.
        """
        log_path = Path(log_path)
        with log_path.open("x") as log:
            token = self.reserve(seconds)
            start = time.monotonic()
            outcome = "FAILED"
            try:
                child_env = dict(os.environ if env is None else env)
                child_env.update(RNA_GYM_BUDGET_TOKEN=token, RNA_GYM_BUDGET_LEDGER=str(self.path), RNA_GYM_BUDGET_SCOPE=self.scope)
                wrapped = [sys.executable, str(Path(__file__).with_name("_budget_child.py")), str(os.getpid()), str(seconds)] + list(command)
                result = subprocess.run(wrapped, cwd=cwd, env=child_env, stdout=log, stderr=subprocess.STDOUT, timeout=seconds)
                if result.returncode == -14:
                    outcome = "TIMEOUT"
                    raise subprocess.TimeoutExpired(command, seconds)
                outcome = "SUCCESS" if result.returncode == 0 else "FAILED"
                return result.returncode
            except subprocess.TimeoutExpired:
                outcome = "TIMEOUT"
                raise
            finally:
                self.settle(token, time.monotonic()-start, outcome=outcome)
