"""Cross-cutting catalogues and registries.

Modules here are neither core record types nor a mirror of one upstream
project. They either aggregate *several* external sources (basis sets from
Basis Set Exchange and q-vSZP; Hamiltonian metadata from PennyLane, HamLib and
ab initio construction) or define a catalogue qpubench itself owns (the
minimizer catalogue over ``scipy.optimize.minimize``, the fragmentation and
distributed-execution vocabularies that several project mirrors specialise).

Everything is re-exported from ``qpubench.schemas``; import from there.
"""
