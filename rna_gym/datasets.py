"""Dataset/task wrappers with separate physical, label and admission states."""
import csv
import gzip
import hashlib
import io
from pathlib import Path
import zipfile
from ._paths import project_root


class DatasetResolutionError(ValueError):pass


class Dataset:
    def __init__(self,hub,record):self.hub,self.record=hub,record
    @property
    def task_id(self):return self.record['task_id']
    @property
    def assets(self):return [self.hub.assets[x] for x in self.record['asset_ids']]
    def describe(self):return {**self.record,'assets':self.assets}

    def preview(self,*,rows=3,asset_id=None,member=None):
        """Inspect raw local rows, never cast T/U, deduplicate or assign a split.

        Inspection is not scientific admission or permission to redistribute raw
        observations. All rows/columns are preserved; output stays with caller.
        """
        if type(rows) is not int or not 1<=rows<=8:raise ValueError('Bounded preview requires 1..8 rows')
        supported=[a for a in self.assets if a['physical_file_present'] and a['label_evidence'] and
                   (str(a['filename']).endswith(('.parquet','.tsv.gz','.csv.gz')))]
        if asset_id is None:
            if len(supported)!=1:raise DatasetResolutionError('Choose asset_id explicitly; package members/versions are not one assay')
            asset_id=supported[0]['asset_id']
        if asset_id not in self.record['asset_ids']:raise DatasetResolutionError('Asset is not a registered source package member')
        asset=self.hub.assets[asset_id]
        location=self.hub.private['assets'].get(asset_id)
        if not location or not location.get('path'):raise FileNotFoundError('LOCAL_RAW_BYTES_NOT_AVAILABLE_NO_DOWNLOAD')
        path=(self.hub.root/location['path']).resolve()
        if not path.is_relative_to(self.hub.root/'raw_cache'):raise ValueError('Raw path escaped quarantine')
        if not path.is_file():raise FileNotFoundError(path.name)
        digest=hashlib.sha256()
        with path.open('rb') as handle:
            for block in iter(lambda:handle.read(1024*1024),b''):digest.update(block)
        if digest.hexdigest()!=location['source_sha256']:raise ValueError('RAW_CHECKSUM_MISMATCH')
        if path.suffix=='.parquet':
            import pyarrow.parquet as pq
            batch=next(pq.ParquetFile(path).iter_batches(batch_size=rows),None)
            records=batch.to_pylist() if batch is not None else []
        elif path.suffix=='.npz':
            import numpy as np
            with zipfile.ZipFile(path) as archive:
                # Explicit primitive targets only; never decompress/load X or pickle.
                info=archive.getinfo('y.npy')
                if info.file_size>4*1024*1024:raise ValueError('NPZ_PRIMITIVE_TARGET_BUDGET_EXCEEDED')
                y=np.load(io.BytesIO(archive.read(info)),allow_pickle=False)
                if y.ndim!=1 or y.dtype.kind not in 'fiu':raise ValueError('UNIMPLEMENTED_NUMERIC_TARGET_SHAPE')
                records=[{'source_row_index':i,'target':float(v),'sequence_not_loaded':True} for i,v in enumerate(y[:rows])]
        elif zipfile.is_zipfile(path):
            if not member:raise DatasetResolutionError('Choose archive member explicitly; no assay guessed from umbrella task')
            with zipfile.ZipFile(path) as archive:
                info=archive.getinfo(member)
                if info.is_dir() or info.file_size>64*1024*1024:raise ValueError('BOUNDED_ARCHIVE_MEMBER_REQUIRED')
                with archive.open(info) as raw,io.TextIOWrapper(raw,encoding='utf-8-sig') as text:
                    reader=csv.DictReader(text,delimiter='\t' if member.endswith(('.tsv','.txt')) else ',')
                    records=[r for _,r in zip(range(rows),reader)]
        elif path.name.endswith(('.csv','.tsv','.csv.gz','.tsv.gz','.txt')):
            opener=gzip.open if path.suffix=='.gz' else open
            with opener(path,'rt',encoding='utf-8-sig',newline='') as handle:
                reader=csv.DictReader(handle,delimiter='\t' if '.tsv' in path.name or path.suffix=='.txt' else ',')
                records=[r for _,r in zip(range(rows),reader)]
        else:raise DatasetResolutionError('Inspection reader not implemented for this format; no silent substitution')
        return {'scope':'LOCAL_RAW_INSPECTION_NOT_ASSAY_ADMISSION','task_id':self.task_id,
                'asset_id':asset_id,'source_sha256':location['source_sha256'],'member':member,
                'records':records,'labels_or_sequences_transformed':False,'observations_dropped':0,
                'official_split_inferred':False,'rankable_real_result':False}


class DatasetHub:
    def __init__(self,*,root=None):
        from tools.evaluation_protocol import read_json
        self.root=project_root(root)
        self.config=read_json(self.root/'configs/native_sdk.json')
        self.catalog=read_json(self.root/self.config['dataset_catalog'])
        self.assets={a['asset_id']:dict(a) for a in self.catalog['assets']}
        self.records={r['task_id']:dict(r) for r in self.catalog['tasks']}
        private=self.root/self.config['private_assets_manifest']
        self.private=read_json(private) if private.is_file() else {'assets':{}}
        for aid,asset in self.assets.items():
            location=self.private['assets'].get(aid,{})
            asset['physical_file_present_at_snapshot']=asset['physical_file_present']
            asset['physical_file_present']=bool(location.get('path') and (self.root/location['path']).is_file())
        for record in self.records.values():
            record['local_package_files_at_snapshot']=record['local_package_files']
            record['local_package_files']=sum(self.assets[aid]['physical_file_present'] for aid in record['asset_ids'])
            record['label_files_present_now']=sum(bool(self.assets[aid]['label_evidence']) and self.assets[aid]['physical_file_present'] for aid in record['asset_ids'])

    def list(self,*,task_type=None,capability=None,with_local_labels=None):
        values=list(self.records.values())
        if task_type is not None:values=[r for r in values if r['task_type']==task_type or r['registered_task_type']==task_type]
        if capability is not None:values=[r for r in values if r['capability']==capability]
        if with_local_labels is not None:values=[r for r in values if (r['label_files_present_now']>0)==with_local_labels]
        return values

    def preview_asset(self,asset_id,*,rows=3,member=None):
        if asset_id not in self.assets:raise DatasetResolutionError('UNKNOWN_ASSET_ID')
        # Unmapped assets remain inspectable, not silently assigned a new task,
        # source assay, split or ranking weight.
        return Dataset(self,{'task_id':None,'asset_ids':[asset_id]}).preview(
            rows=rows,asset_id=asset_id,member=member)

    def resolve(self,name):
        if name in self.records:return [name]
        if name in self.config['dataset_aliases']:return list(self.config['dataset_aliases'][name])
        matched=[r['task_id'] for r in self.records.values() if r['dataset_name']==name]
        if len(matched)==1:return matched
        if matched:raise DatasetResolutionError('Ambiguous name; use original task ID: '+','.join(matched))
        raise DatasetResolutionError('UNREGISTERED_DATASET:'+str(name))

    def get(self,name):
        ids=self.resolve(name)
        if len(ids)!=1:raise DatasetResolutionError('Dataset is a collection, not one assay; choose: '+','.join(ids))
        return Dataset(self,self.records[ids[0]])
