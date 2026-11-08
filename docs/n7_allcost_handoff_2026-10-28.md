# 새 대화 인수인계: 전체 비용 계측 실행기

**2026-10-28 인계 상태: plan-v5 준비됨, 실행하지 않음.** 사용자가 새 창으로 옮기기 위해 인수인계 자료 작성을 요청했다. 여기서 추가 실험·빌드를 시작하지 않았다. 인계 직전 프로세스 목록에서는 이 작업의 실행기·zkFuzz·Circom·Z3·cargo 및 aq 실행기·compact가 관측되지 않았다. 새 대화에서 실행 직전에 다시 확인해야 한다.

작업 디렉터리: `/Users/miiz/Desktop/kwzzzz_zkfr`.

## 1. 지금 무엇을 하려던 것인가

주 목표는 **대형 Circom에서 자동 조각 퍼징 S와 원본 맥락 판정 J가 전체 회로 퍼징 W보다 같은 비용으로 원본에서 검증되는 원인을 더 잘 찾는지** 입증하는 것이다. 10/29는 완성 논문 발표가 아니라 교수님이 현재 기여와 결과, 12월까지의 가능성을 판단하는 자리다.

J→S 피드백 시제품은 합성 3 seed에서 자유 S+J 대비 추가 원인 0으로 **방법 개발을 종료했다**. 다시 살리는 실험을 붙이지 않는다. 기존 S+J 연구는 계속한다. 

바로 직전 하려던 작업은 **새 비용 계측 실행기를 합성 회로 12군으로 시험**하는 것이다. 새 Python 실행기가 기존 발견·준비·퍼저·J를 연결한다. 현재 작업에서 S/J 알고리즘이나 Rust를 고친 것은 아니다. 특히 새 J 보강 옵션을 켜 평가하는 실험도 아니다. 아래 고정 v2.3 기본 바이너리를 사용한다.

## 2. 먼저 읽을 파일과 유지할 규칙

1. [AGENTS.md](../AGENTS.md), [START_HERE 최신성 안내](../reports/START_HERE.md)의 첫 부분, [현재 상태 색인](current_status_index_2026-10-28.md).
2. [비용·원인 감사](n7_cost_cause_audit_2026-10-28.md): 기존 결과에서 무엇이 확인됐고 무엇이 빠졌는가.
3. [운영 시범 v1](n7_allcost_pilot_protocol_v1_2026-10-28.md), [운영 시범 v2](n7_allcost_pilot_protocol_v2_2026-10-28.md). v2가 최신 추가조항이다.
4. [N5 고정 프로토콜](n5_evaluation_protocol_v1_2026-10-06.md), [채택 개정](n5_amendment_b_judging_2026-10-17.md). 이를 사후에 수정하지 않는다.

로컬 수정만 한다. git 쓰기·커밋·푸시·PR·설치·Docker·compact는 하지 않는다. B를 개발에 쓰지 않는다. 버그 위치 목록·RQ-C·zkbugs 정보를 탐색 정책에 쓰지 않는다. aq 판정 폴더와 `/Volumes/zkfdo-jcache` 이미지·캐시에 접근하지 않는다. `runs/` 전체를 재귀 탐색하지 않는다. 새 출력과 원시 산출물은 `runs/n7-allcost-2026-10-28/` 아래에만 둔다. 무거운 실행은 하나씩, nice 19로 한다.

기존 저장소에는 이 작업 전부터 다수의 변경이 있다. 특히 `src/candidate_review/lifting/{mod.rs,repair.rs,wtns.rs}` 등의 변경은 이번 작업의 수정이 아니다. 되돌리거나 덮어쓰지 않는다. 새 실행기 수정 전에도 현재 사본과 SHA를 새 backup 폴더에 남긴다. 고정 계획·실행 기록은 덮어쓰지 않고 새 판을 만든다. 시작·종료 때 계획 문서 진행 표를 갱신한다.

## 3. 현재 연구 근거를 정확히 설명하기

