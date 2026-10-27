"""Native local model loading/encoding; no HTTP, OpenAI client or API key."""
from pathlib import Path
from ._paths import project_root


class ModelUnavailableError(RuntimeError):pass


class RNAEncoder:
    def __init__(self,model_id,adapter,manifest):
        self.model_id,self._adapter,self.manifest=model_id,adapter,manifest
        self.device=adapter.device
        self.initialization=adapter.initialization
        self.initialization_seed=adapter.seed

    @property
    def contract(self):return dict(self._adapter.contract)

    def encode(self,*,sequences,layer='last',pooling='masked_mean',batch_size=4):
        """Return [N,D] numpy array, or N nucleotide arrays for pooling='none'.

        Exact A/C/G/U only. No uppercasing, DNA conversion, truncation, labels or
        head fitting. Padding and special tokens never enter masked means.
        """
        import numpy as np
        if layer!='last':raise ValueError('Only the predeclared last layer is implemented; no label-based layer selection')
        if pooling not in ('masked_mean','none'):raise ValueError('pooling must be masked_mean or none')
        if not isinstance(sequences,(list,tuple)) or not sequences:raise ValueError('Nonempty sequence list required')
        rows=[{'observation_id':str(i),'sequence':sequence} for i,sequence in enumerate(sequences)]
        values=self._adapter.encode(rows,batch_size=batch_size)
        if pooling=='none':return [r['nucleotide_embeddings'] for r in values]
        return np.asarray([r['pooled_embedding'] for r in values],dtype=np.float32)

    def resources(self):return self._adapter.resources()


class RNAHub:
    @staticmethod
    def list(*,root=None):
        from tools.evaluation_protocol import read_json
        registry=read_json(project_root(root)/'configs/model_adapter_registry.yaml')
        return [{'model_id':m['model_id'],'family':m['adapter_family'],
                 'native_adapter_implemented':m['model_id']=='RNA-FM',
                 'runtime_loadability':m['runtime_loadability']} for m in registry['models']]

    @staticmethod
    def load(name,*,root=None,manifest=None,device='cuda:0',initialization='pretrained',seed=0):
        from tools.evaluation_protocol import read_json
        root=project_root(root)
        aliases={'rnafm':'RNA-FM','rna-fm':'RNA-FM','RNA-FM':'RNA-FM'}
        model_id=aliases.get(name,name)
        registered={m['model_id'] for m in RNAHub.list(root=root)}
        if model_id not in registered:raise ModelUnavailableError('UNREGISTERED_MODEL:'+str(name))
        if model_id!='RNA-FM':raise ModelUnavailableError('ADAPTER_NOT_IMPLEMENTED_NO_MODEL_SUBSTITUTION:'+model_id)
        if not isinstance(device,str) or not device.startswith('cuda:'):
            raise ModelUnavailableError('ALL_FM_FORWARD_REQUIRES_GPU_NO_CPU_FALLBACK')
        config=read_json(root/'configs/native_sdk.json')
        path=Path(manifest) if manifest is not None else root/config['model_manifest']
        if not path.is_file():raise ModelUnavailableError('PINNED_LOCAL_MODEL_MANIFEST_MISSING_NO_DOWNLOAD')
        try:
            from tools.rnafm_adapter import RNAFMAdapter
            data=read_json(path)
            adapter=RNAFMAdapter(data,device=device,initialization=initialization,seed=seed)
        except ImportError as exc:
            raise ModelUnavailableError('USE_THE_VERIFIED_LOCAL_GPU_ENVIRONMENT:'+str(exc)) from exc
        return RNAEncoder(model_id,adapter,data)
