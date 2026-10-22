#!/usr/bin/env python3
"""Authorize local-quarantine acquisition of explicitly licensed small HF files.

This does NOT authorize benchmark use, original-assay admission or publication
of any observations. Missing/unknown license, gated or oversize assets stay HOLD.
"""
import csv
import hashlib
import json
from pathlib import Path

from rnagym import ROOT


def main():
    audit=ROOT/'data/audit'
    catalog=json.loads((audit/'hf_mirror_catalog.json').read_text())
    with (audit/'hf_file_candidates.csv').open() as f:rd=csv.DictReader(f);fields=rd.fieldnames;candidates=list(rd)
    byid={r['package_group_id']:r for r in catalog}
    licenses={'cc-by-4.0','cc-by-sa-4.0','mit'}
    rights=json.loads((audit/'rights_decisions.json').read_text())
    selected=[]
    for r in candidates:
        if not r['package_group_id'].startswith('MRNA_'):continue
        license=r['collection_license_claim']
        if license not in licenses:continue
        if not r['declared_size_bytes'] or int(r['declared_size_bytes'])>64*1024*1024:continue
        meta=byid[r['package_group_id']]
        rights[r['asset_id']]={'decision':'ALLOW_PUBLIC_QUARANTINE_POC',
            'license':license+' data-collection card claim',
            'evidence_url':meta['official_source_url']+'/blob/'+r['upstream_commit']+'/README.md',
            'evidence_sha256':hashlib.sha256((audit/'hf_mirror_catalog.json').read_bytes()).hexdigest(),
            'evidence_transport':'USER_AUTHORIZED_HF_MIRROR_METADATA',
            'scope':'Only local quarantine acquisition. Original assay rights, label semantics, identity and human admission unresolved.',
            'human_reviewer':None}
        selected.append(r)
    (audit/'rights_decisions.json').write_text(json.dumps(rights,indent=2)+'\n')
    p=audit/'licensed_small_batch.csv'
    with p.open('w',newline='') as f:w=csv.DictWriter(f,fields);w.writeheader();w.writerows(selected)
    run=ROOT/'runs'/(ROOT/'runs/LATEST').read_text().strip()
    script=run/'manifests/download_licensed_batch.sh'
    lines=['#!/usr/bin/env bash','set -u','failed=0']
    for r in selected:
        aid=r['asset_id']
        lines.append(f'.venv/bin/python -u tools/rnagym.py download --manifest data/audit/licensed_small_batch.csv --asset {aid} --execute --allow-unpinned --max-mb 64 --rate-kbps 4096 --retries 2 --out raw_cache || failed=1')
        lines.append(f'.venv/bin/python -u tools/rnagym.py verify --manifest data/audit/licensed_small_batch.csv --asset {aid} --out raw_cache || failed=1')
    lines.append('exit "$failed"')
    script.write_text('\n'.join(lines)+'\n')
    print(json.dumps({'licensed_small_files':len(selected),'declared_bytes':sum(int(r['declared_size_bytes']) for r in selected),'unknown_license_files_downloaded':0,'shell_script':str(script.relative_to(ROOT))}))


if __name__=='__main__':main()
