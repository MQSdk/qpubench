"""MBQC-FPGA data schemas.

Bit layouts are authoritative against gitlab.com/johnrscott/mbqc-fpga
commit fde787d1 (qubit.vhd, byproduct.vhd, adapt.vhd, ops_update.vhd,
comm_correct.vhd, program.cpp).

16-bit program word layout:
    [15:11]  c_prog  (5 bits)
    [10:6]   s_prog  (5 bits)
    [5:0]    b_prog  (6 bits)

The measurement angle theta is NOT stored in the program word — it is an
analog-domain quantity tracked separately in software only.
"""
from __future__ import annotations

import csv
import io

import pydantic


# ---------------------------------------------------------------------------
# Program word sub-fields
# ---------------------------------------------------------------------------

class ByproductUpdateSpec(pydantic.BaseModel):
    """b_prog — bits [5:0] of the 16-bit program word.

    Encodes XOR masks applied to the neighbourhood measurement triple
    (m_above, m_self, m_below) = m[2:0] to update the Z and X components
    of the byproduct operator register.

    Update equations (ops_update.vhd):
        update_z = (m[0] & z_mask[0]) ^ (m[1] & z_mask[1]) ^ (m[2] & z_mask[2])
        update_x = (m[0] & x_mask[0]) ^ (m[1] & x_mask[1]) ^ (m[2] & x_mask[2])

    m[0] = qubit below, m[1] = self, m[2] = qubit above.
    ops register: bit 0 = Z component, bit 1 = X component.
    """
    z_mask: int = 0    # 3-bit → b_prog[2:0]
    x_mask: int = 0    # 3-bit → b_prog[5:3]

    @pydantic.field_validator("z_mask", "x_mask")
    @classmethod
    def _3bit(cls, v: int) -> int:
        if not 0 <= v <= 0b111:
            raise ValueError(f"mask must fit in 3 bits (0–7), got {v}")
        return v

    @property
    def b_prog(self) -> int:
        return ((self.x_mask & 0b111) << 3) | (self.z_mask & 0b111)

    @classmethod
    def from_b_prog(cls, b: int) -> ByproductUpdateSpec:
        return cls(z_mask=b & 0b111, x_mask=(b >> 3) & 0b111)

    def update(
        self,
        m_below: int,
        m_self: int,
        m_above: int,
    ) -> tuple[int, int]:
        """Return (delta_z, delta_x) to XOR into the ops register."""
        m = [m_below, m_self, m_above]
        dz = 0
        dx = 0
        for i in range(3):
            dz ^= m[i] & ((self.z_mask >> i) & 1)
            dx ^= m[i] & ((self.x_mask >> i) & 1)
        return dz, dx


class AdaptiveSpec(pydantic.BaseModel):
    """s_prog — bits [10:6] of the 16-bit program word.

    Adaptive measurement setting computation (adapt.vhd):
        s = (sr[0] & sr_mask[0]) ^ (sr[1] & sr_mask[1]) ^ (sr[2] & sr_mask[2])
          ^ (ops_stored_z & z_byp_enable)
          ^ (ops_stored_x & x_byp_enable)

    Shift register direction: sr[2] = most recent outcome, sr[0] = oldest.
    ops_stored is latched at gate boundaries (when CommutationSpec.store_ops=True).
    """
    sr_mask:       int  = 0      # 3-bit, selects shift-register positions → s_prog[2:0]
    z_byp_enable:  bool = False  # XOR in stored Z byproduct → s_prog[3]
    x_byp_enable:  bool = False  # XOR in stored X byproduct → s_prog[4]

    @pydantic.field_validator("sr_mask")
    @classmethod
    def _3bit(cls, v: int) -> int:
        if not 0 <= v <= 0b111:
            raise ValueError(f"sr_mask must fit in 3 bits (0–7), got {v}")
        return v

    @property
    def s_prog(self) -> int:
        return (
            (self.sr_mask & 0b111)
            | (int(self.z_byp_enable) << 3)
            | (int(self.x_byp_enable) << 4)
        )

    @classmethod
    def from_s_prog(cls, s: int) -> AdaptiveSpec:
        return cls(
            sr_mask=s & 0b111,
            z_byp_enable=bool((s >> 3) & 1),
            x_byp_enable=bool((s >> 4) & 1),
        )

    def compute_s(
        self,
        shift_register: int,   # 3-bit; sr[2]=MSB=most recent
        ops_stored_z: int,
        ops_stored_x: int,
    ) -> int:
        s = 0
        for i in range(3):
            s ^= ((shift_register >> i) & 1) & ((self.sr_mask >> i) & 1)
        s ^= ops_stored_z & int(self.z_byp_enable)
        s ^= ops_stored_x & int(self.x_byp_enable)
        return s & 1


