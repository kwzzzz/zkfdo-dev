#!/usr/bin/env python3
"""Build the script index from local AST imports without importing task code."""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOTS = {
    "run_n6_v4_4_queue.py": ("N6 고정 큐 실행", "채택된 N6 경로; 새 평가에서는 고정 큐·개정 범위 확인", "n6_b3_mem20_retry_preparation_2026-10-16.md"),
    "run_n6_b5_s_nested_queue.py": ("B S nested-array 재실행", "준비된 경로; 재퍼징 완료를 뜻하지 않음", "n6_b5_preparation_2026-10-17.md"),
    "n6_b3_mem20_retry_prestart_gate.py": ("mem20 시작 전 관문", "N6 v4.4 입력·호스트 관문", "n6_b3_mem20_retry_preparation_2026-10-16.md"),
    "n6_b5_s_nested_prestart_gate.py": ("B S 시작 전 관문", "채택 개정 범위의 준비 검사", "n6_b5_preparation_2026-10-17.md"),
    "n6_b6h_pair_runner.py": ("B 요청별 v2.2→v1 실행", "10-24 개정 운영 경로; 과거 마감·출력을 새 실행에 그대로 쓰지 않음", "n6_b6h_disk_cleanup_2026-10-24.md"),
    "n6_b6h_result_gate.py": ("B 쌍 결과 집계", "두 엔진 완료 요청·미완료 분리", "n6_b6h_disk_cleanup_2026-10-24.md"),
    "n6_a_remeasure_aq_execute_v3_2.py": ("A 구성 입력 재측정", "A 탐색층 운영 경로; 엄격 N5 결과와 분리", "s_round4c_amendment_2026-10-27_v2.md"),
    "run_policy_a_engine_v5_1.py": ("관측 주기 분리 캠페인", "개발용 v5.1; N5 자동 채택 아님", "preexp_top5_2026-11-05.md"),
    "prepare_targets_v2.py": ("wrapper 준비·선택 필터", "개발용; 필터 기본 꺼짐, N5 미채택", "robustness_aws_prep_2026-11-05.md"),
    "zkfdo_preflight_v1.py": ("리비전별 준비 자산 검사", "읽기 전용 개발 검사; 결손 입력 생성 안 함", "preexp_top5_2026-11-05.md"),
    "preexp_preflight_audit_v1.py": ("261건 준비 실패 소급 점검", "보존 기록과 현재 결손의 연결", "preexp_top5_2026-11-05.md"),
    "preexp_observer_bench_v2.py": ("합성 관측 오버헤드 비교", "자식 시계·호출 위치·공간 peak 보완판; N5 후보 사용 안 함", "preexp_top5_2026-11-05.md"),
    "j_speed_compare_v25_20261108.py": ("J v2.5 차등 비교", "A 개발 14요청; v2.3/v2.4 및 N5 판정 보존", "preexp_top5_2026-11-05.md"),
    "build_script_index_v1.py": ("이 색인의 AST 재생성", "읽기 전용 분석 후 INDEX.md만 갱신", "preexp_top5_2026-11-05.md"),
}


