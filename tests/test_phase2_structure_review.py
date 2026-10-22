"""Synthetic adversarial CIFs plus optional already-cached, pinned real members.

No download, upstream code execution, raw archive scan, GPU or atom rewriting.
"""
import hashlib
import io
import json
import lzma
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from phase2_structure_review import (BoundedXZ, BudgetExceeded, LIMITS, OUTPUT,
    extract_prefix, geometry_screen, metadata_review, review_cif)

try:
    import gemmi
    import numpy
    HAVE_CIF = True
except ImportError:
    HAVE_CIF = False


def fixture(extra=None, occupancy='1.0'):
    """Entirely synthetic; serials intentionally reused between residues."""
    rows = [
        ('P', 'P', 1, (0, 0, 0)), ('OP1', 'O', 1, (1.5, 0, 0)),
        ("O5'", 'O', 1, (0, 1.6, 0)), ("C5'", 'C', 1, (0, 3.0, 0)),
        ("C3'", 'C', 1, (4, 4, 4)), ("O3'", 'O', 1, (4, 5.4, 4)),
        ('P', 'P', 2, (4, 7, 4)), ('OP1', 'O', 2, (5.5, 7, 4)),
        ("O5'", 'O', 2, (4, 8.6, 4)), ("C5'", 'C', 2, (4, 10, 4))]
    if extra:
        rows.extend(extra)
    head = '''data_synthetic
_entry.id 1abc_A
_exptl.method 'X-RAY DIFFRACTION'
loop_
_entity_poly.entity_id
_entity_poly.type
1 polyribonucleotide
loop_
_entity_poly_seq.entity_id
_entity_poly_seq.num
_entity_poly_seq.mon_id
1 1 A
1 2 A
1 3 U
loop_
_pdbx_unobs_or_zero_occ_residues.id
_pdbx_unobs_or_zero_occ_residues.PDB_model_num
_pdbx_unobs_or_zero_occ_residues.auth_asym_id
_pdbx_unobs_or_zero_occ_residues.auth_seq_id
1 1 A 3
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_alt_id
_atom_site.label_comp_id
_atom_site.label_asym_id
_atom_site.label_entity_id
_atom_site.label_seq_id
_atom_site.pdbx_PDB_ins_code
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.occupancy
_atom_site.auth_seq_id
_atom_site.auth_asym_id
_atom_site.pdbx_PDB_model_num
'''
    lines = [f'ATOM 1 {element} "{name}" . A A 1 {res} ? {xyz[0]} {xyz[1]} {xyz[2]} {occupancy} {res} A 1'
             for name, element, res, xyz in rows]
    return (head + '\n'.join(lines) + '\n').encode()


