# N6-J2 A 맥락 판정 시범 v2 결과 (2026-10-13 JST)

## 범위와 입력

[2026-10-12 지시](../runs/handoff/n6_b3_j2_instruction_2026-10-12.md)(SHA-256 `a9deb163ec356a8858b8b4887f12c0675e6690157fc37eba05cb5a0bb22f049f`)의 3절만 수행했다. [v1 시범](../runs/n6-j1-2026-10-09.noindex/pilot-v1.noindex/pilot.json)은 수정하지 않았다. 시범은 고정 [요청 index](../runs/n6-j1-2026-10-09.noindex/request-index.json)(SHA-256 `35ed44c86545fc3e56d3a671cbe45eae5db69c1d970f5e453c1db60e52225f3c`)와 기준 입력 [index v3](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/index.json)(SHA-256 `18ad0bee4278fd77f94b11c354e531a31a4a5d2c0f96c9bd87d7e17c850d1508`)를 썼다. 실행 전 두 index와 선택한 요청·후보·소스의 SHA-256을 검증했고 `validate-only` 결과는 `valid`, 준비 실패 0건이었다. 실행 중 다른 컴파일·퍼징·시범은 돌리지 않았다.

첫 [pilot-v2.noindex 기록](../runs/n6-j1-2026-10-09.noindex/pilot-v2.noindex/pilot.json)(SHA-256 `e90ecdf1039d6eac9384ef887204077c1b9491cfa457c10af79e5e3f0133a415`)은 6건을 완료했지만 `/usr/bin/time -l`로 최대 RSS를 측정했다. 지시가 요구한 **직접 `wait4` rusage** 계측과 달라 이 측정 시도는 뒤의 재계측으로 대체하며 원본 기록·[부분 집계](../runs/n6-j1-2026-10-09.noindex/pilot-summary-v2.json)(SHA-256 `588adf048775b3b5f05d4e193352c09abaa8e3c3927df031372fae1a279c1884`)·[캐시](../runs/n6-j1-2026-10-09.noindex/cache-pilot-v2.noindex)를 보존했다. 지정된 정확한 출력 경로가 이미 사용돼 재계측 출력은 별도의 `pilot-v2-wait4.noindex`에, 캐시는 지정 캐시 루트의 새 `wait4` 하위 경로에 두었다. 아래 표와 추정은 모두 재계측 값이다.

선택 규칙은 지정된 각 리비전·방식에서 `main` 범위이고 기준 입력이 통과한 호출 가능 요청을 `queue_order` 오름차순으로 정렬한 첫 건이다. 여섯 번째는 앞의 리비전들과 겹치지 않는 호출 가능 S 요청이 있는 리비전을 제약 수 내림차순, 같은 수면 리비전 ID 오름차순으로 골라 그 첫 요청을 썼다. 따라서 `inference-c771c61c-p`(603,136 제약)가 선정됐다. `inference-loo-dfs`도 603,136 제약이지만 ID 순서가 뒤다. 선택 queue 순서는 `2235, 2442, 0, 2223, 1962, 119`다.

## 6건 실행 결과

2026-10-13 02:50~02:53 JST에 [직접 wait4 실행 기록](../runs/n6-j1-2026-10-09.noindex/pilot-v2-wait4.noindex/pilot.json)(SHA-256 `573b4b826fd40b7631064184cc695fde0d3c68f7ad7818d232d6695787cd542a`)을 만들었다. `measurement_method=wait4`이고 6/6 엔진 종료 코드 0, `preparation.status=ok`, 결과 SHA 일치였다. 5개 리비전의 `lift-instances`도 성공했고 충돌은 0이다. `base_input_unavailable`은 발생하지 않았다. 각 요청의 상태·자기 분류·자기 가정 술어·실효 술어는 아래와 같다. 실효 술어의 `—`는 그 후보에 가정 술어 판정 대상이 없어 결합 결과가 없음을 뜻한다.

