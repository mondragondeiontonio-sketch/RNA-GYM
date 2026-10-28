#!/usr/bin/env python3
"""Audit existing upstream splits without downloading, resplitting or publishing rows.

The user-authorized reuse tier is NOT the original formal human-review gate.
All source bytes and workflow documents must already have pinned evidence.
"""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import io
import itertools
import json
import math
from pathlib import Path, PurePosixPath
import re
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
POLICY_ID = 'USER_SPLIT_WORKFLOW_REUSE_20261028'
ROLES = {'train': 'train', 'training': 'train', 'test': 'test',
         'val': 'validation', 'valid': 'validation', 'validation': 'validation',
         'leftout': 'leftout'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def split_key(name):
    """Recognize explicit role tokens; never infer a random split or a seed."""
    p = PurePosixPath(name)
    if p.suffix.lower() not in ('.csv', '.tsv'):
        return None
    parts = list(p.parts[:-1]) + [p.stem]
    roles = []
    cleaned = []
    for part in parts:
        tokens = re.split(r'([_.-])', part)
        kept = []
        for token in tokens:
            if token.lower() in ROLES:
                roles.append(ROLES[token.lower()])
            else:
                kept.append(token)
        value = ''.join(kept).strip('_.-')
        if value:
            cleaned.append(value)
    if not roles or len(set(roles)) != 1:
        return None
    return '/'.join(cleaned), roles[0]


def assess(protocol):
    """Only the explicitly authorized upstream-reuse scope may pass here."""
    issues = []
    parts = protocol.get('partitions', [])
    roles = [p.get('split') for p in parts]
    if roles.count('train') != 1:
        issues.append('EXACTLY_ONE_TRAIN_PARTITION_REQUIRED')
    heldout = [p for p in parts if p.get('split') in ('test','validation','leftout') and p.get('n_rows',0)>0]
    if not heldout:
        issues.append('EXPLICIT_NONEMPTY_HELDOUT_PARTITION_REQUIRED')
    if len(roles) != len(set(roles)):
        issues.append('AMBIGUOUS_PARTITION_MEMBERS')
    if not protocol.get('source_hashes_verified'):
        issues.append('SOURCE_HASH_NOT_VERIFIED')
    flow = protocol.get('workflow', {})
    if (not re.fullmatch(r'[a-f0-9]{40}', flow.get('commit', '')) or
            not re.fullmatch(r'[a-f0-9]{64}', flow.get('sha256', '')) or
            not flow.get('url', '').startswith('https://github.com/') or
            '/blob/'+flow.get('commit','')+'/' not in flow.get('url','')):
        issues.append('PINNED_AUTHOR_WORKFLOW_REQUIRED')
    if not protocol.get('usage_recipe'):
        issues.append('EXPLICIT_USAGE_RECIPE_REQUIRED')
    for part in parts:
        if '.ipynb_checkpoints' in (part.get('member') or ''):
            issues.append('EDITOR_CHECKPOINT_NOT_AUTHOR_PROTOCOL')
        if not re.fullmatch(r'[a-f0-9]{64}', part.get('sha256', '')):
            issues.append('PARTITION_HASH_REQUIRED')
        if part.get('n_rows', 0) <= 0 and part.get('split') in ('train', 'test'):
            issues.append('NONEMPTY_TRAIN_TEST_REQUIRED')
        if not part.get('input_columns') or not part.get('target_column'):
            issues.append('UNRESOLVED_INPUT_OR_TARGET')
        if part.get('invalid_rows', 0):
            issues.append('INVALID_INPUT_OR_LABEL_ROWS')
    if not protocol.get('overlap_key_basis'):
        issues.append('EXPLICIT_OVERLAP_KEY_BASIS_REQUIRED')
    if protocol.get('cross_partition_key_overlap') is None:
        issues.append('PARTITION_MEMBERSHIP_NOT_CHECKED')
    elif protocol['cross_partition_key_overlap']:
        issues.append('CROSS_PARTITION_KEY_OVERLAP')
    if protocol.get('missing_reference_release'):
        issues.append('MATCHING_REFERENCE_RELEASE_MISSING')
    return {**protocol, 'policy_id': POLICY_ID,
            'admission_scope': 'UPSTREAM_PROTOCOL_REUSE',
            'evaluation_partition': 'test' if 'test' in roles else 'validation' if 'validation' in roles else 'leftout',
            'evaluation_claim': 'UPSTREAM_TEST_REPLAY' if 'test' in roles else 'DEVELOPMENT_HOLDOUT_ONLY_NOT_TEST',
            'status': 'HOLD_UPSTREAM_REUSE' if issues else 'ADMITTED_UPSTREAM_REUSE',
            'admitted_upstream_reuse': not issues,
            'formal_core_admitted': False, 'formal_leaderboard_eligible': False,
            'rights_approval_generated': False, 'human_signature_generated': False,
            'issues': sorted(set(issues))}


def scan_table(data, name, prior=None):
    reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig')),
                            delimiter='\t' if name.endswith('.tsv') else ',')
    columns = reader.fieldnames or []
    inp = 'sequence' if 'sequence' in columns else None
    target = next((c for c in ('DMS_score', 'label', 'target') if c in columns), None)
    if target is None:
        # Use only an exact column name present in the explicit file stem.
        candidates = [c for c in columns if c in ('log_half_life', 'half_life', 'beta')
                      and c in PurePosixPath(name).stem]
        if candidates:
            target = max(candidates, key=len)
    count, invalid, keys = 0, 0, set()
    for row in reader:
        count += 1
        if not inp or not target:
            continue
        sequence = row.get(inp)
        try:
            valid = bool(sequence) and math.isfinite(float(row[target]))
        except (ValueError, TypeError, KeyError):
            valid = False
        if not valid:
            invalid += 1
        if sequence:
            keys.add(hashlib.sha256(sequence.encode('utf-8')).digest())
    digest = sha(data)
    if prior and prior.get('member_sha256') != digest:
        raise ValueError('PRIOR_MEMBER_HASH_MISMATCH:' + name)
    return {'member': name, 'sha256': digest, 'n_rows': count,
            'input_columns': [inp] if inp else [], 'target_column': target,
            'invalid_rows': invalid, 'sequence_transformation': 'NONE',
            'repeated_exact_inputs_within_partition': count-len(keys) if inp else None}, keys


