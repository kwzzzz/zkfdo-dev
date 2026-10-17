# N6-J4c 엔진 v2.2 구현·A 재회귀 준비 (2026-10-17)

## 범위와 상태

사용자 지정 지시 `runs/handoff/n6_j4c_instruction_2026-10-17.md`를 **작업 시작 전에** SHA-256 `70a1cf85cc0eab7971766d68b54a9b6c750999174e81364e88e43c8b1a7627ea`로 확인했다. AGENTS.md·START_HERE·계획 문서를 읽고 진행 표에 miiz 담당 착수를 기록했다. 이번 범위는 v2.2 수정과 A **prepare 완료·execute 미실행**이다. A 전체 관문 통과나 L1 회복은 아직 주장하지 않는다.

v1·v2.1 산출물, 기존 회귀 목록·프로토콜·판정은 보존했다. 기존 v2.1 바이너리는 합성 회귀의 비교 실행에 읽기 전용으로 사용했다. B 후보 값·판정은 열지 않았고 B 작업·의존성 설치·커밋·push·PR은 수행하지 않았다. 시작 전부터 있던 `.vscode/settings.json` 변경 및 미추적 기존 문서는 이번 작업 범위에서 수정하지 않았다.

## 변경 파일과 동작

- `src/candidate_review/lifting/repair.rs`: localization 실패 제약의 기록을 현재 반복의 수리 뒤로 이동했다. with-paths 확장 뒤 unknowns와 wire를 공유하고, assigned를 반영한 현재 값에서 잔차가 0인 이전 실패 제약만 이월한다. 필터에서 빠진 수와 실제 이월 수, `carry=with/without`을 SolveRecord에 남긴다. 이월 질의가 unsat·unknown·timeout이면 같은 슬롯·반복에서 이월 없는 질의를 한 번 재시도한다. 탐색 전용이며 배제 근거로 쓰지 않는다. hub main 입력 모델 적용을 복원하고 pinned·보호 site 제외는 유지했다. apply가 돌려준 실제 변경 wire만 attempted_controls에 기록한다.
- `src/candidate_review/lifting/predicate.rs`: 새 SolveRecord 필드에 맞춰 기존 캐시 단위 테스트 레코드를 보완했다.
- `src/candidate_review/lifting/mod.rs`: 작은 원뿔 UNSAT의 evidence를 `small branch cone`, b_outcome을 `small_cone_unsat`으로 표기한다. joint cone과 판정 논리는 유지한다.
- `tests/lifting_engine_regression_test.rs`: 독립된 Num2Bits 범위 검사 3개가 동시에 실패하는 합성 회귀를 추가했다. fixture는 기존 합성 자료에서 구성하고 후보·컴파일 산출물은 ignored runs 아래 임시 경로에 둔다. 원본 전체 Rust·snarkjs 검사를 통과한 도달과 iteration 0 이월 부재를 검사한다. 비교용 엔진 경로를 환경변수로 지정할 수 있다.
- `scripts/n6_j4c_regression_v2_2.py`: 기존 `n6_j4b_regression_v2.py`를 복사해 BASE 한 줄만 `reaudit-v2.2.noindex`로 변경했다. 즉시 중단·재개·join 관문을 그대로 유지한다.
- `tests/n6_j4c_reaudit_test.py`: 기존 재개·join 관문 테스트를 새 래퍼에 적용했다.
- `docs/plan_revision_2026-10-01.md`: N6-J4c 착수·완료 담당/상태를 기록한다.

반복 6·클래스 공유 6 슬롯·지역 solve timeout 10초 등 수치 상수와 다른 v2.1 탐색·캐시·저장소·계측은 변경하지 않았다. 프로젝트·템플릿·W/S 분기를 추가하지 않았다.

## 테스트 우선: 빨강 → 초록

