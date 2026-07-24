from __future__ import annotations

import pydantic

from .primitives import ComputingModel, QubitModality


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
      provider="quantinuum" — Quantinuum H-Series (pytket-quantinuum)
      provider="qibo"  — Qibo simulator / Qibolab hardware / Qibo cloud
      provider="qrack" — Qrack GPU/CPU simulator (PyQrack ctypes interface)
      provider="mbqc"  — MBQC-FPGA

    auth holds provider-specific credentials as opaque strings so this
    schema stays provider-neutral.  Adapters extract what they need.
    """
    name:              str
    provider:          str
    computing_model:   ComputingModel          = ComputingModel.GATE_BASED
    qubit_modality:    QubitModality | None    = None
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
        channel:   str = "ibm_quantum_platform",
        token_ref: str = "",
    ) -> BackendSpec:
        """
        channel default is "ibm_quantum_platform" — confirmed against the
        installed qiskit-ibm-runtime (0.47.x): QiskitRuntimeService now
        raises ValueError for the old "ibm_quantum" channel ("'channel' can
        only be 'ibm_cloud', or 'ibm_quantum_platform'"), a real migration
        away from the legacy IBM Quantum Platform "IQP" channel.
        `instance` (hub/group/project) may also need to become a Cloud
        Resource Name (CRN) string under the new channel — not verified
        here; check your IBM Quantum account's migration guidance.
        """
        return cls(
            name=backend_name,
            provider="ibm",
            qubit_modality=QubitModality.SUPERCONDUCTING,
            auth={
                "token_ref": token_ref,
                "instance":  instance,
                "channel":   channel,
            },
        )

    @classmethod
    def braket(
        cls,
        device_arn: str,
        *,
        qubit_modality: QubitModality = QubitModality.SUPERCONDUCTING,
        num_qubits: int | None = None,
        s3_bucket_ref: str = "",
        s3_prefix: str = "braket-results",
    ) -> BackendSpec:
        """Generic gate-based AWS Braket device.

        device_arn  full Braket device ARN, e.g.
                     "arn:aws:braket:us-east-1::device/qpu/rigetti/Ankaa-3"
                     "arn:aws:braket:us-east-1::device/qpu/ionq/Aria-1"
                     "arn:aws:braket:::device/quantum-simulator/amazon/sv1"
        s3_bucket_ref  env-var reference to the S3 bucket Braket writes task
                       results to — every Braket job (simulator or QPU)
                       requires an S3 output location; there is no
                       synchronous "just return the result" call.
        s3_prefix      key prefix under the bucket for this backend's results.

        This is the generic gate-based Braket path — distinct from the
        modality-specific Braket wiring elsewhere in the schema layer:
        `xanadu_borealis(via_braket=True)` (GBS) and `aquila()` (neutral-atom
        AHS) each talk to Braket for their own specialized IR, not OpenQASM.
        """
        return cls(
            name=device_arn.rsplit("/", 1)[-1],
            provider="aws_braket",
            qubit_modality=qubit_modality,
            simulator="quantum-simulator" in device_arn,
            num_qubits=num_qubits,
            auth={
                "device_arn":    device_arn,
                "s3_bucket_ref": s3_bucket_ref,
                "s3_prefix":     s3_prefix,
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
            computing_model=ComputingModel.MBQC,
            num_qubits=num_logical_qubits,
            auth={"fpga_family": fpga_family},
        )

    @classmethod
    def photochipsim(cls, num_modes: int = 6) -> BackendSpec:
        """photochipsim linear-optics simulator (thewalrus permanent engine)."""
        return cls(
            name=f"photochipsim_{num_modes}mode",
            provider="photochipsim",
            computing_model=ComputingModel.GATE_BASED,
            qubit_modality=QubitModality.PHOTONIC,
            simulator=True,
            num_qubits=num_modes,
            auth={"num_modes": str(num_modes)},
        )

    @classmethod
    def strawberry_fields(
        cls,
        backend: str = "fock",
        num_modes: int = 6,
        cutoff_dim: int = 5,
    ) -> BackendSpec:
        """Xanadu Strawberry Fields simulator.

        backend  "fock"        — Fock-basis simulator (exact, exponential cost)
                 "gaussian"    — Gaussian state simulator
                 "tf"          — TensorFlow differentiable backend
        """
        return cls(
            name=f"sf_{backend}",
            provider="strawberry_fields",
            computing_model=ComputingModel.GATE_BASED,
            qubit_modality=QubitModality.PHOTONIC,
            simulator=True,
            num_qubits=num_modes,
            auth={"backend": backend, "cutoff_dim": str(cutoff_dim)},
        )

    @classmethod
    def perceval(
        cls,
        backend: str = "SLOS",
        num_modes: int = 6,
    ) -> BackendSpec:
        """Quandela Perceval photonic simulator.

        backend  "SLOS"  — Schrödinger LOQC Simulator (state-vector)
                 "MPS"   — matrix product state backend
                 "Naive" — brute-force permanent computation
        """
        return cls(
            name=f"perceval_{backend}",
            provider="perceval",
            computing_model=ComputingModel.GATE_BASED,
            qubit_modality=QubitModality.PHOTONIC,
            simulator=True,
            num_qubits=num_modes,
            auth={"backend": backend},
        )

    @classmethod
    def photonic_chip_hardware(
        cls,
        chip_id: str,
        platform: str = "silicon_nitride",
        num_modes: int = 6,
    ) -> BackendSpec:
        """Real photonic integrated circuit hardware backend."""
        return cls(
            name=chip_id,
            provider="photonic_hardware",
            computing_model=ComputingModel.GATE_BASED,
            qubit_modality=QubitModality.PHOTONIC,
            simulator=False,
            num_qubits=num_modes,
            auth={"platform": platform, "chip_id": chip_id},
        )

    @classmethod
    def xanadu_x8(cls, num_modes: int = 8) -> BackendSpec:
        """Xanadu X8 photonic chip — 8-mode PNR GBS hardware.

        Accessed via Xanadu Cloud RemoteEngine("X8") or the Strawberry Fields
        remote engine.  num_modes fixed at 8 (4 signal + 4 idler).
        """
        return cls(
            name="xanadu_x8",
            provider="xanadu",
            computing_model=ComputingModel.GBS,
            qubit_modality=QubitModality.PHOTONIC,
            simulator=False,
            num_qubits=num_modes,
            auth={"device": "X8"},
        )

    @classmethod
    def xanadu_borealis(cls, via_braket: bool = False) -> BackendSpec:
        """Xanadu Borealis TDM GBS hardware — 216 effective modes.

        via_braket=True  uses the AWS Braket BraketEngine with the
        Borealis ARN; via_braket=False uses the native SF RemoteEngine.
        """
        arn = "arn:aws:braket:us-east-1::device/qpu/xanadu/Borealis"
        return cls(
            name="xanadu_borealis",
            provider="aws_braket" if via_braket else "xanadu",
            computing_model=ComputingModel.GBS,
            qubit_modality=QubitModality.PHOTONIC,
            simulator=False,
            num_qubits=216,
            auth={
                "device": "Borealis",
                "device_arn": arn if via_braket else "",
                "via_braket": str(via_braket),
            },
        )

    @classmethod
    def strawberry_fields_gaussian(cls, num_modes: int | None = None) -> BackendSpec:
        """Strawberry Fields Gaussian state simulator for GBS.

        Distinct from the Fock-basis SF backend: uses the covariance-matrix
        formalism and thewalrus hafnian for photon-number probabilities.
        """
        return cls(
            name="sf_gaussian",
            provider="strawberry_fields",
            computing_model=ComputingModel.GBS,
            qubit_modality=QubitModality.PHOTONIC,
            simulator=True,
            num_qubits=num_modes,
        )

    @classmethod
    def orca_pt_series(
        cls,
        num_modes: int = 8,
        num_loops: int = 1,
        device: str = "PT-2",
        simulated: bool = True,
    ) -> BackendSpec:
        """ORCA Computing PT Series time-bin interferometer (GBS boson sampler).

        A single physical beamsplitter plus ``num_loops`` fibre delay loops,
        applied across ``num_modes`` time bins.  simulated=True draws hafnian
        samples from the TBI covariance matrix (thewalrus); simulated=False
        targets real PT-1/PT-2 hardware via ORCA's ptseries SDK.
        See mqsdk_photoq.TimeBinInterferometerSpec / PTSeriesSamplingConfig.
        """
        return cls(
            name=f"orca_{device.lower()}_{num_modes}mode",
            provider="orca",
            computing_model=ComputingModel.GBS,
            qubit_modality=QubitModality.PHOTONIC,
            simulator=simulated,
            num_qubits=num_modes,
            auth={"device": device, "num_loops": str(num_loops)},
        )

    @classmethod
    def dtu_qcloud(
        cls,
        job_type: str = "tn-sampling",
        num_modes: int | None = None,
        base_url: str = "https://qcloud.dtu.dk",
    ) -> BackendSpec:
        """DTU QCloud tensor-network GBS backend (REST API v1, qcloud.dtu.dk).

        job_type  "tn-covariance" builds a covariance matrix server-side;
                  "tn-sampling" runs tensor-network (MPS) GBS sampling — the
                  successor of the DASQ Kensingtonian sampler, aligned with the
                  photoq paper's tensor-network method.
        Auth is a Bearer token; obtain one from the QCloud web UI.
        See mqsdk_photoq.QCloudJobSpec / TNSamplingParams.
        """
        return cls(
            name=f"dtu_qcloud_{job_type}",
            provider="dtu_qcloud",
            computing_model=ComputingModel.GBS,
            qubit_modality=QubitModality.PHOTONIC,
            simulator=True,
            num_qubits=num_modes,
            auth={"job_type": job_type, "base_url": base_url},
        )

    @classmethod
    def xanadu_aurora(cls, experiment: str = "cluster_state") -> BackendSpec:
        """Xanadu Aurora dataset backend — modular photonic QC (Nature 638, 2025).

        Aurora (35 chips, 84 squeezers, 36 PNRDs, 12 qubit modes/cycle) is a
        published *dataset*, not a programmable device: the two experiment sets
        are 'cluster_state' (Fig. 3b) and 'decoder_demo' (Figs. 3c-d), served
        from the public S3 bucket 'xanadu-aurora-data'.
        See mqsdk_photoq.AuroraDatasetSpec.
        """
        return cls(
            name=f"xanadu_aurora_{experiment}",
            provider="xanadu",
            computing_model=ComputingModel.GBS,
            qubit_modality=QubitModality.PHOTONIC,
            simulator=False,
            num_qubits=12,
            auth={"experiment": experiment, "dataset": "xanadu-aurora-data"},
        )

    @classmethod
    def qesem(
        cls,
        backend_name: str,
        *,
        api_token_ref: str = "",
        via_qiskit_function: bool = False,
    ) -> BackendSpec:
        """Qedma QESEM error suppression and mitigation service.

        QESEM wraps an IBM gate-based backend with noise-aware transpilation,
        device characterization, and quasi-probabilistic error tuning (QET).

        backend_name         IBM backend to target, e.g. "ibm_fez", "ibm_torino".
        api_token_ref        Env-var name holding the Qedma API token.
        via_qiskit_function  True when submitting through the IBM Qiskit Functions
                             catalog (QiskitFunctionsCatalog) rather than directly
                             via the qedma-api client.
        """
        return cls(
            name=f"qesem_{backend_name}",
            provider="qedma",
            computing_model=ComputingModel.GATE_BASED,
            qubit_modality=QubitModality.SUPERCONDUCTING,
            simulator=False,
            auth={
                "backend_name":         backend_name,
                "api_token_ref":        api_token_ref,
                "via_qiskit_function":  str(via_qiskit_function),
            },
        )

    @classmethod
    def qiskit_aer(
        cls,
        method: str = "statevector",
        num_qubits: int | None = None,
    ) -> BackendSpec:
        """Qiskit Aer simulator — default backend for KQD/QSE benchmarks.

        method  "statevector"   — exact state-vector simulation
                "matrix_product_state" — MPS simulation for larger systems
                "stabilizer"    — Clifford-only stabilizer simulation
        """
        return cls(
            name=f"aer_{method}",
            provider="aer",
            computing_model=ComputingModel.GATE_BASED,
            simulator=True,
            num_qubits=num_qubits,
            auth={"method": method},
        )

    @classmethod
    def qdk_chemistry_simulator(
        cls,
        executor: str = "qdk_sparse_state_simulator",
        num_qubits: int | None = None,
    ) -> BackendSpec:
        """Microsoft QDK chemistry simulator backend.

        executor  "qdk_sparse_state_simulator" — sparse statevector (≤~20 qubits).
                  "qdk_full_state_simulator"   — dense statevector (< 14 qubits).
                  "qiskit_aer_simulator"       — Aer with noise model support.
        """
        return cls(
            name=executor,
            provider="qdk_chemistry",
            computing_model=ComputingModel.GATE_BASED,
            simulator=True,
            num_qubits=num_qubits,
            auth={"executor": executor},
        )

    @classmethod
    def azure_quantum(
        cls,
        target: str,
        *,
        resource_id_ref: str = "",
        location_ref: str = "",
        qubit_modality: QubitModality | None = None,
    ) -> BackendSpec:
        """Azure Quantum hardware / resource-estimation target.

        target  Azure Quantum target id, e.g.:
                  "microsoft.estimator"          — QDK resource estimator
                  "quantinuum.hqs-lt-s1"         — Quantinuum H1 hardware
                  "ionq.simulator"               — IonQ cloud simulator
        Credentials are stored as env-var references.

        qubit_modality  QPU modality override. Inferred from target
                        when omitted: "quantinuum"/"ionq" (non-simulator) →
                        TRAPPED_ION; simulator/estimator targets → None.
        """
        if qubit_modality is None and "simulator" not in target and "estimator" not in target:
            if "quantinuum" in target or "ionq" in target:
                qubit_modality = QubitModality.TRAPPED_ION
        return cls(
            name=target,
            provider="azure_quantum",
            computing_model=ComputingModel.GATE_BASED,
            qubit_modality=qubit_modality,
            simulator=("simulator" in target or "estimator" in target),
            auth={
                "target":           target,
                "resource_id_ref":  resource_id_ref,
                "location_ref":     location_ref,
            },
        )

    @classmethod
    def aquila(
        cls,
        *,
        aws_region: str = "us-east-1",
        api_token_ref: str = "",
    ) -> BackendSpec:
        """QuEra Aquila 256-qubit neutral-atom QPU via AWS Braket.

        aws_region     AWS region hosting the Aquila device.
        api_token_ref  Environment variable name holding the AWS credentials
                       (or empty to use the default boto3 credential chain).
        """
        return cls(
            name="aquila",
            provider="quera",
            computing_model=ComputingModel.ADIABATIC,
            qubit_modality=QubitModality.NEUTRAL_ATOM,
            simulator=False,
            auth={
                "device_arn": f"arn:aws:braket:{aws_region}::device/qpu/quera/Aquila",
                "aws_region": aws_region,
                "api_token_ref": api_token_ref,
            },
        )

    @classmethod
    def iqm(
        cls,
        device_name: str,
        *,
        num_qubits: int | None = None,
        api_token_ref: str     = "",
    ) -> BackendSpec:
        """IQM hardware backend (generic constructor).

        Star architecture: all qubits connected via central resonator (COMPR1).
        Native gates: PRX(θ, φ), CZ, MOVE (qubit ↔ resonator).
        Angles for PRX are in fractions of turns (not radians).

        Use iqm_resonance() for IQM Resonance cloud access.
        """
        return cls(
            name=device_name,
            provider="iqm",
            computing_model=ComputingModel.GATE_BASED,
            qubit_modality=QubitModality.SUPERCONDUCTING,
            simulator=False,
            num_qubits=num_qubits,
            native_gates=["prx", "cz", "move"],
            auth={"api_token_ref": api_token_ref, "device": device_name},
        )

    @classmethod
    def iqm_resonance(
        cls,
        device_name: str = "garnet",
        *,
        num_qubits: int | None = None,
        api_token_ref: str     = "",
    ) -> BackendSpec:
        """IQM Resonance cloud QPU access.

        Known devices:
          "garnet"  — 20-qubit IQM Garnet
          "deneb"   — 6-qubit IQM Deneb (first commercially deployed IQM QPU)
          "sirius"  — 24-qubit IQM Sirius (STAR 24 topology)

        Authentication: bearer token via IQM_TOKEN env var or api_token_ref.
        Endpoint: https://cocos.resonance.meetiqm.com/v1
        """
        _NUM_QUBITS = {"garnet": 20, "deneb": 6, "sirius": 24}
        return cls(
            name=f"iqm_{device_name}",
            provider="iqm",
            computing_model=ComputingModel.GATE_BASED,
            qubit_modality=QubitModality.SUPERCONDUCTING,
            simulator=False,
            num_qubits=num_qubits or _NUM_QUBITS.get(device_name),
            native_gates=["prx", "cz", "move"],
            auth={
                "api_token_ref": api_token_ref,
                "device_name":   device_name,
                "endpoint":      "https://cocos.resonance.meetiqm.com/v1",
            },
        )

    @classmethod
    def iqm_local_server(
        cls,
        url: str,
        device_name: str,
        *,
        num_qubits: int | None = None,
        api_token_ref: str     = "",
    ) -> BackendSpec:
        """IQM on-premise / local IQM Resonance server.

        url  base URL of the local IQM Cortex server, e.g.
             "http://iqm-server.local:8080/v1"
        """
        return cls(
            name=f"iqm_local_{device_name}",
            provider="iqm",
            computing_model=ComputingModel.GATE_BASED,
            qubit_modality=QubitModality.SUPERCONDUCTING,
            simulator=False,
            num_qubits=num_qubits,
            native_gates=["prx", "cz", "move"],
            auth={"api_token_ref": api_token_ref, "device_name": device_name, "endpoint": url},
        )

    @classmethod
    def quantinuum(
        cls,
        device_name: str = "H2-1E",
        *,
        num_qubits: int | None = None,
        user_ref: str = "",
    ) -> BackendSpec:
        """Quantinuum H-Series trapped-ion QPU (accessed via pytket-quantinuum).

        Devices (H2 generation — see Quantinuum's API options docs):
          "H2-1"    — 56-qubit H2 hardware
          "H2-1E"   — H2 emulator (physically-accurate noise model, cloud)
          "H2-1SC"  — H2 syntax checker (free circuit validation, no shots)
          "H1-1" / "H1-1E" / "H1-1SC"  — 20-qubit H1 generation

        All-to-all connectivity (ion shuttling / QCCD), so no SWAP routing.
        Native gates: Rz, PhasedX (U1q), ZZPhase (RZZ) / ZZMax.

        Authentication: pytket-quantinuum logs in through the Quantinuum
        Nexus credential store — run ``QuantinuumBackend.login()`` once (or
        ``qnexus.login()``) to cache a token; ``user_ref`` is the env-var name
        holding the account username/email for non-interactive login.
        """
        _NUM_QUBITS = {
            "H2-1": 56, "H2-1E": 56, "H2-1SC": 56,
            "H1-1": 20, "H1-1E": 20, "H1-1SC": 20,
        }
        return cls(
            name=f"quantinuum_{device_name}",
            provider="quantinuum",
            computing_model=ComputingModel.GATE_BASED,
            qubit_modality=QubitModality.TRAPPED_ION,
            simulator=device_name.endswith(("E", "SC")),
            num_qubits=num_qubits or _NUM_QUBITS.get(device_name),
            native_gates=["rz", "phasedx", "zzphase", "zzmax"],
            auth={"device_name": device_name, "user_ref": user_ref},
        )

    @classmethod
    def qibo_simulator(
        cls,
        backend: str = "numpy",
        num_qubits: int | None = None,
    ) -> BackendSpec:
        """Local Qibo simulator (``qibo.set_backend(backend)``).

        backend  Qibo simulation engine: "numpy" (reference), "qibojit"
                 (Numba/CuPy JIT), "tensorflow", "pytorch". All run locally
                 with no credentials.
        """
        return cls(
            name=f"qibo_{backend}",
            provider="qibo",
            computing_model=ComputingModel.GATE_BASED,
            simulator=True,
            num_qubits=num_qubits,
            auth={"execution": "local", "platform": backend},
        )

    @classmethod
    def qibolab(
        cls,
        platform: str,
        *,
        num_qubits: int | None = None,
        qubit_modality: QubitModality = QubitModality.SUPERCONDUCTING,
    ) -> BackendSpec:
        """Self-hosted QPU driven by Qibolab (``qibo.set_backend("qibolab", platform=...)``).

        Qibolab compiles circuits to pulse sequences and drives the control
        electronics of a self-hosted lab QPU. ``platform`` names a Qibolab
        Platform (a lab's device + instrument configuration), resolved from
        the ``QIBOLAB_PLATFORMS`` directory. See
        https://qibo.science/qibolab/stable/.
        """
        return cls(
            name=f"qibolab_{platform}",
            provider="qibo",
            computing_model=ComputingModel.GATE_BASED,
            qubit_modality=qubit_modality,
            simulator=False,
            num_qubits=num_qubits,
            auth={"execution": "qibolab", "platform": platform},
        )

    @classmethod
    def qibo_cloud(
        cls,
        platform: str = "sim",
        *,
        client: str = "qibo-client",
        token_ref: str = "",
        num_qubits: int | None = None,
        qubit_modality: QubitModality = QubitModality.SUPERCONDUCTING,
    ) -> BackendSpec:
        """Remote QPU via qibo-cloud-backends
        (``qibo.set_backend("qibo-cloud-backends", client=..., platform=...)``).

        client    "qibo-client"  — Qibo cloud infrastructure (TII); token env
                                    var QIBO_CLIENT_TOKEN.
                  "qiskit-client" — IBM Quantum servers; token env var
                                    IBMQ_TOKEN.
        platform  remote device id, e.g. "sim" (Qibo cloud simulator) or
                  "ibm_kyiv" (IBM QPU via the qiskit client).
        token_ref env-var name holding the client access token.
        See https://qibo.science/qibo-cloud-backends/stable/.
        """
        is_sim = platform == "sim"
        return cls(
            name=f"qibo_cloud_{platform}",
            provider="qibo",
            computing_model=ComputingModel.GATE_BASED,
            qubit_modality=None if is_sim else qubit_modality,
            simulator=is_sim,
            num_qubits=num_qubits,
            auth={
                "execution": "cloud",
                "platform":  platform,
                "client":    client,
                "token_ref": token_ref,
            },
        )

    @classmethod
    def quantum_motion(
        cls,
        device_name: str,
        *,
        num_qubits: int | None = None,
        gate_access: str       = "qiskit",
    ) -> BackendSpec:
        """Quantum Motion silicon CMOS spin-qubit QPU.

        Quantum Motion fabricates spin-qubit processors in standard CMOS
        foundries (first full-stack CMOS QPU delivered to UK NQCC, 2025).
        Exposed via Qiskit- or Cirq-compatible backends.

        gate_access  "qiskit" | "cirq"
        """
        return cls(
            name=device_name,
            provider="quantum_motion",
            computing_model=ComputingModel.GATE_BASED,
            qubit_modality=QubitModality.SILICON_SPIN,
            simulator=False,
            num_qubits=num_qubits,
            auth={"gate_access": gate_access},
        )

    @classmethod
    def q_ctrl_fire_opal(
        cls,
        backend_name: str,
        *,
        api_key_ref:  str = "",
        instance_ref: str = "",
    ) -> BackendSpec:
        """Q-CTRL Fire Opal noise-robust compilation service.

        Fire Opal wraps an IBM hardware backend with automated error suppression
        (pulse-level optimisation + dynamical decoupling).

        Credentials: IBM Cloud API key + CRN instance string.
        Python package: fireopal
        API: fo.execute(circuits, shot_count, credentials, backend_name)
        """
        return cls(
            name=f"fire_opal_{backend_name}",
            provider="q_ctrl",
            computing_model=ComputingModel.GATE_BASED,
            qubit_modality=QubitModality.SUPERCONDUCTING,
            simulator=False,
            auth={
                "backend_name": backend_name,
                "api_key_ref":  api_key_ref,
                "instance_ref": instance_ref,
            },
        )

    @classmethod
    def haiqu(
        cls,
        backend_name: str,
        *,
        transpiler_backend: str = "qiskit",
    ) -> BackendSpec:
        """Haiqu Rivet transpilation middleware wrapping a hardware backend.

        Rivet (open-source: haiqu-ai/rivet) provides hardware-aware caching
        and pipelining of transpilation passes.  The proprietary Haiqu SDK
        adds state compression and error mitigation on top.

        transpiler_backend  "qiskit" | "bqskit" | "pytket"
        """
        return cls(
            name=f"haiqu_{backend_name}",
            provider="haiqu",
            computing_model=ComputingModel.GATE_BASED,
            simulator=False,
            auth={"backend_name": backend_name, "transpiler": transpiler_backend},
        )

    @classmethod
    def bloqade_emulator(cls, num_qubits: int | None = None) -> BackendSpec:
        """Bloqade Python local AHS emulator (exact state-vector / KrylovKit).

        Runs on CPU; practical up to ~20 atoms for full state-vector simulation.
        No API credentials required — purely local.
        """
        return cls(
            name="bloqade_python",
            provider="bloqade",
            computing_model=ComputingModel.ADIABATIC,
            qubit_modality=QubitModality.NEUTRAL_ATOM,
            simulator=True,
            num_qubits=num_qubits,
        )
