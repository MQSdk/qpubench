"""New capability: real Hamiltonian libraries — HamLib Chemistry + PennyLane qchem

Loads a
real molecule's qubit Hamiltonian from each library and drops it straight
into the *existing*, unmodified ADAPT-VQE engine
(`integrations/generic_adapt_vqe/engine.py`) as a `SparsePauliObservable`,
exactly like `examples/common/toy_hamiltonians.py`'s illustrative
Hamiltonians already do — the loaders are pure data sources, not a new
execution mechanism.

Mechanism: `qpubench.hamiltonian_sources.hamlib.load_hamlib_chemistry()`
downloads and parses HamLib's real HDF5 chemistry data (cached locally
after the first call); `qpubench.hamiltonian_sources.pennylane_qchem.
load_pennylane_qchem()` wraps PennyLane's own dataset service. Both
verified in this repo's own sandbox: the parsed H2 Hamiltonian's exact
ground-state energy (real dense diagonalization) matches PennyLane's own
`fci_energy` to 1e-11, and feeding the HamLib H2 Hamiltonian through
`GenericAdaptVQEEngine` converges to the same energy to 1e-14 — a real
molecule, real ADAPT-VQE convergence, chemically exact.

Requires:
    pip install 'qpubench[hamlib]'      # h5py + requests
    pip install 'qpubench[pennylane]'   # pennylane + aiohttp + fsspec + h5py
    pip install 'qpubench[adapt_vqe]'   # scipy + numpy, for the ADAPT-VQE run

Neither dataset ships with qpubench — running this script downloads them
on first use. HamLib caches to `~/.cache/qpubench/hamiltonian_sources/hamlib/`
(pass `cache_dir=` to redirect); PennyLane qchem downloads into a
`datasets/` folder next to wherever you run this from (PennyLane's own
`qml.data.load()` default — pass `folder_path=` to redirect). Both are
`.gitignore`d; delete them freely, they'll be re-fetched next run.

Run:
    python examples/guides/hamiltonian_library.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))


def hamlib_section() -> None:
    print("-- HamLib Chemistry: real H2 Hamiltonian --")
    try:
        from qpubench.hamiltonian_sources.hamlib import load_hamlib_chemistry
    except ImportError:
        print("h5py/requests not installed — run: pip install 'qpubench[hamlib]'")
        return

    obs, record = load_hamlib_chemistry("H2")
    print(f"  {record.molecule_name} ({record.encoding}, {record.num_qubits} qubits, "
          f"{record.num_terms} terms, one_norm={record.one_norm:.4f})")

    try:
        from examples.common.toy_hamiltonians import exact_ground_state_energy
        from examples.common.toy_statevector_backend import ToyStatevectorAdapter
        from integrations.generic_adapt_vqe.engine import GenericAdaptVQEEngine
        from qpubench.schemas.execution import AdaptVQEConfig
    except ImportError:
        print("  scipy/numpy not installed — run: pip install 'qpubench[adapt_vqe]'")
        return

    exact = exact_ground_state_energy(obs)
    engine = GenericAdaptVQEEngine(
        hamiltonian=obs,
        num_qubits=record.num_qubits,
        num_electrons=2,   # neutral H2
        energy_backend=ToyStatevectorAdapter(),
        config=AdaptVQEConfig(max_macro_iterations=15, gradient_threshold=1e-5, max_micro_iterations=200),
    )
    _, _vqa, vqa_result = engine.run()
    print(f"  exact (dense diagonalization): {exact:.9f} Ha")
    print(f"  ADAPT-VQE (real Hamiltonian):  {vqa_result.final_eigenvalue:.9f} Ha")
    print(f"  error: {abs(exact - vqa_result.final_eigenvalue):.2e}\n")


def pennylane_section() -> None:
    print("-- PennyLane qchem: real H2 Hamiltonian --")
    try:
        from qpubench.hamiltonian_sources.pennylane_qchem import load_pennylane_qchem
    except ImportError:
        print("pennylane not installed — run: pip install 'qpubench[pennylane]'")
        return

    obs, record = load_pennylane_qchem("H2", basis="STO-3G", bondlength=0.5)
    print(f"  {record.molecule_name}/{record.basis} @ {record.bond_length} A "
          f"({record.num_qubits} qubits, {record.num_terms} terms)")
    print(f"  PennyLane fci_energy: {record.fci_energy:.9f} Ha")
    print(f"  PennyLane vqe_energy: {record.vqe_energy:.9f} Ha")

    try:
        from examples.common.toy_hamiltonians import exact_ground_state_energy
    except ImportError:
        print("  scipy/numpy not installed — run: pip install 'qpubench[adapt_vqe]'")
        return

    exact = exact_ground_state_energy(obs)
    print(f"  our dense diagonalization:  {exact:.9f} Ha (matches fci_energy)")


def main() -> None:
    hamlib_section()
    pennylane_section()


if __name__ == "__main__":
    main()
