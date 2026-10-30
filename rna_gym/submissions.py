"""Private-Holdout intake; no evaluator or hidden labels. Server supplies receipts.

Client bodies cannot grant qualification, choose a team, or supply commands,
paths, labels, or per-sample diagnostics. This is not a deployed HTTP service.
"""
import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


class SubmissionStore:
    FIELDS = {'scope', 'model_id', 'model_version', 'checkpoint_hash', 'adapter_hash',
              'prompt_hash', 'protocol_hash', 'code_version'}

    def __init__(self, database, config, *, verified_public_receipts=()):
        self.database = Path(database)
        self.config = config
        self.receipts = tuple(verified_public_receipts)
        self.database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.database.is_symlink():
            raise ValueError('PRIVATE_STORE_SYMLINK_FORBIDDEN')
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS submissions (id TEXT PRIMARY KEY, principal TEXT NOT NULL, '
                       'week TEXT NOT NULL, scope TEXT NOT NULL, submission_hash TEXT NOT NULL, '
                       'request TEXT NOT NULL, status TEXT NOT NULL)')
        self.database.chmod(0o600)

    def _db(self):
        return sqlite3.connect(str(self.database), timeout=30)

    def qualified(self, principal, request):
        bindings = ('model_id', 'model_version', 'checkpoint_hash', 'adapter_hash', 'prompt_hash', 'code_version')
        return any(r.get('principal') == principal and r.get('status') == 'PUBLIC_BENCHMARK_COMPLETED'
            and r.get('verification_status') == 'SERVER_VERIFIED'
            and all(r.get(k) == request[k] for k in bindings) for r in self.receipts)

    def submit(self, principal, request, *, now=None):
        if not isinstance(principal, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', principal):
            raise ValueError('TRUSTED_AUTHENTICATED_PRINCIPAL_REQUIRED')
        if not isinstance(request, dict) or set(request) != self.FIELDS:
            raise ValueError('EXACT_SUBMISSION_FIELDS_REQUIRED_NO_LABELS_OR_PATHS')
        if request['scope'] not in ('public', 'private'):
            raise ValueError('INVALID_SCOPE')
        for k, value in request.items():
            if not isinstance(value, str) or not value or len(value) > 200:
                raise ValueError('BOUNDED_STRING_REQUIRED')
            if k.endswith('_hash') and not re.fullmatch('[0-9a-f]{64}', value):
                raise ValueError('SHA256_BINDING_REQUIRED')
        if request['scope'] == 'private' and not self.qualified(principal, request):
            raise ValueError('PUBLIC_QUALIFICATION_REQUIRED_NO_RANK_OR_SCORE_THRESHOLD')
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError('UTC_AWARE_TIME_REQUIRED')
        year, week, _ = now.astimezone(timezone.utc).isocalendar()
        week_key = f'{year}-{week:02}'
        quota = self.config['max_private_submissions_per_team_per_week']
        if type(quota) is not int or quota < 1:
            raise ValueError('POSITIVE_PRIVATE_QUOTA_REQUIRED')
        sid = 'SUB_'+uuid.uuid4().hex
        payload = json.dumps(dict(principal=principal, request=request, id=sid), sort_keys=True, separators=(',', ':'))
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            if request['scope'] == 'private':
                n = db.execute("SELECT count(*) FROM submissions WHERE principal=? AND week=? AND scope='private'",
                    (principal, week_key)).fetchone()[0]
                if n >= quota:
                    raise ValueError('PRIVATE_WEEKLY_QUOTA_EXCEEDED')
            db.execute('INSERT INTO submissions VALUES (?,?,?,?,?,?,?)',
                (sid, principal, week_key, request['scope'], digest, payload, 'RECEIVED_NOT_EVALUATED'))
        return dict(id=sid, submission_hash=digest, status='RECEIVED_NOT_EVALUATED')

    def get(self, principal, submission_id):
        with self._db() as db:
            row = db.execute('SELECT id,submission_hash,status,scope FROM submissions WHERE id=? AND principal=?',
                (submission_id, principal)).fetchone()
        if row is None:
            raise KeyError('SUBMISSION_NOT_FOUND')
        return dict(zip(('id', 'submission_hash', 'status', 'scope'), row))