| 순서·요청 | 상태 | 자기 분류; 자기 가정 술어 → 실효 술어 | `sites_found` | 벽시계 초 | 최대 RSS MiB | 캐시 증가 MiB |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| 1 aq-036 W, q2235 | 완료 | `assumption_input_reachable`; `assumption_violation_reachable` → 같음 | **1 (`main`)** | 0.897 | 156.3 | 1.682 |
| 2 aq-036 S, q2442 | 완료 | `assumption_input_reachable`; `assumption_violation_reachable` → 같음 | 1 | 0.647 | 187.9 | 1.682 |
| 3 inference original S, q0 | 완료 | `unknown` 3·`excluded_in_context` 2; — → — | 1,280 | 37.954 | 1,114.3 | 724.461 |
| 4 aq-035 S, q2223 | 완료 | `excluded_in_context`; `assumption_excluded_in_context` → 같음 | 1 | 0.385 | 48.3 | 1.952 |
| 5 zkemail fpmul vulnerable S, q1962 | 완료 | `excluded_in_context`; `assumption_excluded_in_context` → 같음 | 1 | 19.133 | 564.8 | 86.810 |
| 6 inference c771c61c-p S, q119 | 완료 | `unknown`; `unknown` → `unknown` | 256 | 79.844 | 3,480.1 | 1,745.435 |

벽시계 합은 138.860초다. 최대 RSS는 각 lift 자식 프로세스의 직접 `wait4` rusage 값이다. aq-036 W의 `component_wrapper`를 entrypoint로 둔 요청에서 `main` 위치가 1곳 확인됐다. 이 시범의 판정은 전체 J 또는 독립 평가 결과가 아니다. [값 없는 부분 집계](../runs/n6-j1-2026-10-09.noindex/pilot-summary-v2-wait4.json)(SHA-256 `00454271ebb4dcfcb22d15b2f49a85670ba5ddabc27cdc8bbc1c345c41e44ae0`)에는 2,926개 index 요청 중 시범 완료 6, 아직 대기 2,920, 결합 리비전 5개를 분리했다. 예정 `base_input_unavailable`을 시범 관측 실패로 더하지 않았다.

시범 종료 후 두 시도의 캐시를 삭제하지 않았다. 재계측 내장 [cache-pilot-v2.noindex/wait4](../runs/n6-j1-2026-10-09.noindex/cache-pilot-v2.noindex/wait4)의 논리 파일 크기 합은 2.502 GiB이고 파일 168개의 [SHA-256 목록](../runs/n6-j1-2026-10-09.noindex/pilot-v2-wait4-cache-files.sha256)(목록 SHA-256 `b52f7b8e72d0e92ee11b1d17624ac2cfbef8ddcfcea8bbbe95197c6e9d121762`)을 남겼다. 리비전별 종료 캐시 크기는 aq-036 3.364 MiB, inference original 724.461 MiB, aq-035 1.952 MiB, zkemail vulnerable 86.810 MiB, inference c771c61c-p 1,745.435 MiB다. 요청별 기록에는 출력 증가량과 실행 전·후 여유 공간도 있다.

## 765건 시간·디스크 추정

[wait4 환산 근거 JSON](../runs/n6-j1-2026-10-09.noindex/pilot-v2-wait4-extrapolation.json)(SHA-256 `eb798c6502e8c5512110a995bf948ecae4cb6ef553796ae270275f9c229ff91f`)에 본 표에서 호출 가능한 765건의 리비전·방식별 개수와 대응 시범을 적었다. 각 부류의 건수에 재계측 시범 1건의 벽시계·캐시 증가량·출력 증가량을 곱했다. 미측정 inference 수정 리비전은 제약 수가 비슷한 `inference-c771c61c-p` S 값을, zkemail fixed는 vulnerable S 값을 대입했다. 다른 후보의 편집 수·캐시 재사용·위치 수가 달라질 수 있으므로 상한이나 신뢰구간이 아닌 단순 용량 계획 값이다.