def value(node, variables):
    """Resolve literal path expressions only; never evaluate Python source."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int)):
        return node.value
    if isinstance(node, ast.Name):
        return variables.get(node.id)
    if isinstance(node, ast.BinOp):
        left, right = value(node.left, variables), value(node.right, variables)
        if isinstance(left, str) and isinstance(right, str):
            if isinstance(node.op, ast.Div):
                return str(Path(left) / right)
            if isinstance(node.op, ast.Add):
                return left + right
    if isinstance(node, ast.Attribute) and node.attr == "parent":
        parent = value(node.value, variables)
        if isinstance(parent, str):
            return str(Path(parent).parent)
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == "parents":
        parent, index = value(node.value.value, variables), value(node.slice, variables)
        if isinstance(parent, str) and isinstance(index, int):
            return str(Path(parent).parents[index])
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in {"Path", "str"} and node.args:
            return value(node.args[0], variables)
        if isinstance(node.func, ast.Attribute):
            base = value(node.func.value, variables)
            if isinstance(base, str):
                if node.func.attr in {"resolve", "absolute"}:
                    return str(Path(base).resolve())
                if node.func.attr == "with_name" and node.args:
                    name = value(node.args[0], variables)
                    if isinstance(name, str):
                        return str(Path(base).with_name(name))
    return None


def assignments(nodes, variables):
    result = dict(variables)
    for node in nodes:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            resolved = value(node.value, result)
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and resolved is not None:
                    result[target.id] = resolved
    return result


def imports(path, names):
    tree = ast.parse(path.read_text(), filename=str(path))
    variables = assignments(tree.body, {"__file__": str(path), "ROOT": str(HERE.parent), "HERE": str(HERE)})
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    loaders = {name: fn for name, fn in functions.items() if any(
        isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
        and call.func.attr == "spec_from_file_location" for call in ast.walk(fn))}
    edges = defaultdict(set)

    def add(candidate, line, kind):
        if isinstance(candidate, str):
            filename = Path(candidate).name
            if filename in names and filename != path.name:
                edges[filename].add((line, kind))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                add(alias.name.split(".")[0] + ".py", node.lineno, "import")
        elif isinstance(node, ast.ImportFrom) and node.module:
            add(node.module.split(".")[0] + ".py", node.lineno, "from")
        elif isinstance(node, ast.Call):
            fn_name = node.func.id if isinstance(node.func, ast.Name) else None
            attr = node.func.attr if isinstance(node.func, ast.Attribute) else None
            if attr == "spec_from_file_location" and len(node.args) > 1:
                add(value(node.args[1], variables), node.lineno, "dynamic")
            if (fn_name == "__import__" or attr == "import_module") and node.args:
                module = value(node.args[0], variables)
                if isinstance(module, str):
                    add(module.split(".")[0] + ".py", node.lineno, "dynamic")
            if fn_name in loaders:
                fn = loaders[fn_name]
                local = dict(variables)
                local.update({arg.arg: value(actual, variables) for arg, actual in zip(fn.args.args, node.args)})
                local = assignments(fn.body, local)
                for call in ast.walk(fn):
                    if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                            and call.func.attr == "spec_from_file_location" and len(call.args) > 1):
                        add(value(call.args[1], local), node.lineno, "dynamic")
    return edges


def closure(graph, roots):
    reached, pending = set(), list(roots)
    while pending:
        node = pending.pop()
        if node not in reached:
            reached.add(node)
            pending.extend(graph[node])
    return reached


def build():
    files = {path.name: path for path in sorted(HERE.glob("*.py"))}
    graph = {name: imports(path, files) for name, path in files.items()}
    roots = set(ROOTS) & files.keys()
    current = closure(graph, roots)
    tests = {name for name in files if "test" in name and any(
        name.startswith(Path(dependency).stem + "_") for dependency in current)}
    current = closure(graph, current | tests)
    callers = defaultdict(list)
    for name, dependencies in graph.items():
        for dependency, locations in dependencies.items():
            for line, kind in sorted(locations):
                callers[dependency].append(f"[{name}:{line}]({name}#L{line}) ({kind})")
    categories = {name: "현행 진입점" if name in roots else "현행 의존성" if name in current else "역사 기록용" for name in files}
    counts = Counter(categories.values())
    lines = ["# scripts 실행·의존 관계 색인", "", "기준: 현재 작업 트리. 파일명 날짜로 현행 여부를 정하지 않는다. 이 색인은 실행 승인이나 프로토콜 개정이 아니다.", "",
             f"전체 **{len(files)}개** Python 파일: 현행 진입점 {counts['현행 진입점']}개, 현행 의존성 {counts['현행 의존성']}개, 역사 기록용 {counts['역사 기록용']}개. 최초 정리 지시의 301개에 이번에 추가된 파일도 포함한다.", "",
             "`build_script_index_v1.py`가 각 파일을 실행하지 않고 AST의 `import`·`from` 및 리터럴 경로로 해석되는 `spec_from_file_location` 호출을 추적한다. 진입점은 아래 채택 근거로 정하고 전이 import 폐쇄와 해당 모듈의 회귀 테스트를 현행 의존성으로 분류한다. 나머지는 이 진입점 집합에서 도달하지 않는 역사 기록용이다. 역사 기록용도 개별 보고서 재현에 필요하며 삭제 대상이라는 뜻이 아니다.", "",
             "subprocess로 실행하는 경로는 import와 구분한다. B 쌍 실행기가 호출하는 `n6_b6h_j_runner.py`는 직접 import도 하므로 폐쇄에 포함된다. 외부 패키지·`runs/`의 사본·Rust 바이너리는 이 Python 파일 분모 밖이다. 임의 문자열 계산이나 런타임 monkey patch까지 실행해 추론하지 않는다.", "",
             "N5 본 판정은 [채택 개정](../docs/n5_amendment_b_judging_2026-10-17.md)의 고정 J v2.2와 v1을 따른다. J v2.3/v2.4/v2.5와 Policy-A v5/v5.1은 이 색인만으로 채택되지 않는다. 과거 마감·고정 출력 경로가 있는 명령을 새 실험에 그대로 실행하지 않는다.", "",
             "## 현행 진입점", "", "| 파일 | 용도 | 채택·사용 범위 | 근거 |", "|---|---|---|---|"]
    for name in sorted(roots):
        purpose, status, source = ROOTS[name]
        lines.append(f"| [{name}]({name}) | {purpose} | {status} | [기록](../docs/{source}) |")
    for category in ("현행 의존성", "역사 기록용"):
        lines += ["", f"## {category}", "", "| 파일 | 직접 import하는 파일·줄 | 이 파일의 로컬 import |", "|---|---|---|"]
        for name in sorted(files):
            if categories[name] == category:
                incoming = "<br>".join(callers[name]) or "없음 (독립 스크립트·회귀 검사)"
                outgoing = ", ".join(f"[{dep}]({dep})" for dep in sorted(graph[name])) or "없음"
                lines.append(f"| [{name}]({name}) | {incoming} | {outgoing} |")
    lines += ["", "## 갱신", "", "```sh", "python3 -B scripts/build_script_index_v1.py", "python3 -B scripts/build_script_index_v1.py --check", "```", "",
              "새 실행 진입점이나 채택 변경은 생성기의 ROOTS와 근거 링크에 명시한 뒤 재생성한다. 단순 날짜 증가로 진입점을 바꾸지 않는다.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = build()
    target = HERE / "INDEX.md"
    if args.check:
        return 0 if target.exists() and target.read_text() == text else 1
    target.write_text(text)
    print(f"Wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
