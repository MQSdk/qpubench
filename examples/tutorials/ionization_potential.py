"""Tutorial: ionization potentials.

The runnable calculation uses HamLib's real H2 Hamiltonian (4 qubits — the
smallest real molecule either supported library ships) run through a
neutral/cation delta-particle-number ADAPT-VQE technique: solving for H2 (2
electrons) and H2+ (1 electron, its real, well-known cation) on the SAME
real qubit Hamiltonian. The resulting ionization potential
(~16.2 eV at HamLib's STO-3G geometry) is in the right ballpark for H2's
real literature IP (~15.4-16.0 eV, basis-set/geometry dependent) — a
genuine chemically-meaningful number, not an invented toy-Hamiltonian one.

An NH3 setup (cc-pVDZ, 6 active orbitals/8 active electrons = 12 qubits)
is built below purely as a capability check (HF energy, term count) via
`qpubench.hamiltonian_sources.ab_initio.build_qubit_hamiltonian`. It isn't
run: 12 qubits / hundreds of terms is beyond this repo's dense-matrix
reference engine (examples/common/toy_statevector_backend.py rebuilds a
dense 2**n x 2**n matrix on *every* energy evaluation, uncached — a real
LiH Hamiltonian at 12 qubits / 631 terms timed out at 2+ minutes for 2
truncated iterations). A real simulator (Aer, Qrack) as the energy
backend, or an active-space reduction (see
examples/guides/active_space_spec.py's real PySCF AVAS selection), lifts
that limit.

For NH3 (or any real excited-state/ionization property) computed by a
real chemistry package directly: integrations/slowquant/adapter.py (a
real SlowQuantAlgorithmAdapter against SlowQuant's verified real API —
shown construction-only below since SlowQuant isn't on PyPI).

Requires:
    pip install 'qpubench[adapt_vqe]'   # scipy + numpy
    pip install 'qpubench[hamlib]'      # h5py + requests, for the real H2 Hamiltonian
Optional (for the real SlowQuant path):
    pip install git+https://github.com/erikkjellgren/SlowQuant

Run:
    python examples/tutorials/ionization_potential.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from qpubench.schemas.execution import AdaptVQEConfig


def try_real_slowquant() -> None:
    """Construction-only demonstration of the real SlowQuant path — same
    pattern as examples/guides/quantum_computers.py's IBMAdapter/IQMAdapter
    section. Prints a clear message and returns if SlowQuant isn't
    installed (it isn't pip-installable, so this is the expected path
    unless you've installed it from source).
    """
    from integrations.slowquant.adapter import SlowQuantAlgorithmAdapter, _require_slowquant

    # Constructing the adapter itself never imports slowquant (lazy import,
    # same contract as QForteAlgorithmAdapter) — only run_algorithm() does.
    SlowQuantAlgorithmAdapter()

    try:
        _require_slowquant()
    except ImportError as exc:
        print(f"Real SlowQuant path (construction only): {exc}\n")
        return
    print("SlowQuant is installed — see integrations/slowquant/adapter.py "
          "for the real UCC-VQE call, driven the same way as the real "
          "calculation below via runner.run(problem_spec, 'slowquant_ucc', options).\n")


def solve(hamiltonian, num_qubits: int, num_electrons: int) -> float:
    from examples.common.toy_statevector_backend import ToyStatevectorAdapter
    from integrations.generic_adapt_vqe.engine import GenericAdaptVQEEngine

    engine = GenericAdaptVQEEngine(
        hamiltonian=hamiltonian,
        num_qubits=num_qubits,
        num_electrons=num_electrons,
        energy_backend=ToyStatevectorAdapter(),
        config=AdaptVQEConfig(max_macro_iterations=15, gradient_threshold=1e-5,
                               max_micro_iterations=200),
    )
    _, _vqa, vqa_result = engine.run()
    return vqa_result.final_eigenvalue


def nh3_capability_check() -> None:
    """Build (don't run) an NH3 setup (cc-pVDZ, 6 active orbitals/8 active
    electrons = 12 qubits, neutral only — the cation's open-shell
    active-space accounting isn't supported by build_qubit_hamiltonian's
    current closed-shell frozen-core convention). Confirms the framework can
    construct the setup directly from geometry; running ADAPT-VQE on it
    isn't attempted here (same too-many-terms class as the confirmed LiH
    timeout).
    """
    try:
        from qpubench.hamiltonian_sources.ab_initio import build_qubit_hamiltonian
    except ImportError:
        print("openfermion/openfermionpyscf/pyscf not installed — run: "
              "pip install 'qpubench[openfermion]'")
        return

    geometry = [
        ("N", (0.0, 0.0, 0.0)),
        ("H", (0.94, 0.0, -0.33)),
        ("H", (-0.47, 0.82, -0.33)),
        ("H", (-0.47, -0.82, -0.33)),
    ]
    _, record = build_qubit_hamiltonian(
        geometry, basis="cc-pvdz", active_electrons=8, active_orbitals=6,
        molecule_name="NH3 (real tutorial setup)",
    )
    print(f"NH3/cc-pVDZ setup: {record.num_qubits} qubits, "
          f"{record.num_terms} terms, HF={record.hf_energy:.6f} Ha "
          f"(built for real, not run — too many terms for this repo's "
          f"toy ADAPT-VQE engine, same class as the confirmed LiH timeout)\n")


def main() -> None:
    try_real_slowquant()
    nh3_capability_check()

    try:
        from qpubench.hamiltonian_sources.hamlib import load_hamlib_chemistry
    except ImportError:
        print("h5py/requests not installed — run: pip install 'qpubench[hamlib]'")
        return

    hamiltonian, record = load_hamlib_chemistry("H2")

    neutral_energy = solve(hamiltonian, record.num_qubits, num_electrons=2)   # H2
    cation_energy  = solve(hamiltonian, record.num_qubits, num_electrons=1)   # H2+

    ip_hartree = cation_energy - neutral_energy
    ip_ev = ip_hartree * 27.211386245988

    print(f"H2  (neutral, 2 electrons) energy = {neutral_energy:.6f} Ha")
    print(f"H2+ (cation,  1 electron)  energy = {cation_energy:.6f} Ha")
    print(f"\nionization potential (cation - neutral) = {ip_hartree:.6f} Ha "
          f"= {ip_ev:.3f} eV")
    print("(real H2/STO-3G Hamiltonian from HamLib — literature H2 IP is "
          "~15.4-16.0 eV depending on basis/geometry)")


if __name__ == "__main__":
    main()