- A inference에서 **원본 O0 401,664제약을 통과하는 동일 최상위 입력·다른 출력 witness 쌍**이 확인돼 있다. 계산된 중간 입력의 위반을 J가 원본까지 연결한 구현 근거다. [A 양성 사례 및 W 연장](n5_next_gate_2026-10-28.md).
- 같은 개발 회로의 W 1,236초×3은 후보 0이었다. 그러나 결과를 보고 고른 A이며, 완전한 동일 총비용 대조가 아니다.
- 비용 감사의 S+J 확인 가능한 부분합은 **3,749.65166495809초**다. 이는 세 seed·요청의 누적 작업 wall이며 실험 전체 경과시간과 다르다. 후보 목록·요청 생성·일부 정리·사람 검토 등은 미계측이다. [감사 JSON v2](../runs/n7-cost-cause-audit-2026-10-28/a_inference_cost_v2.json).
- N6 TCCT 5요청의 보존 증인은 같은 IntDiv 출력 제약 누락 한 메커니즘에 귀속됐다. 술어 22요청은 저장 증인의 의존성만 확인됐다. 43 L1요청 전체 고유 원인 H는 미산정이다. 템플릿·호출 위치·속성의 조합 수를 H로 세지 않는다.
- A 수치는 개발 사례로 논문에 쓸 수 있다. 독립 성능 추정으로 쓰면 안 된다. N5도 D/Q/B 노출 층이 있으므로 전체를 미노출 평가라고 부르지 않는다. ScaleCirc 대비 능력·비용 우위는 아직 미검증이다.
- 최근 비용 실행기 수정 자체는 새로운 방법 기여가 아니다. 이미 있는 S+J의 효과를 믿을 수 있게 측정하기 위한 작업이다. 사용자에게 기여가 새로 늘었다고 표현하지 않는다.

## 4. 새 코드와 고정 도구

| 파일 | 역할 | 현재 SHA-256 |
|---|---|---|
| [pilot](../scripts/n7_allcost_pilot_20261028.py) | 계획 생성·자동 S 발견/준비·W/S 실행·후보 요청 생성·J·시간 기록 | `20eb9127ea69e1eeb5920e885a2055364e7bcb7c354ee57357d9f1e2ee0d14f4` |
| [supervisor](../scripts/n7_allcost_supervisor_20261028.py) | 전체 worker와 관측한 후손의 시간·RSS·디스크 감독, 종료 회수 | `10703dd0da6ee06a6ae2d801c3c68217142de7d70c2b3628cc6f865f8b8d6736` |
| [process tests](../scripts/n7_allcost_pilot_tests_20261028.py) | 정상 종료·시간 초과·별도 세션 후손·다른 프로세스 보존·자원/경로 검사 | `fbbb046c7a1984a76243aa17026ccb14408be5603061a03d09c88b32157d34fc` |

기존 파일을 수정해 만든 기능이 아니라 위 세 파일을 새로 추가했다. 수정 중간 사본은 `runs/n7-allcost-2026-10-28/backups/pre-v2`, `pre-v3`, `pre-v4`, `pre-v5`와 각각의 `sha256.json`에 있다.

| 도구 | 경로 | SHA-256 |
|---|---|---|
| 자동 발견·준비 | `runs/f01-2026-10-03/supplement-var-scope/tools/zkfDO` | `f8c9f64defd3993ebd845279bc0a245857e23a1ae759ce175e94f369cdd9f4c1` |
| J v2.3 기본 | `runs/s-round4-2026-10-27/round4b/bin/zkfDO-v2.3-development` | `05649971dc0fb9ece435324d3c779e2c6f148f4dc6efd74ff9fecf5a9690e700` |
| circom | `/Users/miiz/.cargo/bin/circom` | `8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227` |
| zkFuzz | `/Users/miiz/.cargo/bin/zkfuzz` | `ac2d9d16fd97ff803b121b7994aef804b4e191636f3f78660ff6ecd6c9ae4edd` |

기존 캠페인은 `scripts/run_policy_a_engine_v4.py`를 import하여 사용한다. `stderr_report` 모드를 유지해 위반 조건을 보존한다. `n6_j1_requests.build()`와 inventory 전체 build는 과거 후보 수·리비전 수가 하드코드되어 있으므로 호출하지 않는다. 새 실행기는 J 요청 schema만 재사용한다. 자동 S는 실제 `targets → manifest_for → prepare → small-first plan`을 거친다.

## 5. 시범 설정과 실행 결과

대상은 기존 작은 합성 fixture `entrypoint_violation`, `compatible_no_top_violation_observed`. 새 사본에서만 pragma 2.2.3→2.2.1로 맞춘다. 원본 제약 수 1,000 이하를 확인한다. 두 fixture×seed 2026102801/02/03×W/S = 12군이며 순서는 fixture마다 W→S / S→W / W→S다.

