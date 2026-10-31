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
