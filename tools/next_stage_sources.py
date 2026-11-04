"""Primary Crossref/EuropePMC discovery receipts. Cached; no dataset download."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import time
import urllib.parse
import urllib.request
from tools.next_stage_taxonomy import OUT,write_json

DEST=OUT/"primary_sources"
QUERIES={
    "danio":"Reimao Pinto 2025 zebrafish embryo 5 UTR translation ribosome",
    "andreasson":"Comprehensive sequence-to-function mapping of cofactor-dependent RNA catalysis in the glmS ribozyme",
    "domingo":"Domingo 2018 tRNA fitness epistasis",
    "karner":"Karner 3 UTR mRNA decay massively parallel",
    "archiveii":"ArchiveII RNA secondary structure benchmark Mathews"}
DOIS={"andreasson":"10.1038/s41467-020-15540-1","saluki":"10.1186/s13059-022-02811-x","sugimoto":"10.1038/s41594-022-00819-2","persist":"10.1038/s41467-022-28776-w"}


def fetch(name,url,suffix="json"):
    DEST.mkdir(exist_ok=True)
    file=DEST/(name+"."+suffix); receipt=DEST/(name+"_receipt.json")
    if file.exists() and receipt.exists():
        r=json.loads(receipt.read_text()); assert hashlib.sha256(file.read_bytes()).hexdigest()==r["sha256"]; return file
    if receipt.exists(): return None
    try:
        request=urllib.request.Request(url,headers={"User-Agent":"RNA-Gym-local-scientific-evidence/1.0"})
        with urllib.request.urlopen(request,timeout=35) as response:
            data=response.read(15*1024*1024+1)
            if len(data)>15*1024*1024: raise ValueError("SOURCE_RESPONSE_BUDGET")
        file.write_bytes(data)
        write_json(receipt,dict(url=url,sha256=hashlib.sha256(data).hexdigest(),bytes=len(data),status="FETCHED_PRIMARY_SOURCE",utc=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())))
        return file
    except Exception as exc:
        write_json(receipt,dict(url=url,status="UNAVAILABLE",error=repr(exc)))
        return None


def discovery(item):
    key,q=item; url="https://api.crossref.org/works?"+urllib.parse.urlencode({"query.bibliographic":q,"rows":3})
    path=fetch(key+"_crossref_discovery",url)
    if path:
        data=json.loads(path.read_text())["message"]["items"]
        return key,[dict(title=x.get("title"),doi=x.get("DOI"),year=x.get("published"),author=x.get("author",[])[:3]) for x in data]
    return key,[]


def fulltext(item):
    key,doi=item
    metadata=fetch(key+"_crossref_work","https://api.crossref.org/works/"+urllib.parse.quote(doi,safe=""))
    query="DOI:"+doi
    lookup=fetch(key+"_europepmc_lookup","https://www.ebi.ac.uk/europepmc/webservices/rest/search?"+urllib.parse.urlencode({"query":query,"format":"json"}))
    result=dict(doi=doi,crossref=str(metadata) if metadata else None,fulltext=None,pmcid=None)
    if lookup:
        hits=json.loads(lookup.read_text()).get("resultList",{}).get("result",[])
        if hits:
            hit=hits[0]; result.update(pmcid=hit.get("pmcid"),title=hit.get("title"),pmid=hit.get("id"))
            if hit.get("pmcid"):
                p=fetch(key+"_primary_fulltext","https://www.ebi.ac.uk/europepmc/webservices/rest/"+hit["pmcid"]+"/fullTextXML","xml")
                result["fulltext"]=str(p) if p else None
    return key,result


def run():
    with ThreadPoolExecutor(max_workers=4) as pool:
        discovered=dict(pool.map(discovery,QUERIES.items()))
        papers=dict(pool.map(fulltext,DOIS.items()))
    write_json(DEST/"discovery_candidates.json",discovered)
    write_json(DEST/"verified_doi_sources.json",papers)
    print(json.dumps(dict(discovery=discovered,papers=papers),ensure_ascii=False)[:9500])

if __name__=="__main__":run()
