"""Original-author QC comparison with primary-source locators.

Keyword candidates are not silently promoted to performed. A small explicit
review map records statements actually inspected; all other checks remain
unknown or not_reported, never not_performed merely because of silence.
"""
import collections
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .core import ROOT,RUN,file_sha,write_tsv,write_json

CHECKS={
 'read_qc':r'phred|quality|low quality|cutadapt|trimmed|pre-processing',
 'coverage_filter':r'input reads|read counts|coverage|sufficient number of reads|low.abundance',
 'replicate_consistency':r'replicat|reproducib|concordance',
 'label_outlier':r'outlier|aberrant|spurious',
 'experimental_controls':r'negative control|positive control|wild.type control|PhiX',
 'invalid_sequence_filter':r'unexpected|excluded|discarded|non.genomic',
 'structure_qc':r'structure quality|ster[e]?ochem|clash|resolution',
 'construct_mutation_identity':r'consensus sequence|variable positions|genotypes|variant identification|variant.*filtered',
 'sample_dedup':r'duplicat|unique molecule|unique genotypes',
 'homology_dedup':r'homolog|paralog|CD.HIT|sequence similarity',
 'leakage_check':r'leakage|train.*overlap|overlap.*test',
 'label_normalization_split':r'normaliz|standardiz|principal component|cross.validation|divided by|fraction.*cleav'
}

# Local primary text + inspected section (not reviewer signatures).
REVIEWED={
 'PMC9507966.xml':{
  'read_qc':('Sec35','Read1 UMI extraction, demultiplexing and Cutadapt adapter removal.'),
  'coverage_filter':('Sec40','Remove TSS subclusters at <=10% of the most abundant isoform for a gene.'),
  'invalid_sequence_filter':('Sec40','Remove artifactual 5-prime termini with <15% non-genomic G; mitochondrial special case.'),
  'sample_dedup':('Sec35','UMI read-level deduplication was not used; this does NOT establish absence of sample/sequence deduplication.','unknown'),
 },
 'PMC10517338.xml':{
  'construct_mutation_identity':('s2-1','ClinVar preferred coding transcript and exonic UTR coordinates mapped to RefSeq v109.'),
  'invalid_sequence_filter':('s2-1','P/LP clinical classes retained; allele frequency >0.05 in any population discarded.'),
 },
 'PMC9684954.xml':{
  'replicate_consistency':('Sec3','Cross-study concordance examined for the human/mouse half-life compendium.'),
  'label_outlier':('Sec4','A biased study identified with PC1 and excluded from consensus analysis.'),
  'label_normalization_split':('Sec4','Sample standardization, iterative PCA imputation and quantile normalization; published global target construction, not hours.'),
 },
 'PMC7125110.xml':{
  'read_qc':('Sec18','Barcode consensus retained with >=66% sequence agreement per position and binomial p<0.05.'),
  'construct_mutation_identity':('Sec18','Sequence used when Hamming distance to its barcode consensus was <3.'),
  'sample_dedup':('Sec18','Seven chips pooled to determine unique molecule barcodes and per-barcode consensus sequences.'),
 },
 'PMC6193533.xml':{
  'read_qc':('S11','Cutadapt removes constants; PEAR merges reads; low-quality or unexpected-length assemblies discarded.'),
  'coverage_filter':('S11','Discard <9 input reads in either input replicate or zero output reads.'),
  'invalid_sequence_filter':('S11','Discard unexpected substitutions and assembly-length/quality failures; 4,176 genotypes remain.'),
  'construct_mutation_identity':('S11','Unique genotypes called and quantified; expected genotype constraints applied.'),
 },
 'PMC4513843.xml':{
  'coverage_filter':('SEC3-2','Author reports every library variant had enough reads; mean 1127-5873 reads/variant; not a claimed numeric filtering cutoff.'),
  'replicate_consistency':('SEC3-2','Independent Lib-P4 construction and sequencing R2=0.90; systematic deviations discussed.'),
  'experimental_controls':('SEC2-4','Sequencing library includes 8.1% PhiX control.'),
  'label_normalization_split':('SEC3-2','Activity is fraction cleaved from cleavage-state sequence read counts.'),
 },
 'PMC8890501.xml':{
  'invalid_sequence_filter':('','Calculating Fitness from Sequence Data Analysis: variants outside expected randomized positions excluded.'),
  'construct_mutation_identity':('','Calculating Fitness from Sequence Data Analysis: expected-position regular expression defines variants.'),
  'label_normalization_split':('','Calculating Fitness from Sequence Data Analysis: variant counts divided by total matching reads for each replicate.'),
 }
}


