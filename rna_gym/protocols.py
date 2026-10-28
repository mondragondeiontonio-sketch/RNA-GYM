"""Fixed low-label frozen readouts; encoder gradients never enter this module."""


def fit_readout(features,rows,splits,selected_ids,*,protocol,problem,seed,device='cpu'):
    import numpy as np
    if protocol not in ('frozen_ridge','frozen_linear','frozen_mlp'):raise NotImplementedError('READOUT_PROTOCOL_NOT_IMPLEMENTED')
    if problem not in ('regression','binary_classification'):raise NotImplementedError('SCALAR_READOUT_IS_NOT_A_TOKEN_PAIR_OR_3D_HEAD')
    if type(seed) is not int or seed<0:raise ValueError('Explicit nonnegative seed required')
    if protocol=='frozen_ridge' and problem!='regression':raise ValueError('FROZEN_RIDGE_IS_REGRESSION_USE_FROZEN_LINEAR_OR_MLP_FOR_BINARY')
    ids=[r['observation_id'] for r in rows]
    if len(set(ids))!=len(ids) or not selected_ids or len(set(selected_ids))!=len(selected_ids):raise ValueError('Unique observation/selected IDs required')
    if len(selected_ids)>64:raise NotImplementedError('LARGER_LABEL_BUDGET_REQUIRES_GROUPED_INNER_CV_NOT_SILENT_FIXED_DEFAULTS')
    if any(i not in ids or splits[i]!='train' for i in selected_ids):raise ValueError('TRAIN_ONLY_LABEL_SELECTION_REQUIRED')
    x=np.asarray(features,dtype=np.float64)
    if x.ndim!=2 or len(x)!=len(rows) or not np.isfinite(x).all():raise ValueError('Finite aligned feature matrix required')
    positions=[i for i,oid in enumerate(ids) if oid in set(selected_ids)]
    y=np.asarray([rows[i]['label'] for i in positions],dtype=np.float64)
    if not np.isfinite(y).all():raise ValueError('FINITE_TRAIN_LABELS_REQUIRED')
    if problem=='binary_classification' and (set(y)!={0.0,1.0}):raise ValueError('INSUFFICIENT_CLASS_SUPPORT_NO_LABEL_BASED_REDRAW')
    mean=x[positions].mean(axis=0);scale=x[positions].std(axis=0);scale[scale==0]=1
    z=(x[positions]-mean)/scale
    ym,ys=(float(y.mean()),float(y.std()) or 1.0) if problem=='regression' else (0.0,1.0)
    target=(y-ym)/ys
    head={'schema_version':'rna_gym.native_frozen_head.v1','protocol':protocol,'problem_type':problem,
          'seed':seed,'scaler_mean':mean.tolist(),'scaler_scale':scale.tolist(),
          'target_mean':ym,'target_scale':ys,'fit_observation_ids':sorted(selected_ids),
          'label_budget':{'fit_unique':len(selected_ids),'tune_unique':0,'calibration_unique':0,
              'total_unique':len(selected_ids),'test_selection_labels':0,'hpo_candidates':0},
          'threshold':0.5,'threshold_tuning':False,'fit_split':'train'}
    if protocol in ('frozen_ridge','frozen_linear'):
        if problem=='regression':
            from sklearn.linear_model import Ridge
            estimator=Ridge(alpha=1.0,solver='svd').fit(z,target)
            coef=estimator.coef_;intercept=float(estimator.intercept_)
        else:
            from sklearn.linear_model import LogisticRegression
            estimator=LogisticRegression(C=1.0,max_iter=3000,random_state=seed).fit(z,target)
            coef=estimator.coef_[0];intercept=float(estimator.intercept_[0])
        head.update(kind='linear',coefficients=coef.tolist(),intercept=intercept,alpha_or_C=1.0)
    else:
        import torch
        from torch import nn
        devices=[int(device.split(':')[1])] if device.startswith('cuda:') else []
        with torch.random.fork_rng(devices=devices):
            torch.manual_seed(seed)
            net=nn.Sequential(nn.Linear(x.shape[1],128),nn.GELU(),nn.Dropout(0.2),nn.Linear(128,1)).to(device)
            net.train()
            inputs=torch.tensor(z,dtype=torch.float32,device=device)
            labels=torch.tensor(target,dtype=torch.float32,device=device)
            optimizer=torch.optim.AdamW(net.parameters(),lr=0.0003,weight_decay=0.01)
            loss_fn=nn.MSELoss() if problem=='regression' else nn.BCEWithLogitsLoss()
            for _ in range(100):
                # At the strict <=64 label budget the declared batch size 64
                # uses one batch; no validation/early stopping/epoch selection.
                optimizer.zero_grad(set_to_none=True)
                loss=loss_fn(net(inputs).squeeze(-1),labels)
                if not torch.isfinite(loss):raise ValueError('NONFINITE_HEAD_LOSS')
                loss.backward();optimizer.step()
            head.update(kind='mlp',hidden_width=128,activation='gelu',dropout=0.2,
                        optimizer='AdamW',learning_rate=0.0003,weight_decay=0.01,
                        epochs=100,batch_size=64,early_stopping=False,
                        state_dict={k:v.detach().cpu().tolist() for k,v in net.state_dict().items()})
    return head


def predict_readout(head,features,*,device='cpu'):
    import numpy as np
    x=np.asarray(features,dtype=np.float64)
    z=(x-np.asarray(head['scaler_mean']))/np.asarray(head['scaler_scale'])
    if head['kind']=='linear':
        raw=z@np.asarray(head['coefficients'])+head['intercept']
    elif head['kind']=='mlp':
        import torch
        from torch import nn
        width=len(head['scaler_mean'])
        net=nn.Sequential(nn.Linear(width,128),nn.GELU(),nn.Dropout(0.2),nn.Linear(128,1)).to(device)
        net.load_state_dict({k:torch.tensor(v,dtype=torch.float32,device=device) for k,v in head['state_dict'].items()})
        net.eval()
        with torch.inference_mode():raw=net(torch.tensor(z,dtype=torch.float32,device=device)).squeeze(-1).cpu().numpy()
    else:raise ValueError('UNKNOWN_NUMERIC_HEAD')
    result=raw*head['target_scale']+head['target_mean']
    if head['problem_type']=='binary_classification':result=1/(1+np.exp(-np.clip(result,-700,700)))
    if not np.isfinite(result).all():raise ValueError('NONFINITE_PREDICTIONS')
    return result.tolist()
