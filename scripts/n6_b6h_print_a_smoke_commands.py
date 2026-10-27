#!/usr/bin/env python3
"""Print exact, SHA-bound A smoke commands after fixtures are created."""

from __future__ import annotations

import json
from pathlib import Path
import shlex


REPO = Path(__file__).resolve().parents[1]
ROOT = Path("/Volumes/zkfdo-jcache/n6-b6h-smoke")
LEAD1 = "9de9eb4aaf1626eb9c14bb0437d1b43e3478f983396910623d0df3805a68193e"
LEAD2 = "4bc7f83da1f70c3ab523a38e56ef501f89508ba22e8dab674843d3995a9f60d6"


def command(engine: str, item: dict, action: str) -> list[str]:
    return ["python3", "scripts/n6_b6h_smoke_a_runner.py",
            "--engine", engine,
            "--index", item["index_path"],
            "--index-sha256", item["index_sha256"],
            "--static-preflight", item["static_preflight_path"],
            "--static-preflight-sha256", item["static_preflight_sha256"],
            "--first-lead-review-sha256", LEAD1,
            "--second-lead-review-sha256", LEAD2,
            "--cache-root", str(ROOT / "cache" / f"full-{engine}"),
            "--workspace-root", str(ROOT / "hint-workspaces"),
            "--instance-root", str(ROOT / "instance-stores"),
            "--observed-request-peak-bytes", "1073741824",
            "--output", str(ROOT / f"full-{engine}.noindex"),
            "--action", action]


def main() -> None:
    manifest = json.loads((ROOT / "fixtures-97-102-115/fixture-manifest.json").read_text())
    if manifest.get("schema") != "n6-b6h-a-smoke-fixtures-v1":
        raise ValueError("A smoke fixture manifest invalid")
    for engine in ("v2.2", "v1"):
        item = manifest["engines"][engine]
        for action in ("validate-only", "execute-all"):
            cmd = command(engine, item, action)
            print(f"{engine} {action}: cd {shlex.quote(str(REPO))} && "
                  f"caffeinate -dimsu {shlex.join(cmd)}")
        if engine == "v2.2":
            wrapped = ["python3", "scripts/n6_b6h_interrupt_resume_a.py", "--",
                       *command(engine, item, "execute-all")]
            print(f"{engine} interrupt-and-resume: cd {shlex.quote(str(REPO))} && "
                  f"caffeinate -dimsu {shlex.join(wrapped)}")
    gate = ["python3", "scripts/n6_b6h_gate_a_smoke.py", "--smoke-root", str(ROOT),
            "--output", str(ROOT / "result-gate.json")]
    print(f"result-gate: cd {shlex.quote(str(REPO))} && "
          f"caffeinate -dimsu {shlex.join(gate)}")


if __name__ == "__main__":
    main()
