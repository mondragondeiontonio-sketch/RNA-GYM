"""Full per-head class counts and fold support; no labels transformed."""
import collections
import json
import pyarrow.parquet as pq
from .core import ROOT,write_tsv,write_json,RUN
from .review import read_reports


def main():
    global_rows=[];fold_rows=[];failed=[]
    for r in read_reports():
        kinds=list(r['target_schema'].values())
        if not kinds or not all(v in ('binary','binary_vector') for v in kinds) or r.get('binary'):continue
        data=pq.read_table(ROOT/r['output_path'],columns=['observation_id','label_json']).to_pylist()
        targets={};global_counts=collections.defaultdict(collections.Counter)
        for row in data:
            heads={};label=json.loads(row['label_json'])
            for k,v in label.items():
                if isinstance(v,list):heads.update({k+':'+str(i):a for i,a in enumerate(v)})
                else:heads[k]=v
            targets[row['observation_id']]=heads
            for h,y in heads.items():global_counts[h][str(y)]+=1
        for h,c in global_counts.items():global_rows.append({'unit':r['unit_id'],'head':h,'class_counts':dict(c),'n':sum(c.values())})
        counts=collections.defaultdict(collections.Counter)
        for batch in pq.ParquetFile((ROOT/r['output_path']).parent/'splits/split_manifest.parquet').iter_batches(batch_size=10000):
            for row in batch.to_pylist():
                for h,y in targets[row['observation_id']].items():counts[(row['protocol'],row['outer_fold'],h)][str(y)]+=1
        for (protocol,fold,head),c in sorted(counts.items()):
            support={float(y) for y in c if y not in ('None','nan')}
            ok=0 in support and 1 in support
            out={'unit':r['unit_id'],'protocol':protocol,'fold':fold,'head':head,'class_counts':dict(c),'two_class_support':ok}
            fold_rows.append(out)
            if not ok:failed.append(out)
    write_tsv(ROOT/'data/audit/classification_label_profiles.tsv',global_rows)
    write_tsv(ROOT/'data/audit/multilabel_split_support.tsv',fold_rows)
    write_json(RUN/'multilabel_support_summary.json',{'heads':len(global_rows),'head_fold_comparisons':len(fold_rows),
        'failures':failed,'all_head_fold_class_support_pass':not failed})
    print('heads',len(global_rows),'head-folds',len(fold_rows),'failures',len(failed))

if __name__=='__main__':main()
