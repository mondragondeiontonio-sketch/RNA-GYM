"""LoRA projection compatible with fused functional attention and module calls."""
import math
import torch
from torch import nn
from torch.nn import functional as F


class LoRALinear(nn.Module):
    def __init__(self, base, rank=4, alpha=8):
        super().__init__()
        if not isinstance(base, nn.Linear) or rank<1: raise ValueError("LINEAR_AND_POSITIVE_RANK_REQUIRED")
        self.base=base; self.rank=rank; self.alpha=alpha
        self.in_features=base.in_features; self.out_features=base.out_features
        self.base.requires_grad_(False)
        self.A=nn.Parameter(torch.empty(rank,base.in_features,device=base.weight.device,dtype=base.weight.dtype))
        self.B=nn.Parameter(torch.zeros(base.out_features,rank,device=base.weight.device,dtype=base.weight.dtype))
        nn.init.kaiming_uniform_(self.A,a=math.sqrt(5))
    @property
    def weight(self): return self.base.weight+(self.B@self.A)*(self.alpha/self.rank)
    @property
    def bias(self): return self.base.bias
    def forward(self,x): return F.linear(x,self.weight,self.bias)
