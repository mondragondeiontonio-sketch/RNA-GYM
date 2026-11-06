"""Render approved public metadata/evidence or emit an immutable BLOCKED_DATA report."""
import argparse
import csv
from pathlib import Path
from rna_gym.research_v06.provenance import (ProtocolError,read_json,write_immutable,
    sha256_file,public_scan,require_public_rights,receipt)


def render(spec, out):
    spec=Path(spec);out=Path(out);out.mkdir(parents=True,exist_ok=True)
    if any(out.iterdir()):
        raise ProtocolError('FIGURE_OUTPUT_EXISTS_USE_NEW_VERSION')
    config=read_json(spec/'figure_input_schema.json')
    path=spec/'source_data.tsv'
    if not path.is_file():
        result={'status':'BLOCKED_DATA','figure_id':config['figure_id'],
                'missing_evidence':config['required_evidence'],'experimental_scores_generated':False}
        write_immutable(out/'data_gap.json',result)
        return result
    require_public_rights(config)
    public_scan([path])
    with path.open() as handle:rows=list(csv.DictReader(handle,delimiter='\t'))
    required={'label','value','data_source','n_constructs','n_independent_assays',
              'n_biological_replicates','split_hash','metric','CI','code_sha'}
    if not rows or not required<=rows[0].keys() or any(r['evidence_kind']!='PUBLIC_REGISTRY_METADATA' for r in rows):
        # Current renderer intentionally accepts only audited metadata, not model-score placeholders.
        raise ProtocolError('UNSUPPORTED_OR_UNAPPROVED_FIGURE_DATA')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':8,'svg.fonttype':'none','pdf.fonttype':42,
                         'axes.spines.top':False,'axes.spines.right':False,'svg.hashsalt':'rnagym-v06'})
    fig,ax=plt.subplots(figsize=(5.2,2.7))
    ax.barh([r['label'] for r in rows],[float(r['value']) for r in rows],color=['#48798c','#b0c8ce'])
    ax.set_xlabel('Legacy UTR views (not independent assays)')
    ax.set_title('Assay-aware atlas: inherited UTR view inventory',loc='left',fontsize=10)
    for i,r in enumerate(rows):ax.text(float(r['value'])+1,i,r['value'],va='center')
    ax.set_xlim(0,max(float(r['value']) for r in rows)*1.18)
    fig.tight_layout()
    fig.savefig(out/'figure.svg',bbox_inches='tight',metadata={'Date':None})
    fig.savefig(out/'figure.pdf',bbox_inches='tight',metadata={'CreationDate':None,'ModDate':None})
    svg=out/'figure.svg'
    svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines())+'\n')
    fig.savefig(out/'preview.png',dpi=160,bbox_inches='tight');plt.close(fig)
    result={'status':'PARTIAL_METADATA_ONLY','figure_id':config['figure_id'],
            'scientific_claim':'VIEW_INVENTORY_ONLY_NO_ASSAY_OR_MODEL_RANKING',
            'source_sha256':sha256_file(path),'renderer_sha256':sha256_file(__file__)}
    write_immutable(out/'figure_receipt.json',result)
    receipt(out,'figure_export',{'source_sha256':sha256_file(path)},
            [out/'figure.svg',out/'figure.pdf',out/'figure_receipt.json'],{'rows':len(rows)})
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--spec',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);a=p.parse_args();print(render(a.spec,a.out))


if __name__=='__main__':main()
