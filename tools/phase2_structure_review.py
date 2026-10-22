#!/usr/bin/env python3
"""Bounded, local RNA3DB review. Screening only: never admits or alters atoms.

Reuses prior full-archive QC; only three pinned prefix CIF members are read.
No upstream program, downloads, GPU, pickle loading, or database mutation.
"""
import argparse
import collections
import csv
import hashlib
import io
import itertools
import json
import lzma
import math
import stat
import tarfile
from pathlib import Path

from qc_atom_identity import TAGS, check_block
from qc_rna3db import cif_check
from rnagym import ROOT, get_target, immutable_json, read_manifest, safe_member, sha256

MIB = 1024 ** 2
OUTPUT = ROOT / 'runs/20261023_043639/reports/structure_review'
PRIOR = ROOT / 'runs/20261022_212625/reports'
LIMITS = {'compressed_bytes': 16 * MIB, 'decompressed_bytes': 32 * MIB,
          'member_bytes': 4 * MIB, 'members_visited': 4096,
          'lzma_memory_bytes': 128 * MIB, 'atom_rows': 100000,
          'spatial_pair_comparisons': 2000000, 'sample_count': 3}
BONDS = [('P', 'OP1', 'P-O'), ('P', 'OP2', 'P-O'), ('P', "O5'", 'P-O'),
         ("C5'", "O5'", 'C-O'), ("C4'", "O4'", 'C-O'),
         ("C1'", "O4'", 'C-O'), ("C2'", "O2'", 'C-O'),
         ("C3'", "O3'", 'C-O'), ('C2', 'O2', 'C-O'),
         ('C4', 'O4', 'C-O'), ('C6', 'O6', 'C-O')]
BOND_RANGES = {'P-O': (1.20, 2.10), 'C-O': (1.00, 1.85)}
LOOPS = ('_pdbx_unobs_or_zero_occ_residues.', '_pdbx_unobs_or_zero_occ_atoms.',
         '_pdbx_poly_seq_scheme.', '_entity_poly_seq.')


