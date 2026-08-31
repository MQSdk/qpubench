"""Build and submit one campaign run as a Cebule `TN_QC_OPT` task.

Imported, not run.  Two things execute a campaign -- `run_campaign.py` on
the command line and
`data/benchmarks/ibm_tn-vqe_qesem/run_campaign_batch.ipynb` in Jupyter --
and both go through here, so a correction to how a run is built reaches
both rather than one of them.  That matters more than usual for this
campaign: a run's identity is its Hamiltonian, its pinned circuit and its
initial parameters together, and two implementations of "build the input"
would eventually disagree about one of them without anything failing.

Requires: `pip install 'qpubench[cebule]'` to submit; building and
validating inputs needs only numpy and this repository.

Credentials are never read from a notebook or a command line.  They come
from CEBULE_EMAIL / CEBULE_PASSWORD in the environment, or from the
repository's gitignored `.env`; see `open_session`.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys
import time
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import numpy as np
from _ansatz_builders import PHI_INIT_SEED

from qpubench.schemas.mirrors.mqsdk_cebule import TNAnsatz, TNQCOptInput
from qpubench.schemas.observable import SparsePauliObservable

REPO = pathlib.Path(__file__).resolve().parents[1]
CAMPAIGN = REPO / "data" / "benchmarks" / "ibm_tn-vqe_qesem"
HAMILTONIAN_DATA = CAMPAIGN / "hamiltonian_data"
RESULTS_DIR = CAMPAIGN / "results"

# get_backend dispatches on this string: 'ibm*' routes to hardware, the
# four named simulators and anything prefixed 'fake' to Qiskit, anything
# else to PennyLane.
NETWORK_ONLY_BACKEND = "aer_simulator"


# --- The circuit ----------------------------------------------------------

def verified_qasm(run: dict[str, str]) -> str:
    """The run's pinned circuit, refusing one that has changed since.

    A named ansatz is not a circuit, so the hash is the run's identity as
    much as the family name is: a silently edited QASM file would make two
    runs that claim to share a circuit not share one.
    """
    path = REPO / run["Qasm_Ansatz_File"]
    text = path.read_text()
    digest = hashlib.sha256(text.encode()).hexdigest()[:12]
    if digest != run["Qasm_Ansatz_SHA256"]:
        raise ValueError(
            f"{path.name}: sha256 {digest} does not match the campaign's "
            f"{run['Qasm_Ansatz_SHA256']}. The pinned circuit changed after "
            f"the campaign was generated; regenerate or restore it before running."
        )
    return text


def phi_init(run: dict[str, str]) -> list[float]:
    """The run's circuit-parameter initialisation, from its own column.

    Keyed on the ansatz family alone, so two runs sharing a circuit start
    from the same phi whatever else differs between them -- which is what
    makes a difference between them attributable to the method.  Upstream
    randomises phi unseeded when it is None, which is the defect this
    pins.
    """
    n = int(run["Num_Opt_Params_Phi"])
    if run["Phi_Init"] == "zeros":
        return [0.0] * n
    return (2 * np.pi * np.random.default_rng(PHI_INIT_SEED).random(n)).tolist()


# --- The Hamiltonian ------------------------------------------------------

def parse_geometry(spec: str) -> list[tuple[str, tuple[float, float, float]]]:
    atoms = []
    for atom in spec.split(";"):
        symbol, x, y, z = atom.split()
        atoms.append((symbol, (float(x), float(y), float(z))))
    return atoms


def to_cebule_operators(observable: Any) -> tuple[list[float], list[str]]:
    """(coefficients, "X0 Y1 Z3" token strings), the inverse of
    SparsePauliObservable.from_cebule_operators. The identity term encodes
    as the empty string, which is what that parser reads it back from."""
    # A molecular Hamiltonian is Hermitian, so every coefficient is real;
    # Cebule's h_coeff_values is a list[float], so assert rather than discard.
    assert all(abs(term.coefficient.im) < 1e-12 for term in observable.terms), \
        "complex coefficient in a Hamiltonian Cebule expects to be real"
    coefficients = [term.coefficient.re for term in observable.terms]
    operators = [
        # op.value, not op: PauliLabel subclasses str but is a plain Enum,
        # so an f-string renders it "PauliLabel.X" rather than "X".
        " ".join(f"{op.value}{qubit}"
                 for qubit, op in zip(term.qubit_indices, term.pauli_ops))
        for term in observable.terms
    ]
    round_trip = SparsePauliObservable.from_cebule_operators(
        operators, coefficients, observable.num_qubits)
    assert round_trip.terms == observable.terms, "Cebule operator encoding is lossy"
    return coefficients, operators


# Committed Hamiltonians, keyed (molecule, basis, mapper). These are the
# operator the run actually optimises, and for mol_map they are the only
# source: that encoding is Cebule's, so this repository cannot derive it.
# File basis spellings differ from the campaign's, hence the table.
_FILE_MOLECULE = {"H2": "h2", "H2O": "water"}
_FILE_BASIS = {"sto-3g": "sto3g", "6-31g": "6-31G", "cc-pvdz": "cc-pvdz",
               "cc-pvtz": "cc-pvtz", "def2-tzvp": "def2-tzvp", "qvSZP": "qvSZP"}
_FILE_MAPPER = {"JW": "JW", "mol_map": "mapped"}


def hamiltonian_file(run: dict[str, str]) -> pathlib.Path | None:
    """The committed Hamiltonian for this run, or None if there is not one."""
    molecule = _FILE_MOLECULE.get(run["Molecule"])
    basis = _FILE_BASIS.get(run["Basis"])
    mapper = _FILE_MAPPER.get(run["Mapper"])
    if molecule is None or basis is None or mapper is None:
        return None
    path = HAMILTONIAN_DATA / f"{molecule}_{basis}_{mapper}.json"
    return path if path.exists() else None


def load_hamiltonian(
    path: pathlib.Path, run: dict[str, str],
) -> tuple[list[float], list[str], Any]:
    """(coefficients, operators, mapping_matrix) from a committed file,
    checked against the run.

    Operators are dense Pauli strings, one character per qubit ("ZIII").
    Cebule takes those as readily as the sparse "X0 Y1 Z3" form, so they
    are passed through rather than re-encoded: the file is the record of
    what was optimised, and rewriting it here would put a transformation
    between the record and the run.
    """
    payload = json.loads(path.read_text())
    coefficients, operators = payload["h_coeff_values"], payload["h_operators"]
    # The mol_map files carry the mapping operator D, and it is not
    # cosmetic: with a mapping_matrix AND tn_ansatz="givens" the run becomes
    # an orbital rotation on the reduced register, which is what sizes theta
    # by the SPATIAL ORBITALS rather than by the register. That is how the
    # campaign counts Num_Opt_Params_Theta, so omitting it here would submit
    # a theta shape the matrix does not describe.
    mapping_matrix = payload.get("mapping_matrix")
    if len(coefficients) != len(operators):
        raise ValueError(f"{path.name}: {len(operators)} operators against "
                         f"{len(coefficients)} coefficients")
    widths = {len(op) for op in operators}
    if len(widths) != 1:
        raise ValueError(f"{path.name}: operators of differing widths {sorted(widths)}")
    width = widths.pop()
    if width != int(run["N_Qubit"]):
        raise ValueError(f"{path.name}: {width}-qubit operators, but run "
                         f"{run['Case_ID']} is {run['N_Qubit']} qubits. The file "
                         f"does not describe this run.")
    return coefficients, operators, mapping_matrix


def unbuildable_reason(run: dict[str, str]) -> str | None:
    """Why this run's Hamiltonian cannot be obtained, or None if it can."""
    if hamiltonian_file(run) is not None:
        return None
    if run["Mapper"] != "JW":
        return (f"no committed Hamiltonian for {run['Molecule']}/{run['Basis']} "
                f"mol_map, and the encoding is Cebule's, so it needs a MOL_MAP task")
    if run["Basis"] == "qvSZP":
        return ("q-vSZP is not a PySCF basis, and hamiltonian_sources/qvszp.py "
                "parses shell letters and function counts only, not exponents")
    return None


