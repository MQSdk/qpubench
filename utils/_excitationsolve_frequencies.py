"""ExcitationSolve's frequency set for each circuit parameter, measured on a
noiseless statevector, and the `opt_options` that hand them to tn-vqe.

Imported, not run. Requires: pip install 'qpubench[qiskit]'.

Along one parameter the energy is a trigonometric polynomial whose
frequencies are differences of that gate's generator eigenvalues.
ExcitationSolve fits each parameter from 1 + 2|f| samples of its set f, so
the set must contain every frequency present: a missing one fits a curve
the energy does not have, an extra one only costs samples. Given in the
task input, the sets are fixed by the campaign rather than measured by
tn-vqe at run time.

Follows tn-vqe's own frequencies_along: a uniform scan over 4*pi (so
half-integer frequencies do not fold), at the start and at a second point
offset in the other parameters, unioned, then checked by refitting.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Sequence

import numpy as np

# 32 samples over 4*pi resolve frequencies up to 7.5 without folding.
_PERIOD = 4 * np.pi
_N_SAMPLES = 32
_RTOL = 1e-6        # keep a harmonic at least this fraction of the largest
_FLAT_RTOL = 1e-10  # flat if the energy varies by less than this, relative
_CHECK_RTOL = 1e-8  # a refit of the found set must reproduce the energy to this


def _spectrum(energy: Callable[[np.ndarray], float], x: np.ndarray, index: int) -> set[int] | None:
    """Harmonics present along one parameter at one point, or None if flat."""
    probe = x.copy()
    values = []
    for t in x[index] + np.linspace(0, _PERIOD, _N_SAMPLES, endpoint=False):
        probe[index] = t
        values.append(energy(probe))
    values = np.asarray(values)
    if np.ptp(values) <= _FLAT_RTOL * max(np.abs(values).max(), 1.0):
        return None
    amplitudes = np.abs(np.fft.rfft(values)) / _N_SAMPLES
    peak = amplitudes[1:].max()
    return {k for k in range(1, len(amplitudes)) if amplitudes[k] >= _RTOL * peak}


def _check(energy: Callable[[np.ndarray], float], x: np.ndarray, index: int,
           frequencies: tuple[float, ...], rng: np.random.Generator) -> None:
    """Raise unless the set reproduces the energy off the scan's grid."""
    n_fit = 2 * (1 + 2 * len(frequencies))
    t = rng.uniform(0, _PERIOD, size=n_fit + 4)
    probe = x.copy()
    values = []
    for value in t:
        probe[index] = x[index] + value
        values.append(energy(probe))
    values = np.asarray(values)
    design = np.column_stack(
        [np.ones_like(t)] + [f(k * t) for k in frequencies for f in (np.cos, np.sin)])
    coefficients, *_ = np.linalg.lstsq(design[:n_fit], values[:n_fit], rcond=None)
    error = np.abs(design[n_fit:] @ coefficients - values[n_fit:]).max()
    if error > _CHECK_RTOL * max(np.abs(values).max(), 1.0):
        raise ValueError(
            f"parameter {index}: frequencies {frequencies} do not reproduce the "
            f"energy (error {error:.2g})"
        )


def frequency_sets(
    energy: Callable[[np.ndarray], float], x0: Sequence[float], *, seed: int = 0,
) -> list[tuple[float, ...]]:
    """One frequency set per parameter of `energy`, measured around `x0`.

    A parameter the energy ignores at both probe points gets the empty set,
    which ExcitationSolve skips.
    """
    x0 = np.asarray(x0, dtype=float)
    sets = []
    for index in range(x0.size):
        rng = np.random.default_rng(seed + index)
        harmonics: set[int] = set()
        flat = True
        for point in (x0, x0 + rng.uniform(0.3, 2.0, size=x0.shape)):
            found = _spectrum(energy, point, index)
            if found is not None:
                harmonics |= found
                flat = False
        if flat:
            sets.append(())
            continue
        frequencies = tuple(k / 2.0 for k in sorted(harmonics))
        _check(energy, x0, index, frequencies, rng)
        sets.append(frequencies)
    return sets


def statevector_energy_fn(qasm_text: str, labels: Sequence[str], coefficients: Sequence[float]):
    """phi -> <psi(phi)|H|psi(phi)> for a pinned circuit and a Hamiltonian in
    Qiskit label order, binding phi positionally as tn-vqe does."""
    from qiskit import qasm3
    from qiskit.quantum_info import SparsePauliOp, Statevector

    circuit = qasm3.loads(qasm_text)
    H = SparsePauliOp(list(labels), list(coefficients)).to_matrix(sparse=True)

    def energy(phi: np.ndarray) -> float:
        psi = Statevector(circuit.assign_parameters(list(phi))).data
        return float(np.real(np.vdot(psi, H @ psi)))

    return energy


def opt_options(
    phi_sets: Sequence[Sequence[float]], num_theta: int, samples: int | None = None,
) -> dict:
    """ExcitationSolve's `opt_options` for a row with these circuit sets.

    A single shared set where every circuit parameter has the same one (tn-vqe
    then takes theta's from its own gates); otherwise one entry per optimized
    parameter, circuit first, with theta's left None for tn-vqe to fill. The
    flatness scan is turned off: flat parameters are already the empty sets,
    and the scan would otherwise run on the noisy objective.

    `samples` fits every parameter from that many points instead of exactly
    its 1 + 2|f| unknowns, averaging noise in each fit. tn-vqe applies one
    count to all parameters, theta's included, so it must cover the largest
    set; fewer points than unknowns would fit an underdetermined curve.
    """
    sets = [list(s) for s in phi_sets]
    if sets and sets[0] and all(s == sets[0] for s in sets):
        frequencies: list = sets[0]
    else:
        frequencies = sets + [None] * num_theta
    options = {"frequencies": frequencies, "check_flat": False}
    if samples is not None:
        needed = max(1 + 2 * len(s) for s in sets)
        if samples < needed:
            raise ValueError(f"samples={samples} is below the {needed} unknowns of the largest set")
        options["samples"] = samples
    return options


def sweep_evals(opt_options_json: str, num_phi: int) -> int:
    """Quantum evaluations per ExcitationSolve sweep that these options imply:
    each non-flat circuit parameter's fit points (1 + 2|f|, or `samples`), one
    reused, plus a closing evaluation."""
    options = json.loads(opt_options_json)
    frequencies, samples = options["frequencies"], options.get("samples")
    if all(np.ndim(f) == 0 for f in frequencies):
        sets = [frequencies] * num_phi
    else:
        sets = frequencies[:num_phi]
    return 1 + sum((samples - 1) if samples else 2 * len(f) for f in sets if f)
