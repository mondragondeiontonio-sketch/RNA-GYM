"""GEO-title candidates, NOT barcode-verified scientific sample admission."""
import csv
import json
import re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"runs/20261102_blocker_optimization_v1"

def run():
    text=(OUT/"persist_geo_all.source").read_text()
    blocks=[s for s in re.split(r"(?m)(?=\^SAMPLE = )",text) if s.startswith("^SAMPLE = ")]
    samples=[]
    for b in blocks:
        accession=b.splitlines()[0].split(" = ")[1]
        title=next((s.split(" = ",1)[1] for s in b.splitlines() if s.startswith("!Sample_title = ")),"")
        samples.append(dict(accession=accession,title=title,body=b))
    original=list(csv.DictReader((ROOT/"runs/20261023_131628/reports/persist_sample_map.tsv").open(),delimiter="\t"))
    used=[r for r in original if r["used_in_author_ribosome_load"]=="True" or r["used_in_author_half_life"]=="True"]
    result=[]
    for r in used:
        if r["used_in_author_ribosome_load"]=="True":
            target="Polysome fraction "+str(int(float(r["source_fraction"])))
            reason="explicit fraction ordinal; source barcode not confirmed in GEO"
        else:
            m=re.fullmatch(r"stability_long_([0-9]+)",r["sample_name"]); i=int(m.group(1))-1
            target=f"RNA in-cell timepoint {i%5+1} replicate {i//5+1}"
            reason="candidate from source layout/replicate ordinal; absolute-hour and barcode correspondence not approved"
        hits=[s for s in samples if s["title"]==target]
        indexhits=[s["accession"] for s in samples if r["source_index"] in s["body"]]
        result.append(dict(sample_name=r["sample_name"],source_index=r["source_index"],source_time_hours=r["source_time_hours"],source_fraction=r["source_fraction"],candidate_GSM=hits[0]["accession"] if len(hits)==1 else "",candidate_title=target,exact_title_candidates=len(hits),barcode_string_GEO_candidates=json.dumps(indexhits),status="CANDIDATE_NOT_APPROVED_EXACT_INDEX_JOIN",reason=reason))
    with (OUT/"persist_GSM_candidates.tsv").open("w") as f:
        w=csv.DictWriter(f,fieldnames=list(result[0]),delimiter="\t"); w.writeheader(); w.writerows(result)
    path=ROOT/"runs/20261023_131628/reports/persist_label_comparison.tsv"
    comparisons=[r for r in csv.DictReader(path.open(),delimiter="\t") if r["raw_target_column"]=="target_in_cell_half_life"]
    ratios=[float(r["raw_original_label"])/float(r["source_original_label"]) for r in comparisons]
    summary=dict(GEO_sample_records=len(samples),author_selected_libraries=len(used),unique_title_candidates=sum(r["exact_title_candidates"]==1 for r in result),barcode_verified_libraries=sum(len(json.loads(r["barcode_string_GEO_candidates"]))==1 for r in result),sample_join_status="PARTIAL_CANDIDATE_ONLY",half_life_version_status="HOLD_NOT_A_CONSTANT_SCALE_ERROR",ratio_min=min(ratios),ratio_max=max(ratios),constant_ratio_range=max(ratios)-min(ratios),source_labels_modified=False,original_split_modified=False,scientific_admitted=False)
    (OUT/"persist_blocker_update.json").write_text(json.dumps(summary,indent=2)+"\n"); print(summary)

if __name__=="__main__":run()
