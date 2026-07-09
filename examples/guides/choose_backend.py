"""qrunch guide: "Choose a Backend"

Verdict: Yes — broader than qrunch's own backend list. BackendSpec exposes
one factory method per backend family; this tours a representative sample.

Run:
    python examples/guides/choose_backend.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from qpubench import BackendSpec


def main() -> None:
    backends = [
        ("Simulator (statevector)", BackendSpec.aer_statevector(num_qubits=8)),
        ("Simulator (GPU, Qrack)",  BackendSpec.qrack(num_qubits=20, gpu=True)),
        ("Simulator (CUDA-Q)",      BackendSpec.cudaq(target="nvidia")),
        ("Real hardware (IBM)",     BackendSpec.ibm("ibm_brisbane")),
        ("Real hardware (IQM)",     BackendSpec.iqm("garnet_star")),
        ("Real hardware (AWS Braket)", BackendSpec.braket(
            "arn:aws:braket:us-east-1::device/qpu/rigetti/Ankaa-3",
            s3_bucket_ref="MY_BRAKET_BUCKET",
        )),
        ("Photonic (Perceval)",     BackendSpec.perceval()),
        ("Neutral atom (Aquila)",   BackendSpec.aquila()),
    ]

    for label, spec in backends:
        print(f"{label:32s} name={spec.name!r:24s} provider={spec.provider!r:14s} "
              f"simulator={spec.simulator!s:6s} modality={spec.qubit_modality}")


if __name__ == "__main__":
    main()