def table_protocols(path, artifact, workflow, prior, max_member=64*1024*1024):
    groups = defaultdict(list)
    keys = defaultdict(dict)
    held = []
    expanded = 0
    def consume(name, data):
        nonlocal expanded
        expanded += len(data)
        if expanded > 2500000000:
            raise ValueError('EXPANDED_TABLE_READ_BUDGET_EXCEEDED')
        parsed = split_key(name)
        if not parsed:
            return
        group, role = parsed
        part, exact = scan_table(data, name, prior.get(name))
        part.update(split=role, artifact_uid=artifact['artifact_uid'])
        groups[group].append(part)
        # Duplicate role names are retained and rejected, never overwritten.
        keys[group].setdefault(role, []).append(exact)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                if member.is_dir() or not split_key(member.filename):
                    continue
                if member.file_size > max_member:
                    held.append(member.filename)
                    continue
                consume(member.filename, archive.read(member))
    else:
        with tarfile.open(path, mode='r|gz') as archive:
            for member in archive:
                if not member.isfile() or not split_key(member.name):
                    continue
                if member.size > max_member:
                    held.append(member.name)
                    continue
                consume(member.name, archive.extractfile(member).read())
    protocols = []
    for group, parts in sorted(groups.items()):
        counts = []
        for a, b in itertools.combinations(keys[group], 2):
            for left in keys[group][a]:
                for right in keys[group][b]:
                    counts.append(len(left & right))
        # Input schema/endpoint must agree; do not merge different readouts.
        schemas = {(tuple(p['input_columns']), p['target_column']) for p in parts}
        if len(schemas) != 1:
            for p in parts:
                p['invalid_rows'] += 1
        ident = artifact['artifact_uid'] + ':' + group
        protocols.append(assess({
            'protocol_id': 'UP_' + sha(ident.encode())[:20],
            'package_group_id': artifact['package_group_id'],
            'source_protocol': group, 'source_hashes_verified': True,
            'workflow': workflow, 'partitions': sorted(parts, key=lambda p: p['split']),
            'cross_partition_key_overlap': sum(counts),
            'overlap_key_basis': 'EXACT_RAW_SEQUENCE_BYTES',
            'usage_recipe': {'loader': 'csv.DictReader',
                'partition_source': 'EXACT_UPSTREAM_ARCHIVE_MEMBERS',
                'input_column': next(iter(schemas))[0] if len(schemas) == 1 else None,
                'target_column': next(iter(schemas))[1] if len(schemas) == 1 else None,
                'resplitting': False, 'normalization': False, 'rows_dropped': 0,
                'adapter_metric_and_label_budget_binding': 'REQUIRED_BEFORE_MODEL_EXECUTION'},
            'independent_original_assay_count': None,
            'limitations': ['Upstream replay only; no full homology clearance or source independence claim',
                            'No automatic RNA alphabet conversion, cropping or formal ranking admission']}))
    return protocols, {'expanded_table_bytes_read': expanded,
                       'oversize_members_not_read': held}


