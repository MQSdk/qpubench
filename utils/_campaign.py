"""Find a campaign and load its configuration.

Imported, not run.  A campaign is a folder under `campaigns/` holding its
matrix, its data and a `campaign.py` that tells the shared tools in
`utils/` what only the campaign knows.  The tools take the campaign as an
argument rather than naming one, so a second campaign needs no change
here.

What a `campaign.py` defines
----------------------------
Required:

    CSV              the matrix the tools run by default
    QASM_DIR         where the campaign's pinned circuits live; the
                     pinning tool deletes files here that no row runs, so
                     it must not be shared with another campaign
    RESULTS_DIR      where run results and checkpoints are written
    hamiltonian_file(run) -> Path | None
                     the committed Hamiltonian for one row, or None

Optional:

    hf_state(run) -> list[int]
                     Hartree-Fock bits for a row whose mapper is not JW,
                     for rows that start hardware-efficient circuits at HF
    simulation_infeasible_reason(run) -> str | None
                     why a row must never be submitted
    PRICING_DEVICE   the IBM device the cost estimate prices against
"""
from __future__ import annotations

import importlib.util
import pathlib
from types import ModuleType

REPO = pathlib.Path(__file__).resolve().parents[1]
CAMPAIGNS_DIR = REPO / "campaigns"

_REQUIRED = ("CSV", "QASM_DIR", "RESULTS_DIR", "hamiltonian_file")


def available() -> list[str]:
    """Names of the campaigns under `campaigns/`."""
    return sorted(
        p.parent.name for p in CAMPAIGNS_DIR.glob("*/campaign.py")
    )


def load(name_or_path: str | pathlib.Path | None = None) -> ModuleType:
    """The `campaign.py` module of one campaign.

    Takes a campaign name, a path to its folder, or None. None picks the
    only campaign when there is exactly one, so a repository with a single
    campaign needs no flag.
    """
    if name_or_path is None:
        names = available()
        if len(names) != 1:
            raise SystemExit(
                "name a campaign with --campaign; available: "
                + (", ".join(names) or "none")
            )
        name_or_path = names[0]

    directory = pathlib.Path(name_or_path)
    if not (directory / "campaign.py").exists():
        directory = CAMPAIGNS_DIR / str(name_or_path)
    path = directory / "campaign.py"
    if not path.exists():
        raise SystemExit(
            f"no campaign {str(name_or_path)!r}; available: "
            + (", ".join(available()) or "none")
        )

    module_name = "campaign_" + directory.name.replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    missing = [attr for attr in _REQUIRED if not hasattr(module, attr)]
    if missing:
        raise SystemExit(f"{path} does not define {', '.join(missing)}")
    return module


def add_argument(parser) -> None:
    """The `--campaign` option every shared tool takes."""
    parser.add_argument(
        "--campaign", default=None, metavar="NAME_OR_DIR",
        help="campaign to act on, by folder name under campaigns/ or by path. "
             "Optional while there is only one; available: "
             + (", ".join(available()) or "none"),
    )
