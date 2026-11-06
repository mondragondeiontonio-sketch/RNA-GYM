"""CPU-only raw-scale replay of completed Frozen OOF using unchanged legacy folds.

This reconstructs an inverse from hash-bound ORIGINAL TRAIN labels; it does not
recover an author's missing stored scaler metadata, change a split, fit a model,
or grant scientific admission. Every output is a new, local-only version.
"""
import argparse
import csv
import gzip
import hashlib
from pathlib import Path
import time
from rna_gym.research_v06.provenance import (ProtocolError, read_json, sha256_file,
    write_immutable, write_table, receipt)
from rna_gym.research_v06.scoring import regression


def train_inverse(raw, scaled, roles):
    import numpy as np
    raw=np.asarray(raw,dtype=float);scaled=np.asarray(scaled,dtype=float)
    roles=np.asarray(roles)
    if not np.isfinite(raw).all() or not np.isfinite(scaled).all():
        raise ProtocolError('NONFINITE_SOURCE_LABEL')
    if not set(roles)<= {'train','val','test'} or not all(np.any(roles==r) for r in ('train','val','test')):
        raise ProtocolError('INVALID_OR_EMPTY_ORIGINAL_ROLE')
    train=raw[roles=='train']
    mean=float(train.mean());std=float(train.std(ddof=0))
    if std<=0:
        raise ProtocolError('CONSTANT_TRAIN_LABEL_NO_INVERSE')
    expected=(raw-mean)/std
    # Fixed numerical tolerance, never optimized using prediction performance.
    if not np.allclose(expected,scaled,rtol=1e-9,atol=1e-10):
        raise ProtocolError('ORIGINAL_TRAIN_SCALER_DOES_NOT_REPLAY_SOURCE_ZSCORE')
    return {'mean':mean,'std_population':std,'n_train':len(train),
            'fit_role':'ORIGINAL_TRAIN_ONLY','max_source_z_error':float(np.max(abs(expected-scaled)))}


def read_dataset(raw_root, record):
    import numpy as np
    base=None;sequences=None;test_fold=None;test_z=None;stats={};proof=[]
    for fold in range(10):
        relative=Path(record['dataset'])/f'fold_{fold}.csv.gz'
        path=(Path(raw_root)/relative).resolve()
        if not path.is_relative_to(Path(raw_root).resolve()):
            raise ProtocolError('RAW_ROOT_ESCAPE')
        digest=sha256_file(path)
        if digest!=record['fold_files'][str(fold)]['sha256']:
            raise ProtocolError('LEGACY_SPLIT_HASH_MISMATCH')
        with gzip.open(path,'rt',newline='') as handle:
            reader=csv.DictReader(handle)
            if reader.fieldnames!=['sequence','raw_label','zscore_label','set','fold']:
                raise ProtocolError('LEGACY_SCHEMA_CHANGED')
            rows=list(reader)
        if any(int(r['fold'])!=fold for r in rows):
            raise ProtocolError('SOURCE_FOLD_COLUMN_MISMATCH')
        y=np.array([float(r['raw_label']) for r in rows])
        z=np.array([float(r['zscore_label']) for r in rows])
        roles=np.array([r['set'] for r in rows])
        hashes=np.array([hashlib.sha256(r['sequence'].encode()).hexdigest() for r in rows])
        if base is None:
            base=y.copy();sequences=hashes.copy()
            test_fold=np.full(len(rows),-1,dtype=int);test_z=np.zeros(len(rows))
        elif not np.array_equal(base,y) or not np.array_equal(sequences,hashes):
            raise ProtocolError('ROW_IDENTITY_CHANGED_BETWEEN_ORIGINAL_FOLDS')
        stats[str(fold)]=train_inverse(y,z,roles)
        mask=roles=='test'
        if np.any(test_fold[mask]!=-1):
            raise ProtocolError('ORIGINAL_TEST_OBSERVATION_REPEATED')
        test_fold[mask]=fold;test_z[mask]=z[mask]
        proof.append({'fold':fold,'raw_sha256':digest,'n':len(rows),
                      'n_test':int(sum(mask))})
    if np.any(test_fold<0):
        raise ProtocolError('INCOMPLETE_ORIGINAL_OUTER_TEST_COVERAGE')
    return {'raw':base,'sequence_sha':sequences,'test_fold':test_fold,
            'test_z':test_z,'stats':stats,'fold_hashes':proof}