def run(root, private_path, hash_path, workflows_path):
    config = json.loads((root/'configs/native_sdk.json').read_text())
    catalog = json.loads((root/config['dataset_catalog']).read_text())
    private = json.loads(private_path.read_text())['artifacts']
    verified = {a['artifact_uid']: a for a in json.loads(hash_path.read_text())['assets']}
    flows = {r['package']: r for r in json.loads(workflows_path.read_text())['sources']}
    assets = {a['artifact_uid']: a for a in catalog['assets']}
    protocols, inventory, scan_limits = [], [], {}
    by_id = {a['asset_id']: a for a in assets.values()}
    if len(by_id)!=len(assets):
        raise ValueError('AMBIGUOUS_ASSET_VERSION_EXPLICIT_AUDIT_SELECTION_REQUIRED')
    for uid, asset in assets.items():
        proof = verified.get(uid)
        if not proof or not proof['hash_matches'] or proof['sha256'] != private[uid]['source_sha256']:
            raise ValueError('CURRENT_RAW_HASH_PROOF_REQUIRED:' + uid)
        inventory.append({'artifact_uid': uid, 'asset_id': asset['asset_id'],
            'filename': asset['filename'], 'package_group_id': asset['package_group_id'],
            'bytes': proof['bytes'], 'sha256': proof['sha256'],
            'current_raw_hash_verified': True, 'split_state': 'NO_VERIFIED_SPLIT_RECIPE',
            'label_evidence_at_snapshot': bool(asset.get('label_evidence'))})
    for aid in ('A0003', 'EUKA_DOWNSTREAM_ASSEMBLED'):
        asset = by_id[aid]; uid = asset['artifact_uid']
        path = root/private[uid]['path']
        old = root/'runs/20261022_212625/reports/archive_qc'/(aid+'.json')
        previous = json.loads(old.read_text())
        if previous['source_sha256'] != verified[uid]['sha256']:
            raise ValueError('PRIOR_ARCHIVE_QC_SOURCE_HASH_MISMATCH')
        prior = {r['member']: r for r in previous['scanned_members']}
        flow = flows['RNAGYM' if aid == 'A0003' else 'EUKAUTR']
        import inspect
        cache_key = sha((asset['artifact_uid']+flow['sha256']+
                         inspect.getsource(table_protocols)+inspect.getsource(scan_table)+inspect.getsource(split_key)).encode())
        cache = hash_path.parent / (aid+'.'+cache_key[:16]+'.table_scan.json')
        if not cache.parent.resolve().is_relative_to(root/'runs'):
            raise ValueError('IGNORED_CACHE_PATH_REQUIRED')
        if cache.is_file():
            saved=json.loads(cache.read_text());found,limits=saved['protocols'],saved['limits']
        else:
            found, limits = table_protocols(path, asset, flow, prior)
            cache.write_text(json.dumps({'protocols':found,'limits':limits},indent=2)+'\n')
        found=[assess(p) for p in found]
        protocols.extend(found); scan_limits[aid] = limits
    # Fixed miRBench file splits. Reuse full-file QC and compound-pair overlap
    # evidence only after CURRENT raw hashes and exact report hashes agree.
    overlap_path = root/'runs/20261023_043639/reports/pair_identity/overlap_comparison_counts.tsv'
    with overlap_path.open() as handle:
        overlaps = list(csv.DictReader(handle, delimiter='\t'))
    if len(overlaps)!=21 or not all(r['exact_input_count_status']=='VERIFIED_FROM_CACHED_FULL_QC' for r in overlaps):
        raise ValueError('COMPLETE_HASH_BOUND_PAIR_COMPARISONS_REQUIRED')
    for label, aids in [
        ('Hejret2023', ['P0_MIR_HEJRET_TRAIN_ZENODO', 'P0_MIR_HEJRET_TEST_ZENODO']),
        ('Manakov2022', ['P0_MIR_MANAKOV_TRAIN_ZENODO', 'P0_MIR_MANAKOV_TEST_ZENODO', 'P0_MIR_MANAKOV_LEFTOUT_ZENODO'])]:
        parts = []
        for aid in aids:
            asset = by_id[aid]; uid = asset['artifact_uid']
            qc_path = root/'runs/20261022_212625/reports/paired_full_qc'/(aid+'-qc.json')
            qc = json.loads(qc_path.read_text())
            if qc['source_sha256'] != verified[uid]['sha256'] or qc['state'] != 'PASS_FULL_FILE_EXACT_PAIRED_QC_ONLY':
                raise ValueError('PRIOR_FULL_PAIRED_QC_SOURCE_OR_STATE_MISMATCH')
            expected = [e for e in asset['label_evidence'] if e['evidence_ref'].endswith(qc_path.name)]
            if not expected or sha(qc_path.read_bytes()) != expected[0]['evidence_sha256']:
                raise ValueError('PRIOR_FULL_PAIRED_QC_EVIDENCE_HASH_MISMATCH')
            parts.append({'artifact_uid': uid, 'member': None, 'sha256': qc['source_sha256'],
                'split': qc['original_split'], 'n_rows': qc['actual_n'],
                'input_columns': ['gene', 'noncodingRNA'], 'target_column': 'label',
                'invalid_rows': sum(qc['row_issues'].values()),
                'full_qc_evidence_sha256': sha(qc_path.read_bytes())})
        comparisons = [r for r in overlaps if r['left_asset'] in aids and r['right_asset'] in aids]
        if len(comparisons) != len(aids)*(len(aids)-1)//2:
            raise ValueError('EXPLICIT_ALL_PARTITION_PAIR_COMPARISONS_REQUIRED')
        protocols.append(assess({'protocol_id': 'UP_MIRBENCH_'+label,
            'package_group_id': 'MIR_BENCH', 'source_protocol': label,
            'source_hashes_verified': True, 'workflow': flows['MIR_BENCH'], 'partitions': parts,
            'cross_partition_key_overlap': sum(int(r['shared_exact_input_pair_count']) for r in comparisons),
            'overlap_key_basis': 'EXACT_ROLE_ORDERED_RAW_TARGET_MIRNA_PAIR',
            'overlap_evidence_sha256': sha(overlap_path.read_bytes()),
            'usage_recipe': {'loader': 'gzip.open + csv.DictReader',
                'partition_source': 'EXACT_ORIGINAL_SPLIT_FILES', 'input_roles': ['gene=target RNA sequence', 'noncodingRNA=miRNA sequence'],
                'target': 'original binary label', 'rows_dropped': 0, 'resplitting': False,
                'cross_dataset_pooling': 'FORBIDDEN_WITHOUT_SEPARATE_OVERLAP_REVIEW'},
            'independent_original_assay_count': None,
            'limitations': ['Pair-input adapter required; pooled embedding scalar MLP is not a pair predictor',
                            'Cross-dataset train/test sharing exists; this approval is within-dataset upstream replay only']}))
    # RNA3DB contains an actual train/valid/test JSON, not just names on disk.
    for aid in ('RNA3DB_20251001_rna3db_jsons', 'RNA3DB_20260105_rna3db_jsons'):
        asset = by_id[aid]; uid = asset['artifact_uid']
        with tarfile.open(root/private[uid]['path']) as archive:
            member = archive.getmember('rna3db-jsons/split.json')
            if member.size > 32*1024*1024:
                raise ValueError('STRUCTURE_SPLIT_JSON_LIMIT')
            data = archive.extractfile(member).read(); value = json.loads(data)
        parts, sets, cluster_sets = [], [], []
        for role, entries in value.items():
            if role not in ('train_set', 'valid_set', 'test_set') or not isinstance(entries, dict):
                raise ValueError('UNEXPECTED_RNA3DB_SPLIT_SCHEMA')
            ids = [item for block in entries.values() for item in block]
            sets.append(set(ids)); cluster_sets.append(set(entries))
            parts.append({'artifact_uid': uid, 'member': member.name,
                'sha256': sha(data), 'split': {'train_set':'train','valid_set':'validation','test_set':'test'}[role],
                'n_rows': len(ids), 'n_component_groups': len(entries),
                'input_columns': ['chain_sequence'], 'target_column': 'reference_coordinates',
                'invalid_rows': len(ids)-len(set(ids))})
        shared = sum(len(a & b) for a,b in itertools.combinations(sets,2))
        cluster_shared = sum(len(a & b) for a,b in itertools.combinations(cluster_sets,2))
        current = '20260105' in aid
        protocols.append(assess({'protocol_id': 'UP_'+aid,
            'package_group_id': 'RNA3DB', 'source_protocol': aid,
            'source_hashes_verified': True, 'workflow': flows['RNA3DB'], 'partitions': parts,
            'cross_partition_key_overlap': shared+cluster_shared,
            'overlap_key_basis': 'RELEASED_CHAIN_ID_AND_COMPONENT_ID_NOT_SEQUENCE_HASH',
            'missing_reference_release': not current,
            'reference_coordinate_artifact_uid': by_id['RNA3DB_20260105_rna3db_mmcifs']['artifact_uid'] if current else None,
            'usage_recipe': {'loader': 'tarfile + json; role -> component -> chain ID',
                'partition_source': 'RELEASED_SPLIT_JSON', 'matching_coordinate_release_required': True,
                'resplitting': False, 'rows_dropped': 0},
            'independent_original_assay_count': None,
            'limitations': ['Structure correspondence/masks and a 3D adapter remain separate execution requirements',
                            'Empty released validation partition retained, not synthesized']}))
    # Check Parquet schema for materialized benchmark role columns, not the HF
    # transport split name "train". Do not read/normalize sequences or labels.
    import pyarrow.parquet as pq
    for row in inventory:
        if row['filename'].endswith('.parquet'):
            path = root/private[row['artifact_uid']]['path']
            parquet = pq.ParquetFile(path)
            fields = parquet.schema_arrow.names
            roles = [c for c in fields if c.lower() in ('split','partition','fold','set','usage')]
            row.update(n_rows=parquet.metadata.num_rows, partition_columns=roles,
                       split_state='PARTITION_COLUMN_REQUIRES_VALUE_AND_WORKFLOW_REVIEW' if roles else 'NO_MATERIALIZED_BENCHMARK_SPLIT_COLUMN')
        elif row['asset_id'] in ('P0_MIR_KLIMENTOVA_MIRROR','P0_MIR_KLIMENTOVA_ZENODO'):
            row['split_state']='EXTERNAL_TEST_ONLY_TRAINING_PROTOCOL_NOT_BOUND_MIRROR_NOT_INDEPENDENT'
        elif row['asset_id'] == 'ORTHRUS_MRL_ISOFORM_14708163':
            row['split_state'] = 'AUTHOR_SPLIT_RULE_AND_EXPLORATORY_RECONSTRUCTION_EXIST_NOT_FIXED_OFFICIAL_PARTITIONS'
        elif 'part-' in row['filename'] or row['filename'].endswith(('.sha256','SHA256SUMS.txt')):
            row['split_state'] = 'ARCHIVE_TRANSPORT_PART_OR_CHECKSUM_NOT_A_SAMPLE_PARTITION'
        elif row['asset_id'] in ('A0005','A0007','A0008','WANG_ZERO_738bc3a1b453'):
            with zipfile.ZipFile(root/private[row['artifact_uid']]['path']) as archive:
                names = archive.namelist()
                row['archive_member_count'] = len(names)
                row['named_partition_candidate_count'] = sum(bool(re.search(r'(^|[/_.-])(train|test|val|valid|validation)([/_.-]|$)',n,re.I)) for n in names)
            row['split_state'] = 'NAMED_ARCHIVE_PARTITION_CANDIDATES_CONTENT_RECIPE_UNRESOLVED'
    rmdb_ids=['HF_077f265b2add15269941','HF_e567b1f79ef75075abec']
    rmdb_parts=[];rmdb_keys=[]
    for aid,role in zip(rmdb_ids,['train','test']):
        asset=by_id[aid];uid=asset['artifact_uid']
        file=pq.ParquetFile(root/private[uid]['path'])
        fields=file.schema_arrow.names
        target=next((n for n in ['reactivity','reactivity_data','target','label'] if n in fields),None)
        exact=set()
        if 'sequence' in fields:
            for batch in file.iter_batches(batch_size=2048,columns=['sequence']):
                for seq in batch.column(0).to_pylist():
                    if isinstance(seq,str):exact.add(hashlib.sha256(seq.encode()).digest())
        rmdb_keys.append(exact)
        rmdb_parts.append({'artifact_uid':uid,'member':None,'sha256':verified[uid]['sha256'],
            'split':role,'n_rows':file.metadata.num_rows,'input_columns':['sequence'] if 'sequence' in fields else [],
            'target_column':target,'invalid_rows':0})
    protocols.append(assess({'protocol_id':'UP_RNAGYM_RMDB_S40','package_group_id':'RNAGYM_RMDB',
        'source_protocol':'RMDB_s40_original_train_test','source_hashes_verified':True,
        'workflow':flows['RNAGYM'],'partitions':rmdb_parts,
        'cross_partition_key_overlap':len(rmdb_keys[0]&rmdb_keys[1]),
        'overlap_key_basis':'EXACT_RAW_SEQUENCE_BYTES',
        'usage_recipe':{'loader':'pyarrow.parquet','input':'sequence','target_kind':'PER_NUCLEOTIDE_PROBING',
                        'resplitting':False,'rows_dropped':0,'scalar_mlp_applicable':False},
        'independent_original_assay_count':None,
        'limitations':['Shared sequences must not be dismissed without reviewed condition identity',
                       'Token targets require a nucleotide-level adapter and mask; not pooled scalar fitness']}))
    related = defaultdict(list)
    for protocol in protocols:
        for uid in {p['artifact_uid'] for p in protocol['partitions']}:
            related[uid].append(protocol)
    for row in inventory:
        items = related[row['artifact_uid']]
        if items:
            row['split_state'] = 'ACTUAL_UPSTREAM_PARTITIONS_VERIFIED'
            row['protocols_observed'] = len(items)
            row['admitted_upstream_protocols'] = sum(p['admitted_upstream_reuse'] for p in items)
    return {'schema_version': 'rna_gym.upstream_split_audit.v1', 'policy_id': POLICY_ID,
        'snapshot_date': '2026-10-28', 'scope': 'USER_AUTHORIZED_UPSTREAM_PROTOCOL_REUSE_NOT_FORMAL_CORE',
        'raw_rows_included': False, 'raw_files_changed': False, 'rows_dropped': 0,
        'formal_core_admitted_by_this_audit': 0, 'rights_or_human_signatures_generated': False,
        'summary': {'local_file_versions': len(inventory),
            'protocols_observed': len(protocols),
            'protocols_admitted_upstream_reuse': sum(p['admitted_upstream_reuse'] for p in protocols),
            'protocols_held': sum(not p['admitted_upstream_reuse'] for p in protocols),
            'admitted_by_package': dict(Counter(p['package_group_id'] for p in protocols if p['admitted_upstream_reuse'])),
            'count_unit': 'VERSIONED UPSTREAM PARTITION PROTOCOLS, NOT INDEPENDENT ASSAYS'},
        'workflow_sources': list(flows.values()), 'inventory': inventory,
        'protocols': protocols, 'scan_limits': scan_limits}


