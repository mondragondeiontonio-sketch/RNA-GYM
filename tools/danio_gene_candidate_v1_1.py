"""New label-blind gene/exact-sequence candidate split; NEVER replaces legacy folds."""
from collections import defaultdict, Counter
import csv
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"runs/20261102_blocker_optimization_v1"
SPLIT=ROOT/"data/splits/RNAGYM_DANIO_GENE_GROUPED_V1_1"


def digest(s): return hashlib.sha256(s.encode()).hexdigest()


def build_assignments(rows):
    parent=list(range(len(rows))); seen={}
    def find(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]]; i=parent[i]
        return i
    keys_by_row=[]
    for i,r in enumerate(rows):
        genes=set(re.findall(r"ENSDARG[0-9]+"," ".join(r["source_insert_ids"])))
        genes.update("symbol:"+x for x in r["source_genes"] if x and x.upper() not in ["NA","NAN","UNKNOWN","NONE"])
        keys=[("sequence",r["sequence_sha256"])]+[("gene",g) for g in genes]
        keys_by_row.append((keys,sorted(genes)))
        for k in keys:
            if k in seen: parent[find(i)]=find(seen[k])
            else: seen[k]=i
    component=defaultdict(list); genes_by_component=defaultdict(set)
    for i,r in enumerate(rows):
        component[find(i)].append(r["record_id"]); genes_by_component[find(i)].update(keys_by_row[i][1])
    gids={i:digest("\n".join(sorted(records))) for i,records in component.items()}
    assignments=[]
    for i,r in enumerate(rows):
        group=gids[find(i)]; genes=genes_by_component[find(i)]
        fold=int(digest("danio-gene-v1.1-seed20261102:"+group),16)%10 if genes else -1
        assignments.append(dict(record_id=r["record_id"],sequence_sha256=r["sequence_sha256"],group_id=group,gene_ids_json=json.dumps(sorted(genes)),outer_fold=fold,status="CANDIDATE" if fold>=0 else "QUARANTINE_NO_GENE_ID"))
    return assignments


def immutable(path,text):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_text()!=text: raise ValueError("IMMUTABLE_SPLIT_CONFLICT_NEW_VERSION_REQUIRED")
    else: path.write_text(text)


def run():
    source=OUT/"danio_source_row_mapping.tsv"
    rows=list(csv.DictReader(source.open(),delimiter="\t"))
    for r in rows:
        r["source_insert_ids"]=json.loads(r["source_insert_ids"]); r["source_genes"]=json.loads(r["source_genes"])
        if int(r["compatible_label_rows"])!=1: raise ValueError("SOURCE_IDENTITY_NOT_UNIQUE")
    assignments=build_assignments(rows); audits=[]
    for fold in range(10):
        keys=defaultdict(set); counts=Counter()
        for r in assignments:
            if r["outer_fold"]<0: continue
            role="test" if r["outer_fold"]==fold else "validation" if r["outer_fold"]==(fold+1)%10 else "train"
            counts[role]+=1
            for k in [("seq",r["sequence_sha256"]),("group",r["group_id"])]+[("gene",g) for g in json.loads(r["gene_ids_json"])]: keys[k].add(role)
        leaking={str(k):sorted(v) for k,v in keys.items() if len(v)>1}
        assert not leaking
        audits.append(dict(test_fold=fold,counts=dict(counts),cross_role_gene_sequence_component_keys=0))
    import io
    f=io.StringIO(); w=csv.DictWriter(f,fieldnames=list(assignments[0]),delimiter="\t",lineterminator="\n"); w.writeheader(); w.writerows(assignments)
    immutable(SPLIT/"assignments.tsv",f.getvalue())
    summary=dict(protocol="RNAGYM_DANIO_GENE_GROUPED_V1_1",status="TECHNICAL_SPLIT_PASS_NOT_SCIENTIFIC_ADMISSION",n_records=len(rows),n_groups=len({r["group_id"] for r in assignments}),quarantined_n=sum(r["outer_fold"]<0 for r in assignments),source_row_mapping_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),assignments_sha256=digest(f.getvalue()),grouping="connected components of exact normalized sequence + recovered Ensembl gene and gene symbol",split_rule="label-blind sha256 group assignment; test_fold=f; validation=(f+1)%10; others=train",difficulty="CANDIDATE_GENE_HELD_OUT_NOT_HOMOLOGY_CLEARED",audits=audits,existing_splits_modified=False,model_evaluations_performed=0,human_approved=False,formal_score_eligible=False)
    text=json.dumps(summary,indent=2)+"\n"; immutable(SPLIT/"split_summary.json",text); immutable(OUT/"danio_gene_candidate_summary.json",text); print(summary)

if __name__=="__main__":run()