class BudgetExceeded(ValueError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save_bytes(path, data):
    """Immutable local evidence; filenames never justify replacing bytes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError('immutable evidence conflict: ' + path.name)
    else:
        with path.open('xb') as handle:
            handle.write(data)
        path.chmod(0o444)


class BoundedXZ:
    """Pull decompression with hard *input*, output, and LZMA memory budgets.

    The tar reader gets only the requested output. max_length prevents expansion
    of a compressed chunk into an unbounded Python bytes object.
    """
    def __init__(self, source, limits):
        self.source = source
        self.limits = limits
        self.decoder = lzma.LZMADecompressor(memlimit=limits['lzma_memory_bytes'])
        self.compressed_bytes = 0
        self.decompressed_bytes = 0
        self.prefix_hash = hashlib.sha256()

    def read(self, size):
        if size < 0:
            raise BudgetExceeded('unbounded decompressed read refused')
        out = bytearray()
        while len(out) < size:
            if self.decoder.eof:
                break
            remaining = self.limits['decompressed_bytes'] - self.decompressed_bytes
            if remaining <= 0:
                raise BudgetExceeded('decompressed byte budget reached')
            data = b''
            if self.decoder.needs_input:
                left = self.limits['compressed_bytes'] - self.compressed_bytes
                if left <= 0:
                    raise BudgetExceeded('compressed byte budget reached')
                data = self.source.read(min(65536, left))
                if not data:
                    raise ValueError('truncated XZ stream')
                self.compressed_bytes += len(data)
                self.prefix_hash.update(data)
            chunk = self.decoder.decompress(data, max_length=min(size-len(out), remaining))
            self.decompressed_bytes += len(chunk)
            out.extend(chunk)
        return bytes(out)


def extract_prefix(raw, pins, cache, limits=None):
    """Never extractall/seek whole XZ. Verify every cached member against prior SHA.

    A member has to match its old content hash even when archive SHA is inherited
    from the prior completed full-byte proof. Missing prefix members => BLOCKED.
    """
    limits = limits or LIMITS
    results = []
    missing = []
    for pin in pins:
        path = cache / (pin['member_sha256'] + '.cif')
        if path.exists():
            if path.stat().st_size > limits['member_bytes'] or sha256(path) != pin['member_sha256']:
                raise ValueError('cached member hash/size mismatch')
            results.append(dict(pin, cache_file=path.name))
        else:
            missing.append(pin)
    stats = {'mode': 'CACHED_MEMBERS_ONLY', 'compressed_bytes_read': 0,
             'decompressed_bytes_read': 0, 'members_visited': 0,
             'full_archive_scanned': False, 'xz_footer_verified': False}
    if not missing:
        return results, stats
    desired = {p['member']: p for p in missing}
    stats['mode'] = 'BOUNDED_ARCHIVE_PREFIX'
    try:
        with raw.open('rb') as source:
            reader = BoundedXZ(source, limits)
            try:
                with tarfile.open(fileobj=reader, mode='r|') as archive:
                    for member in archive:
                        stats['members_visited'] += 1
                        if stats['members_visited'] > limits['members_visited']:
                            raise BudgetExceeded('tar member budget reached')
                        safe_member(member.name, cache)
                        if member.isdir():
                            continue
                        if not member.isfile():
                            raise ValueError('archive symlink/hardlink/special refused')
                        if member.size > limits['member_bytes']:
                            raise BudgetExceeded('per-member byte budget reached')
                        if member.name not in desired:
                            continue
                        data = archive.extractfile(member).read(member.size + 1)
                        pin = desired[member.name]
                        if len(data) != member.size or digest(data) != pin['member_sha256']:
                            raise ValueError('member bytes do not match prior content hash')
                        path = cache / (pin['member_sha256'] + '.cif')
                        save_bytes(path, data)
                        results.append(dict(pin, cache_file=path.name, bytes=len(data)))
                        del desired[member.name]
                        if not desired:
                            break
            finally:
                stats.update(compressed_bytes_read=reader.compressed_bytes,
                             decompressed_bytes_read=reader.decompressed_bytes,
                             compressed_prefix_sha256=reader.prefix_hash.hexdigest())
        if desired:
            stats['blocked_reason'] = 'pinned members absent within available archive prefix'
    except (BudgetExceeded, ValueError, lzma.LZMAError, tarfile.TarError) as exc:
        stats['blocked_reason'] = type(exc).__name__ + ': ' + str(exc)
    return results, stats


def read_small_bundle(raw):
    """Only the small already-downloaded JSON release; never coordinates/cmscans."""
    if raw.stat().st_size > 16 * MIB:
        raise BudgetExceeded('metadata compressed budget')
    docs, members, total = {}, [], 0
    with tarfile.open(raw, 'r|gz') as archive:
        for index, member in enumerate(archive):
            if index >= 32:
                raise BudgetExceeded('metadata member budget')
            safe_member(member.name, OUTPUT)
            if member.isdir():
                continue
            total += member.size
            if not member.isfile() or member.size > 128 * MIB or total > 256 * MIB:
                raise BudgetExceeded('metadata expanded bytes/type budget')
            if not member.name.endswith('.json'):
                raise ValueError('unexpected metadata format')
            data = archive.extractfile(member).read(member.size + 1)
            if len(data) != member.size:
                raise ValueError('truncated metadata')
            key = Path(member.name).name
            if key in docs:
                raise ValueError('duplicate JSON basename')
            docs[key] = json.loads(data)
            members.append({'member': member.name, 'bytes': len(data), 'sha256': digest(data)})
    if set(docs) != {'parse.json', 'filter.json', 'cluster.json', 'split.json'}:
        raise ValueError('unexpected RNA3DB metadata set')
    return docs, members


def leaf_members(groups):
    """component -> sequence representative -> actual PDB-chain -> metadata."""
    for component, representatives in groups.items():
        for representative, chains in representatives.items():
            for chain, meta in chains.items():
                if not isinstance(meta, dict) or not isinstance(meta.get('sequence'), str):
                    raise ValueError('unexpected three-level cluster schema')
                yield component, representative, chain, meta


def metadata_review(docs, release):
    membership = list(leaf_members(docs['cluster.json']))
    chains = collections.Counter(row[2] for row in membership)
    seq_groups = collections.defaultdict(set)
    for component, representative, chain, meta in membership:
        seq_groups[(component, representative)].add(meta['sequence'])
    split_sets, flat, mapping = {}, {}, []
    for label, groups in docs['split.json'].items():
        leaves = list(leaf_members(groups))
        chain_keys = [row[2] for row in leaves]
        split_sets[label] = {
            'component': set(groups),
            'sequence_cluster': {(c, r) for c, r, _, _ in leaves},
            'chain': set(chain_keys),
            'structure': {chain.split('_', 1)[0] for chain in chain_keys},
            'exact_sequence': {digest(m['sequence'].encode()) for _, _, _, m in leaves}}
        flat[label] = {
            'component_count': len(groups),
            'sequence_cluster_count': len(split_sets[label]['sequence_cluster']),
            'actual_chain_count': len(chain_keys),
            'repeated_chain_memberships': len(chain_keys) - len(set(chain_keys))}
        for comp, representative, chain, meta in leaves:
            mapping.append({'release': release, 'split': label, 'component_id': comp,
                            'sequence_cluster_representative': representative,
                            'chain_id': chain, 'sequence_sha256': digest(meta['sequence'].encode()),
                            'raw_sequence_length': len(meta['sequence'])})
    overlaps = []
    for left, right in itertools.combinations(sorted(split_sets), 2):
        row = {'release': release, 'left': left, 'right': right}
        for kind in ['component', 'sequence_cluster', 'chain', 'structure', 'exact_sequence']:
            shared = split_sets[left][kind] & split_sets[right][kind]
            row['shared_' + kind + '_count'] = len(shared)
            row['shared_' + kind + '_examples'] = sorted(shared)[:12]
        overlaps.append(row)
    all_split = {r['chain_id'] for r in mapping}
    cluster_chain = set(chains)
    filters = set(docs['filter.json'])
    split_members = {(r['component_id'], r['sequence_cluster_representative'], r['chain_id']) for r in mapping}
    source_members = {(c, r, chain) for c, r, chain, _ in membership}
    report = {'release': release, 'status': 'VERIFIED_METADATA_SCHEMA_ONLY',
              'parse_chains': len(docs['parse.json']), 'filtered_chains': len(filters),
              'component_count': len(docs['cluster.json']), 'sequence_cluster_count': len(seq_groups),
              'actual_cluster_chain_count': len(cluster_chain), 'split_counts': flat,
              'chain_membership_reused_in_clusters': sum(n-1 for n in chains.values()),
              'cluster_vs_filter_symmetric_difference': sorted(cluster_chain ^ filters),
              'split_vs_filter_symmetric_difference': sorted(all_split ^ filters),
              'split_vs_cluster_membership_difference_count': len(split_members ^ source_members),
              'sequence_clusters_with_multiple_exact_sequences': sum(len(s)>1 for s in seq_groups.values()),
              'sequence_hash_definition': 'SHA256 of exact UTF-8 upstream sequence; no U/T/case conversion',
              'sequence_cluster_alignment_threshold_verified': False,
              'rfam_assignment_recomputed_or_independently_verified': False,
              'official_split_preserved': True, 'new_split_generated': False,
              'overlaps': overlaps, 'admitted': False}
    return report, mapping


def values(block, tag, count=None, default=''):
    import gemmi
    raw = list(block.find_values(tag))
    if count is not None and raw and len(raw) != count:
        raise ValueError('CIF column length mismatch: ' + tag)
    return [gemmi.cif.as_string(x) for x in raw] if raw else [default] * (count or 0)


def compatible(left, right):
    return not left or not right or left == right


def loop_evidence(block, prefix):
    category = block.get_mmcif_category(prefix, raw=True)
    lengths = {len(v) for v in category.values()}
    if len(lengths) > 1:
        raise ValueError('CIF loop length mismatch')
    return {'present': bool(category), 'rows': next(iter(lengths), 0),
            'columns': sorted(category),
            'examples': [{k: vals[i] for k, vals in category.items()} for i in range(min(3, next(iter(lengths), 0)))]}


def geometry_screen(atoms, pair_budget=2000000):
    """Loose named-bond and severe inter-residue overlap screens, not validation.

    All models/altloc records are retained. Models never interact; different
    nonblank altloc labels are conservatively considered incompatible.
    """
    residues = collections.defaultdict(list)
    for atom in atoms:
        residues[atom['residue_key']].append(atom)
    distances = collections.defaultdict(list)
    examples, links = [], set()
    bond_candidates = 0
    eligible = lambda a: a['occupancy'] is not None and 0 < a['occupancy'] <= 1
    def add_bond(a, b, kind):
        nonlocal bond_candidates
        bond_candidates += 1
        if bond_candidates > pair_budget:
            raise BudgetExceeded('named-bond candidate budget reached')
        if not eligible(a) or not eligible(b) or not compatible(a['altloc'], b['altloc']):
            return
        d = math.dist(a['xyz'], b['xyz'])
        distances[kind].append(d)
        links.add(frozenset((a['row'], b['row'])))
        lo, hi = BOND_RANGES[kind]
        if not lo <= d <= hi and len(examples) < 32:
            examples.append({'kind': kind, 'distance_angstrom': d,
                             'left_composite_key': a['key'], 'right_composite_key': b['key']})
    indexed = collections.defaultdict(list)
    for key, group in residues.items():
        by_name = collections.defaultdict(list)
        for atom in group:
            by_name[atom['name']].append(atom)
        for first, second, kind in BONDS:
            for a, b in itertools.product(by_name[first], by_name[second]):
                add_bond(a, b, kind)
        # Only unambiguous integer label adjacency; never infer author renumbering.
        model, chain, auth_chain, label_seq, auth_seq, insertion, component = key
        try:
            label_num = int(label_seq)
        except ValueError:
            continue
        if not insertion:
            indexed[(model, chain, auth_chain, label_num)].append(group)
    for (model, chain, auth_chain, number), groups in indexed.items():
        next_groups = indexed.get((model, chain, auth_chain, number+1), [])
        if len(groups) != 1 or len(next_groups) != 1:
            continue
        for a, b in itertools.product([a for a in groups[0] if a['name'] == "O3'"],
                                      [a for a in next_groups[0] if a['name'] == 'P']):
            add_bond(a, b, 'P-O')
    cutoff = 1.2
    bins = collections.defaultdict(list)
    examined, clashes, clash_examples, skipped = 0, 0, [], 0
    exhausted = False
    for atom in atoms:
        if atom['element'].upper() not in {'C', 'N', 'O', 'P', 'S'} or not eligible(atom):
            skipped += 1
            continue
        cell = tuple(math.floor(x/cutoff) for x in atom['xyz'])
        for delta in itertools.product((-1, 0, 1), repeat=3):
            key = (atom['model'], *(v+d for v, d in zip(cell, delta)))
            for other in bins.get(key, []):
                examined += 1
                if examined > pair_budget:
                    exhausted = True
                    break
                if (atom['residue_key'] == other['residue_key'] or
                        not compatible(atom['altloc'], other['altloc']) or
                        frozenset((atom['row'], other['row'])) in links):
                    continue
                d = math.dist(atom['xyz'], other['xyz'])
                if d < cutoff:
                    clashes += 1
                    if len(clash_examples) < 32:
                        clash_examples.append({'distance_angstrom': d,
                                               'left_composite_key': atom['key'],
                                               'right_composite_key': other['key']})
            if exhausted:
                break
        if exhausted:
            break
        bins[(atom['model'], *cell)].append(atom)
    return {'status': 'BLOCKED_PAIR_BUDGET' if exhausted else 'PROVISIONAL_HEURISTIC_SCREEN_ONLY',
            'bond_ranges_angstrom': BOND_RANGES, 'bond_candidates': bond_candidates,
            'named_bond_distances': {kind: {'count': len(ds), 'min': min(ds), 'max': max(ds),
                'outside_range_count': sum(not BOND_RANGES[kind][0] <= d <= BOND_RANGES[kind][1] for d in ds)}
                for kind, ds in distances.items()},
            'bond_outlier_examples': examples,
            'severe_overlap_cutoff_angstrom': cutoff,
            'inter_residue_nonbonded_severe_overlap_count': clashes,
            'overlap_examples': clash_examples, 'spatial_pair_comparisons': min(examined, pair_budget),
            'spatial_screen_complete': not exhausted,
            'spatial_atoms_not_eligible': skipped,
            'intra_residue_nonbonded_screened': False,
            'ccd_bond_restraints_loaded': False, 'full_stereochemistry_pass': False,
            'formal_vdw_clashscore_computed': False}


def review_cif(data, member):
    import gemmi
    text = data.decode('utf-8', errors='strict')
    block = gemmi.cif.read_string(text).sole_block()
    count = len(block.find_values('_atom_site.Cartn_x'))
    if not count or count > LIMITS['atom_rows']:
        raise BudgetExceeded('per-sample atom-row budget')
    schema = cif_check(text, member)
    identity = check_block(block)
    columns = [values(block, tag, count) for tag in TAGS]
    keys = list(zip(*columns))
    coords = list(zip(*(values(block, '_atom_site.Cartn_' + axis, count) for axis in 'xyz')))
    raw_occ = values(block, '_atom_site.occupancy', count)
    elements = values(block, '_atom_site.type_symbol', count)
    occupancy, atoms = collections.Counter(), []
    for index, (key, xyz, occ, element) in enumerate(zip(keys, coords, raw_occ, elements)):
        xyz = tuple(float(x) for x in xyz)
        if not all(math.isfinite(v) for v in xyz):
            raise ValueError('nonfinite coordinate; geometry refused')
        try:
            numeric_occ = float(occ)
        except ValueError:
            numeric_occ = None
        if numeric_occ is None:
            occupancy['missing_or_not_numeric'] += 1
        elif not math.isfinite(numeric_occ):
            occupancy['nonfinite'] += 1
            numeric_occ = None
        else:
            occupancy['finite'] += 1
            occupancy['outside_0_1'] += int(not 0 <= numeric_occ <= 1)
            occupancy['zero'] += int(numeric_occ == 0)
            occupancy['fractional'] += int(0 < numeric_occ < 1)
        atoms.append({'row': index, 'key': key, 'residue_key': key[:7],
                      'model': key[0], 'name': key[7], 'altloc': key[8],
                      'xyz': xyz, 'occupancy': numeric_occ, 'element': element})
    per_chain = collections.defaultdict(set)
    for atom in atoms:
        key = atom['key']
        per_chain[(key[0], key[1], key[2])].add(key[3:7])
    loops = {prefix: loop_evidence(block, prefix) for prefix in LOOPS}
    return {'status': 'PROVISIONAL_REPRESENTATIVE_REVIEW_NOT_ADMISSION',
            'member': member, 'member_sha256': digest(data), 'bytes': len(data),
            'schema_reused_from_qc_rna3db': schema,
            'identity_reused_from_qc_atom_identity': identity,
            'occupancy_counts': dict(occupancy),
            'observed_residues_by_model_label_auth_chain': [
                {'model': k[0], 'label_chain': k[1], 'auth_chain': k[2], 'observed_residues': len(v)}
                for k, v in per_chain.items()],
            'missing_residue_and_polymer_loops': loops,
            'absence_of_unobserved_loop_does_not_mean_no_missing_residues': True,
            'geometry': geometry_screen(atoms, LIMITS['spatial_pair_comparisons']),
            'all_atoms_retained': True, 'atom_rows_removed': 0,
            'biological_assembly_verified': False, 'cross_benchmark_homology_verified': False,
            'admitted': False}


def write_tsv(path, rows, fields):
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fields, delimiter='\t', lineterminator='\n')
    writer.writeheader()
    for row in rows:
        writer.writerow({key: json.dumps(row[key], sort_keys=True) if isinstance(row[key], (list, dict)) else row[key]
                         for key in fields})
    save_bytes(path, buffer.getvalue().encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(OUTPUT.resolve()):
        parser.error('worker output must remain inside its owned structure_review folder')
    if not args.execute:
        print(json.dumps({'status': 'DRY_RUN', 'limits': LIMITS, 'network': False,
                          'gpu': False, 'full_coordinate_rescan': False,
                          'output': str(output.relative_to(ROOT))}, indent=2))
        return
    if (output / 'execution_audit.json').exists():
        audit = json.loads((output / 'execution_audit.json').read_text())
        if sha256(Path(__file__)) != audit['script_sha256']:
            raise ValueError('script changed; use a new version subfolder, not overwrite')
        for item in audit['outputs']:
            if sha256(output / item['file']) != item['sha256']:
                raise ValueError('immutable output hash mismatch')
        print(json.dumps({'status': 'REUSED_COMPLETE_CHECKPOINT', 'summary': json.loads((output/'summary.json').read_text())}))
        return
    output.mkdir(parents=True, exist_ok=True)
    evidence = []
    def snapshot(path, name=None):
        data = path.read_bytes()
        rel = str(path.relative_to(ROOT))
        target = output / 'evidence' / (name or path.name)
        save_bytes(target, data)
        evidence.append({'path': rel, 'sha256': digest(data), 'snapshot': str(target.relative_to(output))})
        return json.loads(data) if path.suffix == '.json' else None
    names = ['rna3db_coordinate_summary.json', 'rna3db_atom_identity_qc.json',
             'rna3db-metadata-2025-10-01-incremental-release.json',
             'rna3db-metadata-2026-01-05-full-release.json', 'rna3db_actual_version_diff.json',
             'rna3db_cmscan_qc.json', 'rna3db_structural_review_flags.json',
             'cluster_mapping_review.json', 'final_raw_byte_verification.json']
    prior = {name: snapshot(PRIOR/name) for name in names}
    snapshot(ROOT/'runs/20261022_212625/manifests/source_metadata/marcellszi__rna3db/README.source.txt')
    snapshot(ROOT/'runs/20261022_212625/manifests/source_metadata/marcellszi__rna3db/inspection.json')
    assets = [r for r in read_manifest(ROOT/'data/audit/additional_source_assets.csv').values()
              if r['package_group_id'] == 'RNA3DB']
    proof = {r['asset_id']: r for r in prior['final_raw_byte_verification.json']['artifacts']}
    raw_records, docs_by_release = [], {}
    for row in assets:
        raw = get_target(row, ROOT/'raw_cache')
        item = proof[row['asset_id']]
        prov = snapshot(raw.parent/'provenance.json', row['asset_id']+'-provenance.json')
        if (raw.parent.name != item['sha256'] or raw.stat().st_size != item['bytes'] or
                stat.S_IMODE(raw.stat().st_mode) & 0o222 or
                not item.get('actual_raw_bytes_verified') or prov['sha256'] != item['sha256']):
            raise ValueError('prior content-addressed proof, size or read-only status mismatch')
        entry = {'asset_id': row['asset_id'], 'release': row['release_tag'],
                 'raw_sha256': item['sha256'], 'raw_bytes': item['bytes'],
                 'source_url': row['official_source_url'],
                 'whole_raw_sha_rehashed_this_run': False,
                 'whole_raw_hash_evidence': 'REUSED_PRIOR_FULL_BYTE_VERIFICATION',
                 'expected_download_pin_sha256': prov.get('expected_sha256'),
                 'upstream_checksum_independently_verified_this_run': False}
        if 'jsons' in row['asset_id']:
            if sha256(raw) != item['sha256']:
                raise ValueError('small metadata raw SHA mismatch')
            docs, members = read_small_bundle(raw)
            docs_by_release[row['release_tag']] = docs
            entry.update(whole_raw_sha_rehashed_this_run=True, members=members)
        raw_records.append(entry)
    mapping, audits, leakage = [], {}, []
    for release, docs in docs_by_release.items():
        audit, rows = metadata_review(docs, release)
        audits[release] = audit
        mapping.extend(rows)
        leakage.extend(audit['overlaps'])
    audit_doc = {'status': 'VERIFIED_METADATA_MAPPING_NOT_ADMISSION', 'releases': audits,
                 'prior_split_chain_count_correction': 'Earlier original_split_chain_counts count sequence-cluster representatives, not actual leaf chains. Original reports unchanged.',
                 'cluster_40_parquet': {'package_group_id': 'RNAGYM_RMDB', 'is_rna3db_cluster': False,
                    'source_sha256': prior['cluster_mapping_review.json']['source_sha256'],
                    'status': 'BLOCKED_RMDB_CLUSTER_SCHEMA_NOT_STRUCTURE_HOMOLOGY'},
                 'rfam_evidence': {'status': 'PROVISIONAL_REUSED_CMSCAN_SCHEMA_ONLY',
                    'reported_hits': prior['rna3db_cmscan_qc.json']['hit_records'],
                    'reported_rfam_accessions': prior['rna3db_cmscan_qc.json']['rfam_accession_count'],
                    'independent_assignment_or_cross_benchmark_verification': False},
                 'admitted': False}
    immutable_json(output/'metadata_audit.json', audit_doc)
    write_tsv(output/'chain_cluster_mapping.tsv', mapping, list(mapping[0]))
    write_tsv(output/'structure_leakage_report.tsv', leakage, list(leakage[0]))
    coordinate = next(r for r in assets if 'mmcifs' in r['asset_id'])
    raw = get_target(coordinate, ROOT/'raw_cache')
    pins = []
    with (PRIOR/'rna3db_coordinate_entries.jsonl').open() as stream:
        for line_number, line in enumerate(stream, 1):
            pin = json.loads(line)
            if pin.get('member_sha256'):
                pins.append({'member': pin['member'], 'member_sha256': pin['member_sha256'],
                             'prior_index_line': line_number})
            if len(pins) == LIMITS['sample_count']:
                break
    if len(pins) != 3:
        raise ValueError('three prior member hash pins required')
    extraction_checkpoint = output/'sample_extraction.json'
    if extraction_checkpoint.exists():
        checkpoint = json.loads(extraction_checkpoint.read_text())
        samples, stream_stats = checkpoint['samples'], checkpoint['stream']
        for sample in samples:
            if sha256(output/'cache'/sample['cache_file']) != sample['member_sha256']:
                raise ValueError('sample checkpoint hash mismatch')
    else:
        samples, stream_stats = extract_prefix(raw, pins, output/'cache')
        immutable_json(extraction_checkpoint, {'samples': samples, 'stream': stream_stats})
    reviews = []
    new_docs = docs_by_release['2026-01-05-full-release']
    new_mapping = {r['chain_id']: r for r in mapping if r['release']=='2026-01-05-full-release'}
    for sample in samples:
        report = review_cif((output/'cache'/sample['cache_file']).read_bytes(), sample['member'])
        entry_id = report['schema_reused_from_qc_rna3db']['entry_id']
        chain = new_docs['parse.json'].get(entry_id)
        source_membership = new_mapping.get(entry_id)
        report['exact_entry_id_metadata_match'] = bool(chain)
        report['official_membership'] = source_membership
        report['metadata_chain_length_not_an_observed_residue_count'] = chain.get('length') if chain else None
        path = Path(sample['member'])
        parts = path.parts
        report['archive_path_mapping'] = {'raw_path_sequence_cluster_directory': path.parent.name,
            'actual_entry_id': entry_id,
            'parent_directory_is_sequence_representative_not_necessarily_actual_chain': True,
            'split_matches_metadata': bool(source_membership) and parts[1] == source_membership['split'],
            'component_matches_metadata': bool(source_membership) and parts[2] == source_membership['component_id']}
        immutable_json(output/'samples'/(sample['member_sha256']+'.json'), report)
        reviews.append({'member': sample['member'], 'member_sha256': sample['member_sha256'],
                        'report': 'samples/'+sample['member_sha256']+'.json',
                        'entry_id': entry_id, 'atoms': report['schema_reused_from_qc_rna3db']['atom_rows'],
                        'bond_outliers': sum(d['outside_range_count'] for d in report['geometry']['named_bond_distances'].values()),
                        'severe_nonbonded_overlaps': report['geometry']['inter_residue_nonbonded_severe_overlap_count']})
    immutable_json(output/'source_artifact_evidence.json', {'artifacts': raw_records, 'prior_evidence': evidence,
        'sample_pins_from_prior_coordinate_index': pins,
        'sample_selection': 'First three hashed prior coordinate-index members, in archive order; deterministic prefix convenience sample, NOT a representative statistical validation set.',
        'coordinate_whole_archive_rehashed_this_run': False,
        'raw_data_modified': False, 'upstream_program_executed': False})
    old = prior['rna3db_actual_version_diff.json']['parse.json']
    summary = {'status': 'PROVISIONAL_BOUNDED_STRUCTURAL_REVIEW',
               'samples_completed': len(reviews), 'samples_requested': 3,
               'samples': reviews, 'stream': stream_stats, 'limits': LIMITS,
               'prior_coordinate_chain_count_reused': prior['rna3db_coordinate_summary.json']['coordinate_files_scanned'],
               'version_diff': {'old_parse_chains': old['old_ids'], 'new_parse_chains': old['new_ids'],
                    'added_chains': len(old['added_chain_ids']), 'removed_chains': len(old['removed_chain_ids']),
                    'selected_version': None},
               'admitted': 0, 'full_stereochemistry_pass': False,
               'blocked': ['original biological assembly and inter-chain context',
                           'independent Rfam assignment/sequence alignment threshold verification',
                           'cross-benchmark homology and pretraining contamination',
                           'complete CCD/stereochemistry/van-der-Waals validation',
                           'assay rights and human scientific admission review'],
               'new_downloads': 0, 'gpu_jobs': 0, 'raw_atoms_deleted': 0}
    immutable_json(output/'summary.json', summary)
    files = sorted(p for p in output.rglob('*') if p.is_file() and p.name!='execution_audit.json')
    immutable_json(output/'execution_audit.json', {'status': 'VERIFIED_LOCAL_EXECUTION_NOT_ADMISSION',
                   'script_sha256': sha256(Path(__file__)), 'network_used': False, 'gpu_used': False,
                   'run_id': str(output.relative_to(ROOT)),
                   'outputs': [{'file': str(p.relative_to(output)), 'sha256': sha256(p)} for p in files]})
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
