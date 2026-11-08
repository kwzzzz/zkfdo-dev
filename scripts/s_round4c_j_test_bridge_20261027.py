#!/usr/bin/env python3
"""Post-stop bridge for unchanged J regression assertions; never a default engine."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys

import s_round4c_postdeadline_20261027 as post


def bridge(argv, config):
    post.require(argv[:1] == ["experiment"] and len(argv) > 1, "only experiment test calls")
    action, args = argv[1], argv[2:]
    root = Path(config["temporary_root"]).resolve()
    post.require(root.is_relative_to(post.IMAGE), "test output must be in this execution's image")
    post.require(action in ("lift", "lift-instances"), "test bridge action refused")
    def owned(value):
        p = Path(value).absolute()
        post.require(p.resolve().is_relative_to(root), "test output escapes dedicated temporary tree")
        return p
    post.require("--output" in args, "explicit test output required")
    output = owned(args[args.index("--output") + 1])
    if action == "lift-instances":
        exe = post.checked_input(config["join_engine"]["path"])
        post.require(post.sha(exe) == config["join_engine"]["sha256"], "join executable SHA changed")
        return [str(exe), *args]
    allowed = {"--request", "--output", "--cache", "--instance-store", "--circom-bin",
               "--node-bin", "--snarkjs-bin", "--z3-bin"}
    post.require(len(args) % 2 == 0 and all(args[i] in allowed for i in range(0, len(args), 2)),
                 "unexpected test flags")
    options = dict(zip(args[::2], args[1::2]))
    post.require(len(options) * 2 == len(args), "duplicate test option")
    engine = post.checked_input(config["engine"]["path"])
    post.require(engine.is_relative_to(post.ROUND) and post.sha(engine) == config["engine"]["sha256"],
                 "v2.3 test engine SHA changed")
    for flag, name in (("--cache", "cache"), ("--instance-store", "store")):
        options[flag] = str(owned(options.get(flag, str(output.parent / (output.name + "-" + name)))))
    for name, pin in config["tools"].items():
        if "--" + name + "-bin" not in options:
            post.require(post.sha(Path(pin["path"])) == pin["sha256"], "tool SHA changed")
            options["--" + name + "-bin"] = pin["path"]
        else:
            # Deliberately failing fake tools belong to regression tests. Do not
            # replace them with a working tool and accidentally pass a test.
            owned(options["--" + name + "-bin"])
    return [str(engine), *(item for pair in options.items() for item in pair)]


def main():
    post.quiet_host()
    post.require(post.sha(post.AQ_STATE) == os.environ.get("S_ROUND4C_AQ_START_SHA256"),
                 "test bridge requires the saved final aq state")
    pin = json.loads(os.environ["S_ROUND4C_TEST_CONFIG"])
    _, config = post.read_pin(pin)
    command = bridge(sys.argv[1:], config)
    os.execv(command[0], command)


if __name__ == "__main__":
    main()