class BoundedStreamTests(unittest.TestCase):
    def test_expansion_hard_limit(self):
        limits = dict(LIMITS, decompressed_bytes=1024)
        reader = BoundedXZ(io.BytesIO(lzma.compress(b'A' * (2*1024*1024))), limits)
        self.assertEqual(reader.read(1024), b'A'*1024)
        with self.assertRaises(BudgetExceeded):
            reader.read(1)
        self.assertEqual(reader.decompressed_bytes, 1024)

    def test_input_hard_limit(self):
        limits = dict(LIMITS, compressed_bytes=1)
        reader = BoundedXZ(io.BytesIO(lzma.compress(b'hello')), limits)
        with self.assertRaises(BudgetExceeded):
            reader.read(1024)
        self.assertEqual(reader.compressed_bytes, 1)

    def make_archive(self, root, *, link=False):
        target = root/'small.tar.xz'
        data = fixture()
        with tarfile.open(target, 'w:xz') as archive:
            if link:
                member = tarfile.TarInfo('link.cif')
                member.type = tarfile.SYMTYPE
                member.linkname = '/etc/passwd'
                archive.addfile(member)
            member = tarfile.TarInfo('a/sample.cif')
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
            # A large trailing expansion must never be consumed to get the sample.
            member = tarfile.TarInfo('large-trailing.txt')
            member.size = 2 * 1024 * 1024
            archive.addfile(member, io.BytesIO(b'Z'*member.size))
        return target, [{'member': 'a/sample.cif', 'member_sha256': hashlib.sha256(data).hexdigest()}]

    def test_prefix_and_cache_reuse_without_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw, pins = self.make_archive(root)
            samples, stats = extract_prefix(raw, pins, root/'cache')
            self.assertEqual(len(samples), 1)
            self.assertFalse(stats['full_archive_scanned'])
            self.assertLess(stats['decompressed_bytes_read'], 100000)
            raw.unlink()  # Test temporary artifact only; not the project raw cache.
            again, stats = extract_prefix(raw, pins, root/'cache')
            self.assertEqual(again[0]['member_sha256'], pins[0]['member_sha256'])
            self.assertEqual(stats['compressed_bytes_read'], 0)

    def test_links_refused_without_following(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw, pins = self.make_archive(root, link=True)
            samples, stats = extract_prefix(raw, pins, root/'cache')
            self.assertFalse(samples)
            self.assertIn('symlink', stats['blocked_reason'])

    def test_hash_mismatch_not_cached(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw, pins = self.make_archive(root)
            pins[0]['member_sha256'] = '0'*64
            samples, stats = extract_prefix(raw, pins, root/'cache')
            self.assertFalse(samples)
            self.assertIn('content hash', stats['blocked_reason'])

    def test_budget_blocks_missing_deep_member(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw, pins = self.make_archive(root)
            pins[0]['member'] = 'absent.cif'
            limits = dict(LIMITS, decompressed_bytes=4096)
            samples, stats = extract_prefix(raw, pins, root/'cache', limits)
            self.assertFalse(samples)
            self.assertIn('budget', stats['blocked_reason'])
            self.assertLessEqual(stats['decompressed_bytes_read'], 4096)


class MetadataTests(unittest.TestCase):
    def test_nested_representatives_not_chain_counts(self):
        a = {'sequence': 'ACGU', 'length': 4}
        b = {'sequence': 'ACGT', 'length': 4}
        train = {'component_1': {'1abc_A': {'1abc_A': a, '1abc_B': a}}}
        test = {'component_2': {'1abc_C': {'1abc_C': b}}}
        docs = {'parse.json': {'1abc_A': a, '1abc_B': a, '1abc_C': b},
                'filter.json': {'1abc_A': a, '1abc_B': a, '1abc_C': b},
                'cluster.json': dict(train, **test),
                'split.json': {'train': train, 'test': test}}
        report, mapping = metadata_review(docs, 'synthetic')
        self.assertEqual(report['split_counts']['train']['actual_chain_count'], 2)
        self.assertEqual(report['split_counts']['train']['sequence_cluster_count'], 1)
        self.assertEqual(report['overlaps'][0]['shared_structure_count'], 1)
        self.assertEqual(report['overlaps'][0]['shared_chain_count'], 0)
        self.assertEqual(report['overlaps'][0]['shared_exact_sequence_count'], 0)  # No T/U collapsing.
        self.assertEqual(len(mapping), 3)
        self.assertFalse(report['admitted'])


@unittest.skipUnless(HAVE_CIF, 'gemmi/numpy are optional; use .venv-qc for CIF review')
class CifReviewTests(unittest.TestCase):
    def test_reused_serial_retains_every_atom_and_missing_loop(self):
        report = review_cif(fixture(), 'synthetic.cif')
        self.assertEqual(report['identity_reused_from_qc_atom_identity']['reused_serial_numbers'], 9)
        self.assertEqual(report['identity_reused_from_qc_atom_identity']['duplicate_composite_atom_rows'], 0)
        self.assertEqual(report['atom_rows_removed'], 0)
        self.assertEqual(report['missing_residue_and_polymer_loops']['_pdbx_unobs_or_zero_occ_residues.']['rows'], 1)
        self.assertFalse(report['geometry']['full_stereochemistry_pass'])
        self.assertFalse(report['admitted'])

    def test_known_bonds_and_strict_inter_residue_overlap(self):
        clean = review_cif(fixture(), 'clean.cif')
        self.assertEqual(clean['geometry']['inter_residue_nonbonded_severe_overlap_count'], 0)
        clash = review_cif(fixture([('N9', 'N', 2, (0.1, 0, 0))]), 'clash.cif')
        self.assertGreater(clash['geometry']['inter_residue_nonbonded_severe_overlap_count'], 0)
        self.assertEqual(clash['atom_rows_removed'], 0)

    def test_occupancy_not_silently_defaulted(self):
        unknown = review_cif(fixture(occupancy='?'), 'missing.cif')
        self.assertEqual(unknown['occupancy_counts']['missing_or_not_numeric'], 10)
        self.assertEqual(unknown['geometry']['spatial_atoms_not_eligible'], 10)
        invalid = review_cif(fixture(occupancy='1.4'), 'bad.cif')
        self.assertEqual(invalid['occupancy_counts']['outside_0_1'], 10)
        self.assertEqual(invalid['geometry']['spatial_atoms_not_eligible'], 10)

    def test_models_do_not_clash_and_altloc_atoms_not_deleted(self):
        text = fixture().decode()
        lines = text.splitlines()
        atom = next(line for line in lines if line.startswith('ATOM'))
        duplicate_model = atom.rsplit(' ', 1)[0] + ' 2'
        report = review_cif((text + duplicate_model + '\n').encode(), 'models.cif')
        self.assertEqual(report['schema_reused_from_qc_rna3db']['model_ids'], ['1', '2'])
        self.assertEqual(report['geometry']['inter_residue_nonbonded_severe_overlap_count'], 0)
        atom_alt = atom.replace(' . A A ', ' B A A ')
        report = review_cif((text + atom_alt + '\n').encode(), 'altloc.cif')
        self.assertEqual(report['schema_reused_from_qc_rna3db']['atom_rows'], 11)
        self.assertEqual(report['schema_reused_from_qc_rna3db']['altloc_atom_counts']['B'], 1)
        self.assertEqual(report['atom_rows_removed'], 0)

    def test_named_bond_outlier_is_a_warning_not_an_atom_filter(self):
        bad = fixture().replace(b'4 5.4 4', b'4 15.4 4')
        report = review_cif(bad, 'bond-outlier.cif')
        self.assertGreater(sum(v['outside_range_count'] for v in
                               report['geometry']['named_bond_distances'].values()), 0)
        self.assertEqual(report['atom_rows_removed'], 0)
        self.assertFalse(report['geometry']['full_stereochemistry_pass'])

    def test_strict_decoding_never_ignores_bad_bytes(self):
        with self.assertRaises(UnicodeDecodeError):
            review_cif(fixture() + b'\xff', 'invalid-encoding.cif')

    def test_spatial_pair_limit_does_not_report_complete(self):
        def atom(row, residue, altloc=''):
            key = ('1', 'A', 'A', str(residue), str(residue), '', 'A', 'N9', altloc)
            return {'row': row, 'key': key, 'residue_key': key[:7], 'model': '1',
                    'name': 'N9', 'altloc': altloc, 'xyz': (0, 0, 0),
                    'occupancy': 1.0, 'element': 'N'}
        report = geometry_screen([atom(0, 1), atom(1, 2)], pair_budget=0)
        self.assertFalse(report['spatial_screen_complete'])
        self.assertEqual(report['status'], 'BLOCKED_PAIR_BUDGET')
        report = geometry_screen([atom(0, 1, 'A'), atom(1, 2, 'B')])
        self.assertEqual(report['inter_residue_nonbonded_severe_overlap_count'], 0)
        report = geometry_screen([atom(0, 1), atom(1, 2, 'B')])
        self.assertEqual(report['inter_residue_nonbonded_severe_overlap_count'], 1)

    def test_nonfinite_geometry_refused(self):
        bad = fixture().replace(b'0 0 0 1.0', b'nan 0 0 1.0', 1)
        with self.assertRaisesRegex(ValueError, 'nonfinite'):
            review_cif(bad, 'bad.cif')

    def test_cached_real_members_without_archive_access(self):
        checkpoint = OUTPUT/'sample_extraction.json'
        if not checkpoint.is_file():
            self.skipTest('local bounded sample cache not built; no download attempted')
        samples = json.loads(checkpoint.read_text())['samples']
        self.assertEqual(len(samples), 3)
        for sample in samples:
            data = (OUTPUT/'cache'/sample['cache_file']).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), sample['member_sha256'])
            report = review_cif(data, sample['member'])
            self.assertEqual(report['identity_reused_from_qc_atom_identity']['duplicate_composite_atom_rows'], 0)
            self.assertFalse(report['admitted'])
            self.assertFalse(report['geometry']['full_stereochemistry_pass'])


if __name__ == '__main__':
    unittest.main()