수정 전에 legacy carry 선택을 분리한 단위 테스트와 hub main 입력 테스트를 먼저 작성해 실패 로그를 남겼다. 초기 공유 hint 회로는 문제를 재현하지 못해 독립 quotient/remainder hint 세 쌍으로 분리했다. 이 세 범위 검사 회귀는 **수정 전 소스에서 unknown/no_progress로 실패**했고, 수정 후 도달했다. 별도로 SHA `f9a6ba687707aa0b3bb4dafd04d9232c7e0bd4c12802a086f86fd1c5db54296e`인 보존 v2.1 바이너리도 같은 실패를 재현했다. 새 release v2.2 바이너리는 같은 테스트를 통과했다.

단위 검사는 동시 실패 A/B의 이월 배제와 assert false 부재, 다음 반복의 이미 고쳐진 제약만 공유 unknown 질의에 이월, hub main 입력 반영 및 pinned·보호 site 유지, 실제 적용 controls 집합을 검사한다. 엔진 회귀는 합성 개발 자료이며 A 재회귀와 구분한다.

필수 검사: cargo fmt·`cargo clippy --all-targets --all-features -- -D warnings` 통과. Python J 테스트 `python3 -m unittest discover -s tests -p 'n6_j*_test.py'`: **68 통과**. 단위 검사 **99 통과·1 ignored**, 전체 lifting_engine_regression **20 통과**. 전체 `cargo test`: **376 통과·0 실패·24 ignored**, 종료 코드 0.

## A prepare와 고정 해시

| 항목 | SHA-256 / 상태 |
|---|---|
| 새 바이너리 `runs/n6-j4c-2026-10-17.noindex/zkfDO-v2.2` | `c78166319c0e12a62d89697ec0b248ef916e236961db9f890ec992f53c59a835` |
| `runs/n6-j4-2026-10-15.noindex/reaudit-v2.2.noindex/lock.json` | `9ee02679f481851ee0914970c6461bfe764c68356bab02277427b08fd39a060d` |
| `runs/n6-j4-2026-10-15.noindex/reaudit-v2.2.noindex/request-index-v2.json` | `d1102d837e5d78116cb44a2b67f5a9796f57bbc2a6733d712205eb1d528ceed8` |
| 기존 회귀 목록 `docs/n6_j4b_regression_lists_2026-10-16.json` | `dd54296714dd1f7114770ad59314d6b7aceef2b091a5c6a71767e71f9ccc4290` |
| 새 래퍼 | `65bcb30406814443f2b204fafd25c9a3dc6a48254d495208156441733535b3d9` |
| 원본 v1 index | `35ed44c86545fc3e56d3a671cbe45eae5db69c1d970f5e453c1db60e52225f3c` |
| 보존 v2.1 state | `05ef01917dc3fbac1ca42458cb84d5ac64ed4da8921b20f90c0b64c2acd76a03` |

prepare는 `prepared_not_executed`로 종료했다. cache 디렉터리는 비어 있고 j-execute 디렉터리·store·state는 아직 없다. 회귀 목록을 재생성하지 않았다. 기존 래퍼와 새 래퍼는 BASE 한 줄 차이임을 확인했다. 기존 v1 index·v2.1 state·바이너리와 목록 해시는 지시/기존 값과 일치했다.

## 미주 터미널에서 실행할 명령 (이 작업에서는 실행하지 않음)

저장소 루트 `/Users/miiz/Desktop/kwzzzz_zkfr`에서:

```sh
python3 scripts/n6_j4c_regression_v2_2.py \
  --engine /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-j4c-2026-10-17.noindex/zkfDO-v2.2 \
  --engine-sha256 c78166319c0e12a62d89697ec0b248ef916e236961db9f890ec992f53c59a835 \
  --action execute
```

일반 중단이면 같은 명령으로 재개한다. `REGRESSION_STOP.json`이 생기면 marker를 지우거나 재개하지 않고 리드에게 보고한다. 수정판 또는 배제 50건에서 L1이 나오면 즉시 중단하며, 재개 결과와 join 승격에도 같은 관문을 적용한다.

완료 후 요약 명령 (이 작업에서는 실행하지 않음):

