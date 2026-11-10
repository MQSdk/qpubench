# Hardware runs

How the `ibm_phoenix` runs are defined, what they cost, how interrupted
runs were recovered, and what the device's noise does to them. The
results table is in the [campaign README](../README.md#hardware-results).

`hardware_runs.csv` is the set of runs bought on `ibm_phoenix`, in IBM's
us-east data centre. Each is a
`fake_berlin` row of `targeted_screen.csv` (cases 202–206) copied
unchanged except for `Backend_Platform` (`ibm_phoenix`) and
`Repeats_Case_ID`, which names the row it repeats. The twins already run
as the device will: tensored readout correction (`readout_tensored`),
the device shots for the ansatz (`DEVICE_SHOTS`), and independent
evaluations batched into one job (`Reduce_Job_Submissions`). Circuit,
start point, optimizer, sweep cap and budget are the twin's too, so a
hardware result reads directly against its simulator twin, and a
difference between them is the device's;
`tests/test_docs_consistency.py` fails if anything else differs. The
one exception is `Initial_Layout`, which pins a run to physical qubits
and means nothing on the simulator.

## Jobs and QPU time

The results table's Jobs column counts each run's measuring jobs, one to three batched evaluations
each, and its one readout-calibration job, as its twin submitted them
(case 1: as it ran). The time per job is the run's average under the
model fitted to case 1 (4.39 s per job plus 7.58 µs per shot, see
[Cost](#cost) below): the fixed part is most of it at 12,500 shots and 15–25%
at 50,000.

## Sweep cap

All five use `ExcitationSolve` capped at 12 sweeps (`HARDWARE_SWEEPS`),
on H2/6-31g under `MolMap_sb` with `grouped` measurement. At 6 sweeps
1-layer tUPS TN-VQE stops well short of its plateau: on `fake_berlin` it
is at 9.9 mHa after 6 sweeps and about 4.1–4.6 mHa from sweep 8 on (case
155), while the other four have settled by then; 12 keeps one cap for
every run with a margin past that plateau. In the results table, the final-state
columns are the final parameters evaluated by noiseless statevector;
the measured columns are the lowest noisy evaluation the run saw, which carries the
device-noise offset that readout correction leaves (about 10–20 mHa
plus 1.9 mHa per two-qubit gate). On the twins, the network beats a
missing tUPS layer in the measured energy (case 200 reads 126 mHa below
case 206, whose circuit has twice the two-qubit gates) but not in the
final state (4.4 against 1.1 mHa).

## Resuming case 2

Case 2's first attempt stopped after 37 jobs, when
IBM failed a job with a temporary internal error (9701), and Cebule kept
no result. Its first two sweeps are recovered from the attempt's IBM
workload files by replaying tn-vqe offline against the recorded results
(every job's circuits and parameters matched what IBM ran), which gives
3.1 mHa after sweep 2 against twin 203's 4.0. Case 6 resumes from the
attempt's parameters there (`converged_params/hardware_case_2_try1_sweep2.json`,
`Phi_Init` = `resumed(...)`) for the remaining 10 sweeps, and the two
together are case 2's result. ExcitationSolve carries nothing between
sweeps but the parameters, so resuming differs from an uninterrupted run
only in a fresh starting evaluation, the first-sweep fit checks run
again, and a new readout calibration, possibly on other physical qubits.
Its twin, case 207, resumes twin 203 from its own sweep 2 in the same
way, so the device's stitched run reads against a stitched twin, and 207
against 203 shows what resuming alone changes. Case 207 ended on 203's
plateau (a median of 1.04 mHa over sweeps 7–12, against 1.19) for 20
more evaluations than 203's last ten sweeps, so resuming costs about 2%
and moves nothing systematic. `price_plans.py` leaves it out, since it
finishes case 2 rather than adding a run.

## Case 6 halted

Case 6 stopped sending jobs after 91 of its 132,
with sweeps 1–6 complete and sweep 7 one job short, and could not be
revived; IBM completed every job it was sent, so the stop was on
Cebule's side. Its six sweeps are replayed from the IBM workload files
the same way (`results/hardware_runs.case6_try1_replay.ndjson`), and
with case 2's first attempt they are case 2's result: 8 of the 12
sweeps. From the resume at 3.1 mHa the final state stays at 3.2–4.4 mHa
through sweep 8 while twin 207 descends to 1.0–1.6, so the device run
stalled instead of converging more slowly. After the starting
evaluation its measured energies sit within 5 mHa of the final state
(twin 207's are 6–12 mHa high), twice below FCI, the lowest at
−0.9 mHa: consistent with shot noise of a few mHa that each sweep's
updates follow rather than the energy.

## Qubit layout

[`utils/device_fidelity.py`](../../../utils/device_fidelity.py) compares
every measured circuit of a run with its noiseless distribution on the
physical qubits it touched, after readout correction. The comparison is
over the 15 Z-string expectations of the four measured qubits, scored by
their damping (measured ≈ f × ideal; 1 is noiseless) and the error left
once that is scaled out, against shot noise at the same shots. The
transpiler chose the qubits for each evaluation afresh, so the circuits
are grouped by region:

| Case | Qubits touched | Circuits | CZ | Damping | Error after damping (shot noise) |
|---|---|---|---|---|---|
| 3 | 106, 115–117 | 1528 | 72 | 0.84 | 0.040 (0.012) |
| 3 | 84–86, 95 | 382 | 73 | 0.88 | 0.038 (0.014) |
| 3 | 84–86, 94, 95 | 382 | 75 | 0.87 | 0.029 (0.014) |
| 3 | 75, 76, 84–86 | 382 | 76 | 0.59 | 0.148 (0.014) |
| 3 | 103, 104, 113, 114 | 382 | 94 | 0.86 | 0.037 (0.010) |
| 4 | 80–82, 91 | 3471 | 72 | 0.84 | 0.049 (0.016) |
| 4 | 80–82, 90, 91 | 1131 | 74 | 0.86 | 0.027 (0.013) |
| 4 | 80–82, 91, 92 | 1131 | 76 | 0.84 | 0.037 (0.019) |
| 4 | 80, 81, 90, 91 | 403 | 94 | 0.87 | 0.042 (0.021) |

Case 3 spread over five regions, and one, {75, 76, 84–86}, fell from
about 0.88 to 0.4 between 02 and 03 UTC on 2026-11-04, during sweep 5,
and stayed there while the others held. Its readout rates are normal, so
the fault is in gates on 75 or 76. Case 4 stayed inside one block,
{80–82, 90–92}, and every region held at 0.78–0.89 per hour for the
whole run. Its weakest qubit, 91 (3.6% of ones read as zero), is in every
region, and readout correction takes most of that out. So case 4's stall
at 12–15 mHa against twin 205's 4.5 is not the layout. Both runs carry
2–3× shot noise of error that damping does not account for, which moves
the minimum instead of only shrinking the landscape, and case 3 stalled
the same way in sweeps 1–4, before its bad region failed. Pinning a run
with `Initial_Layout` guards against a region failing mid-run, as in
case 3; it does not remove that error. The shallow RealAmplitudes
circuits of cases 1 and 6 damp to 0.98–0.99, with errors at shot noise.

```sh
python utils/device_fidelity.py <IBM workload folder of one run> --by-hour
```

## Layout probe

Case 5, the deepest circuit (145 CZs), ran its first 16 jobs on
{57–59, 67–69} at a damping of 0.29, swinging between 0.14 and 0.41
from one job to the next. Estimated from the device's calibration
(2026-11-10, 11:35 UTC), as the product of each gate's error and the
qubits' T1/T2 decay over the circuit, that region should give 0.47, and
the best placements 0.55–0.62: the region did far worse than its
calibration says, not worse than the device's other regions. The same
estimate gives 0.77 for case 4 on its region, where 0.84 was measured.

Hardware case 7 tests that reading. It is case 5 cut to 3 sweeps
(`HARDWARE_PROBES`, twin case 208), pinned with `Initial_Layout` to
`[70, 80, 71, 81]`, the best-scoring placement, beside case 4's block
and clear of qubit 91's 4.8% readout error. The logical circuit couples
every pair of its four qubits, so held to four physical ones its routing
swaps inside them: 180–184 CZs per circuit, against 145 on case 5's six.
If its damping comes out near the calibration's 0.6, case 5's region
was the fault, and a pinned region can be chosen from a calibration; if
it is again far below, the calibration does not predict what this
circuit gets.

## Readout correction

Every row sets tn-vqe's tensored readout
correction (`readout_mitigation="tensored"`, cebule-tn_vqe `ef0dc47`):
two calibration circuits per run measure each qubit's flip rates, which
are inverted out of every measured distribution. On `fake_berlin` it
removes 29–33 mHa of the offset, and readout error is most of what
moves the noisy minimum (see
[Known limitations](simulator_runs.md#known-limitations)). The twins are corrected the
same way, so a hardware-against-twin difference is the device's alone;
cases 92, 108 and 96–98 are the uncorrected runs, and cases 128, 122 and
129–131 the corrected but unbatched ones. Cebule must be running that tn-vqe revision or later (`4e52b1e`, for
the batching), so check the deployed version before submitting: an
older one does not apply the correction.

## Cost

About 3.2 h of QPU time for the six rows, 3.0 h as it will be
spent, with case 2 finished by its first attempt (about 4 min) and case
6 rather than rerun; priced by
`utils/estimate_ibm_cost.py` from each run's recorded jobs and circuits
per job, the twin's until the run is collected (see
[ibm_cost_estimator.md](../../../docs/integrations/ibm_cost_estimator.md)).
qiskit-ibm-runtime ships no snapshot of `ibm_phoenix`, so the estimate
transpiles against `ibm_berlin`'s (`PRICING_CALIBRATION`). The time per
shot and per job are fitted to case 1, which IBM billed at 15 min 31 s
for 158 jobs and 31.2 M shots: its execution spans give 7.58 µs per shot
(`PRICING_SHOT_TIME_US`; IBM states 109.7 kHz MCPS, 9.12 µs), and the
billed time left over is 4.39 s per job (`PRICING_JOB_OVERHEAD_S`),
against IBM's stated 2 s. The overhead is about three quarters of case
1's time, so batching (`Reduce_Job_Submissions`) is what keeps the
total down: the twins send 341 jobs over 6 sweeps where the unbatched
runs sent 1,310.

Wall-clock time is far longer, because every job waits on the previous
one's result and queues on its own: case 1's 11 minutes of execution
took 35 h, 34.6 h of it in IBM's queue (median 3 min per job, the
longest 4.1 h). A session would skip the queue but bills its whole
duration, Cebule's few seconds between jobs included, which for this
many jobs would more than double the QPU time. On
`ibm_berlin`, where this matrix first pointed, the same runs take 569 h
at its 4 ms default rep_delay.

```sh
PYTHONPATH=src python utils/estimate_ibm_cost.py --csv campaigns/ibm_tn-vqe_qesem/hardware_runs.csv
```

## On `ibm_aachen` instead

`ibm_aachen` is a Heron r3 at a 250 µs
rep_delay, so the same five runs take about 37.8 h there. Cases 123–127
of `targeted_screen.csv` are its simulator twins: the five hardware runs,
readout correction and device shots included, on `fake_aachen`. Its
tUPS circuits transpile to 84 and 166 two-qubit gates, against 62 and
118 on Berlin, so its noise offset is expected to be larger.

## At half the shots

Cases 132–146 run the five hardware runs at half
the device shots (6,250 for RealAmplitudes, 25,000 for tUPS) on
`aer_simulator` (132–136), `fake_berlin` (137–141) and `fake_aachen`
(142–146), each with the same 6-sweep cap; the two noisy simulators
apply the readout correction, and `aer_simulator`, which has no readout
error, runs uncorrected. Halving the shots roughly halves each run's QPU
time. Earlier, uncorrected, 1-layer tUPS TN-VQE lost its gain over VQE
at 25,000 shots (case 105); these show whether that holds with the
correction, and on the other four runs.

## At 18 sweeps

Cases 147–161 run the five hardware runs at the
device shots but 18 sweeps instead of 6, on `aer_simulator` (147–151),
`fake_berlin` (152–156) and `fake_aachen` (157–161), corrected as
above. On the uncorrected `fake_berlin` twins, 1-layer tUPS TN-VQE was
still descending at 6 sweeps (8.7 mHa, against 5.9 mHa at 18); these
show whether any hardware run needs more than the cap.

## Cutting sweeps

`price_plans.py` takes the sweep at which each run's
longest readout-corrected mirror converged (the first within 0.5 mHa of
its plateau; `fake_berlin` by default, warm starts from `fake_aachen`,
where they ran) and prices three reduced plans from the mirrors'
recorded calls:

| Plan | `ibm_phoenix` | `ibm_aachen` |
|---|---|---|
| As defined | 3.0 h at 12 sweeps | 37.4 h at 6 sweeps |
| B: each run stopped where its mirror converged | 1.6 h | 32.3 h (16.8 h with tUPS at 25,000 shots) |
| C: VQE runs as 10 evaluations at the noiseless optimum, TN-VQE runs warm-started | 0.3 h | 5.4 h |
| D: every run warm-started | 1.0 h | 15.1 h |

The Phoenix column is priced from the batched twins at case 1's fitted
rates; the warm starts of C and D are priced from unbatched mirrors, so
those are upper bounds. On Phoenix any of them is affordable, so the
plans matter less for cost than for what they change about the
comparison. On `fake_berlin`, 1-layer tUPS TN-VQE and 2-layer tUPS VQE
need 9 sweeps, the other three fewer. B barely helps on Aachen: 1-layer tUPS TN-VQE needs 10 sweeps there
(case 160), sitting at the VQE value for the first five, and 2-layer
tUPS VQE needs 4. Warm-started, the TN-VQE runs settle in one and two
sweeps (cases 184 and 185): RealAmplitudes at about 1.0 mHa, where the
cold runs end, and 1-layer tUPS at about 3.6 mHa, below the cold run's
5.3 mHa after 18 sweeps. A warm-started TN-VQE job measures all 16
circuits, against 11–14 from a cold start, since U†HU at a converged
theta has more terms. C leaves only TN-VQE free to adapt to the
device's noise; D gives VQE the same start and the same chance. Warm-started,
the VQE runs settle in one, one and three sweeps (cases 186–188).

```sh
PYTHONPATH=src python campaigns/ibm_tn-vqe_qesem/price_plans.py [--device ibm_aachen --backend fake_aachen] [--tups-shots 25000]
```

The rows are ordered cheapest first, so the RealAmplitudes pair runs before any tUPS row and serves as the pilot. QESEM is not part of
this matrix; it goes through the stage-3 path once a hardware run has
converged parameters to refine.

## Running

The matrix is generated, and submitted, with

```sh
PYTHONPATH=src python campaigns/ibm_tn-vqe_qesem/build_matrix.py --stage hardware
PYTHONPATH=src python utils/run_campaign.py --csv campaigns/ibm_tn-vqe_qesem/hardware_runs.csv --allow-hardware --submit
```

Results collect in `results/hardware_runs.ndjson`. The runner refuses an
`ibm*` backend without `--allow-hardware`, even for a dry run.