class CommutationSpec(pydantic.BaseModel):
    """c_prog — bits [15:11] of the 16-bit program word.

    Bit layout (comm_correct.vhd):
      [0]  store_ops   — copy ops_current → ops_stored on clk_r (gate boundary)
      [1]  cnot_enable — enable CNOT commutation correction
      [3:2] role       — CNOT role and neighbour direction (see table below)
      [4]  add_const   — add constant correction directly to ops

    CNOT role encoding (c_prog[3:2]) when cnot_enable=1, add_const=0:
      0b11  control, target above  → comm_z ^= ops_above_z
      0b10  target,  control above → comm_x ^= ops_above_x
      0b01  control, target below  → comm_z ^= ops_below_z
      0b00  target,  control below → comm_x ^= ops_below_x
    """
    store_ops:   bool = False    # bit 0
    cnot_enable: bool = False    # bit 1
    role:        int  = 0        # bits [3:2], 2-bit
    add_const:   bool = False    # bit 4

    @pydantic.field_validator("role")
    @classmethod
    def _2bit(cls, v: int) -> int:
        if not 0 <= v <= 0b11:
            raise ValueError(f"role must fit in 2 bits (0–3), got {v}")
        return v

    @property
    def c_prog(self) -> int:
        return (
            int(self.store_ops)
            | (int(self.cnot_enable) << 1)
            | ((self.role & 0b11) << 2)
            | (int(self.add_const) << 4)
        )

    @classmethod
    def from_c_prog(cls, c: int) -> CommutationSpec:
        return cls(
            store_ops=bool(c & 1),
            cnot_enable=bool((c >> 1) & 1),
            role=(c >> 2) & 0b11,
            add_const=bool((c >> 4) & 1),
        )

    @classmethod
    def gate_boundary(cls) -> CommutationSpec:
        """Latch byproduct operators before starting a new gate."""
        return cls(store_ops=True)

    @classmethod
    def cnot_control_target_below(cls) -> CommutationSpec:
        return cls(cnot_enable=True, role=0b01)

    @classmethod
    def cnot_target_control_above(cls) -> CommutationSpec:
        return cls(cnot_enable=True, role=0b10)

    @classmethod
    def cnot_control_target_above(cls) -> CommutationSpec:
        return cls(cnot_enable=True, role=0b11)

    @classmethod
    def cnot_target_control_below(cls) -> CommutationSpec:
        return cls(cnot_enable=True, role=0b00)


# ---------------------------------------------------------------------------
# Program word
# ---------------------------------------------------------------------------

class MBQCProgramWord(pydantic.BaseModel):
    """16-bit FPGA program word: c_prog[15:11] | s_prog[10:6] | b_prog[5:0].

    theta is NOT part of this word; see MBQCRound.
    """
    byproduct_update: ByproductUpdateSpec = pydantic.Field(
        default_factory=ByproductUpdateSpec
    )
    adaptive:         AdaptiveSpec        = pydantic.Field(
        default_factory=AdaptiveSpec
    )
    commutation:      CommutationSpec     = pydantic.Field(
        default_factory=CommutationSpec
    )

    @property
    def word(self) -> int:
        return (
            (self.commutation.c_prog << 11)
            | (self.adaptive.s_prog << 6)
            | self.byproduct_update.b_prog
        )

    @classmethod
    def from_word(cls, w: int) -> MBQCProgramWord:
        w &= 0xFFFF
        return cls(
            byproduct_update=ByproductUpdateSpec.from_b_prog(w & 0b111111),
            adaptive=AdaptiveSpec.from_s_prog((w >> 6) & 0b11111),
            commutation=CommutationSpec.from_c_prog((w >> 11) & 0b11111),
        )

    def to_bin_str(self) -> str:
        """16-character binary string, MSB first (COE file line format)."""
        return format(self.word, "016b")


