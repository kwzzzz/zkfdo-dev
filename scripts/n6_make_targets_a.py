#!/usr/bin/env python3
"""Create the frozen N6-A inventory before any N6-A zkFuzz campaign.

The inventory is an audit of all 70 Circom zkbugs records.  It deliberately
uses the original/project-mode entrypoint from zkbugs_vars.sh; the direct
wrapper remains reference metadata only.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
ZKBUGS = ROOT / ".external/zkbugs/dataset/circom"
OUT = ROOT / "docs/n6_targets_a_2026-10-07.json"
SOURCES = {
    "c03": ROOT / "docs/c03_corpus_results_2026-10-02.json",
    "e01": ROOT / "docs/e01_setup_results_2026-10-03.json",
    "e02": ROOT / "docs/e02_production_mains_results_2026-10-05.json",
}
DEVELOPMENT_PROJECTS = {
    "inference-labs-inc/subnet-2-circom",
    "banyancomputer/hot-proofs-blake3-circom",
    "zkemail/zk-email-verify",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def repository_name(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname and parsed.hostname.lower() != "github.com":
        raise ValueError(f"non-GitHub Project URL: {url}")
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) != 2:
        raise ValueError(f"Project URL is not owner/name: {url}")
    return f"{parts[0]}/{parts[1].removesuffix('.git')}"


def repository_key(name: str) -> str:
    parts = name.strip("/").split("/")
    if len(parts) != 2:
        raise ValueError(f"repository is not owner/name: {name}")
    return f"{parts[0].lower()}/{parts[1].removesuffix('.git').lower()}"


def setup_index() -> dict[str, list[dict]]:
    evidence: dict[str, list[dict]] = defaultdict(list)
    c03 = json.loads(SOURCES["c03"].read_text())
    for row in c03["repositories"]:
        name = row.get("canonical_full_name") or row["full_name"]
        setup = row.get("setup") or {}
        evidence[repository_key(name)].append(
            {"source": "C-03", "repository": name, "status": setup.get("status", "unknown")}
        )
    e01 = json.loads(SOURCES["e01"].read_text())
    for row in e01["repositories"]:
        evidence[repository_key(row["repository"])].append(
            {"source": "E-01", "repository": row["repository"],
             "status": row.get("e01_setup_status", "unknown")}
        )
    e02 = json.loads(SOURCES["e02"].read_text())
    for row in e02["repositories"]:
        environment = row.get("environment_reuse") or {}
        status = "success" if environment.get("setup_success", 0) else (
            "setup_failure" if environment.get("excluded_setup_failure", 0) else "unknown"
        )
        evidence[repository_key(row["repository"])].append(
            {"source": "E-02", "repository": row["repository"], "status": status}
        )
    return evidence


def shell_assignment(text: str, name: str) -> str | None:
    match = re.search(rf"^{re.escape(name)}=(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else None


def unquote(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def original_entrypoint(vars_text: str) -> tuple[str | None, str | None, str | None]:
    expression = unquote(shell_assignment(vars_text, "CIRCOM_CIRCUIT_ORIGINAL"))
    direct_expression = unquote(shell_assignment(vars_text, "CIRCOM_CIRCUIT_DIRECT"))
    if expression is None:
        return None, None, "missing_CIRCOM_CIRCUIT_ORIGINAL"
    if expression == "$CIRCOM_CIRCUIT_DIRECT":
        return direct_expression, "original_is_direct", None
    prefix = "$CODEBASE_PATH/"
    if not expression.startswith(prefix):
        return expression, None, "original_expression_not_codebase_relative"
    path = expression[len(prefix):]
    lower = "/" + path.lower()
    if re.search(r"(^|/)(test|tests|tester)(/|$)", path.lower()) or ".test." in lower:
        kind = "project_test"
    elif any(marker in vars_text.lower() for marker in
             ("thin entrypoint", "thin main", "thin wrapper")):
        kind = "zkbugs_thin"
    else:
        kind = "project_main"
    return path, kind, None


def fix_commits(value: object) -> list[str]:
    if value is None or value == "":
        return []
    values = value if isinstance(value, list) else [value]
    return [str(item) for item in values if str(item).strip()]


def development_units() -> list[dict]:
    inference = [
        ("inference-original", "d310309c141d36504b3486cebd96ed70ef3a4fdf", None),
        ("inference-r-intdiv", "d310309c141d36504b3486cebd96ed70ef3a4fdf", "r_intdiv"),
        ("inference-c9221e8d", "9221e8dfff3c13153eadeaaba46458060056873b", "c9221e8d"),
        ("inference-c79f42ee", "79f42eef3fc103638fed9fefaeae12dcbf0b9cf2", "c79f42ee"),
        ("inference-c771c61c-p", "771c61c221a647f35ecab3c9f278dfa7bcc1a359", "c771c61c_p"),
        ("inference-loo-clamp", "b8f92bdec1694138df0e069921f1aa0bdc94053e", "loo_clamp"),
        ("inference-loo-dfs", "b8f92bdec1694138df0e069921f1aa0bdc94053e", "loo_dfs"),
        ("inference-all-fixed", "b8f92bdec1694138df0e069921f1aa0bdc94053e", "all_fixed"),
    ]
    rows = []
    for unit_id, revision, tree in inference:
        row = {
            "unit_id": unit_id, "project": "inference-labs-inc/subnet-2-circom",
            "revision": revision, "entrypoint": "src/circuit.circom",
            "source": "runs/dev-projects/inference", "evidence": "docs/lifting_l06_results_2026-10-05.md",
        }
        if tree:
            diff = ROOT / f"runs/l06-2026-10-03/trees/{tree}.diff"
            row["revision_tree"] = tree
            row["diff"] = {"path": relative(diff), "sha256": sha256(diff)}
        rows.append(row)
    rows += [
        {"unit_id": "banyan-vulnerable", "project": "banyancomputer/hot-proofs-blake3-circom",
         "revision": "76b83107eb00c8f886bde82172eaa3cdd5d57f25", "entrypoint": "circuit.circom",
         "source": "datasets/controlled-v2/banyan-check-depth/vulnerable/project",
         "evidence": "datasets/controlled-v2/banyan-check-depth/manifest.json"},
        {"unit_id": "banyan-fixed", "project": "banyancomputer/hot-proofs-blake3-circom",
         "revision": "e37eb56e29b304024055f3d0a1681e6f22132ecc", "entrypoint": "circuit.circom",
         "source": "datasets/controlled-v2/banyan-check-depth/fixed/project",
         "evidence": "datasets/controlled-v2/banyan-check-depth/manifest.json"},
        {"unit_id": "zkemail-fpmul-vulnerable", "project": "zkemail/zk-email-verify",
         "revision": "fc9949763858ca363a73a2764d9c1d26ef227478",
         "entrypoint": "packages/circuits/tests/test-circuits/rsa-test.circom",
         "source": "runs/dev-projects/zkemail", "evidence": "reports/dev-rq1-pilot-2026-09-29/README.md"},
        {"unit_id": "zkemail-fpmul-fixed", "project": "zkemail/zk-email-verify",
         "revision": "9ed3769dc3d96fb0d7c45f1f014dcd9bfb63675b",
         "entrypoint": "packages/circuits/tests/test-circuits/rsa-test.circom",
         "source": "runs/dev-projects/zkemail", "evidence": "reports/dev-rq1-pilot-2026-09-29/README.md"},
    ]
    return rows


def main() -> int:
    setup = setup_index()
    raw: list[tuple[Path, str, dict]] = []
    for config in sorted(ZKBUGS.rglob("zkbugs_config.json")):
        content = json.loads(config.read_text())
        if len(content) != 1:
            raise ValueError(f"expected one item in {config}")
        title, item = next(iter(content.items()))
        raw.append((config, title, item))
    if len(raw) != 70:
        raise ValueError(f"expected 70 zkbugs items, got {len(raw)}")

    shared: dict[tuple[str, tuple[str, ...]], list[str]] = defaultdict(list)
    normalized = []
    for config, title, item in raw:
        project = repository_name(item.get("Project", ""))
        fixes = fix_commits(item.get("Fix Commit"))
        if fixes:
            shared[(repository_key(project), tuple(fixes))].append(item.get("Id", relative(config.parent)))
        normalized.append((config, title, item, project, fixes))

    records = []
    for config, title, item, project, fixes in normalized:
        vars_path = config.with_name("zkbugs_vars.sh")
        vars_text = vars_path.read_text(errors="replace") if vars_path.is_file() else ""
        original, original_kind, original_reason = original_entrypoint(vars_text)
        observations = setup.get(repository_key(project), [])
        setup_success = any(row["status"] == "success" for row in observations)
        if repository_key(project) in {repository_key(name) for name in DEVELOPMENT_PROJECTS}:
            bucket, reason = "A-D", "development_project_precedence"
        elif not fixes:
            bucket, reason = "vulnerable_only", "fix_commit_not_recorded_RQ-C_excluded"
        elif setup_success:
            bucket, reason = "A-Q-stage1", "fix_commit_and_setup_success_record"
        else:
            bucket, reason = "A-Q-stage2", "fix_commit_but_no_setup_success_record"
        group = shared.get((repository_key(project), tuple(fixes)), [])
        config_dir = config.parent
        original_input = config_dir / str((item.get("Input") or {}).get("Original", "input.json"))
        location = item.get("Location") or {}
        loo = None
        if fixes and len(group) > 1:
            loo = {
                "required": True,
                "shared_fix_item_count": len(group),
                "shared_fix_item_ids": sorted(group),
                "base_fix_commits": fixes,
                "restore_from_vulnerable_commit": item.get("Commit"),
                "method": "apply full fix revision, then restore only this item's vulnerable location",
                "planned_diff_scope": {"path": location.get("Path"), "function": location.get("Function"),
                                       "line": location.get("Line")},
                "diff_path": None,
                "diff_sha256": None,
            }
        reasons = []
        for field in ("Id", "Project", "Commit", "Direct Entrypoint"):
            if not item.get(field):
                reasons.append(f"missing_{field.lower().replace(' ', '_')}")
        if original_reason:
            reasons.append(original_reason)
        if not original_input.is_file():
            reasons.append("original_input_missing_locally")
        records.append({
            "id": item.get("Id"), "title": title, "project": project,
            "project_match_key": repository_key(project), "vulnerable_commit": item.get("Commit"),
            "fix_commits": fixes, "bucket": bucket, "bucket_reason": reason,
            "dataset_case": relative(config_dir),
            "config": {"path": relative(config), "sha256": sha256(config)},
            "vars": {"path": relative(vars_path), "sha256": sha256(vars_path)} if vars_path.is_file() else None,
            "original_entrypoint": original, "original_entrypoint_kind": original_kind,
            "original_input": {"path": relative(original_input), "exists": original_input.is_file(),
                               "sha256": sha256(original_input) if original_input.is_file() else None},
            "direct_entrypoint_reference_only": item.get("Direct Entrypoint"),
            "location": location, "setup_success": setup_success,
            "setup_observations": observations or [{"source": "C-03/E-01/E-02", "status": "not_recorded"}],
            "leave_one_out": loo, "missing_or_unknown": reasons,
        })

    counts = Counter(row["bucket"] for row in records)
    kinds = Counter(row["original_entrypoint_kind"] or "unknown" for row in records)
    if sum(counts.values()) != 70 or sum(bool(row["fix_commits"]) for row in records) != 50:
        raise AssertionError("70-item/fix-commit denominator changed")
    output = {
        "schema_version": 1,
        "task": "N6-A known-answer target inventory",
        "protocol": "docs/n5_evaluation_protocol_v1_2026-10-06.md",
        "correction": "N5 appendix A pre-list correction, 2026-10-07, miiz decision",
        "zkfuzz_invocations": 0,
        "selection_before_preparation": True,
        "source_records": [{"path": relative(path), "sha256": sha256(path)} for path in SOURCES.values()],
        "rules": {
            "entrypoint": "CIRCOM_CIRCUIT_ORIGINAL plus input.json; Direct is reference only",
            "project_match": "case-insensitive exact GitHub owner/name; forks remain distinct",
            "setup_success": "success in any of C-03, E-01, E-02",
            "development_precedence": sorted(DEVELOPMENT_PROJECTS),
            "missing_fields": "retain in denominator with reason",
        },
        "counts": {"all": 70, "with_fix_commit": 50, "without_fix_commit": 20,
                   **dict(sorted(counts.items())), "original_entrypoint_kinds": dict(sorted(kinds.items())),
                   "shared_fix_groups": sum(len(items) > 1 for items in shared.values()),
                   "leave_one_out_items": sum(row["leave_one_out"] is not None for row in records)},
        "development_units": development_units(),
        "items": records,
    }
    text = json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if "/Users/" in text:
        raise AssertionError("absolute local path leaked into shared inventory")
    if OUT.exists() and OUT.read_text() != text:
        raise SystemExit(f"{relative(OUT)} already exists with different content; create a new version")
    OUT.write_text(text)
    print(json.dumps({"path": relative(OUT), "sha256": sha256(OUT), "counts": output["counts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
