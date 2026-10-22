#!/usr/bin/env python3
"""Diagnose mislabeled text files without guessing encodings or changing raw.

The original uncompressed member SHA is distinct from a diagnostic parser stream.
Unknown non-ASCII encoding is kept HOLD even after byte-level numeric inspection.
"""
import argparse,hashlib,io,json,tarfile,zipfile
from pathlib import Path
from rnagym import ROOT,get_target,immutable_json,read_manifest
from qc_supplemental_formats import table


def diagnose(raw,name):
 if len(raw)>128*1024**2:raise ValueError('recovery size cap')
 first=raw.splitlines()[0] if raw else b''
 separator='\t' if b'\t' in first else ',' if b',' in first else None
 if separator is None:
  return {'member':name,'member_sha256':hashlib.sha256(raw).hexdigest(),'state':'HOLD_TEXT_ENCODING_AND_SCHEMA_AFTER_BYTE_AUDIT','raw_values_rewritten':False,'physical_lines_not_sample_n':len(raw.splitlines()),'actual_rows':None,'ragged_rows':None,'encoding_handling':'No unambiguous first-line tab/comma schema; raw retained without guessing encoding/header or numeric semantics','admission_gate_pass':False}
 digest=hashlib.sha256(raw).hexdigest()
 try:
  raw.decode('utf-8-sig');stream=raw;encoding='UTF-8 decoded strictly';held=False
 except UnicodeDecodeError:
  stream=raw.decode('ascii',errors='backslashreplace').encode('utf-8')
  encoding='UNKNOWN: non-ASCII bytes escaped for diagnostic numeric/shape scan ONLY; no text encoding guessed';held=True
 report=table(io.BytesIO(stream),name,sep=separator)
 report['diagnostic_parser_stream_sha256']=report.pop('member_sha256')
 report.update(member_sha256=digest,encoding_handling=encoding,raw_values_rewritten=False,
  state='HOLD_ENCODING_CONFIRMATION_AFTER_BYTE_SCAN' if held else 'PARSED_DELIMITED_TEXT_WITH_MISLEADING_SUFFIX' if name.endswith('.xls') else 'PARSED_TEXT_ASSAY_SCHEMA_PENDING')
 return report


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run.resolve();records=[]
 row=read_manifest(ROOT/'data/audit/full_download_assets.csv')['A0002'];raw=get_target(row,ROOT/'raw_cache');name='raw_data/li_2018/GSE111508_FitnessDataMultiEnv.txt'
 with zipfile.ZipFile(raw) as z:records.append(diagnose(z.read(name),name))
 row=read_manifest(ROOT/'data/audit/assembled_assets.csv')['EUKA_DOWNSTREAM_ASSEMBLED'];name='downstream_data/west_2025/Clones.xls'
 with tarfile.open(get_target(row,ROOT/'raw_cache')) as tar:
  raw=tar.extractfile(name).read(128*1024**2+1)
  if raw.startswith((b'\xd0\xcf\x11\xe0',b'PK\x03\x04')):raise ValueError('Expected source suffix mismatch, got binary Excel')
  records.append(diagnose(raw,name))
 immutable_json(run/'reports/format_recovery_qc.json',{'members':records,'no_encoding_invented':True,'admission_gate_pass':False})
 print(json.dumps([{k:r[k] for k in ['member','state','actual_rows','ragged_rows','encoding_handling']} for r in records],indent=2))


if __name__=='__main__':main()