```sh
python3 scripts/n6_j1_summarize.py --require-complete \
  --index runs/n6-j4-2026-10-15.noindex/reaudit-v2.2.noindex/request-index-v2.json \
  --run-output runs/n6-j4-2026-10-15.noindex/reaudit-v2.2.noindex/j-execute.noindex \
  --preparation-units runs/n6-a1-2026-10-07/preparation-units.json \
  --targets docs/n6_targets_a_2026-10-07.json \
  --main-queue runs/n6-a2b-2026-10-08.noindex/queue-a-v4.json \
  --mem20-queue runs/n6-a3-2026-10-08.noindex/queue-a3-mem20.json \
  --rq-c-map runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json \
  --output runs/n6-j4-2026-10-15.noindex/reaudit-v2.2.noindex/j-summary-v2.2.json
```

이후 대조 집계는 리드가 수행한다. 관문 결과, v1 L1 650 중 누락 요청·요청별 원인(목표 0), v2.1 새 L1 24건 유지, v1 도달→v2.2 unknown 클래스 및 v2.1에서 잃은 entrypoint_violation 9·partial-fix 7클래스, unknown 요청/클래스/인스턴스 표, 총 wall·최대 요청·단계별 비용·solver 호출을 대조한다. 이 구현 보고서는 재회귀 결과를 선취하지 않는다.

## 로그 SHA-256

| 경로 | SHA-256 |
|---|---|
| `runs/n6-j4c-2026-10-17.noindex/red-carry.log` | `0d6840109fcac4b1e503b2d301acb64d02012c7ec9dd5596d6a3bfd1ef819da4` |
| `runs/n6-j4c-2026-10-17.noindex/red-hub.log` | `39b6948e2e24515b618441f7ab951c5cab4a8e8d1cc75d32bf462bb0e60c3a12` |
| `runs/n6-j4c-2026-10-17.noindex/red-engine-multiple.log` | `0702fd5d1d72b6d0cee0fcce55b9ff359ebb5feb45b254f13813ce773228942f` |
| `runs/n6-j4c-2026-10-17.noindex/red-frozen-v2.1-engine.log` | `0bb16a5607aa864340a4b79aa5d09375be0c10b4c3661c71509256bb638c0acd` |
| `runs/n6-j4c-2026-10-17.noindex/green-unit.log` | `65335230995dd7fb1e3818bdaafaf3905b5bc1b566490e78743023fbde0c4545` |
| `runs/n6-j4c-2026-10-17.noindex/green-engine.log` | `b4a84383b5ce5d472f2083536aa0f84e8f561f8e33e482fdb97e558a15052a22` |
| `runs/n6-j4c-2026-10-17.noindex/green-frozen-v2.2-engine.log` | `c4efe10588f2d071387f1192051ada168901851cdbff6770fad810ebb77aa8ff` |
| `runs/n6-j4c-2026-10-17.noindex/fmt-final.log` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `runs/n6-j4c-2026-10-17.noindex/clippy-final.log` | `6b27b982f6770947c2a6e50a1aa555f99bb4e20e6f6de53ad5fa4ebffbc2fcfe` |
| `runs/n6-j4c-2026-10-17.noindex/python-j.log` | `4eb4028b0f22275e98967ab156fc3e76320ae76b3d869b9f45884510565dc6ee` |
| `runs/n6-j4c-2026-10-17.noindex/build-release.log` | `9101871772b9c4217fabb72fd64d756daeb1d3cdb7a9247a0fc239477c9d22d7` |
| `runs/n6-j4c-2026-10-17.noindex/prepare.log` | `4dcee0ef8b1cf32aeed47a9e763cc7a3dd2259cd58bc482dda398132da9d83e5` |
| `runs/n6-j4c-2026-10-17.noindex/preservation-check.json` | `5ae4a8cdca8cd97d17ac4da8cf775c8fae649603f8236c29cfb77aabbb0b3c80` |

| `runs/n6-j4c-2026-10-17.noindex/cargo-test.log` | `3d49ce36a7dfa507aa0ae4f441d7bf6bcc126cb49a63ab2a61fd6480e13eabad` |
