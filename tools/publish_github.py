#!/usr/bin/env python3
"""Publish a sanitized candidate using a token read with terminal echo disabled.

The credential is passed ONLY in child-process environment memory, never as a
command argument, stored credential or remote URL. Never pipe a token into a
logged shell command. No GitHub auth login/config write is performed.
"""
import argparse
import getpass
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from rnagym import ROOT, now


def run(cmd, *, cwd, env, ok=(0,)):
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=240)
    # Only nonsecret structured output is ever printed by this script.
    if p.returncode not in ok:
        message = p.stderr[-1500:]
        token = env.get('GH_TOKEN', '')
        if token:
            message = message.replace(token, '[REDACTED]')
        raise RuntimeError(f'{cmd[0]} failed ({p.returncode}): {message}')
    return p


def publish(candidate, owner, name, report_path):
    if not candidate.is_dir() or not (candidate / 'PUBLIC_FILE_MANIFEST.json').is_file():
        raise ValueError('sanitized candidate with PUBLIC_FILE_MANIFEST required')
    if not candidate.resolve().is_relative_to(ROOT / 'runs'):
        raise ValueError('candidate must be inside local runs/')
    if not shutil.which('gh'):
        raise RuntimeError('BLOCKED_GITHUB_AUTH: gh not installed')
    if not re.fullmatch('[A-Za-z0-9-]+', owner) or not re.fullmatch('[A-Za-z0-9_.-]+', name):
        raise ValueError('invalid owner/repo')
    # Validate files before reading any secret and before creating remote state.
    manifest = json.loads((candidate / 'PUBLIC_FILE_MANIFEST.json').read_text())
    intended = {f['path'] for f in manifest['files']} | {'PUBLIC_FILE_MANIFEST.json'}
    actual = {str(p.relative_to(candidate)) for p in candidate.rglob('*') if p.is_file() and '.git' not in p.relative_to(candidate).parts}
    if actual != intended:
        raise ValueError('candidate contains unmanifested or missing files')
    for row in manifest['files']:
        if hashlib.sha256((candidate / row['path']).read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('candidate changed after public scan')
    token = getpass.getpass('GitHub token (not stored; terminal echo disabled): ')
    if not token:
        raise ValueError('missing credential')
    env = dict(os.environ)
    env.update({'GH_TOKEN': token, 'GIT_TERMINAL_PROMPT': '0', 'GH_PROMPT_DISABLED': '1'})
    report = {'state': 'PUBLISHING', 'owner': owner, 'repository': name,
              'started_at_utc': now(), 'repo_url': None, 'pages_url': None,
              'ci_green': False, 'raw_data_uploaded': False, 'token_stored': False}
    try:
        auth = run(['gh', 'auth', 'status'], cwd=candidate, env=env, ok=(0, 1))
        user = json.loads(run(['gh', 'api', 'user'], cwd=candidate, env=env).stdout)
        login = user.get('login')
        print(json.dumps({'verified_login': login, 'requested_owner': owner,
                          'gh_auth_status_exit_code': auth.returncode}), flush=True)
        if login is None or login.lower() != owner.lower():
            raise PermissionError('GitHub owner mismatch; no repository or push attempted')
        report['verified_login'] = login
        repo = owner + '/' + name
        existing = run(['gh', 'api', 'repos/' + repo], cwd=candidate, env=env, ok=(0, 1))
        if existing.returncode == 0:
            # Do not overwrite an existing project or force-push under any circumstances.
            raise RuntimeError('Target repository already exists. Inspect history and prepare a PR instead; no push attempted.')
        # Distinguish 404 from permissions/network errors with a public lookup.
        lookup = run(['gh', 'api', '--include', 'repos/' + repo], cwd=candidate, env=env, ok=(0, 1))
        if '404' not in lookup.stdout and '404' not in lookup.stderr:
            raise RuntimeError('Repository absence not verified; creation refused')
        clean_env = {k:v for k,v in env.items() if k not in ('GH_TOKEN', 'GITHUB_TOKEN')}
        if not (candidate / '.git').exists():
            run(['git', 'init', '-b', 'main'], cwd=candidate, env=clean_env)
        run(['git', 'config', 'user.name', 'RNA-Gym audit automation'], cwd=candidate, env=clean_env)
        run(['git', 'config', 'user.email', 'rna-gym-audit@users.noreply.github.com'], cwd=candidate, env=clean_env)
        run(['git', 'add', '--all'], cwd=candidate, env=clean_env)
        staged = run(['git', 'ls-files'], cwd=candidate, env=clean_env).stdout.splitlines()
        if set(staged) != intended:
            raise ValueError('git staged files differ from audited allowlist')
        status = run(['git', 'status', '--short'], cwd=candidate, env=clean_env)
        print(json.dumps({'dry_run_files': len(staged), 'dirty_expected': bool(status.stdout),
                          'secret_scan': manifest['secret_scan']}), flush=True)
        run(['git', 'commit', '-m', 'Initial metadata-only audit preview and bounded acquisition tools'], cwd=candidate, env=clean_env)
        # Create without --push so credential handling can be constrained explicitly.
        run(['gh', 'repo', 'create', repo, '--public', '--source', '.', '--remote', 'origin',
             '--description', 'Transparent RNA benchmark registry: source provenance, task download plans and audit preview; no raw data or scores'],
            cwd=candidate, env=env)
        report['repo_url'] = 'https://github.com/' + repo
        run(['git', 'remote', 'set-url', 'origin', 'https://github.com/' + repo + '.git'], cwd=candidate, env=clean_env)
        run(['git', '-c', 'credential.helper=', '-c',
             'credential.helper=!gh auth git-credential', 'push', '-u', 'origin', 'main'],
            cwd=candidate, env=env)
        report['commit_sha'] = run(['git', 'rev-parse', 'HEAD'], cwd=candidate, env=clean_env).stdout.strip()
        report['state'] = 'REPOSITORY_PUSHED_PAGES_PENDING'
        report_path.write_text(json.dumps(report, indent=2) + '\n')
        # Configure Actions Pages only in the verified, newly created repository.
        pages = run(['gh', 'api', '--method', 'POST', 'repos/' + repo + '/pages',
                     '-f', 'build_type=workflow'], cwd=candidate, env=env, ok=(0, 1))
        if pages.returncode:
            report['pages_config_state'] = 'HOLD_PAGES_PERMISSION_OR_CONFIGURATION'
        else:
            report['pages_config_state'] = 'ACTIONS_ENABLED'
        run(['gh', 'workflow', 'run', 'pages.yml', '--repo', repo, '--ref', 'main'],
            cwd=candidate, env=env, ok=(0, 1))
        for attempt in range(18):
            p = run(['gh', 'run', 'list', '--repo', repo, '--workflow', 'pages.yml', '--limit', '3',
                     '--json', 'databaseId,status,conclusion,url,headSha'], cwd=candidate, env=env)
            jobs = [r for r in json.loads(p.stdout) if r['headSha'] == report['commit_sha']]
            if jobs:
                job = jobs[0]
                report['workflow_run_url'] = job['url']
                report['workflow_status'] = job['status']
                report['workflow_conclusion'] = job['conclusion']
                if job['status'] == 'completed':
                    report['ci_green'] = job['conclusion'] == 'success'
                    report['state'] = 'PUBLISHED_CI_GREEN' if report['ci_green'] else 'PUSHED_CI_FAILED'
                    break
            time.sleep(10)
        page = run(['gh', 'api', 'repos/' + repo + '/pages'], cwd=candidate, env=env, ok=(0, 1))
        if page.returncode == 0:
            page_data = json.loads(page.stdout)
            report['configured_pages_url'] = page_data.get('html_url')
            if report['ci_green']:
                report['pages_url'] = page_data.get('html_url')
        report['site_data_sha256'] = hashlib.sha256((candidate / 'site/data/summary.json').read_bytes()).hexdigest()
        report['finished_at_utc'] = now()
        report_path.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2), flush=True)
        # No credential config was written. Remove in-memory child credential references.
    except Exception as e:
        report['state'] = 'HOLD_GITHUB_PUBLICATION'
        report['error'] = str(e).replace(token, '[REDACTED]')
        report_path.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2), flush=True)
        raise SystemExit(1)
    finally:
        env.pop('GH_TOKEN', None)
        token = None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate', type=Path, required=True)
    p.add_argument('--owner', required=True)
    p.add_argument('--name', default='RNA-GYM')
    p.add_argument('--report', type=Path, required=True)
    args = p.parse_args()
    publish(args.candidate.resolve(), args.owner, args.name, args.report)


if __name__ == '__main__':
    main()
