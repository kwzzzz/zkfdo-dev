#!/usr/bin/env python3
"""C-03 setup coverage correction, retaining the frozen pre-installation meter.

The compilation/preparation path and caps remain v1. Only automatic installation
root discovery additionally sees tracked circuits introduced by submodules and
keeps independent nested packages outside undeclared ancestor workspaces.
This extension is pinned before any setup and cannot rewrite earlier records.
"""

import argparse
from pathlib import Path

import measure_c03_corpus as base
import c03_environment_v2 as environment


def extension_lock(census):
    path = base.RUN / "measurement-extension-lock.v2.json"
    implementations = [base.ref(Path(__file__)), base.ref(Path(environment.__file__))]
    baseline = base.RUN / "entrypoints-before.json"
    original = base.RUN / "measurement-lock.json"
    authority = {"census_ref": base.ref(census), "inventory_before_ref": base.ref(baseline),
                 "measurement_v1_ref": base.ref(original), "implementations": implementations}
    if path.exists():
        lock = base.read(path)
        if any(lock.get(key) != value for key, value in authority.items()):
            raise ValueError("measurement_extension_identity_changed")
        return
    if (base.RUN / "setups").exists() or (base.RUN / "entrypoints-after.json").exists():
        raise ValueError("extension_must_be_fixed_before_setup")
    base.write_new(path, {"schema_version": 2, "fixed_at": base.legacy.now(), **authority,
                          "change": "Include initialized tracked submodule circuits and independent nested packages when selecting automatic package roots.",
                          "compilation_and_preparation": "unchanged_v1",
                          "zkfuzz_executions": 0, "setup_started": False})


def execute(census, phase):
    base.ensure_tools(census, base.RUN / "entrypoints-before.json")
    extension_lock(census)
    base.environment = environment
    base.execute(census, phase)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--census", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, default=base.RUN)
    parser.add_argument("--phase", choices=("setup", "after"), required=True)
    args = parser.parse_args()
    base.RUN = args.run_dir.resolve()
    execute(args.census.resolve(), args.phase)


if __name__ == "__main__":
    main()
