"""How far a hardware run's measurements sit from noiseless, per qubit region.

Requires: pip install 'qpubench[qiskit]' (qiskit and qiskit-ibm-runtime).

Reads the job files of one run as downloaded from the IBM Quantum workload
page (`<job>-info.json` and `<job>-result.json`). For every measuring pub it
takes the transpiled circuit at the parameters IBM bound, simulates it on
the physical qubits it touches, and compares the ideal distribution with the
counts IBM returned after tensored readout correction, using the rates from
the run's own calibration jobs (two parameter-free pubs: all 0, all 1).

The comparison is over the diagonal Z-string expectations of the measured
qubits (15 for four qubits):

- damping: measured = f * ideal by least squares; 1 is noiseless, and
  depolarising gate noise lowers it;
- error: mean absolute difference from ideal;
- shot noise: that error for a multinomial draw from the ideal distribution
  at the same shots, so the floor the device is measured against;
- error after damping: what is left once the damping is scaled out, which
  is the part that moves the minimum rather than shrinking the landscape.

Every evaluation is transpiled afresh, so pubs are grouped by the physical
qubits they touch, and `--by-hour` shows the damping per region over the
run to catch qubits that degrade partway through.

Run:
    python utils/device_fidelity.py WORKLOAD_DIR [--by-hour] [--json OUT.json]
"""
from __future__ import annotations

import argparse
import collections
import itertools
import json
import pathlib

import numpy as np
from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector
from qiskit_ibm_runtime.json import RuntimeDecoder


def load_jobs(workload: pathlib.Path) -> list[tuple[str, dict, list]]:
    """(created, info, result) for every job in the folder, oldest first."""
    jobs = []
    for info_path in workload.glob("*-info.json"):
        result_path = info_path.with_name(info_path.name.replace("-info", "-result"))
        if not result_path.exists():
            continue
        info = json.loads(info_path.read_text(), cls=RuntimeDecoder)
        result = json.loads(result_path.read_text(), cls=RuntimeDecoder)
        jobs.append((str(info["created"]), info, result))
    return sorted(jobs, key=lambda job: job[0])


def measured_qubits(circuit: QuantumCircuit) -> list[int]:
    """Physical qubit of each classical bit, in clbit order."""
    by_clbit = {circuit.find_bit(i.clbits[0]).index: circuit.find_bit(i.qubits[0]).index
                for i in circuit.data if i.operation.name == "measure"}
    return [by_clbit[k] for k in sorted(by_clbit)]


def readout_rates(jobs: list[tuple[str, dict, list]]) -> dict[int, tuple[float, float]]:
    """(p01, p10) per physical qubit from the run's calibration jobs; a later
    calibration of the same qubit replaces an earlier one."""
    rates: dict[int, list[float]] = {}
    for _, info, result in jobs:
        pubs = info["params"]["pubs"]
        if len(pubs) != 2 or pubs[0][0].parameters:
            continue
        for prepared_one, (pub, data) in enumerate(zip(pubs, result)):
            ones = data.data.meas.to_bool_array(order="little").mean(axis=0)
            for qubit, rate in zip(measured_qubits(pub[0]), ones):
                rates.setdefault(qubit, [0.0, 0.0])[prepared_one] = (
                    1 - rate if prepared_one else rate)
    return {q: (p01, p10) for q, (p01, p10) in rates.items()}


def correct(p: np.ndarray, physical: list[int], rates: dict) -> np.ndarray:
    """Tensored readout correction; bit k of the index is clbit k."""
    n = len(physical)
    t = p.reshape([2] * n)  # axis 0 is the most significant bit, clbit n-1
    for k, qubit in enumerate(physical):
        p01, p10 = rates[qubit]
        inverse = np.linalg.inv(np.array([[1 - p01, p10], [p01, 1 - p10]]))
        axis = n - 1 - k
        t = np.moveaxis(np.tensordot(inverse, t, axes=([1], [axis])), 0, axis)
    return t.reshape(-1)


def z_strings(p: np.ndarray, n: int) -> np.ndarray:
    """Expectation of every non-empty product of Z on the n measured bits."""
    index = np.arange(2 ** n)
    return np.array([
        float(((-1) ** sum((index >> k) & 1 for k in subset)) @ p)
        for size in range(1, n + 1) for subset in itertools.combinations(range(n), size)
    ])


def on_touched_qubits(circuit: QuantumCircuit) -> tuple[QuantumCircuit, list[int]]:
    """The circuit compacted onto the physical qubits its gates touch, and
    those qubits, so a 156-qubit transpiled circuit simulates on a few."""
    skip = ("barrier", "measure")
    touched = sorted({circuit.find_bit(q).index for i in circuit.data for q in i.qubits
                      if i.operation.name not in skip})
    position = {q: k for k, q in enumerate(touched)}
    small = QuantumCircuit(len(touched))
    for i in circuit.data:
        if i.operation.name not in skip:
            small.append(i.operation, [position[circuit.find_bit(q).index] for q in i.qubits])
    return small, touched


