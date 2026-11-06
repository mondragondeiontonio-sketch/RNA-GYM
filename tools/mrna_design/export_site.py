"""Deterministic public-safe status export from public registry metadata only."""
import argparse
import json
from pathlib import Path
from rna_gym.research_v06.provenance import read_json, canonical_bytes, immutable_text


def payload(root):
    rows=read_json(Path(root)/'data/registries/utr_legacy_102.json')['datasets']
    return {'schema':'rnagym.mrna_design.public_status.v06','date':'2026-11-06',
            'formal_admitted':0,'universal_score':None,'legacy_utr_views':len(rows),
            'legacy_view_records':sum(r['profile']['n'] for r in rows),
            'count_semantics':'VIEWS_NOT_INDEPENDENT_ASSAYS',
            'implemented':['source_rights_validation','therna_import','axis_splits',
                           'bounded_cpu_baselines','prediction_replay','polya_label_gate'],
            'scientific_holds':['original_assay_identity','replicate_noise',
                'source_copy_rights','unseen_cell_descriptors','polya_measured_labels'],
            'penta_raw':'BLOCKED_MISSING_RAW_TARGET','candidate_248':'NOT_LOCATED',
            'real_statistics':'LOCAL_ONLY_PENDING_PUBLICATION_RIGHTS',
            'figures':{'1':'PARTIAL_PUBLIC_METADATA','2':'BLOCKED_REVIEWED_COMPARISON',
              '3':'LOCAL_EXPLORATORY_NOT_PUBLISHABLE','4':'BLOCKED_MATCHED_MATRIX_GPU_SCOPE',
              '5':'BLOCKED_PERSIST_VERSION_AND_TAIL_EVIDENCE','6':'BLOCKED_INDEPENDENT_VALIDATION'},
            'new_gpu_hours':0,'automatically_merged':False}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path('.'))
    p.add_argument('--verify',action='store_true');a=p.parse_args()
    text=canonical_bytes(payload(a.root)).decode();out=a.root/'site/data/mrna-design-v06.json'
    if a.verify:
        if out.read_text()!=text:raise SystemExit('PUBLIC_SITE_EXPORT_MISMATCH')
    else:immutable_text(out,text)
    print('PUBLIC_SITE_V06_VERIFIED')


if __name__=='__main__':main()