# ---------------------------------------------------------------------------
# Measurement round and full pattern
# ---------------------------------------------------------------------------

class MBQCRound(pydantic.BaseModel):
    """One measurement round for one logical qubit.

    theta is the measurement basis angle in radians.  It drives the analog
    photon source and the software simulator but is never encoded in the COE
    file — that stores only the 16-bit digital control word.
    """
    theta:        float
    program_word: MBQCProgramWord = pydantic.Field(
        default_factory=MBQCProgramWord
    )

    @classmethod
    def non_adaptive(cls, theta: float) -> MBQCRound:
        """Minimal round with no adaptive correction (useful for testing)."""
        return cls(theta=theta)


class MBQCPattern(pydantic.BaseModel):
    """Complete measurement pattern for N logical qubits over D rounds.

    rounds[d][q] = MBQCRound for qubit q in measurement round d.

    Qubit ordering: qubit 0 is the bottom qubit; qubit N-1 is the top.
    Neighbourhood convention (ops_update.vhd):
      m_above = outcome of qubit q+1   (boundary: 0)
      m_below = outcome of qubit q-1   (boundary: 0)
    """
    num_logical_qubits: int
    rounds: list[list[MBQCRound]]    # shape: [num_rounds][num_logical_qubits]

    @pydantic.model_validator(mode="after")
    def _check_shape(self) -> MBQCPattern:
        for d, row in enumerate(self.rounds):
            if len(row) != self.num_logical_qubits:
                raise ValueError(
                    f"Round {d}: expected {self.num_logical_qubits} entries, "
                    f"got {len(row)}"
                )
        return self

    @property
    def num_rounds(self) -> int:
        return len(self.rounds)

    def to_single_qubit_coe(self, qubit_idx: int) -> str:
        """Xilinx COE file for a single qubit's program ROM.

        Radix 2; one 16-bit binary word per line, MSB first.
        theta is emitted as a comment annotation — it is not part of the word.
        """
        lines = [
            "memory_initialization_radix=2;",
            "memory_initialization_vector=",
        ]
        for d, row in enumerate(self.rounds):
            r = row[qubit_idx]
            lines.append(
                f"{r.program_word.to_bin_str()}  "
                f"; round={d}  theta={r.theta:.6f}"
            )
        return "\n".join(lines)

    def to_multi_qubit_coe(self) -> str:
        """Combined COE for all N qubits, radix hex.

        Each line is N×4 hex digits (qubit N-1 is most significant).
        Word for qubit q occupies bits [16*(q+1)-1 : 16*q].
        """
        hex_width = self.num_logical_qubits * 4
        lines = [
            "memory_initialization_radix=16;",
            "memory_initialization_vector=",
        ]
        for d, row in enumerate(self.rounds):
            combined = 0
            for q, r in enumerate(row):
                combined |= r.program_word.word << (16 * q)
            lines.append(f"{combined:0{hex_width}x}  ; round={d}")
        return "\n".join(lines)

    @classmethod
    def from_single_qubit_coe(cls, coe_text: str, thetas: list[float]) -> MBQCPattern:
        """Parse a single-qubit COE file back into a MBQCPattern (N=1)."""
        rounds: list[list[MBQCRound]] = []
        for line in coe_text.splitlines():
            line = line.split(";")[0].strip()
            if not line or line.endswith("=") or line.endswith(","):
                continue
            word = int(line, 2)
            idx  = len(rounds)
            rounds.append([
                MBQCRound(
                    theta=thetas[idx] if idx < len(thetas) else 0.0,
                    program_word=MBQCProgramWord.from_word(word),
                )
            ])
        return cls(num_logical_qubits=1, rounds=rounds)


# ---------------------------------------------------------------------------
# Execution result (per-round FPGA register state)
# ---------------------------------------------------------------------------

