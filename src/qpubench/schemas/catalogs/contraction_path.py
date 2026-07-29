"""Tensor-network contraction path configuration/result.

Configures how a tensor-network circuit simulator orders its pairwise
contractions, which drives runtime and peak memory. The real implementation
(`qpubench.tensor_network.contraction_path`, lazy `quimb`/`cotengra`
imports) stays out of this module — matching the core-never-imports-a-
quantum-library invariant. Four strategies are modeled, as
`ContractionPathStrategy`:

  SEQUENTIAL          default — fast greedy first, escalates to a fuller
                      search if resource thresholds are exceeded.
  RANDOM_GREEDY_128   quick heuristic, randomized greedy across many trials
                      (128 by default, hence the name).
  MULTI_STRATEGY      evaluates several approaches, picks the best by
                      cost while respecting a memory constraint.
  NONE                delegates path-finding to the contraction engine
                      itself (no explicit path optimization).

Schema version: 2.7.0
"""
from __future__ import annotations

import enum

import pydantic


class ContractionPathStrategy(str, enum.Enum):
    SEQUENTIAL = "sequential"
    RANDOM_GREEDY_128 = "random_greedy_128"
    MULTI_STRATEGY = "multi_strategy"
    NONE = "none"


class ContractionPathConfig(pydantic.BaseModel):
    """Real strategy selection across the four supported approaches.

    num_repeats           trials for RANDOM_GREEDY_128 (128 by default).
    max_memory_fraction    for MULTI_STRATEGY: fraction of a configured
                           memory budget the path search may target
                           (mapped onto cotengra's real slicing mechanism
                           — an approximation, not an exact budget).
    memory_budget_elements  the "100%" reference for max_memory_fraction,
                           in tensor elements (default 2**28 ~ 1GB of
                           complex128 — adjust for your machine).
    """
    strategy: ContractionPathStrategy = ContractionPathStrategy.SEQUENTIAL
    num_repeats: int = 128
    max_memory_fraction: float = 0.8
    memory_budget_elements: int = 2**28


class ContractionPathResult(pydantic.BaseModel):
    """Real cost/memory stats for the chosen path — populated from
    `opt_einsum.contract.PathInfo` (quimb's `contraction_info()` return
    type), not fabricated.

    opt_cost              optimized FLOP count for the contraction.
    largest_intermediate  largest intermediate tensor size (elements).
    """
    strategy_used: ContractionPathStrategy
    opt_cost: float
    largest_intermediate: float


__all__ = [
    "ContractionPathConfig",
    "ContractionPathResult",
    "ContractionPathStrategy",
]