def replay_arrays(table, source):
    import numpy as np
    n=len(source['raw'])
    if len(table['sample_id'])!=n or len(set(table['sample_id']))!=n:
        raise ProtocolError('OOF_MISSING_OR_DUPLICATE_SAMPLE')
    ids=np.array([int(v) for v in table['sample_id']])
    if not np.array_equal(np.sort(ids),np.arange(n)):
        raise ProtocolError('OOF_ROW_ID_POPULATION_MISMATCH')
    fold=np.asarray(table['outer_fold'],dtype=int)
    if not np.array_equal(fold,source['test_fold'][ids]):
        raise ProtocolError('OOF_DOES_NOT_USE_ORIGINAL_TEST_ROLES')
    if not np.array_equal(np.array(table['sequence_sha']),source['sequence_sha'][ids]):
        raise ProtocolError('OOF_SEQUENCE_IDENTITY_MISMATCH')
    if not np.array_equal(np.array(table['y_true_raw']),source['raw'][ids]):
        raise ProtocolError('OOF_RAW_LABEL_VERSION_MISMATCH')
    truth_z=np.array(table['y_true_scaled'],dtype=float)
    if not np.allclose(truth_z,source['test_z'][ids],rtol=1e-12,atol=1e-12):
        raise ProtocolError('OOF_SCALED_LABEL_VERSION_MISMATCH')
    prediction=np.array(table['y_pred_scaled'],dtype=float)
    if not np.isfinite(prediction).all():
        raise ProtocolError('INVALID_OOF_PREDICTION')
    mean=np.array([source['stats'][str(f)]['mean'] for f in fold])
    scale=np.array([source['stats'][str(f)]['std_population'] for f in fold])
    raw_prediction=prediction*scale+mean
    return ids,fold,raw_prediction