def compare(jobs: list[tuple[str, dict, list]], rates: dict, seed: int = 0) -> list[dict]:
    """One entry per measuring pub: when its job was created, the qubits it
    touches, its CZ count, and the ideal, measured and shot-noise Z strings."""
    rng = np.random.default_rng(seed)
    pubs = []
    for created, info, result in jobs:
        if not info["params"]["pubs"][0][0].parameters:
            continue  # a calibration job
        for pub, data in zip(info["params"]["pubs"], result):
            circuit, values = pub[0], np.asarray(pub[1], float).reshape(-1)
            physical = measured_qubits(circuit)
            small, touched = on_touched_qubits(circuit)
            position = {q: k for k, q in enumerate(touched)}
            ideal = Statevector(small.assign_parameters(values)).probabilities(
                [position[q] for q in physical])
            counts = data.data.meas.get_counts()
            shots = sum(counts.values())
            measured = np.zeros(2 ** len(physical))
            for bits, count in counts.items():
                measured[int(bits, 2)] = count / shots
            n = len(physical)
            pubs.append(dict(
                created=created, touched=touched,
                cz=sum(1 for i in circuit.data if i.operation.name == "cz"),
                ideal=z_strings(ideal, n),
                measured=z_strings(correct(measured, physical, rates), n),
                shot_noise=z_strings(
                    correct(rng.multinomial(shots, ideal) / shots, physical, rates), n),
            ))
    return pubs


def damping(pubs: list[dict]) -> float:
    ideal = np.concatenate([p["ideal"] for p in pubs])
    measured = np.concatenate([p["measured"] for p in pubs])
    return float(measured @ ideal / (ideal @ ideal))


def summarise(pubs: list[dict]) -> list[dict]:
    """Damping and errors per touched-qubit region, most-used region first."""
    regions = collections.defaultdict(list)
    for p in pubs:
        regions[tuple(p["touched"])].append(p)
    rows = []
    for touched, group in sorted(regions.items(), key=lambda r: -len(r[1])):
        ideal, measured, noise = (np.concatenate([p[k] for p in group])
                                  for k in ("ideal", "measured", "shot_noise"))
        f = damping(group)
        rows.append(dict(
            touched=list(touched), pubs=len(group),
            cz=float(np.mean([p["cz"] for p in group])), damping=f,
            error=float(np.abs(measured - ideal).mean()),
            shot_noise=float(np.abs(noise - ideal).mean()),
            error_after_damping=float(np.abs(measured - f * ideal).mean()),
        ))
    return rows


def by_hour(pubs: list[dict], regions: list[list[int]]) -> list[tuple[str, list]]:
    """Damping (and pub count) per UTC hour and region; None where a region
    ran nothing that hour."""
    hours = collections.defaultdict(lambda: collections.defaultdict(list))
    for p in pubs:
        hours[p["created"][:13]][tuple(p["touched"])].append(p)
    return [(hour, [(damping(g), len(g)) if (g := hours[hour].get(tuple(r))) else None
                    for r in regions])
            for hour in sorted(hours)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("workload", type=pathlib.Path,
                        help="folder of one run's IBM job files")
    parser.add_argument("--by-hour", action="store_true",
                        help="also print the damping per UTC hour and region")
    parser.add_argument("--json", type=pathlib.Path,
                        help="write the rates, the per-region summary and every pub's "
                             "Z strings here")
    args = parser.parse_args()

    jobs = load_jobs(args.workload)
    rates = readout_rates(jobs)
    pubs = compare(jobs, rates)
    print(f"{len(jobs)} jobs, {len(pubs)} measuring pubs")
    print("readout (p01, p10):",
          ", ".join(f"{q}: {p01:.4f}, {p10:.4f}" for q, (p01, p10) in sorted(rates.items())))
    regions = summarise(pubs)
    for r in regions:
        print(f"qubits {r['touched']}: {r['pubs']} pubs, {r['cz']:.0f} CZ, "
              f"damping {r['damping']:.3f}, error {r['error']:.4f} "
              f"(shot noise {r['shot_noise']:.4f}, after damping {r['error_after_damping']:.4f})")

    if args.by_hour:
        touched = [r["touched"] for r in regions]
        print("\nhour (UTC)     " + "".join(f"{str(t):>24}" for t in touched))
        for hour, cells in by_hour(pubs, touched):
            print(hour + "  " + "".join(
                f"{'-' if c is None else f'{c[0]:.2f} ({c[1]})':>24}" for c in cells))

    if args.json:
        args.json.write_text(json.dumps(dict(
            rates={str(q): list(r) for q, r in rates.items()},
            regions=regions,
            pubs=[{**p, **{k: p[k].tolist() for k in ("ideal", "measured", "shot_noise")}}
                  for p in pubs],
        ), indent=1))


if __name__ == "__main__":
    main()
