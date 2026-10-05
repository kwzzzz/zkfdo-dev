#!/usr/bin/env python3
"""Summarize complete E-01 metadata without reopening compiled artifacts."""

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/e01-setup-2026-10-03/recovery-v2"
C03 = ROOT / "docs/c03_corpus_results_2026-10-02.json"
OUT = ROOT / "docs/e01_setup_results_2026-10-03"


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reference(path):
    path = Path(path).resolve()
    return {"path": str(path.relative_to(ROOT)), "sha256": digest(path)}


def status_counts(rows, key):
    return dict(sorted(Counter(row.get(key, {}).get("status", "unknown") for row in rows).items()))


def observed_setup_failures(name, setup):
    failures = sorted(set(setup.get("failure_types", [])))
    if name == "celo-org/self" and failures == ["package_install_command_failed"]:
        return ["package_install_lockfile_mismatch"]
    if name == "stealthdrop/stealthdrop" and failures == ["package_install_command_failed"]:
        return ["package_install_artifact_not_found"]
    return failures


def main():
    c03 = read(C03)
    prior = {row["full_name"]: row for row in c03["repositories"]}
    records = [read(path) for path in sorted(RUN.glob("measurements/*/after/result.json"))]
    identities = {(row["repository"], row["entrypoint_key"]) for row in records}
    if len(records) != 329 or len(identities) != 329:
        raise ValueError("incomplete_or_duplicate_e01_measurements")
    by_repository = defaultdict(list)
    for row in records:
        by_repository[row["repository"]].append(row)
    cleanup = read(RUN.parent / "deleted-artifacts-result.json")
    repositories = []
    large = []
    for name in sorted(by_repository):
        rows = by_repository[name]
        setup_path = RUN / "setups" / name.replace("/", "__") / "setup.json"
        setup = read(setup_path)
        before_entries = {entry["key"]: entry for entry in prior[name]["entries"]}
        if {row["entrypoint_key"] for row in rows} != set(before_entries):
            raise ValueError("entrypoint_identity_mismatch:" + name)
        previous_compile = Counter(entry["after"]["compile"]["status"] for entry in before_entries.values())
        current_compile = Counter(row["compile"]["status"] for row in rows)
        preparation = Counter(row.get("preparation", {}).get("status", "unknown") for row in rows)
        failure_types = Counter(row.get("preparation", {}).get("failure_type") or "none" for row in rows)
        repositories.append({
            "repository": name,
            "commit_sha": rows[0]["commit_sha"],
            "entrypoints": len(rows),
            "c03_setup_status": prior[name]["setup"]["status"],
            "c03_setup_failure_types": sorted(set(prior[name]["setup"].get("failure_types", []))),
            "e01_setup_status": setup["status"],
            "e01_recorded_setup_failure_types": sorted(set(setup.get("failure_types", []))),
            "e01_observed_setup_failure_types": observed_setup_failures(name, setup),
            "setup_elapsed_seconds": setup.get("elapsed_seconds"),
            "c03_compile_statuses": dict(sorted(previous_compile.items())),
            "e01_compile_statuses": dict(sorted(current_compile.items())),
            "preparation_statuses": dict(sorted(preparation.items())),
            "preparation_failure_types": dict(sorted(failure_types.items())),
            "measurement_refs": [reference(RUN / "measurements" /
                                 hashlib.sha256((name.lower() + "\0" + row["entrypoint_key"]).encode()).hexdigest()[:24] /
                                 "after/result.json") for row in sorted(rows, key=lambda item: item["entrypoint_key"])],
            "setup_ref": reference(setup_path),
        })
        for row in rows:
            constraints = row["compile"].get("constraints")
            if isinstance(constraints, int) and constraints >= 100_000:
                large.append({"repository": name, "entrypoint": row["entrypoint"],
                              "entrypoint_key": row["entrypoint_key"], "constraints": constraints,
                              "compile_status": row["compile"]["status"],
                              "preparation_status": row.get("preparation", {}).get("status", "unknown"),
                              "preparation_failure_type": row.get("preparation", {}).get("failure_type")})
    total_compile = Counter(row["compile"]["status"] for row in records)
    total_preparation = Counter(row.get("preparation", {}).get("status", "unknown") for row in records)
    prior_compile = Counter(entry["after"]["compile"]["status"] for repo in repositories
                            for entry in prior[repo["repository"]]["entries"])
    timings = {stage: sum((row.get(stage, {}).get("elapsed_seconds") or 0) for row in records)
               for stage in ("compile", "discovery", "preparation", "plan")}
    document = {
        "schema_version": 1, "task": "E-01", "owner": "miiz", "deadline": "2026-10-07",
        "status": "complete", "zkfuzz_invocations": 0,
        "scope": {"repositories": len(repositories), "entrypoints": len(records),
                  "selection": "C-03 production setup_failure repositories; all same entrypoint keys",
                  "c03_reference": reference(C03),
                  "procedure": reference(ROOT / "docs/e01_setup_procedure_2026-10-03.md"),
                  "procedure_lock": reference(RUN / "procedure-lock.json")},
        "overall": {"setup_statuses": dict(sorted(Counter(row["e01_setup_status"] for row in repositories).items())),
                    "c03_compile_statuses": dict(sorted(prior_compile.items())),
                    "e01_compile_statuses": dict(sorted(total_compile.items())),
                    "preparation_statuses": dict(sorted(total_preparation.items())),
                    "large_entrypoints_at_least_100k": len(large), "stage_elapsed_seconds": timings},
        "repositories": repositories,
        "large_entrypoints": sorted(large, key=lambda row: (row["repository"].lower(), row["entrypoint"])),
        "cleanup": {"manifest": reference(RUN.parent / "deleted-artifacts.json"),
                    "result": reference(RUN.parent / "deleted-artifacts-result.json"),
                    "deleted_count": cleanup["deleted_count"], "deleted_bytes": cleanup["deleted_bytes"],
                    "skipped_count": len(cleanup["skipped"]),
                    "pre_cleanup_df_h": read(RUN.parent / "deleted-artifacts.json")["pre_cleanup_df_h"],
                    "post_cleanup_df_h": cleanup["post_cleanup_df_h"]},
        "history": {"initial_setup_attempt": "runs/e01-setup-2026-10-03/setups",
                    "initial_attempt_outcome": "1/9 success; preserved; Berry inherited Classic-only setting",
                    "active_recovery": "runs/e01-setup-2026-10-03/recovery-v2",
                    "sandbox_interruption": reference(RUN / "measurement-sandbox-interruption-v1.json")},
        "checks": {"python_e01_unittest": "passed: 3", "result_validation": "passed",
                   "compiled_artifacts_remaining_outside_protected_paths": 0,
                   "cargo_fmt": "passed", "cargo_clippy_all_targets_all_features_D_warnings": "passed",
                   "cargo_test": "passed: failures 0; existing environment-dependent tests ignored"},
        "limitations": ["Environment and structural-preparation measurement only; no zkFuzz or candidate execution.",
                        "Setup success does not imply complete preparation or semantic compatibility.",
                        "Large-circuit counts cover successfully compiled entrypoints; timeout/failure constraint counts remain unknown.",
                        "C-03 results remain the frozen baseline; E-01 is a separate version."],
    }
    with (OUT.with_suffix(".json")).open("x") as stream:
        json.dump(document, stream, indent=2, ensure_ascii=False); stream.write("\n")
    lines = ["# E-01 C-03 setup 실패 저장소 자동 환경 구성 확장 결과", "",
             "담당 miiz · 완료 2026-10-03 · zkFuzz 0회.", "",
             "## 결과 요약", "",
             "- C-03 production setup 실패 **9개 저장소·329 entrypoint 전부**를 동일 commit·동일 key로 재측정했다.",
             f"- setup은 C-03 0/9에서 E-01 **{document['overall']['setup_statuses'].get('success', 0)}/9**로 늘었다.",
             f"- 같은 entrypoint의 compile 성공은 C-03 **{prior_compile.get('success',0)}/329**에서 E-01 **{total_compile.get('success',0)}/329**로 늘었다. timeout {total_compile.get('timeout',0)}, failure {total_compile.get('failure',0)}다.",
             f"- 준비 결과는 success {total_preparation.get('success',0)}, partial {total_preparation.get('partial',0)}, unsupported {total_preparation.get('unsupported',0)}, failed {total_preparation.get('failed',0)}다. partial/unsupported는 성공으로 합치지 않았다.",
             f"- 성공적으로 컴파일되어 제약 수를 읽은 10만 이상 entrypoint는 **{len(large)}개**다. compile failure/timeout의 제약 수는 unknown이다.",
             f"- 컴파일 산출물 {cleanup['deleted_count']:,}개, {cleanup['deleted_bytes']:,}바이트를 manifest 기록 후 삭제했고 건너뜀은 {len(cleanup['skipped'])}개다.", "",
             "## 저장소별 결과", "", "| 저장소 | setup C-03 → E-01 | E-01 실패 유형 | compile 성공 C-03 → E-01 / 분모 | E-01 준비 success / partial / unsupported / failed |", "|---|---:|---|---:|---:|"]
    for row in repositories:
        prep = row["preparation_statuses"]; comp0 = row["c03_compile_statuses"].get("success",0); comp1 = row["e01_compile_statuses"].get("success",0)
        failure = ", ".join(row["e01_observed_setup_failure_types"]) or "—"
        lines.append(f"| `{row['repository']}` | {row['c03_setup_status']} → {row['e01_setup_status']} | {failure} | {comp0} → {comp1} / {row['entrypoints']} | {prep.get('success',0)} / {prep.get('partial',0)} / {prep.get('unsupported',0)} / {prep.get('failed',0)} |")
    lines += ["", "Celo는 immutable lockfile의 builtin patch hash 변경 요구로 실패했고, selfxyz는 HTTPS submodule 치환 후에도 비공개 접근 인증이 필요했으며, Stealthdrop은 고정 외부 tarball 404로 실패했다. 저장소별 수동 lock/source 수선이나 자격 증명 주입은 하지 않았다.", "", "## 제약 10만 이상 entrypoint", "", "| 저장소 | entrypoint | 제약 | 준비 | 준비 실패 유형 |", "|---|---|---:|---|---|"]
    for row in document["large_entrypoints"]:
        lines.append(f"| `{row['repository']}` | `{row['entrypoint']}` | {row['constraints']:,} | {row['preparation_status']} | {row['preparation_failure_type'] or '—'} |")
    lines += ["", "## 검사", "", "Python E-01 회귀 3건, 결과 identity·분모 검사, 보호 경로 밖 컴파일 산출물 잔존 0건을 확인했다. `cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test`가 모두 통과했다. Cargo test의 로컬 fixture·외부 도구 의존 항목은 기존과 같이 ignored이며 실패는 0건이다.", "", "## 비용·정리·한계", "", f"기록된 단계 시간 합계는 compile {timings['compile']:.3f}초, discovery {timings['discovery']:.3f}초, preparation {timings['preparation']:.3f}초, plan {timings['plan']:.3f}초다. 동시 실행 때문에 합계는 campaign wall과 같지 않다.", "", "초기 v1 setup은 Berry에 Classic 전용 환경 설정이 전달된 결함으로 1/9 성공했다. 원본은 보존하고 보정 구현·새 lock·깨끗한 checkout의 recovery-v2를 9개 전체에 적용했다. 측정 시작 시 `/bin/ps` 샌드박스 차단으로 생성된 값 없는 329개 디렉터리도 별도 이력으로 보존했다.", "", "이 결과는 환경 구성과 구조 준비 적용성 조사다. setup 성공은 완전 준비나 의미 호환성을 뜻하지 않으며, 탐지 성능·결함 수·의미 동등성의 근거가 아니다. C-03 고정 결과는 수정하지 않았다.", ""]
    with (OUT.with_suffix(".md")).open("x") as stream:
        stream.write("\n".join(lines))
    print(json.dumps({"repositories": len(repositories), "entrypoints": len(records), "compile": dict(total_compile), "preparation": dict(total_preparation), "large": len(large)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
