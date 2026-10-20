"""Add `circuits_measured` to results collected before records carried it.

Re-fetches each record's task from Cebule by its `task_id` and fills the
per-call circuit counts from the task's metadata (see
`_campaign_runner.circuits_measured`). Records that already carry the
field are left alone. The results file is copied to `<name>.pre_backfill`
before it is rewritten.

Run:
    PYTHONPATH=src python utils/backfill_circuits_measured.py [--campaign NAME]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import _campaign
import _campaign_runner as runner


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    _campaign.add_argument(parser)
    args = parser.parse_args()
    campaign = _campaign.load(args.campaign)
    path = campaign.RESULTS_DIR / f"{campaign.CSV.stem}.ndjson"

    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    missing = [r for r in records if "circuits_measured" not in r]
    print(f"{len(missing)} of {len(records)} records lack circuits_measured")
    if not missing:
        return

    session = runner.open_session()
    for record in missing:
        payload = session.cebule.get_result(record["task_id"], runner.RESULT_TYPE)
        record["circuits_measured"] = runner.circuits_measured(payload.get("metadata"))
        counts = record["circuits_measured"]
        print(f"  case {record['Case_ID']}: "
              + (f"{len(counts)} calls, {sum(counts)} circuits" if counts else "no metadata"))

    shutil.copy2(path, path.with_name(path.name + ".pre_backfill"))
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    print(f"rewrote {path}")


if __name__ == "__main__":
    main()