def compile_evidence():
    files={}
    mrna=json.loads((ROOT/'data/audit/phase2_mrna_source_evidence.json').read_text())
    for name,item in mrna['evidence_catalog'].items():
        if name.endswith('.xml') and name in REVIEWED:
            path=ROOT/item['path']
            if path.is_file() and file_sha(path)==item['sha256']:
                files[name]={'path':path,'source_url':item['source_url'],'units':[]}
    index=RUN/'primary_methods/index.json'
    bibliographic=json.loads(index.read_text()) if index.exists() else []
    for item in bibliographic:
        if item.get('xml_path'):
            path=ROOT/item['xml_path']
            if file_sha(path)!=item['xml_sha256']:raise ValueError('PRIMARY_XML_HASH_CHANGED')
            files[path.name]={'path':path,'source_url':item['xml_url'],'units':item['assay_ids'],'doi':item.get('doi')}
    evidence=[]
    for name,item in sorted(files.items()):
        root=ET.parse(item['path']).getroot()
        sections=[]
        for sec in root.iter('sec'):
            title=sec.findtext('title','')
            # Include all sections for evidence candidates, but section titles
            # and status clearly distinguish candidates from inspected Methods.
            text=' '.join(' '.join(sec.itertext()).split())
            sections.append((sec.attrib.get('id',''),title,text))
        reviewed=REVIEWED.get(name,{})
        for check,pattern in CHECKS.items():
            candidates=[]
            for anchor,title,text in sections:
                if re.search(pattern,text,re.I):
                    match=re.search(pattern,text,re.I)
                    start=max(0,match.start()-130);end=min(len(text),match.end()+360)
                    candidates.append({'section':anchor,'title':title,'excerpt':text[start:end]})
            status='unknown' if candidates else 'not_reported'
            locator='FULL_PRIMARY_XML_SEARCH; not evidence of author nonperformance'
            method='Unreviewed keyword candidates; primary Methods/Supplement requires targeted confirmation.' if candidates else 'Not found in this acquired main-article XML; supplements/code not exhaustively covered.'
            if check in reviewed:
                values=reviewed[check];locator=values[0];method=values[1]
                status=values[2] if len(values)>2 else 'performed'
                if locator and not any(s[0]==locator for s in sections):
                    raise ValueError('PRIMARY_LOCATOR_NOT_FOUND:'+name+':'+locator)
            evidence.append({'source_document':name,'doi':item.get('doi'),'assay_aliases':item['units'],
                'check':check,'status':status,'evidence_path':str(item['path'].relative_to(ROOT)),
                'evidence_sha256':file_sha(item['path']),'source_url':item['source_url'],
                'section':locator,'method_summary':method,'candidate_excerpts':candidates[:3],
                'upstream_raw_reproducible':False,'raw_reproduction_limit':'author processed release; original read/barcode/experiment data not fully acquired',
                'evidence_review':'CODEX_TEXT_INSPECTION_NOT_HUMAN_ADMISSION' if check in reviewed else 'UNVERIFIED_KEYWORD_CANDIDATE_OR_NOT_REPORTED'})
    evidence.append({'source_document':'PMC9507966.xml','check':'UMI_read_dedup',
        'status':'not_performed','section':'Sec35','method_summary':'Authors explicitly did not use insufficient-diversity UMIs; READ-LEVEL ONLY, not a claim about sample or sequence deduplication.',
        'evidence_path':str(files['PMC9507966.xml']['path'].relative_to(ROOT)),
        'evidence_sha256':file_sha(files['PMC9507966.xml']['path']),
        'evidence_review':'CODEX_TEXT_INSPECTION_NOT_HUMAN_ADMISSION'})
    # Explicit coverage gaps for local sources with no acquired original paper.
    for source in ['miRBench_Manakov2022','miRBench_Hejret2023','miRBench_Klimentova2022',
                   'RMDB_per_experiment','EukaUTR_per_source','RNA3DB_per_PDB_experiment']:
        for check in CHECKS:
            evidence.append({'source_document':source,'check':check,'status':'unknown',
                'method_summary':'Original experiment Methods/supplement not fully bound in this run; benchmark code is not substituted.',
                'upstream_raw_reproducible':False,'evidence_review':'EXPLICIT_PRIMARY_EVIDENCE_GAP'})
    write_tsv(ROOT/'data/audit/original_qc_evidence.tsv',evidence)
    write_json(RUN/'original_qc_summary.json',{'primary_fulltexts':len(files),'bibliographic_sources':len(bibliographic),
        'checks':len(evidence),'status_counts':dict(collections.Counter(r['status'] for r in evidence)),
        'manual_admission_signatures_created':0})
    return evidence
