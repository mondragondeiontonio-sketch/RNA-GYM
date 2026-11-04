"""Residue-aligned RNA3DB CMP/DMP anchor; C4-prime geometry, NOT base pairs."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import numpy as np
from tools.next_stage_taxonomy import ROOT, OUT, write_json, write_tsv, read_table

POLICY = dict(atom="C4\'", distance="Euclidean Angstrom; first deposited model only", contact_threshold_angstrom=8.0, contact_comparison="strictly_less_than", exclude_sequence_separation_le=3, evaluation_triangle="strict_upper", coordinate_frame="deposited single chain; no assembly reconstruction", altloc="highest positive occupancy; equal-occupancy distinct coordinates invalidate residue", modified_residues="map only explicit CCD parent A/C/G/U; otherwise mask, never invent parent", missing="full polymer sequence retained; absent representative atom masked", ssp_labels_generated=False)


def labels_from_columns(d):
    sequences=d.get("_entity_poly.pdbx_seq_one_letter_code_can",[])
    if len(sequences)!=1: raise ValueError("SINGLE_CHAIN_ENTITY_SEQUENCE_REQUIRED")
    sequence="".join(sequences[0].split()).upper()
    if not sequence or len(sequence)>4096 or set(sequence)-set("ACGUTN"):
        raise ValueError("UNSUPPORTED_FULL_POLYMER_SEQUENCE")
    # T->U is a recorded representation view, never a raw-file rewrite.
    sequence=sequence.replace("T","U")
    prefix="_atom_site."
    n=len(d[prefix+"Cartn_x"])
    def col(key,default="?"):
        values=d.get(prefix+key,[default]*n)
        if len(values)!=n: raise ValueError("ATOM_COLUMN_LENGTH")
        return values
    cols={k:col(k) for k in ["label_seq_id","auth_seq_id","label_comp_id","label_atom_id","label_asym_id","auth_asym_id","label_alt_id","pdbx_PDB_ins_code","Cartn_x","Cartn_y","Cartn_z","occupancy","pdbx_PDB_model_num"]}
    chains=set(cols["label_asym_id"])
    if len(chains)!=1: raise ValueError("MULTICHAIN_NEEDS_EXPLICIT_ENTITY_BINDING")
    models=sorted(set(cols["pdbx_PDB_model_num"]),key=lambda x:int(x))
    model=models[0]
    ids=d.get("_chem_comp.id",[])
    parents=d.get("_chem_comp.mon_nstd_parent_comp_id",["?"]*len(ids))
    parent=dict(zip(ids,parents))
    candidates=defaultdict(list); identities=defaultdict(set); masked_unknown=set(); all_positions=set()
    for a in range(n):
        if cols["pdbx_PDB_model_num"][a]!=model: continue
        raw=cols["label_seq_id"][a]
        if raw in ["?","."]: continue
        pos=int(raw)-1
        if not 0<=pos<len(sequence): raise ValueError("LABEL_SEQ_ID_OUT_OF_FULL_SEQUENCE")
        all_positions.add(pos)
        comp=cols["label_comp_id"][a]
        canonical=comp if comp in "ACGU" and len(comp)==1 else parent.get(comp)
        if canonical not in ["A","C","G","U"]:
            masked_unknown.add(pos); continue
        if sequence[pos]!=canonical: raise ValueError("RESIDUE_SEQUENCE_MISMATCH:"+str(pos+1))
        identities[pos].add((cols["label_asym_id"][a],cols["auth_asym_id"][a],cols["auth_seq_id"][a],cols["pdbx_PDB_ins_code"][a],comp))
        if cols["label_atom_id"][a] != POLICY["atom"]: continue
        xyz=np.array([float(cols[k][a]) for k in ["Cartn_x","Cartn_y","Cartn_z"]])
        occ=float(cols["occupancy"][a])
        if occ>0 and np.isfinite(occ) and np.isfinite(xyz).all(): candidates[pos].append((occ,cols["label_alt_id"][a],xyz,a))
    xyz=np.full((len(sequence),3),np.nan); residue_rows=[]
    for pos in range(len(sequence)):
        choices=candidates[pos]; reason="MISSING_C4_PRIME"; chosen=None
        if len(identities[pos])>1: reason="AMBIGUOUS_RESIDUE_IDENTITY"
        elif pos in masked_unknown: reason="UNKNOWN_MODIFIED_PARENT"
        elif choices:
            best=max(c[0] for c in choices); top=[c for c in choices if c[0]==best]
            if len(top)>1 and any(not np.array_equal(c[2],top[0][2]) for c in top): reason="AMBIGUOUS_ALTLOC_TIE"
            else:
                chosen=sorted(top,key=lambda c:(c[1],c[3]))[0]; xyz[pos]=chosen[2]; reason="VALID"
        identity=sorted(identities[pos])[0] if len(identities[pos])==1 else ("",)*5
        residue_rows.append(dict(sequence_index_0=pos,label_seq_id=pos+1,base=sequence[pos],label_asym_id=identity[0],auth_asym_id=identity[1],auth_seq_id=identity[2],insertion_code=identity[3],component_id=identity[4],coordinate_valid=reason=="VALID",reason=reason,atom_row=chosen[3] if chosen else "",altloc=chosen[1] if chosen else ""))
    observed=np.isfinite(xyz).all(axis=1)
    delta=np.abs(np.arange(len(sequence))[:,None]-np.arange(len(sequence))[None,:])
    valid=observed[:,None]&observed[None,:]&(delta>POLICY["exclude_sequence_separation_le"])
    distance=np.linalg.norm(xyz[:,None,:]-xyz[None,:,:],axis=-1).astype(np.float32)
    distance[~valid]=np.nan
    contact=np.zeros(valid.shape,dtype=np.int8); contact[valid]=(distance[valid]<POLICY["contact_threshold_angstrom"]).astype(np.int8)
    audit=dict(full_sequence_length=len(sequence),observed_residues=len(all_positions),valid_c4_residues=int(observed.sum()),missing_or_masked_residues=int((~observed).sum()),valid_upper_pairs=int(np.triu(valid,1).sum()),unknown_modified_parent_positions=sorted(p+1 for p in masked_unknown),selected_model=model,all_models=models,chain=next(iter(chains)),sequence_residue_alignment="PASS_EXPLICIT_LABEL_SEQ_ID_AND_MONOMER_CHECK",sequence_view="canonical full polymer; explicit TtoU; missing residues NOT deleted")
    return sequence,xyz,distance,contact,valid,residue_rows,audit


def load_cif(path):
    import gemmi
    block=gemmi.cif.read_file(str(path)).sole_block()
    tags=["_entry.id","_entity_poly.pdbx_seq_one_letter_code_can","_chem_comp.id","_chem_comp.mon_nstd_parent_comp_id"]
    tags += ["_atom_site."+k for k in ["label_seq_id","auth_seq_id","label_comp_id","label_atom_id","label_asym_id","auth_asym_id","label_alt_id","pdbx_PDB_ins_code","Cartn_x","Cartn_y","Cartn_z","occupancy","pdbx_PDB_model_num"]]
    return {tag:[gemmi.cif.as_string(v) for v in block.find_values(tag)] for tag in tags if len(block.find_values(tag))}


def run():
    from sklearn.metrics import average_precision_score, f1_score
    directory=OUT/"structure_anchor"; directory.mkdir(exist_ok=False)
    prior=ROOT/"runs/20261023_043639/reports/structure_review"
    source=json.loads((prior/"summary.json").read_text())
    roles={r["observation_id"]:r for r in read_table(ROOT/"data/splits/RNAGYM_RNA3DB_RANDOM_D1_V1_1/assignments.tsv")}
    audits=[]; results=[]; group_seen=set()
    for s in source["samples"]:
        p=prior/"cache"/(s["member_sha256"]+".cif")
        assert hashlib.sha256(p.read_bytes()).hexdigest()==s["member_sha256"]
        d=load_cif(p); seq,xyz,dist,contact,valid,residues,audit=labels_from_columns(d)
        entry=d["_entry.id"][0]; role=roles[entry]
        # Also bind full sequence to the existing content-addressed split manifest.
        split_hash=hashlib.sha256(seq.encode()).hexdigest()
        assert split_hash==role["equivalent_input_sha256"], (entry,split_hash,role)
        stem=entry; np.savez_compressed(directory/(stem+".npz"),sequence=np.array(seq),coordinates=xyz,distance=dist,contact=contact,valid_mask=valid)
        write_tsv(directory/(stem+"_residues.tsv"),residues)
        audit.update(entry_id=entry,source_member=s["member"],source_sha256=s["member_sha256"],role=role["role"],group_id=role["group_id"],split_sequence_hash_verified=True)
        audits.append(audit)
        # Predetermined, parameter-free baseline: NO labels used to fit/tune it.
        # 6*sqrt(sequence separation) Angstrom is only a chain-geometry null.
        gap=np.abs(np.arange(len(seq))[:,None]-np.arange(len(seq))[None,:])
        prediction=(6*np.sqrt(gap)).astype(np.float32)
        probability=np.exp(-prediction/8).astype(np.float32)
        np.savez_compressed(directory/(stem+"_predictions.npz"),distance=prediction,contact_probability=probability)
        mask=np.triu(valid,1); y=contact[mask]; yp=probability[mask]; errors=prediction[mask]-dist[mask]
        # Independently replay every valid pair directly from coordinates (not saved labels).
        pairs=np.argwhere(mask); direct=np.array([np.sqrt(sum((float(xyz[i,k])-float(xyz[j,k]))**2 for k in range(3))) for i,j in pairs])
        replay_mae=float(np.mean(np.abs(prediction[mask]-direct)))
        mae=float(np.mean(np.abs(errors)))
        assert abs(mae-replay_mae)<1e-4
        unique=role["group_id"] not in group_seen; group_seen.add(role["group_id"])
        results.append(dict(entry_id=entry,role=role["role"],group_id=role["group_id"],independent_group_first=unique,n_pairs=len(y),positive_contacts=int(y.sum()),AUPRC=float(average_precision_score(y,yp)) if len(set(y))==2 else None,F1=float(f1_score(y,prediction[mask]<8,zero_division=0)),MAE=mae,RMSE=float(np.sqrt(np.mean(errors**2))),replay_MAE=replay_mae,replay_max_distance_delta=float(np.max(np.abs(direct-dist[mask]))),replay_pass=True,model="fixed_sequence_separation_null_NOT_RNAFM",formal_eligible=False))
    write_json(directory/"label_policy.json",POLICY)
    write_json(directory/"alignment_audit.json",audits)
    write_tsv(directory/"metrics.tsv",results)
    write_json(directory/"summary.json",dict(status="REAL_COORDINATE_LABEL_SCORE_REPLAY_PASS",chains=len(audits),independent_groups=len(group_seen),training_labels_used=0,validation_used_for_tuning=False,protocol="RNAGYM_RNA3DB_RANDOM_D1_V1_1",formal_admitted=False,limitations=["only cached chains; two independent groups; no aggregate leaderboard","parameter-free geometry null, not learned structure model","all three cached chains are validation/test; none repurposed for training","SSP needs actual base-pair annotations; SSI needs partial-signal observation/evaluation masks","underlying structure rights, assembly and scientific review remain separate"]))
    print(results)

if __name__=="__main__": run()
