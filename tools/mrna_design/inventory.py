"""Source-bound inventory of public registries and optional authorized local assets."""
import argparse
import csv
from pathlib import Path
from collections import Counter
from rna_gym.research_v06.provenance import (read_json,sha256_file,write_immutable,
                                            write_table,receipt,validate_source)


def inventory(root,out):
    root=Path(root);out=Path(out);out.mkdir(parents=True,exist_ok=True)
    names=['utr_legacy_102.json','utr_revised_87_metadata.json','utr_historical_result_status.json',
           'dataset_catalog.json','task_baselines_and_admission_198.csv']
    records=[]
    for name in names:
        path=root/'data/registries'/name
        records.append({'path':str(path.relative_to(root)),'exists':path.is_file(),
                        'sha256':sha256_file(path) if path.is_file() else 'MISSING',
                        'scientific_status':'EXISTING_REVIEW_STATUS_NOT_AUTO_ADMITTED',
                        'local_only':False})
    legacy=read_json(root/'data/registries/utr_legacy_102.json')['datasets']
    history=read_json(root/'data/registries/utr_historical_result_status.json')
    counts={'legacy_views':len(legacy),'regions':dict(Counter(r['row']['region'] for r in legacy)),
            'view_records':sum(r['profile']['n'] for r in legacy),
            'revised_metadata_views':87,'original_task_rows':198,'canonical_ids':28,
            'candidate_248_rows':'NOT_LOCATED_IN_AVAILABLE_ROOTS',
            'formal_admitted':0,'historical_model_head_task_combinations':history['matrix_rows'],
            'historical_fold_metrics':history['full_fold_metric_rows'],
            'historical_reporting_status':history['reporting_status'],
            'count_semantics':'NON_ADDITIVE_VIEW_COUNTS_NOT_INDEPENDENT_ASSAYS'}
    write_table(out/'00_ASSET_STATUS.tsv',records)
    write_immutable(out/'inventory.json',counts)
    receipt(out,'public_registry_inventory',{'root':'REPOSITORY','registry_files':records},
            [out/'00_ASSET_STATUS.tsv',out/'inventory.json'],{'views':len(legacy)})
    return counts


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('.'));p.add_argument('--out',type=Path,required=True)
    p.add_argument('--config',type=Path);p.add_argument('--raw-root',type=Path)
    p.add_argument('--dry-run',action='store_true');p.add_argument('--verify-only',action='store_true')
    a=p.parse_args()
    if a.verify_only:
        from .__main__ import verify_receipt
        print(verify_receipt(a.out))
    elif a.config:
        print(validate_source(read_json(a.config),a.raw_root))
    elif a.dry_run: print('NO_WRITE_REGISTRY_INVENTORY')
    else: print(inventory(a.root,a.out))


if __name__=='__main__':main()
