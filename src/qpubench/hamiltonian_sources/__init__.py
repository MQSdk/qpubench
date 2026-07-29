"""Hamiltonian source loaders (HamLib, PennyLane qchem, PySCF ab initio, QUBO, ...).

Submodules are imported directly (``from qpubench.hamiltonian_sources.hamlib
import ...``) rather than re-exported here: each loader lazily imports its
optional SDK (pyscf, openfermion, requests, ...), so an eager re-export would
defeat the optional-dependency design.
"""
