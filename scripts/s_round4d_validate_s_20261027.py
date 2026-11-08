#!/usr/bin/env python3
"""Read-only revalidation of every rebuilt S v4 plan after snapshot restoration."""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_policy_a_engine_v4 as engine
import s_round4d_prepare_s_20261027 as prep


def main() -> None:
    bundle_path = prep.BASE / "s-input-bundle.json"
    bundle = json.loads(bundle_path.read_text())
    if len(bundle["jobs"]) != 45:
        raise ValueError("45 S plans required")
    rows = []
    for job in bundle["jobs"]:
        spec = prep.read(job["prepared_spec"])
        prep.read(job["prepared_plan"])
        engine.validate_spec_v4(spec)
        roots = {row["id"]: Path(row["path"]) for row in spec["source_snapshots"]}
        result = engine.verify_plan_v4(spec, roots)
        if result != job["plan_validation"]:
            raise ValueError("S plan verification changed")
        rows.append({"revision": job["revision"], "seed": job["seed"], **result})
    output = prep.ROUND / "round4d/S-validation-after-restore-v2.json"
    prep.save(output, {"schema": "s-round4d-S-validation-v1", "bundle": prep.pin(bundle_path),
                       "verified": len(rows), "target_total": sum(r["target_count"] for r in rows),
                       "fingerprint_total": sum(r["fingerprints"] for r in rows), "rows": rows})
    print(json.dumps({"verified": len(rows), "target_total": sum(r["target_count"] for r in rows),
                      "fingerprint_total": sum(r["fingerprints"] for r in rows)}))


if __name__ == "__main__":
    main()
