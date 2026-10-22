#!/usr/bin/env python3
"""Bounded, resumable acquisition into quarantine. No command admits an assay.

Each invocation performs one stage. SQLite is authoritative for job state;
immutable content-addressed objects and sidecars are evidence, not admission.
Python 3.10+, standard library only; TLS verification is never disabled.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import datetime as dt
import fcntl
import hashlib
import http.client
import socket
import json
import os
import re
import shutil
import sqlite3
import stat
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit, urlunsplit, parse_qsl

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / 'data/assets/download_assets.csv'
ALLOWED_HOSTS = {'marks.hms.harvard.edu', 'raw.githubusercontent.com',
                 'huggingface.co', 'hf-mirror.com', 'zenodo.org', 'github.com', 'api.github.com'}
STAGES = ('QUEUED', 'FETCHING', 'DOWNLOADED', 'HASHED', 'PARSED', 'QC_PASS',
          'DEDUP_PASS', 'REVIEW_READY', 'ADMITTED')
SIGNED_CDN_HOSTS = {'cas-bridge.xethub.hf.co', 'release-assets.githubusercontent.com'}
SIGNED_QUERY_KEYS = {'Expires', 'Policy', 'Signature', 'Key-Pair-Id', 'X-Xet-Cas-Uid',
    'response-content-type', 'response-content-disposition', 'xip',
    'X-Amz-Algorithm', 'X-Amz-Credential', 'X-Amz-Date', 'X-Amz-Expires',
    'X-Amz-SignedHeaders', 'X-Amz-Signature',
    'sp','sv','sr','spr','se','rscd','rsct','skoid','sktid','skt','ske','sks','skv','sig','jwt'}
MAX_DEFAULT = 16 * 1024 * 1024
RESERVE_BYTES = 64 * 1024 * 1024


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read_manifest(path=REGISTRY):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    result = {r['asset_id']: r for r in rows}
    if len(result) != len(rows):
        raise ValueError('duplicate asset IDs')
    return result


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def immutable_json(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True) + '\n').encode()
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError('immutable evidence already exists with different content')
        return
    with path.open('xb') as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    path.chmod(0o444)


class StateDB:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=60)
        self.db.row_factory = sqlite3.Row
        # DELETE journal is portable on this project's network filesystem.
        self.db.execute('PRAGMA busy_timeout=60000')
        self._last_heartbeat = {}
        self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS jobs (
          idempotency_key TEXT PRIMARY KEY, task_id TEXT, package_group_id TEXT,
          assay_id TEXT, asset_id TEXT, artifact_sha256 TEXT, stage TEXT NOT NULL,
          retry_count INTEGER NOT NULL DEFAULT 0, exit_code INTEGER,
          last_heartbeat TEXT NOT NULL, evidence_paths TEXT NOT NULL DEFAULT '[]',
          error TEXT);
        CREATE TABLE IF NOT EXISTS events (
          event_id INTEGER PRIMARY KEY AUTOINCREMENT, idempotency_key TEXT,
          at_utc TEXT NOT NULL, stage TEXT NOT NULL, detail_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS artifacts (
          asset_id TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL,
          raw_path TEXT NOT NULL, first_seen TEXT NOT NULL,
          PRIMARY KEY(asset_id, sha256));
        ''')
        self.db.commit()

    @contextlib.contextmanager
    def transaction(self):
        # A short OS lock serializes writers on the shared filesystem. Do not
        # hold it across HTTP requests or transfers; SQLite remains authoritative.
        with Path(str(self.path) + '.lock').open('a') as lock:
            started = time.monotonic()
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() - started > 60:
                        raise TimeoutError('state writer lock timeout; retry stage safely')
                    time.sleep(0.1)
            try:
                with self.db:
                    yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def ensure(self, row, task_id=None):
        key = hashlib.sha256(json.dumps([task_id, row['asset_id'], row.get('direct_url')],
                                      separators=(',', ':')).encode()).hexdigest()
        with self.transaction():
            self.db.execute('''INSERT OR IGNORE INTO jobs
              (idempotency_key,task_id,package_group_id,assay_id,asset_id,stage,last_heartbeat)
              VALUES (?,?,?,?,?,'QUEUED',?)''',
              (key, task_id, row['package_group_id'], None, row['asset_id'], now()))
        return key

    def job(self, key):
        return dict(self.db.execute('SELECT * FROM jobs WHERE idempotency_key=?',
                                    (key,)).fetchone())

    def transition(self, key, stage, *, detail=None, evidence=None, digest=None,
                   retry=False, exit_code=0):
        if stage not in STAGES and not stage.startswith(('HOLD_', 'EXCLUDED_')):
            raise ValueError('unknown stage')
        if stage == 'ADMITTED':
            raise PermissionError('downloader cannot approve human admission')
        old = self.job(key)
        if old['stage'] in STAGES and stage in STAGES:
            i, j = STAGES.index(old['stage']), STAGES.index(stage)
            if stage != old['stage'] and not (j == i + 1 or stage == 'FETCHING'):
                raise ValueError(f'invalid stage transition {old["stage"]} -> {stage}')
        detail = detail or {}
        with self.transaction():
            self.db.execute('''UPDATE jobs SET stage=?,last_heartbeat=?,exit_code=?,
              artifact_sha256=COALESCE(?,artifact_sha256), evidence_paths=?,
              retry_count=retry_count+?,error=? WHERE idempotency_key=?''',
              (stage, now(), exit_code, digest,
               json.dumps(evidence if evidence is not None else json.loads(old['evidence_paths'])),
               int(retry), detail.get('error'), key))
            self.db.execute('''INSERT INTO events
              (idempotency_key,at_utc,stage,detail_json) VALUES (?,?,?,?)''',
              (key, now(), stage, json.dumps(detail, sort_keys=True)))

    def heartbeat(self, key):
        current = time.monotonic()
        if current - self._last_heartbeat.get(key, 0) < 3:
            return
        self._last_heartbeat[key] = current
        with self.transaction():
            self.db.execute('UPDATE jobs SET last_heartbeat=? WHERE idempotency_key=?',
                            (now(), key))

    def artifact(self, aid, digest, path):
        with self.transaction():
            self.db.execute('INSERT OR IGNORE INTO artifacts VALUES (?,?,?,?,?)',
                            (aid, digest, Path(path).stat().st_size, str(path), now()))

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def validate_url(url, *, signed_redirect=False):
    p = urlsplit(url)
    if p.scheme != 'https' or p.hostname not in (ALLOWED_HOSTS | (SIGNED_CDN_HOSTS if signed_redirect else set())):
        raise ValueError('HTTPS host not allowlisted')
    if p.username or p.password or p.port not in (None, 443):
        raise ValueError('URL credentials or nonstandard port refused')
    if p.fragment:
        raise ValueError('URL fragments refused')
    if p.query and not (signed_redirect and p.hostname in SIGNED_CDN_HOSTS
                        and {k for k, _ in parse_qsl(p.query)} <= SIGNED_QUERY_KEYS):
        raise ValueError('query credentials refused outside public signed CDN redirects')


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl, signed_redirect=True)  # Check BEFORE following; do not leak credentials.
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def ipv4_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, **kwargs):
    # Same HTTPS hostname, route family only; no proxy, certificate bypass or credentials.
    last_error = None
    for family, kind, proto, _, target in socket.getaddrinfo(address[0], address[1], socket.AF_INET, socket.SOCK_STREAM):
        sock = socket.socket(family, kind, proto)
        try:
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(target)
            return sock
        except OSError as exc:
            last_error = exc
            sock.close()
    raise last_error or OSError('no IPv4 route for approved HTTPS host')


class IPv4HTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = ipv4_connection


class IPv4HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(IPv4HTTPSConnection, req, context=self._context, check_hostname=self._check_hostname)


def open_https(url, *, headers=None, method=None, timeout=25):
    validate_url(url)
    h = {'User-Agent': 'RNA-Gym-audit/0.2', 'Accept-Encoding': 'identity'}
    h.update(headers or {})
    return urllib.request.build_opener(IPv4HTTPSHandler(), SafeRedirect()).open(
        urllib.request.Request(url, headers=h, method=method), timeout=timeout)


def snapshot(response):
    headers = response.headers
    total = headers.get('Content-Length')
    content_range = headers.get('Content-Range', '')
    if content_range and '/' in content_range:
        total = content_range.rsplit('/', 1)[1]
    return {'http_status': response.status, 'final_url': urlunsplit((*urlsplit(response.url)[:3], '', '')),
            'ephemeral_query_redacted': bool(urlsplit(response.url).query),
            'etag': headers.get('ETag'), 'last_modified': headers.get('Last-Modified'),
            'size_bytes': int(total) if total and total.isdigit() else None,
            'content_range': content_range, 'content_type': headers.get('Content-Type'),
            'probed_at_utc': now()}


def probe(url):
    try:
        with open_https(url, method='HEAD') as response:
            return snapshot(response)
    except urllib.error.HTTPError as e:
        if e.code not in (403, 405, 501):
            raise
    with open_https(url, headers={'Range': 'bytes=0-0'}) as response:
        result = snapshot(response)
        response.read(1)  # Never consume an unbounded response to a Range probe.
        return result


def asset_dir(row, out):
    for key in ('asset_id', 'package_group_id'):
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', row[key]):
            raise ValueError('unsafe identifier')
    name = row['relative_filename']
    if name in ('', '.', '..') or any(c in name for c in '/\\:'):
        raise ValueError('unsafe filename')
    root = Path(out).resolve()
    path = root / 'quarantine' / row['package_group_id'] / row['asset_id']
    if not path.resolve().is_relative_to(root):
        raise ValueError('cache symlink escape')
    return path


def get_target(row, out):
    folder = asset_dir(row, out)
    index = folder / 'latest.json'
    if not index.exists():
        return folder / 'NOT_DOWNLOADED' / row['relative_filename']
    digest = json.loads(index.read_text())['sha256']
    if not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('invalid cache index')
    target = folder / digest / row['relative_filename']
    if not target.resolve().is_relative_to(Path(out).resolve()):
        raise ValueError('raw symlink escape')
    return target


def check_rights(row, decisions):
    if row.get('rights_status') in ('BLOCKED', 'EXPLICITLY_PROHIBITED'):
        raise PermissionError('upstream rights prohibit acquisition')
    decision = decisions.get(row['asset_id'], {})
    if decision.get('decision') != 'ALLOW_PUBLIC_QUARANTINE_POC':
        raise PermissionError('HOLD_LICENSE: explicit asset-specific acquisition evidence required')
    if not decision.get('evidence_url') or not re.fullmatch(
            '[0-9a-f]{64}', decision.get('evidence_sha256', '')):
        raise PermissionError('HOLD_LICENSE: missing archived license evidence')
    return decision


def compatible_partial(previous, current):
    etag = previous.get('etag')
    if etag and not etag.startswith('W/'):
        return (etag == current.get('etag') and
                previous.get('size_bytes') == current.get('size_bytes'))
    return bool(previous.get('last_modified') and
                previous.get('last_modified') == current.get('last_modified') and
                previous.get('size_bytes') == current.get('size_bytes'))


def fetch(row, out, max_bytes, allow_unpinned, *, db=None, decisions=None,
          retries=2, rate_kbps=512, refresh=False):
    if max_bytes <= 0 or retries not in range(6) or rate_kbps <= 0:
        raise ValueError('positive cap/rate and 0..5 retries required')
    own_db = db is None
    db = db or StateDB(Path(out) / 'run-state.sqlite')
    key = db.ensure(row)
    try:
        rights = check_rights(row, decisions or {})
        expected = row.get('sha256_expected', '').strip().lower()
        if expected and not re.fullmatch('[0-9a-f]{64}', expected):
            raise ValueError('invalid expected SHA256')
        if not expected and not allow_unpinned:
            raise ValueError('un-pinned bytes require --allow-unpinned; quarantine only')
        folder = asset_dir(row, out)
        folder.mkdir(parents=True, exist_ok=True)
        target = get_target(row, out)
        if target.is_file() and not refresh:
            actual = sha256(target)
            if actual != target.parent.name or (expected and actual != expected):
                raise ValueError('cached bytes do not match immutable digest')
            # Recover a completed byte transfer whose final SQLite commit was
            # interrupted, with a recorded receipt + a fresh observed hash.
            receipt = target.parent / 'download.json'
            if not receipt.is_file() or json.loads(receipt.read_text()).get('observed_sha256') != actual:
                raise ValueError('cached bytes lack matching acquisition receipt')
            old_stage = db.job(key)['stage']
            if old_stage in ('QUEUED', 'FETCHING') or old_stage.startswith('HOLD_'):
                if old_stage != 'FETCHING':
                    db.transition(key, 'FETCHING', detail={'event':'RECONCILE_LOCAL_RECEIPT'})
                db.artifact(row['asset_id'], actual, target)
                db.transition(key, 'DOWNLOADED', digest=actual, evidence=[str(receipt)],
                              detail={'event':'RECOVERED_AFTER_INTERRUPTED_STATE_COMMIT', 'bytes':target.stat().st_size})
            else:
                db.transition(key, old_stage, digest=actual,
                              detail={'event': 'REUSED_HASH_VERIFIED', 'bytes': target.stat().st_size})
            return target
        db.transition(key, 'FETCHING')
        part = folder / (row['relative_filename'] + '.part')
        part_meta = folder / 'partial.json'
        last_error = None
        for attempt in range(retries + 1):
            try:
                current = probe(row['direct_url'])
                size = current['size_bytes']
                if size is not None and size > max_bytes:
                    raise ValueError('declared size exceeds explicit --max-mb')
                if shutil.disk_usage(folder).free < max_bytes + RESERVE_BYTES:
                    raise OSError('HOLD_DISK: insufficient free space plus safety reserve')
                previous = json.loads(part_meta.read_text()) if part_meta.exists() else {}
                if part.exists() and part.stat().st_size and not compatible_partial(previous, current):
                    stale = part.with_name(part.name + '.stale-' + sha256(part))
                    if stale.exists():
                        if sha256(stale) != sha256(part):
                            raise ValueError('stale partial collision')
                        part.unlink()
                    else:
                        part.rename(stale)
                    db.transition(key, 'FETCHING', detail={'event': 'STALE_PARTIAL_PRESERVED'})
                part_meta.write_text(json.dumps(current, indent=2) + '\n')
                existing = part.stat().st_size if part.exists() else 0
                headers = {}
                if existing:
                    headers['Range'] = f'bytes={existing}-'
                    validator = current.get('etag')
                    if not validator or validator.startswith('W/'):
                        validator = current.get('last_modified')
                    if validator:
                        headers['If-Range'] = validator
                started = time.monotonic()
                with open_https(row['direct_url'], headers=headers) as response:
                    transfer = snapshot(response)
                    append = bool(existing and response.status == 206)
                    if append:
                        match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', transfer['content_range'])
                        if not match or int(match[1]) != existing:
                            raise ValueError('invalid resume Content-Range')
                        if not compatible_partial(current, transfer):
                            raise ValueError('upstream changed between probe and Range GET')
                    elif response.status != 200:
                        raise ValueError('unexpected transfer status')
                    count = existing if append else 0
                    transfer_bytes = 0
                    with part.open('ab' if append else 'wb') as f:
                        while True:
                            block = response.read(64 * 1024)
                            if not block:
                                break
                            count += len(block)
                            transfer_bytes += len(block)
                            if count > max_bytes:
                                raise ValueError('stream exceeds explicit --max-mb')
                            f.write(block)
                            db.heartbeat(key)
                            delay = transfer_bytes / (rate_kbps * 1024) - (time.monotonic() - started)
                            if delay > 0:
                                time.sleep(delay)
                        f.flush()
                        os.fsync(f.fileno())
                    wanted = transfer['size_bytes']
                    if wanted is not None and count != wanted:
                        raise OSError(f'truncated response: {count} != {wanted}')
                actual = sha256(part)
                target = folder / actual / row['relative_filename']
                target.parent.mkdir(exist_ok=True)
                reused = target.exists()
                if reused:
                    if sha256(target) != actual:
                        raise ValueError('content-addressed object corrupted')
                    part.unlink()
                else:
                    part.rename(target)
                    target.chmod(0o444)
                record = {'asset_id': row['asset_id'], 'package_group_id': row['package_group_id'],
                          'requested_url': row['direct_url'],
                          'official_source_url': row.get('official_source_url') or row['direct_url'],
                          'transport_role': row.get('transport_role', 'OFFICIAL'), 'http': transfer,
                          'probe': current, 'bytes': target.stat().st_size, 'observed_sha256': actual,
                          'upstream_commit': row.get('upstream_commit') or None,
                          'release_tag': row.get('release_tag') or None,
                          'rights': rights, 'expected_sha256': expected or None, 'downloaded_at_utc': now(),
                          'acquisition_state': 'QUARANTINED', 'admitted': False}
                sidecar = target.parent / 'download.json'
                if not sidecar.exists():
                    immutable_json(sidecar, record)
                else:
                    immutable_json(target.parent / ('retrieval-' + hashlib.sha256(
                        json.dumps(record, sort_keys=True).encode()).hexdigest() + '.json'), record)
                temp = folder / 'latest.json.tmp'
                temp.write_text(json.dumps({'sha256': actual}) + '\n')
                temp.replace(folder / 'latest.json')
                db.artifact(row['asset_id'], actual, target)
                db.transition(key, 'DOWNLOADED', digest=actual, evidence=[str(sidecar)],
                              detail={'reused_digest': reused, 'bytes': target.stat().st_size})
                return target
            except (urllib.error.HTTPError, urllib.error.URLError, OSError) as e:
                last_error = e
                retryable = not isinstance(e, urllib.error.HTTPError) or e.code in (408, 429, 500, 502, 503, 504)
                db.transition(key, 'FETCHING', retry=bool(retryable and attempt < retries), exit_code=1,
                              detail={'error': f'{type(e).__name__}: {e}', 'attempt': attempt + 1})
                if not retryable or 'HOLD_DISK' in str(e) or attempt == retries:
                    raise
                time.sleep(min(2 ** attempt, 16))
        raise last_error or RuntimeError('transfer failed')
    except BaseException as e:
        state = 'HOLD_LICENSE' if isinstance(e, PermissionError) else 'HOLD_DISK' if 'HOLD_DISK' in str(e) else 'HOLD_SOURCE'
        db.transition(key, state, exit_code=130 if isinstance(e, KeyboardInterrupt) else 1,
                      detail={'error': f'{type(e).__name__}: {e}'})
        raise
    finally:
        if own_db:
            db.close()


def verify(row, out, *, db=None):
    target = get_target(row, out)
    if not target.is_file():
        return {'asset_id': row['asset_id'], 'state': 'NOT_DOWNLOADED', 'admitted': False}
    actual = sha256(target)
    expected = row.get('sha256_expected', '').strip().lower()
    match = actual == target.parent.name and (not expected or expected == actual)
    result = {'asset_id': row['asset_id'], 'state': 'CHECKSUM_FAIL' if not match else
              'CHECKSUM_MATCH_QUARANTINED' if expected else 'HASHED_UNPINNED_QUARANTINED',
              'sha256': actual, 'size_bytes': target.stat().st_size, 'admitted': False,
              'expected_sha256_pinned': bool(expected),
              'sha256_pin_basis': row.get('sha256_pin_basis') or 'CALLER_MANIFEST_NOT_UPSTREAM_ATTESTATION'}
    if match:
        sums = target.parent / 'sha256sum.txt'
        text = f'{actual}  {target.name}\n'
        if sums.exists() and sums.read_text() != text:
            raise ValueError('immutable checksum record conflict')
        if not sums.exists():
            with sums.open('x') as f:
                f.write(text)
            sums.chmod(0o444)
        provenance = json.loads((target.parent / 'download.json').read_text())
        provenance.update({'sha256': actual, 'hash_algorithm': 'SHA-256',
                           'raw_filename': target.name, 'expected_sha256': provenance.get('expected_sha256')})
        immutable_json(target.parent / 'provenance.json', provenance)
        immutable_json(target.parent / ('verification-' + (expected or 'unpinned') + '.json'),
            {'sha256': actual, 'bytes': target.stat().st_size, 'expected_sha256': expected or None,
             'pin_basis': 'caller manifest assertion, not upstream attestation', 'admitted': False})
        if db:
            key = db.ensure(row)
            old = db.job(key)['stage']
            if old == 'DOWNLOADED':
                db.transition(key, 'HASHED', digest=actual,
                              evidence=[str(target.parent / 'provenance.json'), str(sums)])
            elif old.startswith(('HOLD_', 'EXCLUDED_')) and db.job(key)['artifact_sha256'] == actual:
                # Byte verification is independent of scientific/rights holds.
                # Preserve the hold; never regress to HASHED or imply admission.
                db.transition(key, old, digest=actual, detail={'event':'BYTES_REVERIFIED_UNDER_EXISTING_DISPOSITION'})
            elif old not in STAGES or STAGES.index(old) < STAGES.index('HASHED'):
                raise ValueError('SQLite state must be reconciled before verify')
    elif db:
        db.transition(db.ensure(row), 'HOLD_HASH', digest=actual, exit_code=2,
                      detail={'error': 'checksum mismatch'})
    return result


def safe_member(name, root):
    if '\\' in name or ':' in name or '\x00' in name:
        raise ValueError('unsafe archive member')
    p = PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or not p.parts:
        raise ValueError('archive traversal')
    dest = root.joinpath(*p.parts)
    if not dest.resolve().is_relative_to(root.resolve()):
        raise ValueError('archive symlink escape')
    return dest


def safe_extract(archive, output, *, max_bytes=64 * 1024 * 1024,
                 max_files=10000, max_ratio=1000, member_allowlist=None):
    """Extract only regular files/directories, with preflight AND streaming budgets.

    Caller supplies a NEW empty quarantine directory. Failed extractions remain
    visibly incomplete; no derived/approved data is generated by this function.
    """
    archive, output = Path(archive), Path(output)
    if output.exists():
        raise ValueError('extraction output must not exist')
    if max_bytes <= 0 or max_files <= 0:
        raise ValueError('invalid extraction budget')
    output.mkdir(parents=True)
    total = 0
    members_seen = set()
    manifest = []

    def write_member(name, size, source):
        nonlocal total
        dest = safe_member(name, output)
        if name in members_seen or dest.exists():
            raise ValueError('duplicate archive member')
        members_seen.add(name)
        if len(members_seen) > max_files or total + size > max_bytes:
            raise ValueError('archive extraction budget exceeded')
        if (total + size) > max(1, archive.stat().st_size) * max_ratio:
            raise ValueError('archive compression ratio exceeded')
        dest.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with dest.open('xb') as f:
            while True:
                b = source.read(64 * 1024)
                if not b:
                    break
                count += len(b)
                total += len(b)
                if total > max_bytes or count > size:
                    raise ValueError('archive streaming budget exceeded')
                f.write(b)
        if count != size:
            raise ValueError('archive member truncated')
        dest.chmod(0o444)
        manifest.append({'path': name, 'bytes': size, 'sha256': sha256(dest)})

    try:
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as z:
                if len(z.infolist()) > max_files:
                    raise ValueError('too many archive members')
                for member in z.infolist():
                    safe_member(member.filename, output)
                    if member_allowlist is not None and member.filename not in member_allowlist:
                        continue
                    mode = member.external_attr >> 16
                    kind = stat.S_IFMT(mode)
                    if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                        raise ValueError('zip links and special files refused')
                    if member.flag_bits & 1:
                        raise ValueError('encrypted archives refused')
                    if member.is_dir():
                        safe_member(member.filename, output).mkdir(parents=True, exist_ok=True)
                    else:
                        with z.open(member) as src:
                            write_member(member.filename, member.file_size, src)
        else:
            with tarfile.open(archive, 'r:*') as t:
                for i, member in enumerate(t, 1):
                    if i > max_files:
                        raise ValueError('too many archive members')
                    dest = safe_member(member.name, output)
                    if member_allowlist is not None and member.name not in member_allowlist:
                        continue
                    if member.isdir():
                        dest.mkdir(parents=True, exist_ok=True)
                    elif member.isfile():
                        with contextlib.closing(t.extractfile(member)) as src:
                            write_member(member.name, member.size, src)
                    else:
                        raise ValueError('tar links and special files refused')
        if member_allowlist is not None and {m['path'] for m in manifest} != set(member_allowlist):
            raise ValueError('allowlisted archive members missing')
        immutable_json(output / 'extraction_manifest.json', {'state': 'QUARANTINED',
                       'archive_sha256': sha256(archive), 'files': manifest,
                       'bytes': total, 'admitted': False})
        return manifest
    except BaseException as e:
        immutable_json(output / 'EXTRACTION_FAILED.json', {'error': type(e).__name__,
                       'complete': False, 'admitted': False})
        raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['plan', 'probe', 'download', 'verify', 'status', 'extract'])
    p.add_argument('--asset', action='append', default=[])
    p.add_argument('--manifest', type=Path, default=REGISTRY)
    p.add_argument('--out', type=Path, default=ROOT / 'raw_cache')
    p.add_argument('--state-db', type=Path, default=ROOT / 'run-state.sqlite')
    p.add_argument('--rights', type=Path, default=ROOT / 'data/audit/rights_decisions.json')
    p.add_argument('--execute', action='store_true')
    p.add_argument('--extract-allowlist', type=Path)
    p.add_argument('--extract-subdir', default='unpacked')
    p.add_argument('--allow-unpinned', action='store_true')
    p.add_argument('--refresh', action='store_true')
    p.add_argument('--max-mb', type=int, default=16)
    p.add_argument('--rate-kbps', type=int, default=512)
    p.add_argument('--retries', type=int, default=2)
    args = p.parse_args()
    rows = read_manifest(args.manifest)
    selected = args.asset or list(rows)
    if any(a not in rows for a in selected):
        p.error('unknown asset')
    if args.command in ('download', 'probe', 'extract') and (not args.asset or not args.execute):
        p.error('explicit --asset and --execute required; no implicit batch transfer')
    if args.max_mb <= 0:
        p.error('--max-mb must be positive')
    decisions = json.loads(args.rights.read_text()) if args.rights.exists() else {}
    failures = 0
    with StateDB(args.state_db) as db:
        for aid in selected:
            row = rows[aid]
            try:
                if args.command == 'plan':
                    result = {**row, 'state': 'PLAN_ONLY', 'admitted': False}
                elif args.command == 'download':
                    target = fetch(row, args.out, args.max_mb * 1024 * 1024,
                                   args.allow_unpinned, db=db, decisions=decisions,
                                   retries=args.retries, rate_kbps=args.rate_kbps,
                                   refresh=args.refresh)
                    result = {'asset_id': aid, 'state': 'DOWNLOADED_QUARANTINED',
                              'path': str(target), 'admitted': False}
                elif args.command == 'verify':
                    result = verify(row, args.out, db=db)
                    if result['state'] in ('CHECKSUM_FAIL', 'NOT_DOWNLOADED'):
                        failures += 1
                elif args.command == 'probe':
                    result = {'asset_id': aid, 'state': 'PROBE_ONLY', **probe(row['direct_url'])}
                    db.transition(db.ensure(row), db.job(db.ensure(row))['stage'], detail=result)
                elif args.command == 'extract':
                    target = get_target(row, args.out)
                    if verify(row, args.out, db=db)['state'] in ('CHECKSUM_FAIL', 'NOT_DOWNLOADED'):
                        raise ValueError('verified raw bytes required before extraction')
                    if not re.fullmatch('[A-Za-z0-9_-]+', args.extract_subdir):
                        raise ValueError('unsafe extraction subdir')
                    output = target.parent / args.extract_subdir
                    if not output.resolve().is_relative_to(target.parent.resolve()):
                        raise ValueError('extraction output symlink escape')
                    allow = set(json.loads(args.extract_allowlist.read_text())) if args.extract_allowlist else None
                    existing = output / 'extraction_manifest.json'
                    if existing.exists():
                        doc = json.loads(existing.read_text())
                        if doc['archive_sha256'] != sha256(target):
                            raise ValueError('extraction archive hash changed')
                        files = doc['files']
                        if allow is not None and set(x['path'] for x in files) != allow:
                            raise ValueError('extraction allowlist changed')
                        for item in files:
                            if sha256(safe_member(item['path'], output)) != item['sha256']:
                                raise ValueError('extracted file hash mismatch')
                    else:
                        files = safe_extract(target, output, max_bytes=args.max_mb * 1024 * 1024, member_allowlist=allow)
                    result = {'asset_id': aid, 'state': 'EXTRACTED_QUARANTINED',
                              'files': len(files), 'admitted': False}
                else:
                    key = db.ensure(row)
                    result = {'asset_id': aid, 'job': db.job(key), 'bytes': verify(row, args.out)}
                print(json.dumps(result, ensure_ascii=False))
            except (OSError, ValueError, PermissionError, urllib.error.URLError, sqlite3.Error) as e:
                failures += 1
                print(json.dumps({'asset_id': aid, 'state': 'FAILED',
                                  'error': f'{type(e).__name__}: {e}', 'admitted': False}))
    raise SystemExit(1 if failures else 0)


if __name__ == '__main__':
    main()
