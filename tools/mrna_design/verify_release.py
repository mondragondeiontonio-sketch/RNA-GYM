"""Protect historical assets and scan every V0.6 publishable file, including untracked."""
import argparse
import subprocess
from pathlib import Path
from rna_gym.research_v06.provenance import (ProtocolError, read_json, sha256_file,
                                            public_scan, write_immutable)

MUTABLE={'README.md','.gitignore','pyproject.toml','tools/prepare_public.py','site/index.html','tests/test_site.py'}
PREFIXES=('rna_gym/research_v06/','tools/mrna_design/','tests/mrna_design/',
          'configs/studies/mrna_design_v06/','docs/mrna_design/',
          'reports/research_v06/','manifests/research_v06_',
          'paper/','site/mrna-design.html','site/data/mrna-design-v06.json','site/assets/mrna-v06-atlas.svg',
          '.github/workflows/research-v06.yml')


def verify(root,base):
    root=Path(root)
    snapshot=read_json(root/'manifests/research_v06_source_snapshot.json')
    changed=[]
    for row in snapshot['files']:
        p=root/row['path']
        if not p.is_file() or sha256_file(p)!=row['sha256']:
            changed.append(row['path'])
    unexpected=set(changed)-MUTABLE
    if unexpected:raise ProtocolError('HISTORICAL_ASSET_CHANGED:'+','.join(sorted(unexpected)))
    cmd=['git','-C',str(root),'diff','--name-only',base,'--']
    names=set(subprocess.check_output(cmd,text=True).splitlines())
    names.update(subprocess.check_output(['git','-C',str(root),'ls-files','--others','--exclude-standard'],text=True).splitlines())
    paths=[]
    for name in sorted(names):
        if name not in MUTABLE and not name.startswith(PREFIXES):
            raise ProtocolError('NOT_IN_V06_PUBLIC_ALLOWLIST:'+name)
        p=root/name
        if p.is_file():paths.append(p)
    # CI on a committed branch still checks all nested v06 files, not just git status.
    for prefix in PREFIXES:
        p=root/prefix
        if p.is_dir():paths.extend(x for x in p.rglob('*') if x.is_file() and '__pycache__' not in x.parts)
        elif p.is_file():paths.append(p)
    paths=sorted(set(paths))
    public_scan(paths)
    return {'status':'PASS','historical_files_checked':len(snapshot['files']),
            'authorized_engineering_changes':sorted(changed),'public_files_scanned':len(paths),
            'formal_admitted':0,'new_gpu_hours':0}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',default='origin/main')
    p.add_argument('--root',type=Path,default=Path('.'));p.add_argument('--out',type=Path)
    a=p.parse_args();result=verify(a.root,a.base)
    if a.out:write_immutable(a.out,result)
    print(result)


if __name__=='__main__':main()
