"""Read-only UTR legacy data adapter. No training, downloads or approval."""
import copy
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def taxonomy(hub):
    path=hub.root/hub.config.get('fine_task_registry','data/registries/fine_task_catalog.json')
    return read(path) if path.is_file() else {'categories':[],'datasets':[]}


def categories(hub):
    return copy.deepcopy(taxonomy(hub)['categories'])


def dataset_views(hub,category=None,source=None):
    value=taxonomy(hub)
    if category is not None and category not in {r['category_id'] for r in value['categories']}:
        raise ValueError('UNKNOWN_FINE_CATEGORY:'+str(category))
    result=[]
    private_path=hub.root/hub.config.get('utr_private_manifest','runs/20261028_utr_taxonomy/utr_local_manifest.private.json')
    private=read(private_path) if private_path.is_file() else {}
    for row in value['datasets']:
        if category is not None and category not in row['category_ids']:continue
        if source is not None and row['source_collection']!=source:continue
        record=copy.deepcopy(row)
        if row['source_collection']=='UTR_LEGACY_102':
            binding=private.get('datasets',{}).get(row['unit_id'],{})
            files=binding.get('folds',{})
            available=binding.get('local_verified',False) and len(files)==10 and all(
                Path(f['path']).is_file() and Path(f['path']).stat().st_size==f['bytes'] and
                Path(f['path']).stat().st_mtime_ns==f['mtime_ns'] for f in files.values())
        else:
            path=hub.root/'data/processed'/row['unit_id']/'rnagym-qc-2026-10-28-v1/curated_data.parquet'
            available=path.is_file()
        record['bytes_available_now']=bool(available)
        record['automatic_download']=False
        result.append(record)
    return result


class UTRDataset:
    def __init__(self,hub,dataset_id):
        self.hub=hub
        values={r['dataset_id']:r for r in taxonomy(hub)['datasets'] if r['source_collection']=='UTR_LEGACY_102'}
        if dataset_id not in values:raise ValueError('UNKNOWN_UTR_DATASET_ID:'+str(dataset_id))
        self.record=copy.deepcopy(values[dataset_id])

    def describe(self):
        return next(r for r in dataset_views(self.hub,source='UTR_LEGACY_102') if r['dataset_id']==self.record['dataset_id'])

    def _fold_path(self,fold):
        if type(fold) is not int or not 0<=fold<10:raise ValueError('fold must be an integer in 0..9')
        manifest_path=self.hub.root/self.hub.config.get('utr_private_manifest','runs/20261028_utr_taxonomy/utr_local_manifest.private.json')
        if not manifest_path.is_file():raise FileNotFoundError('UTR_LOCAL_BYTES_NOT_BOUND_NO_DOWNLOAD')
        manifest=read(manifest_path);binding=manifest['datasets'].get(self.record['unit_id'])
        if not binding or not binding['local_verified']:raise ValueError('UTR_DATASET_NOT_VERIFIED')
        proof=binding['folds'][str(fold)];path=Path(proof['path']).resolve();root=Path(manifest['allowed_data_root']).resolve()
        if not path.is_relative_to(root):raise ValueError('UTR_PATH_ESCAPED_BOUND_ROOT')
        if not path.is_file():raise FileNotFoundError('UTR_LOCAL_FILE_MISSING_NO_DOWNLOAD')
        stat=path.stat()
        if stat.st_size!=proof['bytes']:raise ValueError('UTR_FILE_CHANGED_SINCE_BINDING')
        if stat.st_mtime_ns!=proof['mtime_ns']:
            digest=hashlib.sha256()
            with path.open('rb') as f:
                for block in iter(lambda:f.read(4*1024*1024),b''):digest.update(block)
            if digest.hexdigest()!=proof['sha256']:raise ValueError('UTR_FILE_CHECKSUM_CHANGED')
        return path

    def iter_fold(self,*,fold,split=None):
        """Yield existing five-column rows; cast numeric text but never transform."""
        if split not in (None,'train','val','test'):raise ValueError('split must be train, val, test or None')
        path=self._fold_path(fold)
        with gzip.open(path,'rt',encoding='utf-8-sig',newline='') as f:
            reader=csv.DictReader(f)
            if reader.fieldnames!=['sequence','raw_label','zscore_label','set','fold']:
                raise ValueError('UTR_SCHEMA_CHANGED')
            for row in reader:
                if int(row['fold'])!=fold or row['set'] not in ('train','val','test'):raise ValueError('UTR_INVALID_SOURCE_SPLIT')
                if split is not None and row['set']!=split:continue
                raw,scaled=float(row['raw_label']),float(row['zscore_label'])
                if not math.isfinite(raw) or not math.isfinite(scaled):raise ValueError('UTR_NONFINITE_LABEL')
                yield {'sequence':row['sequence'],'raw_label':raw,'zscore_label':scaled,'set':row['set'],'fold':fold}

    def preview(self,*,fold=0,rows=3,split=None):
        if type(rows) is not int or not 1<=rows<=8:raise ValueError('Bounded preview requires 1..8 rows')
        from itertools import islice
        return list(islice(self.iter_fold(fold=fold,split=split),rows))