def hamiltonian(run: dict[str, str]) -> tuple[list[float], list[str], Any] | None:
    """(coefficients, operators, mapping_matrix), or None if no source has it.

    A committed file wins over building one here: it is what the campaign
    recorded, and for mol_map it is the only thing that exists.
    """
    path = hamiltonian_file(run)
    if path is not None:
        return load_hamiltonian(path, run)
    if unbuildable_reason(run) is not None:
        return None
    from qpubench.hamiltonian_sources.ab_initio import build_qubit_hamiltonian
    restricted = run["Active_Space"] != "full"
    observable, _ = build_qubit_hamiltonian(
        parse_geometry(run["Geometry"]),
        basis=run["Basis"],
        charge=int(run["Charge"]),
        multiplicity=int(run["Multiplicity"]),
        active_electrons=int(run["Active_Electrons"]) if restricted else None,
        active_orbitals=int(run["Active_Orbitals"]) if restricted else None,
        mapper="jordan_wigner",
    )
    # Jordan-Wigner is not a reduced encoding, so there is no mapping
    # operator to hand back.
    return (*to_cebule_operators(observable), None)


# --- The task input -------------------------------------------------------

def backend_for(run: dict[str, str], override: str | None = None) -> str:
    """Which backend string this run is submitted against.

    THE RUN'S OWN `Backend_Platform` WINS by default, and that is not a
    detail: stage 0's backend is a factor it crosses, half its rows naming
    `aer_simulator` and half `fake_aachen`, so a single backend chosen at
    submission time would run one arm of that factor twice and the other
    never.  An override exists for the case the column cannot express --
    executing a hardware-targeted stage-1 row on a simulator first -- and
    it is a deliberate act rather than the default.

    A network run takes no quantum measurements whatever either says, so
    it never goes to hardware: naming a device there only makes Cebule
    authenticate against one the run does not use.
    """
    if run["Optimization_Mode"] == "network":
        return NETWORK_ONLY_BACKEND
    return override or run["Backend_Platform"]


