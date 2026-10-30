"""Strict pilot metric support checks; no test-label tuning or retraining."""
import numpy as np
from tools.pilot_v1_2_run import metric_values as raw_metric_values


def metric_values(y,pred,problem,classes):
    result=raw_metric_values(y,pred,problem,classes)
    if problem=='classification':
        missing=[name for i,name in enumerate(classes) if not np.any(y==i)]
        if missing:
            result['Macro-F1']=None
            result['undefined_reasons']['Macro-F1']='declared test ontology lacks positive support: '+','.join(missing)+'; fixed split retained, no missing-class zero fill'
    return result


def enforce_table_support(rows):
    """Apply the strict rule to the raw runner table before replay/public export.

    Keeps the historical training runner intact. This makes end-to-end reproduction
    automatic; it does not require manually editing a score after each rerun.
    """
    import json
    changed=[]
    for row in rows:
        if row.get('primary_metric')!='Macro-F1' or row.get('Macro-F1') in ('',None):
            continue
        support=json.loads(row.get('class_support') or '{}')
        missing=[name for name,item in support.items() if item['positive']==0]
        if missing:
            changed.append(dict(dataset_id=row['dataset_id'],outer_fold=row['outer_fold'],baseline=row['baseline'],old_macro_f1=row['Macro-F1'],missing_classes=missing))
            row['Macro-F1']=''
            reasons=json.loads(row.get('undefined_reasons') or '{}')
            reasons['Macro-F1']='declared test ontology lacks positive support: '+','.join(missing)+'; fixed split retained, no missing-class zero fill'
            row['undefined_reasons']=json.dumps(reasons,sort_keys=True)
    return changed