def replay(matrix, project_root, raw_root, out, registry, historical, datasets=None):
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq
    begin=time.process_time();matrix=Path(matrix);project_root=Path(project_root).resolve()
    out=Path(out)
    if out.exists():
        raise ProtocolError('OUTPUT_VERSION_ALREADY_EXISTS')
    original=read_json(historical)
    if sha256_file(matrix)!=original['matrix_sha256']:
        raise ProtocolError('HISTORICAL_MATRIX_CHANGED')
    records={r['dataset']:r for r in read_json(registry)['datasets']}
    with matrix.open() as handle:units=list(csv.DictReader(handle))
    requested=set(datasets or [r['dataset'] for r in units])
    if requested-set(records) or requested-{r['dataset'] for r in units}:
        raise ProtocolError('DATASET_NOT_BOUND_TO_HISTORICAL_MATRIX')
    out.mkdir(parents=True)
    result=[];scalers={};inputs=[]
    for dataset in sorted(requested):
        source=read_dataset(raw_root,records[dataset]);scalers[dataset]=source['stats']
        for unit in [r for r in units if r['dataset']==dataset]:
            if unit['full_compute_status']!='PASS' or unit['metric_scale']!='zscore_label':
                raise ProtocolError('UNSUPPORTED_HISTORICAL_COMPUTE_OR_SCALE')
            summary_path=(project_root/unit['summary_path']).resolve()
            if not summary_path.is_relative_to(project_root):
                raise ProtocolError('PROJECT_ROOT_ESCAPE')
            if sha256_file(summary_path)!=unit['summary_sha256']:
                raise ProtocolError('HISTORICAL_SUMMARY_HASH_MISMATCH')
            complete=summary_path.parent/'PARQUET_COMPLETE.json'
            if sha256_file(complete)!=unit['parquet_complete_sha256']:
                raise ProtocolError('ORIGINAL_COMPLETION_RECEIPT_HASH_MISMATCH')
            oof=summary_path.parent/'oof_predictions.parquet'
            proof=read_json(oof.with_suffix('.parquet.receipt.json'))
            if sha256_file(oof)!=proof['sha256'] or proof.get('summary_sha256')!=unit['summary_sha256']:
                raise ProtocolError('ORIGINAL_OOF_RECEIPT_HASH_MISMATCH')
            bound=read_json(complete)
            if not any(Path(f['path']).name==oof.name and f['sha256']==proof['sha256'] for f in bound['files']):
                raise ProtocolError('OOF_NOT_BOUND_TO_COMPLETION_RECEIPT')
            columns=['sample_id','outer_fold','sequence_sha','y_true_raw','y_true_scaled',
                     'y_pred_scaled','valid_pred','synthetic_test']
            schema=pq.ParquetFile(oof).schema_arrow.names
            table=pq.read_table(oof,columns=[c for c in columns if c in schema]).to_pydict()
            if not all(table['valid_pred']) or any(table.get('synthetic_test',[])):
                raise ProtocolError('INVALID_OR_SYNTHETIC_HISTORICAL_OOF')
            ids,fold,prediction=replay_arrays(table,source)
            truth=source['raw'][ids]
            name=f"{dataset.split('/')[1].split('_')[0]}_{unit['model']}_{unit['head']}"
            path=out/(name+'.predictions.private.parquet')
            pq.write_table(pa.table({'sample_id':ids,'outer_fold':fold,'label_raw':truth,
                                    'prediction_raw':prediction}),path,compression='zstd')
            metrics=regression(truth,prediction)
            folds=[{'fold':f,**regression(truth[fold==f],prediction[fold==f])} for f in range(10)]
            row={'dataset':dataset,'model':unit['model'],'head':unit['head'],
                 'n_oof':len(truth),'raw_label_unit':records[dataset]['row']['raw_label_unit'],
                 'raw_label_formula':records[dataset]['row']['raw_label_formula'],
                 'inverse_status':'TRAIN_ONLY_RECONSTRUCTED_NOT_ORIGINAL_STORED_METADATA',
                 'scientific_status':'EXPLORATORY_SCIENTIFIC_HOLD','formal_admitted':False,
                 **{k:v for k,v in metrics.items() if k!='n'}}
            write_immutable(out/(name+'.metrics.private.json'),{'pooled_raw':metrics,'folds':folds,
                'original_oof_sha256':proof['sha256'],'raw_label_unit':row['raw_label_unit'],
                'original_status_unchanged':'RAW_INVERSE_PENDING','new_scope':row['inverse_status'],
                'scientific_status':'HOLD','gpu_hours':0})
            result.append(row)
            inputs.append({'dataset':dataset,'model':unit['model'],'head':unit['head'],
                           'summary_sha256':unit['summary_sha256'],'oof_sha256':proof['sha256'],
                           'fold_hashes':source['fold_hashes']})
            print(dataset,unit['model'],unit['head'],'REPLAYED_NO_TRAINING',flush=True)
        del source
    write_table(out/'raw_scale_results.private.tsv',result)
    write_immutable(out/'train_only_inverse.private.json',scalers)
    summary={'models_heads_tasks':len(result),'datasets':len(requested),
             'oof_rows_replayed':sum(r['n_oof'] for r in result),
             'cpu_process_seconds':time.process_time()-begin,'gpu_hours':0,
             'model_forward_calls':0,'splits_changed':False,'formal_admitted':0,
             'inverse':'RECONSTRUCTED_FROM_HASH_BOUND_ORIGINAL_TRAIN_ONLY',
             'original_stored_inverse_metadata':'STILL_NOT_RECOVERED'}
    write_immutable(out/'summary.private.json',summary)
    receipt(out,'legacy_frozen_train_only_raw_replay',{'matrix_sha256':sha256_file(matrix),'units':inputs},
            [p for p in out.iterdir() if p.is_file()],summary)
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('matrix','project-root','raw-root','out','registry','historical'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--dataset',action='append');p.add_argument('--dry-run',action='store_true')
    a=p.parse_args()
    if a.dry_run:print('CPU_ONLY_NO_TRAINING_NO_SPLIT_CHANGES');return
    print(replay(a.matrix,a.project_root,a.raw_root,a.out,a.registry,a.historical,a.dataset))


if __name__=='__main__':main()