class MBQCQubitState(pydantic.BaseModel):
    """Snapshot of FPGA registers for one qubit after one measurement round.

    Mirrors the signal set in qubit.vhd / byproduct.vhd.
    ops register convention: bit 0 = Z, bit 1 = X.
    """
    round_index:    int
    qubit_index:    int
    theta:          float          # angle used (software side only)
    measurement:    int            # 0 or 1  (meas signal)
    setting_used:   int            # 0 or 1  (s value applied)
    ops_z:          int            # 0 or 1  (ops[0])
    ops_x:          int            # 0 or 1  (ops[1])
    ops_stored_z:   int            # 0 or 1  (latched at gate boundary)
    ops_stored_x:   int            # 0 or 1
    shift_register: int            # 3-bit; sr[2]=MSB=most recent

    @property
    def ops_word(self) -> int:
        return (self.ops_z & 1) | ((self.ops_x & 1) << 1)


class MBQCExecutionResult(pydantic.BaseModel):
    """Complete single-shot execution result for one MBQC program run.

    history[d][q] = MBQCQubitState after round d for qubit q.
    """
    num_logical_qubits: int
    num_rounds:         int
    history: list[list[MBQCQubitState]]    # [num_rounds][num_logical_qubits]
    fidelity: float | None = None          # Fubini-Study from software sim

    @property
    def final_byproduct_z(self) -> int:
        """Packed N-bit Z byproduct register after the last round."""
        return sum(s.ops_z << s.qubit_index for s in self.history[-1])

    @property
    def final_byproduct_x(self) -> int:
        return sum(s.ops_x << s.qubit_index for s in self.history[-1])

    @property
    def raw_outcomes(self) -> list[int]:
        return [s.measurement for s in self.history[-1]]

    def corrected_outcomes(self) -> list[int]:
        """Apply X byproduct corrections to final measurement outcomes.

        Z byproducts affect only phase; they do not flip the computational
        basis outcome.  Only X byproducts flip the result.
        """
        return [
            self.history[-1][q].measurement ^ self.history[-1][q].ops_x
            for q in range(self.num_logical_qubits)
        ]

    def to_bitstring(self, corrected: bool = True) -> str:
        """Bitstring with qubit 0 as the rightmost (LSB) character."""
        outcomes = self.corrected_outcomes() if corrected else self.raw_outcomes
        return "".join(str(outcomes[q]) for q in reversed(range(self.num_logical_qubits)))

    def to_multi_qubit_csv(self) -> str:
        """Emit mtb.csv compatible with the mbqc2_tb.vhd testbench.

        Columns: line, meas, ops, s
        """
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["line", "meas", "ops", "s"])
        N = self.num_logical_qubits
        for d, row in enumerate(self.history):
            meas = sum(row[q].measurement << q for q in range(N))
            ops  = sum(row[q].ops_word    << (2 * q) for q in range(N))
            s    = sum(row[q].setting_used << q for q in range(N))
            writer.writerow([
                d,
                format(meas, f"0{N}b"),
                format(ops,  f"0{2 * N}b"),
                format(s,    f"0{N}b"),
            ])
        return buf.getvalue()

    @classmethod
    def from_multi_qubit_csv(
        cls,
        csv_text: str,
        num_logical_qubits: int,
    ) -> MBQCExecutionResult:
        """Parse mtb.csv output from an FPGA simulation run."""
        N    = num_logical_qubits
        rows = list(csv.DictReader(io.StringIO(csv_text)))
        history: list[list[MBQCQubitState]] = []
        for row in rows:
            d    = int(row["line"])
            meas = int(row["meas"], 2)
            ops  = int(row["ops"],  2)
            s    = int(row["s"],    2)
            history.append([
                MBQCQubitState(
                    round_index=d,
                    qubit_index=q,
                    theta=float("nan"),
                    measurement=(meas >> q) & 1,
                    setting_used=(s >> q) & 1,
                    ops_z=(ops >> (2 * q)) & 1,
                    ops_x=(ops >> (2 * q + 1)) & 1,
                    ops_stored_z=0,
                    ops_stored_x=0,
                    shift_register=0,
                )
                for q in range(N)
            ])
        return cls(
            num_logical_qubits=N,
            num_rounds=len(history),
            history=history,
        )
