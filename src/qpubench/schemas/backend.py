from __future__ import annotations

import pydantic

from .primitives import QPUModality


class QubitCharacteristics(pydantic.BaseModel):
    """Per-qubit hardware properties.

    Mirrors fields reported by IBM Quantum backend properties and
    Qiskit C QkInstructionProperties {duration_s, error_rate}.
    All fields are optional — simulators leave them None.
    """
    qubit_index:       int
    t1_s:              float | None = None   # T1 energy relaxation time (seconds)
    t2_s:              float | None = None   # T2 dephasing time (seconds)
    frequency_hz:      float | None = None
    anharmonicity_hz:  float | None = None
    readout_error:     float | None = None   # average (p(1|0) + p(0|1)) / 2
    readout_length_s:  float | None = None
    prob_meas0_prep1:  float | None = None   # |0⟩ prepared, |1⟩ measured
    prob_meas1_prep0:  float | None = None   # |1⟩ prepared, |0⟩ measured


class GateCharacteristics(pydantic.BaseModel):
    """Per-gate hardware properties.

    Mirrors Qiskit C API QkInstructionProperties {duration_s, error_rate}.
    qubit_indices is a tuple to support both 1Q and 2Q gates.
    """
    gate_name:     str
    qubit_indices: tuple[int, ...]
    duration_s:    float | None = None
    error_rate:    float | None = None


class BackendSpec(pydantic.BaseModel):
    """Hardware / simulator description.

    Covers all supported backend families:
      provider="aer"   — Qiskit Aer (statevector, QASM, noise model)
      provider="ibm"   — IBM Quantum Runtime
      provider="iqm"   — IQM hardware
      provider="qibo"  — Qibo cloud
      provider="qrack" — Qrack GPU/CPU simulator (PyQrack ctypes interface)
      provider="mbqc"  — MBQC-FPGA

    auth holds provider-specific credentials as opaque strings so this
    schema stays provider-neutral.  Adapters extract what they need.
    """
    name:              str
    provider:          str
    qpu_modality:      QPUModality             = QPUModality.GATE_BASED
    num_qubits:        int | None              = None
    simulator:         bool                    = False
    native_gates:      list[str]               = []
    max_shots:         int | None              = None
    coupling_map:      list[tuple[int, int]]   = []
    qubit_characteristics: list[QubitCharacteristics] = []
    gate_characteristics:  list[GateCharacteristics]  = []
    avg_gate_fidelity: float | None            = None   # Qrack: GetUnitaryFidelity()
    auth:              dict[str, str]          = {}

    def gate_error(self, gate_name: str, qubits: tuple[int, ...]) -> float | None:
        for g in self.gate_characteristics:
            if g.gate_name == gate_name and g.qubit_indices == qubits:
                return g.error_rate
        return None

    def qubit_t1(self, qubit: int) -> float | None:
        for q in self.qubit_characteristics:
            if q.qubit_index == qubit:
                return q.t1_s
        return None

    # Convenience constructors -------------------------------------------------

    @classmethod
    def aer_statevector(cls, num_qubits: int | None = None) -> BackendSpec:
        return cls(
            name="aer_statevector",
            provider="aer",
            simulator=True,
            num_qubits=num_qubits,
        )

    @classmethod
    def aer_qasm(cls, num_qubits: int | None = None) -> BackendSpec:
        return cls(
            name="aer_qasm_simulator",
            provider="aer",
            simulator=True,
            num_qubits=num_qubits,
            max_shots=100_000,
        )

    @classmethod
    def ibm(
        cls,
        backend_name: str,
        *,
        instance:  str = "ibm-q/open/main",
        channel:   str = "ibm_quantum",
        token_ref: str = "",
    ) -> BackendSpec:
        return cls(
            name=backend_name,
            provider="ibm",
            auth={
                "token_ref": token_ref,
                "instance":  instance,
                "channel":   channel,
            },
        )

    @classmethod
    def qrack(
        cls,
        num_qubits: int | None = None,
        *,
        gpu: bool = True,
    ) -> BackendSpec:
        return cls(
            name=f"qrack_{'gpu' if gpu else 'cpu'}",
            provider="qrack",
            simulator=True,
            num_qubits=num_qubits,
            auth={"gpu": str(gpu)},
        )

    @classmethod
    def cudaq(
        cls,
        target: str = "nvidia",
        num_qubits: int | None = None,
    ) -> BackendSpec:
        """CUDA-Q simulator — default backend for GSOpt VQE benchmarks.

        target  CUDA-Q device target: "nvidia" (GPU), "qpp-cpu" (CPU simulator),
                "tensornet", etc.
        """
        return cls(
            name=target,
            provider="cudaq",
            simulator=True,
            num_qubits=num_qubits,
            auth={"target": target},
        )

    @classmethod
    def lightning_qubit(cls, num_qubits: int | None = None) -> BackendSpec:
        """PennyLane lightning.qubit — used as default backend in Cebule TN_QC_OPT."""
        return cls(
            name="lightning.qubit",
            provider="pennylane",
            simulator=True,
            num_qubits=num_qubits,
        )

    @classmethod
    def cebule(
        cls,
        *,
        email_ref: str = "",
        password_ref: str = "",
    ) -> BackendSpec:
        """Cebule cloud backend (MQS SDK). Credentials are env-var references."""
        return cls(
            name="cebule_cloud",
            provider="cebule",
            simulator=False,
            auth={
                "email_ref":    email_ref,
                "password_ref": password_ref,
            },
        )

    @classmethod
    def mbqc_fpga(
        cls,
        num_logical_qubits: int,
        *,
        fpga_family: str = "xilinx_7series",
    ) -> BackendSpec:
        return cls(
            name=f"mbqc_fpga_{fpga_family}",
            provider="mbqc",
            qpu_modality=QPUModality.MBQC,
            num_qubits=num_logical_qubits,
            auth={"fpga_family": fpga_family},
        )
