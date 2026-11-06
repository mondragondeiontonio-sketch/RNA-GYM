"""Deterministic synthetic-only panels; never eligible as biological evidence."""
import random
from .provenance import digest_json


def additive_panel(seed=6):
    rng=random.Random(seed)
    result=[]
    for i in range(40):
        seq=''.join(rng.choices('ACGT',k=20))
        for j,c in enumerate(('A','B','C','D','E','F')):
            result.append({'observation_id':str(i)+'_'+c,'sequence_id':digest_json(seq),
                'sequence':seq,'cell_id':c,'label_raw':seq.count('G')*.1+j*.2,
                'timepoint_value':str((i%3)*2),'assay_id':'test-assay',
                'readout_id':'synthetic','unit':'synthetic','missing_reason':'NOT_MISSING'})
    return result
