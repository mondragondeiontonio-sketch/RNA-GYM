"""Locate a checkout without network access or implicit data downloads."""
import os
from pathlib import Path


def project_root(root=None):
    path=Path(root or os.environ.get('RNA_GYM_ROOT') or Path(__file__).resolve().parents[1]).resolve()
    if not (path/'configs/model_adapter_registry.yaml').is_file():
        raise FileNotFoundError('RNA Gym assets not found; pass root= or set RNA_GYM_ROOT to the checkout')
    return path