군당 전체 30초, 절대 탐색 cutoff 15초, S 시도 상한 3초다. 최신 v2 프로토콜/plan-v5는 **퍼저 시도도 군당 최대 2회**로 제한한다. 남은 시간으로 J를 처리한다. 준비·원본 기준 입력 검사·조각 발견/준비·전처리·퍼징·후보 정리·요청 생성·J·증거 저장을 단일 시간에 포함한다. 군별 새 캐시·instance-store를 사용한다. OS 캐시까지 cold라고 주장하지 않는다.

| 기록 | 실제 상태 |
|---|---|
| `supervisor-tests-v1/normal` | 부모와 자식에 nice를 중복 적용해 macOS에서 요구값 19를 벗어남. 실패 보존. |
| [supervisor-tests-v2](../runs/n7-allcost-2026-10-28/supervisor-tests-v2/summary.json) | 5검사 통과. 정상 종료, deadline에서 TERM을 무시하는 별도 세션 손자 KILL 및 별도 형제 프로세스 생존, 메모리·디스크·출력 경로 거부. |
| `execution-v3` | 첫 군이 argv 기록의 PosixPath JSON 직렬화 오류로 퍼저 실행 전에 실패. `list(map(str, argv))`로 수정. |
| [execution-v4](../runs/n7-allcost-2026-10-28/execution-v4/summary.json) | 4군만 실행 후 중단. 아래 표 참고. 음성 fixture는 아직 한 번도 실행되지 않음. |
| [plan-v5](../runs/n7-allcost-2026-10-28/plan-v5.json) | **준비만 완료, 실행 미착수.** SHA `7efdac2f926664e07798a1b71ed1e2952b1c9f6bff499a06812f0a1504070f01`. 인계 시 모든 pin 일치, `execution-v5` 없음. |

execution-v4는 모두 양성 fixture(O0 3제약)다. 아래 L1은 반복 후보에 대한 클래스 판정이며 고유 원인 수가 아니다.

| 순번 | seed·군 | 자동 대상 | 보존 후보 | 완료 J | 기록된 L1 클래스 | 감독 호출 wall | 종료 |
|---|---|---:|---:|---:|---:|---:|---|
| 0 | 01 W | 1 | 13 | 3 | 3 | 30.321초 | 전체 시간 종료, 관측 후손 회수 |
| 1 | 01 S | 2 | 12 | 3 | 3 | 30.317초 | 전체 시간 종료, 관측 후손 회수 |
| 2 | 02 S | 2 | 12 | 3 | 3 | 30.320초 | 전체 시간 종료, 관측 후손 회수 |
| 3 | 02 W | 미완료 | 미집계 | 미실행 | 미판정 | 15.260초 | 기존 v4 인프라 실패 뒤 새 수집기의 KeyError |

네 번째 군의 정확한 원천은 `execution-v4/03-entrypoint_violation-2026102802-W/work/campaign/ledger.json`: `status=incomplete`, `fatal_error="PermissionError: [Errno 1] Operation not permitted"`, 마지막 attempt index 13에 `candidates` 필드가 없다. 새 수집기가 이 필드를 바로 읽어 `KeyError`를 추가로 냈다. 현재 코드는 불완전 ledger를 명시적 인프라 실패로 처리하도록 고쳤다.

**PermissionError의 발생 syscall은 아직 특정하지 못했다.** 기존 v4 파일을 수정하지 않았으며, 최대 2회 제한은 운영 시범의 범위 축소다. 그 오류를 고쳤거나 긴 캠페인의 안정성을 입증했다고 쓰면 안 된다. 동일한 30초 상한·2회 시도에서 실행되는 v5는 앞선 장시간 반복형 관문의 완전한 대체가 아니다.

## 6. 고친 문제와 아직 검증할 것

이미 고친 것:

- macOS nice 중복: 현재 nice에서 19까지의 차이만 적용하고 자식에서도 실제 nice 19를 확인한다.
- J 소스 자기복사: 원본·발견 wrapper는 `work/input/` 아래, J 출력·캐시는 그 밖의 sibling이다. `source_root=work`로 두면 J가 자기 출력을 재귀 복사할 위험이 있었다.
- 실제 v4 반환값은 `run['ledger']`다. 후보 보존 시각은 부모 반환 시각−campaign wall+attempt 저장 완료 offset의 보수적 상한으로 변환한다.
- J 요청 SHA·후보 SHA·원본 O0 R1CS SHA를 확인한다. 준비 실패·클래스 없음은 `j_status=incomplete`, L1 수 null이다.
- J 전체 근거를 `events.jsonl`에 fsync한 뒤의 `durably_recorded_offset_seconds`로 예산 내 확인 여부를 정한다. `result.json`은 파생 색인이다.

미완료·주의:

