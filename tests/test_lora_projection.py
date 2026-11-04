import unittest
try:
    import torch
    from torch import nn
    from torch.nn import functional as F
    from rna_gym.lora import LoRALinear
except ImportError:
    torch=None

@unittest.skipIf(torch is None, "optional torch unavailable")
class LoRAProjectionTests(unittest.TestCase):
    def test_zero_init_equivalence_and_frozen_base(self):
        torch.manual_seed(42); base=nn.Linear(8,8); layer=LoRALinear(base,rank=2,alpha=4); x=torch.randn(3,8)
        torch.testing.assert_close(layer(x),base(x))
        self.assertFalse(layer.base.weight.requires_grad)
        layer(x).sum().backward(); self.assertIsNotNone(layer.B.grad); self.assertGreater(float(layer.B.grad.abs().sum()),0)
    def test_fused_attention_uses_live_low_rank_weight(self):
        torch.manual_seed(42); q=LoRALinear(nn.Linear(8,8)); k=nn.Linear(8,8); v=LoRALinear(nn.Linear(8,8)); out=nn.Linear(8,8); x=torch.randn(5,2,8)
        y,_=F.multi_head_attention_forward(x,x,x,8,2,torch.empty(0),torch.cat((q.bias,k.bias,v.bias)),None,None,False,0,out.weight,out.bias,training=True,need_weights=False,use_separate_proj_weight=True,q_proj_weight=q.weight,k_proj_weight=k.weight,v_proj_weight=v.weight)
        y.square().mean().backward()
        self.assertGreater(float(q.B.grad.abs().sum()),0); self.assertGreater(float(v.B.grad.abs().sum()),0)
        self.assertIsNone(q.base.weight.grad)
        with torch.no_grad(): q.B.add_(.1)
        self.assertFalse(torch.equal(q.weight,q.base.weight))
