"""Run from an installed repository: python paper/figure_specs/figN/script.py --out runs/figN-001."""
import argparse
from pathlib import Path
from tools.mrna_design.export_figures import render

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    print(render(Path(__file__).parent,args.out))
