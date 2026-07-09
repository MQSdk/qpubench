"""Tensor-network circuit simulation utilities (quimb + cotengra).

Requires: pip install 'qpubench[tensor_network]'
"""
from __future__ import annotations

from .contraction_path import build_quimb_circuit, choose_contraction_path

__all__ = [
    "build_quimb_circuit",
    "choose_contraction_path",
]