def task_payload(task_input: TNQCOptInput) -> dict[str, Any]:
    """Keyword arguments for create_task.

    Fields left at an "unset" default are removed rather than sent: Cebule
    reads a missing theta_init as "use all zeros", but reads an empty list
    as a wrongly shaped one and raises.

    mode="json" so enums serialise to their values: TNAnsatz subclasses str
    and survives json.dumps by luck, but str() or an f-string on it anywhere
    upstream would render "TNAnsatz.GIVENS" rather than "givens".
    """
    payload = task_input.model_dump(mode="json", exclude={"task_type"}, exclude_none=True)
    if not payload.get("theta_init"):
        payload.pop("theta_init", None)
    return payload


def build_input(
    run: dict[str, str], backend_override: str | None = None,
) -> TNQCOptInput | None:
    """The task input for one run, or None if its Hamiltonian is unavailable."""
    h = hamiltonian(run)
    if h is None:
        return None
    coefficients, operators, mapping_matrix = h

    # A plain-VQE run is TN_QC_OPT with the network switched off: mode
    # "circuit" freezes theta, and zero network layers means there is no
    # theta to freeze.  tn_theta_parameter_count validates n_layers_network
    # >= 0 explicitly and returns 0 parameters at 0, which is why the
    # campaign leaves TN_Layers_Network and TN_Ansatz empty on these runs.
    plain_vqe = run["Method"] == "VQE"
    network_only = run["Optimization_Mode"] == "network"

    return TNQCOptInput(
        h_coeff_values=coefficients,
        h_operators=operators,
        mapping_matrix=mapping_matrix,
        n_iterations=int(run["Iterations"]),
        n_layers_network=0 if plain_vqe else int(run["TN_Layers_Network"]),
        qasm_ansatz=verified_qasm(run),
        # Supplying qasm_ansatz makes 1 the effective default upstream; pin it.
        n_layers_circuit=1,
        # Irrelevant at zero layers, so the model's own default stands.
        tn_ansatz=TNAnsatz.ROTATION_3PARAM if plain_vqe else TNAnsatz(run["TN_Ansatz"]),
        # theta_init is deliberately not set: the task's own default is
        # all-zero theta, and an empty list is not that -- it reaches the
        # shape check as a length-0 array against the (n_layers, n_nodes)
        # theta_shape and fails. task_payload drops it.
        phi_init=phi_init(run),
        opt_method=run["Optimizer"],
        opt_options=json.loads(run["Opt_Options"]),
        n_shots=None if network_only else int(run["Shots"]),
        backend=backend_for(run, backend_override),
        measurement_method="pauli" if network_only else run["Measurement_Method"],
        optimization_mode="circuit" if plain_vqe else run["Optimization_Mode"],
    )


