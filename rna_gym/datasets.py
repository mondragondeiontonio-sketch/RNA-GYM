"""Dataset/task wrappers with separate physical, label and admission states."""
import csv
import gzip
import hashlib
import io
from pathlib import Path
import zipfile
from ._paths import project_root
from tools.asset_identity import artifact_uid


class DatasetResolutionError(ValueError):pass


class Dataset:
    def __init__(self,hub,record):self.hub,self.record=hub,record
    @property
    def task_id(self):return self.record['task_id']
    @property
    def assets(self):return [self.hub.artifacts[x] for x in self.record['artifact_uids']]
    def describe(self):return {**self.record,'assets':self.assets}

    def preview(self,*,rows=3,asset_id=None,source_sha256=None,member=None):
        """Inspect raw local rows, never cast T/U, deduplicate or assign a split.

        Inspection is not scientific admission or permission to redistribute raw
        observations. All rows/columns are preserved; output stays with caller.
        """
        if type(rows) is not int or not 1<=rows<=8:raise ValueError('Bounded preview requires 1..8 rows')
        supported=[a for a in self.assets if a['physical_file_present'] and a['label_evidence'] and
                   (str(a['filename']).endswith(('.parquet','.tsv.gz','.csv.gz')))]
        if asset_id is None:
            if len(supported)!=1:raise DatasetResolutionError('Choose asset_id explicitly; package members/versions are not one assay')
            asset_id=supported[0]['artifact_uid']
        asset=self.hub.resolve_asset(asset_id,source_sha256=source_sha256)
        uid=asset['artifact_uid']
        if uid not in self.record['artifact_uids']:
            raise DatasetResolutionError('Asset is not a registered source package member')
        location=self.hub.private['artifacts'].get(uid)
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
                'asset_id':asset['asset_id'],'artifact_uid':uid,
                'source_sha256':location['source_sha256'],'member':member,
                'records':records,'labels_or_sequences_transformed':False,'observations_dropped':0,
                'official_split_inferred':False,'rankable_real_result':False}


class DatasetHub:
    def __init__(self,*,root=None):
        from tools.evaluation_protocol import read_json
        self.root=project_root(root)
        self.config=read_json(self.root/'configs/native_sdk.json')
        self.catalog=read_json(self.root/self.config['dataset_catalog'])
        self.artifacts={}
        self.asset_versions={}
        for original in self.catalog['assets']:
            asset=dict(original)
            uid=artifact_uid(asset['asset_id'],asset['source_sha256'])
            if asset.get('artifact_uid',uid)!=uid or uid in self.artifacts:
                raise ValueError('INVALID_OR_DUPLICATE_ARTIFACT_VERSION')
            asset['artifact_uid']=uid
            self.artifacts[uid]=asset
            self.asset_versions.setdefault(asset['asset_id'],[]).append(uid)
        # Preserve the old logical-ID lookup when it is unambiguous. Multiple
        # versions instead expose their explicit keys; nothing is overwritten.
        self.assets={}
        for aid,uids in self.asset_versions.items():
            for uid in uids:
                self.assets[aid if len(uids)==1 else uid]=self.artifacts[uid]
        self.records={r['task_id']:dict(r) for r in self.catalog['tasks']}
        private=self.root/self.config['private_assets_manifest']
        original=read_json(private) if private.is_file() else {}
        locations=original.get('artifacts',original.get('assets',{}))
        normalized={}
        for uid,asset in self.artifacts.items():
            location=locations.get(uid)
            if location is None and asset['asset_id'] in locations:
                if len(self.asset_versions[asset['asset_id']])!=1:
                    raise ValueError('AMBIGUOUS_LEGACY_ARTIFACT_LOCATOR_REBUILD_REQUIRED')
                location=locations[asset['asset_id']]
            if location is not None:
                if location.get('source_sha256')!=asset['source_sha256']:
                    raise ValueError('ARTIFACT_LOCATOR_HASH_MISMATCH')
                normalized[uid]=location
            asset['physical_file_present_at_snapshot']=asset['physical_file_present']
            asset['physical_file_present']=bool(location and location.get('path') and
                (self.root/location['path']).is_file())
        self.private={'artifacts':normalized,'assets':{
            key:normalized[asset['artifact_uid']] for key,asset in self.assets.items()
            if asset['artifact_uid'] in normalized}}
        for record in self.records.values():
            record['asset_ids']=list(dict.fromkeys(record['asset_ids']))
            uids=record.get('artifact_uids')
            if uids is None:
                uids=[uid for aid in record['asset_ids'] for uid in self.asset_versions.get(aid,[])]
            if len(set(uids))!=len(uids) or any(uid not in self.artifacts or
                    self.artifacts[uid]['asset_id'] not in record['asset_ids'] for uid in uids):
                raise ValueError('TASK_ARTIFACT_VERSION_MAPPING_MISMATCH')
            record['artifact_uids']=list(uids)
            record['local_package_files_at_snapshot']=record['local_package_files']
            record['local_package_files']=sum(self.artifacts[uid]['physical_file_present'] for uid in uids)
            record['label_files_present_now']=sum(bool(self.artifacts[uid]['label_evidence']) and
                self.artifacts[uid]['physical_file_present'] for uid in uids)

    def resolve_asset(self,asset_id,*,source_sha256=None):
        if asset_id in self.artifacts:
            candidates=[asset_id]
        else:
            candidates=self.asset_versions.get(asset_id,[])
        if source_sha256 is not None:
            candidates=[uid for uid in candidates if self.artifacts[uid]['source_sha256']==source_sha256]
        if not candidates:raise DatasetResolutionError('UNKNOWN_ASSET_VERSION')
        if len(candidates)!=1:raise DatasetResolutionError('AMBIGUOUS_ASSET_VERSION_SELECT_SHA256')
        return self.artifacts[candidates[0]]

    def list(self,*,task_type=None,capability=None,with_local_labels=None):
        values=list(self.records.values())
        if task_type is not None:values=[r for r in values if r['task_type']==task_type or r['registered_task_type']==task_type]
        if capability is not None:values=[r for r in values if r['capability']==capability]
        if with_local_labels is not None:values=[r for r in values if (r['label_files_present_now']>0)==with_local_labels]
        return values

    def preview_asset(self,asset_id,*,rows=3,source_sha256=None,member=None):
        asset=self.resolve_asset(asset_id,source_sha256=source_sha256)
        # Raw inspection does not infer an assay, split, or ranking weight.
        return Dataset(self,{'task_id':None,'asset_ids':[asset['asset_id']],
            'artifact_uids':[asset['artifact_uid']]}).preview(
                rows=rows,asset_id=asset['artifact_uid'],member=member)

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
