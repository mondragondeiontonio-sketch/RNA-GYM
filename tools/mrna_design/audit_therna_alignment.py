"""Audit shared sequence/cell populations without treating rate and abundance as independent."""
import argparse
import csv
from pathlib import Path
from rna_gym.research_v06.provenance import (canonical_sequence,sha256_file,digest_json,
                                            write_immutable,receipt)


def profile(path, kind):
    sequences=set()
    with Path(path).open(newline='',encoding='utf-8-sig') as f:
        reader=csv.DictReader(f)
        cells={c.split('__')[0] for c in reader.fieldnames if c not in ('sequence','DNA_T0_pooled_count')}
        n=0
        for r in reader:
            n+=1;sequences.add(digest_json(canonical_sequence(r['sequence'])))
    return {'raw_sha256':sha256_file(path),'kind':kind,'rows':n,'cells':cells,'sequences':sequences}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--abundance',type=Path,required=True);p.add_argument('--decay',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    x,y=profile(a.abundance,'abundance'),profile(a.decay,'decay')
    result={'abundance_sha256':x['raw_sha256'],'decay_sha256':y['raw_sha256'],
            'abundance_rows':x['rows'],'decay_rows':y['rows'],
            'shared_sequence_ids':len(x['sequences']&y['sequences']),
            'abundance_only_sequences':len(x['sequences']-y['sequences']),
            'decay_only_sequences':len(y['sequences']-x['sequences']),
            'cell_set_equal':x['cells']==y['cells'],'abundance_cells':sorted(x['cells']),
            'decay_cells':sorted(y['cells']), 'scientific_status':'SCIENTIFIC_HOLD',
            'warning':'RELATED_READOUTS_DIFFERENT_POPULATIONS_NO_SILENT_JOIN_OR_INDEPENDENT_VOTES'}
    a.out.mkdir(parents=True,exist_ok=True);write_immutable(a.out/'alignment.private.json',result)
    receipt(a.out,'therna_endpoint_alignment',{'raw_hashes':[x['raw_sha256'],y['raw_sha256']]},
            [a.out/'alignment.private.json'],{'abundance_rows':x['rows'],'decay_rows':y['rows']})
    print(result)


if __name__=='__main__':main()
