import importlib.util
import io
import json
import stat
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('manager', ROOT / 'tools/rnagym.py')
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.row = {'asset_id': 'A_TEST', 'package_group_id': 'TEST',
                    'relative_filename': 'test.csv', 'sha256_expected': '',
                    'direct_url': 'https://raw.githubusercontent.com/test/test/main/test.csv'}
        self.db = d.StateDB(self.root / 'state.sqlite')

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_state_idempotent_and_no_auto_admission(self):
        key = self.db.ensure(self.row)
        self.assertEqual(key, self.db.ensure(self.row))
        for stage in d.STAGES[1:-1]:
            self.db.transition(key, stage)
        with self.assertRaises(PermissionError):
            self.db.transition(key, 'ADMITTED')
        self.assertEqual(self.db.job(key)['stage'], 'REVIEW_READY')

    def test_cannot_skip_qc(self):
        key = self.db.ensure(self.row)
        with self.assertRaises(ValueError):
            self.db.transition(key, 'QC_PASS')

    def test_rights_fail_closed(self):
        with self.assertRaises(PermissionError):
            d.fetch(self.row, self.root, 100, True, db=self.db)
        self.assertEqual(self.db.job(self.db.ensure(self.row))['stage'], 'HOLD_LICENSE')

    def test_unpinned_still_requires_optin(self):
        rights = {self.row['asset_id']: {'decision': 'ALLOW_PUBLIC_QUARANTINE_POC',
                  'evidence_url': 'https://example.org/license', 'evidence_sha256': 'a' * 64}}
        with self.assertRaises(ValueError):
            d.fetch(self.row, self.root, 100, False, db=self.db, decisions=rights)

    def test_urls_and_paths(self):
        for url in ['http://github.com/test', 'https://evil.test/data',
                    'https://github.com/data?token=secret', 'https://user:pw@github.com/a']:
            with self.assertRaises(ValueError):
                d.validate_url(url)
        self.row['package_group_id'] = '../outside'
        with self.assertRaises(ValueError):
            d.asset_dir(self.row, self.root)

    def test_signed_cdn_only_on_redirect_and_no_tokens_logged(self):
        url = 'https://cas-bridge.xethub.hf.co/blob?Signature=ephemeral&Expires=123'
        with self.assertRaises(ValueError):
            d.validate_url(url)
        d.validate_url(url, signed_redirect=True)
        with self.assertRaises(ValueError):
            d.validate_url('https://cas-bridge.xethub.hf.co/blob?token=secret', signed_redirect=True)
        response = type('R', (), {'headers': {}, 'url': url, 'status': 200})()
        self.assertNotIn('ephemeral', d.snapshot(response)['final_url'])
        self.assertTrue(d.snapshot(response)['ephemeral_query_redacted'])

    def test_etag_resume_validation(self):
        a = {'etag': '"a"', 'size_bytes': 100}
        self.assertTrue(d.compatible_partial(a, a))
        self.assertFalse(d.compatible_partial(a, {'etag': '"b"', 'size_bytes': 100}))
        self.assertFalse(d.compatible_partial({}, {}))

    def test_immutable_evidence(self):
        f = self.root / 'evidence.json'
        d.immutable_json(f, {'a': 1})
        d.immutable_json(f, {'a': 1})
        with self.assertRaises(ValueError):
            d.immutable_json(f, {'a': 2})

    def make_zip(self, name, content=b'data', mode=None):
        path = self.root / 'test.zip'
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
            info = zipfile.ZipInfo(name)
            if mode:
                info.external_attr = mode << 16
            z.writestr(info, content)
        return path

    def test_zip_traversal(self):
        for i, name in enumerate(['../escape', '/absolute', 'a\\..\\escape', 'C:/escape']):
            with self.assertRaises(ValueError):
                d.safe_extract(self.make_zip(name), self.root / f'out{i}')

    def test_zip_link(self):
        with self.assertRaises(ValueError):
            d.safe_extract(self.make_zip('link', mode=stat.S_IFLNK | 0o777), self.root / 'out')

    def test_zip_bomb_budget(self):
        with self.assertRaises(ValueError):
            d.safe_extract(self.make_zip('big', b'x' * 10000), self.root / 'out', max_bytes=100)

    def test_tar_link(self):
        path = self.root / 'test.tar'
        with tarfile.open(path, 'w') as t:
            member = tarfile.TarInfo('link')
            member.type = tarfile.LNKTYPE
            member.linkname = '/etc/passwd'
            t.addfile(member)
        with self.assertRaises(ValueError):
            d.safe_extract(path, self.root / 'out')

    def test_safe_extract_and_no_overwrite(self):
        path = self.make_zip('dir/test.csv')
        out = self.root / 'out'
        result = d.safe_extract(path, out)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['sha256'], d.sha256(out / 'dir/test.csv'))
        with self.assertRaises(ValueError):
            d.safe_extract(path, out)

    def test_recover_interrupted_state_commit_without_redownload(self):
        class Response(io.BytesIO):
            status = 200
            url = self.row['direct_url']
            headers = {'Content-Length': '4', 'ETag': '"v1"'}
        rights = {self.row['asset_id']: {'decision':'ALLOW_PUBLIC_QUARANTINE_POC',
                  'evidence_url':'https://example.org/license','evidence_sha256':'a'*64}}
        with patch.object(d,'open_https',side_effect=lambda *a,**k: Response(b'data')):
            target=d.fetch(self.row,self.root,100,True,db=self.db,decisions=rights)
        key=self.db.ensure(self.row)
        self.db.transition(key,'FETCHING',detail={'event':'simulated interrupted final commit'})
        with patch.object(d,'open_https',side_effect=AssertionError('redownload refused')):
            self.assertEqual(d.fetch(self.row,self.root,100,True,db=self.db,decisions=rights),target)
        self.assertEqual(self.db.job(key)['stage'],'DOWNLOADED')
        self.assertEqual(d.verify(self.row,self.root,db=self.db)['state'],'HASHED_UNPINNED_QUARANTINED')

    def test_refresh_keeps_both_content_versions(self):
        class Response(io.BytesIO):
            status = 200
            url = self.row['direct_url']
            headers = {'Content-Length': '4','ETag':'"v1"'}
        rights={self.row['asset_id']:{'decision':'ALLOW_PUBLIC_QUARANTINE_POC',
                'evidence_url':'https://example.org/license','evidence_sha256':'a'*64}}
        with patch.object(d,'open_https',side_effect=lambda *a,**k:Response(b'data')):
            old=d.fetch(self.row,self.root,100,True,db=self.db,decisions=rights)
        d.verify(self.row,self.root,db=self.db)
        with patch.object(d,'open_https',side_effect=lambda *a,**k:Response(b'new!')):
            new=d.fetch(self.row,self.root,100,True,db=self.db,decisions=rights,refresh=True)
        self.assertNotEqual(old,new)
        self.assertEqual(old.read_bytes(),b'data')
        self.assertEqual(new.read_bytes(),b'new!')
        self.assertEqual(self.db.db.execute('SELECT COUNT(*) FROM artifacts').fetchone()[0],2)

    def test_missing_allowlisted_member_fails_explicitly(self):
        with self.assertRaisesRegex(ValueError,'allowlisted'):
            d.safe_extract(self.make_zip('present'),self.root/'out',member_allowlist={'missing'})
        self.assertTrue((self.root/'out/EXTRACTION_FAILED.json').exists())
        self.assertFalse((self.root/'out/extraction_manifest.json').exists())

    def test_actual_transfer_and_hash_separate_stages(self):
        class Response(io.BytesIO):
            status = 200
            url = self.row['direct_url']
            headers = {'Content-Length': '4', 'ETag': '"v1"'}
        rights = {self.row['asset_id']: {'decision': 'ALLOW_PUBLIC_QUARANTINE_POC',
                  'evidence_url': 'https://example.org/license', 'evidence_sha256': 'a' * 64}}
        with patch.object(d, 'open_https', side_effect=lambda *a, **k: Response(b'data')):
            target = d.fetch(self.row, self.root, 100, True, db=self.db, decisions=rights)
        self.assertEqual(self.db.job(self.db.ensure(self.row))['stage'], 'DOWNLOADED')
        self.assertEqual(d.verify(self.row, self.root, db=self.db)['state'],
                         'HASHED_UNPINNED_QUARANTINED')
        self.assertEqual(self.db.job(self.db.ensure(self.row))['stage'], 'HASHED')
        self.assertTrue((target.parent / 'sha256sum.txt').is_file())
        self.db.transition(self.db.ensure(self.row), 'HOLD_QC', detail={'scope':'test scientific hold'})
        self.assertEqual(d.verify(self.row,self.root,db=self.db)['state'],'HASHED_UNPINNED_QUARANTINED')
        self.assertEqual(self.db.job(self.db.ensure(self.row))['stage'],'HOLD_QC')
        self.db.transition(self.db.ensure(self.row),'FETCHING')
        self.db.transition(self.db.ensure(self.row),'DOWNLOADED')
        d.verify(self.row,self.root,db=self.db)
        with patch.object(d, 'open_https', side_effect=AssertionError('must reuse hash')):
            self.assertEqual(d.fetch(self.row, self.root, 100, True,
                                     db=self.db, decisions=rights), target)


if __name__ == '__main__':
    unittest.main()