| 캐시 운영 | 추정 캐시 | 결과 출력 추정 | 합계 사용량 추정 | 현재 내장 디스크 판정 |
| --- | ---: | ---: | ---: | --- |
| 정리 없음 | 157.0 GiB 합계 | 14.6 GiB | 171.6 GiB | 부족: 측정 시 여유 165.6 GiB 중 40 GiB 관문 전 사용 가능 125.6 GiB |
| 리비전별 정리 | 한 리비전 최대 48.8 GiB | 전체 14.6 GiB | 최대 약 63.4 GiB | 추정상 가능: 40 GiB 관문까지 약 62 GiB 여유 |

같은 산술의 요청 벽시계 합은 8,453초, 약 **2.35시간**이며 최초 전체 index·source 검증, 인스턴스 결합, 관문 대기와 후보별 편차는 제외했다. 별도 L-07의 141건 3,731초를 765건에 단순 비례시키면 약 **5.6시간**이다. 이 값도 대상과 캐시 재사용이 달라 예측이 아니다. 실제 실행 시간은 최소 수 시간으로 보고 충분히 긴 실행 창을 잡아야 한다. 시범 최대 RSS 3.40 GiB는 전체 765건의 메모리 상한을 뜻하지 않는다.

내장 디스크 전체 J에는 리비전별 정리를 권고한다. `--cleanup-cache-per-revision`은 각 리비전 완료 후 캐시 경로·크기·SHA-256을 기록하고 그 캐시만 지우며, 요청 결과와 인스턴스 저장소는 유지한다. 실행기 자체의 40 GiB 미만 관문도 그대로 적용한다. 두 시범의 캐시는 위 경로에 남겨 두고 전체 J용 캐시는 별도 내장 경로를 쓴다.

## A J 전체 터미널 명령 — 작성만, 미실행

[실행 입력 해시 목록](../runs/n6-j1-2026-10-09.noindex/j-execution-inputs.sha256)은 6/6 `shasum -c` 통과했다. 다음 한 줄은 내장 캐시를 쓰고 리비전별 정리를 켠 전체 J 명령이다. `mem20 B` 명령과 동시에 실행하지 않는다.

```sh
mkdir -p /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-j1-2026-10-09.noindex/cache-j-execute.noindex && shasum -a 256 -c /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-j1-2026-10-09.noindex/j-execution-inputs.sha256 && caffeinate -dimsu python3 /Users/miiz/Desktop/kwzzzz_zkfr/scripts/run_n6_j1.py --index /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-j1-2026-10-09.noindex/request-index.json --index-sha256 35ed44c86545fc3e56d3a671cbe45eae5db69c1d970f5e453c1db60e52225f3c --cache-root /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-j1-2026-10-09.noindex/cache-j-execute.noindex --cleanup-cache-per-revision --action execute --output /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-j1-2026-10-09.noindex/j-execute.noindex > /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-j1-2026-10-09.noindex/terminal-j.log 2>&1; rc=$?; printf 'log=%s exit_code=%s\n' /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-j1-2026-10-09.noindex/terminal-j.log "$rc"
```

전체 J는 지시대로 실행하지 않았다. 사용한 [v2 파일럿 실행기](../scripts/n6_j2_pilot.py)(SHA-256 `3ee6ada59fb6dc752567a99b963397d4bdee7ddf4b73282e9e4ca3013dbe2e46`)와 [직접 wait4 진입 파일](../scripts/n6_j2_pilot_wait4.py)(SHA-256 `a1f21e04d9093519bd07c8cfb9f2759d05760cc877da693d2a1437d6ea8723c0`)은 v1 실행기와 별도 파일이다. index 수준의 `base_input_unavailable`은 기록 후 다음 요청으로 가도록 작성됐으나 이번 선택된 6건에는 없었다. 엔진이 판정 중 기준 파일 부재를 반환하면 사전 해시 검증 뒤 입력 파일이 사라진 도구/입력 실패로 중단한다. 정상 종료했지만 W `sites_found=0`이면 값으로 기록하고 계속하도록 v1의 W 중단 조건을 제거했다. 실제 W 값은 1이었으므로 기존 전체 J 실행기의 W 관문과도 일치한다.