def run_label(run: dict[str, str], backend_override: str | None = None) -> str:
    """One line describing what a run is, for a log or a dry run."""
    return (f"{run['Molecule']}/{run['Basis']} {run['Mapper']} {run['Method']} "
            f"{run['Ansatz']} {run['Optimizer']} {run['Optimization_Mode']} "
            f"on {backend_for(run, backend_override)}")


# --- Submitting and checkpointing -----------------------------------------

def open_session() -> Any:
    """A logged-in Cebule session, from the environment or the repo's .env.

    Credentials are deliberately not read from a notebook cell or a command
    line: one is saved into the document, the other into a shell history.
    """
    import mqsdk
    from dotenv import load_dotenv

    # Anything already exported in the shell wins, which is what
    # override=False gives us.
    load_dotenv(REPO / ".env", override=False)

    email, password = os.environ.get("CEBULE_EMAIL"), os.environ.get("CEBULE_PASSWORD")
    if not (email and password):
        raise RuntimeError(
            "Set CEBULE_EMAIL and CEBULE_PASSWORD, either in the repo's .env "
            f"({REPO / '.env'}) or exported in the shell. They are deliberately "
            "not read from a notebook cell or a command-line argument."
        )
    return mqsdk.Cebule(email, password)


def completed_case_ids(results_path: pathlib.Path) -> set[str]:
    """Case_IDs already in the checkpoint file, so a resumed pass skips them."""
    if not results_path.exists():
        return set()
    with results_path.open() as f:
        return {json.loads(line)["Case_ID"] for line in f if line.strip()}


def submit_run(
    session: Any, run: dict[str, str], task_input: TNQCOptInput, task_name: str,
) -> tuple[Any, float, str]:
    """Submit one run, wait for it, return (result, wall-clock seconds, task id).

    The task id comes back because it is the only handle on the submission
    afterwards -- it is what a result record is traced through to Cebule --
    and the caller never sees the task object.
    """
    from qpubench.schemas.mirrors.mqsdk_cebule import CebuleTaskType, TNQCOptResult

    started = time.time()
    task = session.cebule.create_task(
        task_name, CebuleTaskType.TN_QC_OPT, **task_payload(task_input),
    )
    # create_task returns immediately with a CebuleTask; the result is
    # fetched by id, under the result type the task uploads ('result').
    session.cebule.wait_for_result(task.id, "result")
    status = session.cebule.task_status(task.id)
    if status.status != "done":
        raise RuntimeError(f"run {run['Case_ID']} finished with status "
                           f"{status.status!r}: {status.error_message}")
    result = TNQCOptResult.from_task_result(session.cebule.get_result(task.id, "result"))
    return result, time.time() - started, task.id


def append_record(
    results_path: pathlib.Path, run: dict[str, str], result: Any,
    task_id: str, wall_s: float, batch: str, backend_override: str | None = None,
) -> None:
    """Append one finished run to the checkpoint, written and closed per run.

    Per run rather than per batch, so an interrupt loses at most the run in
    flight and the next pass reads this file and skips everything in it.
    """
    results_path.parent.mkdir(parents=True, exist_ok=True)
    with results_path.open("a") as f:
        f.write(json.dumps({
            "Case_ID": run["Case_ID"], "Batch": batch, "task_id": task_id,
            "Backend": backend_for(run, backend_override),
            "Molecule": run["Molecule"], "Basis": run["Basis"],
            "Mapper": run["Mapper"], "Method": run["Method"],
            "Ansatz": run["Ansatz"], "Optimizer": run["Optimizer"],
            "Optimization_Mode": run["Optimization_Mode"],
            "Measurement_Method": run["Measurement_Method"],
            "vqe_energy": result.vqe_energy,
            "function_calls": result.function_calls,
            "cost_history": result.cost_history,
            "wall_clock_s": round(wall_s, 3),
            "estimated_qpu_s": float(run.get("Est_QPU_Time_S") or 0),
        }) + "\n")