1. **현재 plan-v5 코드는 실제 12군 실행 미검증이다.** 원인 분석·판정 의미를 바꾸지 않는 수정만 하고 새 계획판을 만들 것.
2. `execute()`의 부모 summary는 프로세스 완료 여부 중심이다. `worker.status=incomplete_j_preparation`, 탐색 전 예산 소진, 음성에서 잘못된 L1, 자연 후보 전달 부재를 별도 운영 관문에서 확인해야 한다. `summary.status=completed`만으로 시범 통과나 A 실행 준비 완료라고 선언하지 말 것.
3. 감독기의 `cleanup_complete`는 **관측한 후손** 기준이다. 0.2초 표본 사이 완전히 고아화한 미관측 후손·SIGKILL 등의 한계가 있다. RSS도 표본합이다.
4. 준비와 탐색을 총시간의 절반으로 제한하고 시도를 2회로 막는 방식은 운영 확인용이다. 후보 없는 W의 잔여 시간 활용, 큰 A의 탐색/J 전환 정책은 아직 결정하지 않았다. 이것을 대형 A 성능 비교에 그대로 쓰지 말 것.
5. **이번 새 코드에 대한 필수 `cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test`는 아직 실행하지 않았다.** 이전 작업의 통과 기록을 이번 결과로 인용하지 말 것. Rust 수정은 없지만 AGENTS의 관문은 남아 있다. 전용 target·nice 19·-j 1·공간 관문을 유지하고, 대형 회로를 쓰는 검사는 기존 bounded harness 규칙을 먼저 확인할 것. 기본 `target`은 사용하지 말 것.
6. 최종 결과 보고서 `docs/n7_allcost_pilot_results_2026-10-28.md`는 아직 없다. 이 인계 문서는 미완료 상태를 남긴 것이다.

## 7. 새 창의 다음 순서와 명령

우선 현재 문서·코드를 읽고 위 미완료 항목을 점검한다. 계획의 모든 pin을 확인하고 실행 중 무거운 프로세스 및 내장 여유를 확인한다. 인계 시 v5를 그대로 실행하려던 명령은 다음이었다. **이 문서를 작성하면서는 실행하지 않았다.**

```sh
cd /Users/miiz/Desktop/kwzzzz_zkfr
nice -n 19 python3 -B scripts/n7_allcost_pilot_20261028.py run \
  --plan runs/n7-allcost-2026-10-28/plan-v5.json \
  --output runs/n7-allcost-2026-10-28/execution-v5
```

코드를 수정했다면 v5 pin이 달라지므로 v5를 수정하지 말고 새 계획과 새 출력 이름을 사용한다.

```sh
python3 -B scripts/n7_allcost_pilot_20261028.py plan \
  --output runs/n7-allcost-2026-10-28/plan-v6.json --seconds 30
```

시범은 군별 wall·준비/퍼징/J 단계·자연 후보 수·예산 안 J 확인 수·준비 실패·양성/음성 판정·관측 후손 회수·샘플 peak RSS를 표로 정리한다. 12군의 수율 차이를 방법 기여나 새 원인으로 쓰지 않는다. 필수 검사와 최종 소스/바이너리 SHA를 기록하고 [계획 진행 표](plan_revision_2026-10-01.md#7-진행-표), [상태 색인](current_status_index_2026-10-28.md)을 갱신한다.

큰 A 비교는 운영 시범 뒤 별도 계획으로 결정한다. 탐색/J 시간 배분·유휴 시간·후보 검토 순서·공통비용·사람 검토 인시·원인 중복 제거를 먼저 정한다. 원인·결과를 본 A는 개발 근거이며, 독립 평가의 추가 실행은 N5 및 채택 개정을 따른다.

## 8. 새 대화에 붙여 넣을 지시

> `/Users/miiz/Desktop/kwzzzz_zkfr/docs/n7_allcost_handoff_2026-10-28.md`를 읽고 이어서 진행해. J→S 피드백은 종료된 상태다. 현재 목표는 W 대 S+J의 준비부터 원본 검증까지 비용을 계측하는 실행기의 합성 운영 검증을 마치는 것이다. plan-v5는 만들어졌지만 실행 전이며, 앞선 v4의 PermissionError 근본 원인은 미해결이다. 제한된 시범 통과를 대형 비교 안정성이나 논문 기여로 과장하지 말고, 누락된 의미 관문·필수 검사를 끝내고 결과를 정리해. 기존 코드와 도구를 재사용하고, B·aq 이미지/캐시·고정 결과를 건드리지 마.
