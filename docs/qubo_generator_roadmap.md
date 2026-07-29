# Molecule → QUBO generation: analysis and roadmap

**Status: analysis only. No generator is implemented.** This document exists to
answer whether qpubench should grow a QUBO *constructor* alongside
[`hamiltonian_sources/qubo.py`](../src/qpubench/hamiltonian_sources/qubo.py)'s
loaders, and what building one would actually involve.

The brief was: if a QUBO generator is added, it should work the way
[`ab_initio.py`](../src/qpubench/hamiltonian_sources/ab_initio.py) does — you
define a molecule, and a QUBO is constructed for it.

---

## The short version

The analogy to `ab_initio.py` is exact in shape and misleading in difficulty.

`ab_initio.py` is a thin, honest pipeline because the mapping from a molecule
to a qubit Hamiltonian is **canonical**: geometry → SCF → active space →
second-quantised Hamiltonian → Jordan-Wigner. Every step has one textbook
answer and one well-tested library implementing it. The module composes PySCF
and OpenFermion and adds almost no physics of its own.

There is no canonical molecule-to-QUBO mapping. Electronic structure is not
naturally a quadratic *unconstrained* binary problem: the physics lives in
fermionic operators with antisymmetry, and the useful QUBO encodings all work
by choosing a discretisation, then paying penalty terms to enforce the
constraints that the discretisation broke. Different choices give different
QUBOs for the same molecule, with different variable counts, different
conditioning, and different answers when a solver returns something
infeasible.

So a generator is not one function. It is a **choice of encoding**, and the
encoding is the research contribution, not the plumbing.

---

## What "a QUBO for a molecule" can mean

Four distinct families, in rough order of how well-defined they are.

### 1. CI-vector / configuration-selection QUBOs

Assign one binary variable per Slater determinant in a truncated CI space;
minimise the energy expectation subject to normalisation and (optionally)
spin symmetry, with those constraints folded in as penalties. Directly
inherits an active space, so it composes with `ab_initio.py`'s existing
`occupied_indices` / `active_indices` machinery.

- **Variables:** one per selected determinant — grows combinatorially with
  active space size, which is the binding constraint.
- **Well-defined?** The construction is, once you fix the determinant list and
  the penalty weights. Neither has a canonical choice.
- **Hardest part:** penalty weighting. Too small and the optimum is infeasible;
  too large and the QUBO's spectrum is dominated by the penalties, which is
  exactly the regime annealers and QAOA do worst in.

### 2. Geometry / conformer search

Discretise torsion angles or lattice positions, one-hot encode each rotatable
bond's allowed values, and write the force-field energy as a pairwise sum.
This is the family with real published traction — the lattice protein-folding
formulations are the canonical example.

- **Variables:** (rotatable bonds) × (angle bins), plus one-hot penalties.
- **Well-defined?** Yes, given a force field and a discretisation. Both are
  inputs, not derivations.
- **Fit with this repo:** good. It is a *classical* energy model, so it needs
  no quantum-chemistry step, and it maps cleanly onto
  `schemas/mirrors/pyscf_pyscf.py`'s molecule specs for the geometry side.

### 3. Fragment / partitioning problems

Choosing how to cut a molecule into fragments, which fragments to keep after
screening, and which solver to assign to each is a combinatorial optimisation
problem in its own right. qpubench already models all three
(`schemas/catalogs/fragmentation.py` — `FragmentScreeningRule`,
`FragmentSolverAssignment`).

- **Variables:** one per candidate fragment or per fragment-solver pair.
- **Well-defined?** The objective needs a cost model that does not currently
  exist in the schema.
- **Fit with this repo:** the most *native* option — it optimises something
  qpubench already represents, rather than importing an unrelated problem.

### 4. Reaction-network / kinetics selection

Pick a subset of elementary reactions reproducing observed kinetics under a
complexity budget. `schemas/catalogs/reactions.py` already models mechanisms
and Arrhenius rate constants.

- **Well-defined?** Least of the four. The objective is a modelling choice.

---

## What a generator would need that does not exist yet

Independent of which family is chosen:

1. **A `QUBOSpec` input model.** `ab_initio.py` takes a geometry, basis, charge
   and multiplicity — all standard. A QUBO generator's inputs are the
   *encoding choices*: discretisation, penalty weights, variable ordering. None
   is standard, so all must be captured explicitly or results are not
   reproducible. This is the piece that must be designed first; it is a schema
   question, not an algorithm question.

2. **Penalty-weight provenance in the record.** A QUBO's optimum depends on its
   penalty weights. Two benchmarks of "the same molecule" with different
   weights are not comparable, and nothing in the current `BenchmarkRecord`
   would reveal the difference. `QUBOInstance` would need the weights attached,
   and `VQAConfig` a field pointing at them.

3. **A feasibility check on results.** Unconstrained means the solver may
   return a bitstring violating the encoded constraints. A benchmark that
   reports such a solution's energy without flagging it is reporting a number
   that means nothing. `QUBOInstance.objective()` already lets a caller check
   the value; a `feasible()` predicate would have to come from the encoding,
   since only the encoding knows what the constraints were.

4. **A classical reference.** Every other Hamiltonian source in this repo pairs
   with one — `HamiltonianLibraryRecord.fci_energy`, GSOpt's
   `REFERENCE_ENERGIES`. For QUBOs the analogue is a best-known objective
   value. OR-Library publishes these for its instances; a *generated* QUBO has
   none, so a generator must also produce a classical baseline (exhaustive for
   small instances, a heuristic solver above that) or its benchmarks have
   nothing to be scored against.

---

## Recommendation

**Do not build a general molecule-to-QUBO generator.** The abstraction does not
exist to be wrapped; each family above is a separate research choice, and a
module that pretended otherwise would be making physics decisions silently on
the user's behalf — the opposite of what the loaders do.

Instead, in this order:

1. **Ship the loaders** (done — `hamiltonian_sources/qubo.py`). Pre-defined
   instances from OR-Library and MQLib, with best-known objective values, are
   what a benchmark framework actually needs first: they make QUBO results
   comparable against published numbers immediately.

2. **Design `QUBOSpec` before any generator.** Encoding choices, penalty
   weights and their provenance, plus a feasibility predicate. This is
   independently useful — it is also what is needed to record a QUBO produced
   by any external tool, including a QBPP or QUBO.jl model.

3. **If one family is implemented first, make it family 3 (fragment /
   solver assignment).** It optimises something qpubench already models, its
   cost model is internal rather than borrowed, instances are small enough to
   verify exhaustively, and getting it wrong costs a bad fragmentation rather
   than a wrong energy. Family 2 (conformer search) is the natural second: also
   well-posed, but it needs a force field this repo does not currently wrap.

4. **Leave families 1 and 4 to the literature.** Both are active research
   questions where any choice this repo made would be arbitrary and quickly
   dated.

---

## What exists today

| Capability | Status |
|---|---|
| Load pre-defined QUBOs (OR-Library, MQLib) | implemented — `hamiltonian_sources/qubo.py` |
| Read QUBOTools/qbsolv `.qubo` and BQPJSON | implemented |
| QUBO → Ising `SparsePauliObservable` | implemented — exact change of variable, offset returned separately |
| Evaluate an objective at a bitstring | implemented — `QUBOInstance.objective()` |
| `QUBOSpec` for encoding provenance | **not designed** — step 2 above |
| Any molecule → QUBO generator | **not implemented, not recommended as a general facility** |