def verify(report):
    if report['policy_id'] != POLICY_ID or report['formal_core_admitted_by_this_audit'] != 0:
        raise ValueError('POLICY_SCOPE_MISMATCH')
    ids = [p['protocol_id'] for p in report['protocols']]
    if len(ids) != len(set(ids)):
        raise ValueError('DUPLICATE_PROTOCOL_ID')
    for protocol in report['protocols']:
        checked = assess(protocol)
        for key in ('status','admitted_upstream_reuse','issues','formal_core_admitted','formal_leaderboard_eligible',
                    'admission_scope','policy_id','evaluation_partition','evaluation_claim',
                    'rights_approval_generated','human_signature_generated'):
            if checked[key] != protocol[key]:
                raise ValueError('STALE_ADMISSION_DECISION:'+protocol['protocol_id'])
    if report['summary']['protocols_admitted_upstream_reuse'] != sum(p['admitted_upstream_reuse'] for p in report['protocols']):
        raise ValueError('STALE_SUMMARY')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', type=Path)
    parser.add_argument('--private-manifest', type=Path)
    parser.add_argument('--raw-hashes', type=Path)
    parser.add_argument('--workflow-sources', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if args.verify:
        report = json.loads(args.verify.read_text()); verify(report)
        print(json.dumps({'state':'PASS_FROZEN_UPSTREAM_REUSE_REGISTRY',**report['summary']})); return
    if not all([args.private_manifest,args.raw_hashes,args.workflow_sources,args.out]):
        parser.error('audit requires existing private paths, raw hashes, workflow pins and --out')
    out = args.out.resolve()
    if not out.is_relative_to(ROOT/'runs') or out.exists():
        raise ValueError('NEW_IGNORED_OUTPUT_REQUIRED')
    report = run(ROOT,args.private_manifest,args.raw_hashes,args.workflow_sources)
    verify(report);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report['summary'],indent=2))


if __name__ == '__main__':
    main()
