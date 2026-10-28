"""Refresh the single current scientific audit from completed real data outputs."""
import argparse
import json
from .review import read_reports,compile_review
from .overlap import audit_overlap
from .evidence import compile_evidence
from .profiles import profiles


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--skip-overlap',action='store_true')
    args=p.parse_args()
    reports=read_reports()
    compile_evidence()
    if args.skip_overlap:
        summary=compile_review(reports)
    else:
        _,overlap=audit_overlap(reports)
        summary=compile_review(reports,overlap)
    profiles(reports)
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
