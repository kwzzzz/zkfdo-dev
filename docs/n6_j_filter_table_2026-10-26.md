1번 결과: 문제 있음 — 자동 RQ-C 프로토콜 해시 불일치([별도 래퍼 검증 완료](n6_a_rqc_input_audit_2026-10-26.md)).

# J가 걸러 낸 고친 버전의 S 후보

기준 시각: 2026-10-26T09:58:28.084541+00:00. 후보 단위는 공식 main의 seed별 발견 기록이며 값은 열지 않았다. 중복 제거한 버그 수가 아니다. aq의 엄격·탐색 J 점수는 모두 대기로 유지한다.

대상은 동결 RQ-C 매핑에 있는 revision_kind=fixed의 6개 리비전과 banyan-fixed, 총 7개다 ([runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json](../runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json), [runs/n6-a1-2026-10-07/preparation-units.json](../runs/n6-a1-2026-10-07/preparation-units.json)). leave_one_out은 fixed가 아니므로 제외했다.

| 리비전 | 고친 버전 | 전체 제약 | S 후보 / 대응 가능 생성템플릿 후보 | 엄격 J: L1/배제/모름 | 탐색 v2.2: L1/배제/모름 | 탐색 v1: L1/배제/모름 | S만 거짓 경보 | S+J 거짓 경보: 엄격 / v2.2 / v1 |
|---|---|---:|---|---|---|---|---:|---|
| aq-006-1680f955c185 | 예 [M](#m) | 1,110,996 [C01](#c01) | 21 [F01](#f01) / 9 [M](#m) | 대기 | 대기 | 대기 | 21 [F01](#f01) | 대기 / 대기 / 대기 |
| aq-007-0bb83f9eab0f | 예 [M](#m) | 1,081,440 [C02](#c02) | 21 [F02](#f02) / 12 [M](#m) | 대기 | 대기 | 대기 | 21 [F02](#f02) | 대기 / 대기 / 대기 |
| aq-012-44d0df2ab46e | 예 [M](#m) | 276,422 [C03](#c03) | 24 [F03](#f03) / 15 [M](#m) | 대기 | 대기 | 대기 | 24 [F03](#f03) | 대기 / 대기 / 대기 |
| aq-025-70328d3fd35e | 예 [M](#m) | 55,066 [C04](#c04) | 27 [F04](#f04) / 3 [M](#m) | 대기 | 대기 | 대기 | 27 [F04](#f04) | 대기 / 대기 / 대기 |
| aq-035-8f826c822cb8 | 예 [M](#m) | 3,250 [C05](#c05) | 12 [F05](#f05) / 미확정 | 대기 | 대기 | 대기 | 12 [F05](#f05) | 대기 / 대기 / 대기 |
| aq-037-94fe3080fc18 | 예 [M](#m) | 1,667,456 [C06](#c06) | 6 [F06](#f06) / 미확정 | 대기 | 대기 | 대기 | 6 [F06](#f06) | 대기 / 대기 / 대기 |
| banyan-fixed | 예 [M](#m) | 47 [C07](#c07) | 24 [F07](#f07) / 매핑 없음 | —/—/—; 준비 실패 24 [J0](#j0) | 0/24/0 [J2](#j2) | 0/24/0 [J1](#j1) | 24 [F07](#f07) | 미판정 [J0](#j0) / 0 [J2](#j2) / 0 [J1](#j1) |

`대응 가능 생성템플릿 후보`는 고정된 source·template·parameter가 버그 위치 인스턴스 또는 그 하위와 대응 가능한 후보 수다. 한 템플릿이 여러 인스턴스에 쓰일 수 있으므로 실제 위반이 버그 위치에서 일어났다는 뜻은 아니다. 실제 버그 위치별 후보 수는 미확정으로 남긴다. aq-035는 pragma 수정 후 wrapper 바이트가 다르고, aq-037의 capture는 가벼운 분석의 128 MiB 입력 한도를 넘어서 대응 수를 확정하지 않았다 ([기존 위치 규칙](../scripts/n6_a_remeasure_aq_order_v2.py):146–200, 271–280; [이번 수집기](../scripts/n6_j_filter_table_20261026.py):155).

보수적 선택: ‘거짓 경보’는 요청대로 고친 대조군의 S 후보 수와 L1 요청 수를 비교하는 지표다. 고친 버전에 별개 버그가 없다는 독립 증명은 아니므로 실제 거짓 양성률로 일반화하지 않는다. 엄격 banyan은 준비 실패를 배제·모름이나 L1=0으로 바꾸지 않았다. 탐색층의 구성 입력 결과를 엄격층에 합치지 않았다.

## 원본 확인

banyan-fixed의 탐색층은 두 엔진 각각 S 후보 24개와 완료 요청 24개가 대응하고, 각각 L1 0·배제 24·모름 0이다 ([F07](#f07), [J2](#j2), [J1](#j1)). result SHA-256, request SHA-256, state/index 엔진 해시, join의 전체 결과 경로 집합을 다시 확인했다. 엄격층은 24개 전부 준비 실패다 ([J0](#j0)) ([영수증 확인 코드](../scripts/n6_j_filter_table_20261026.py):228; [판정 분류](../scripts/n6_a_size_cost_j_20261026.py):98–136).

aq 상태는 존재하는 지정 파일 3개의 수정 시각 중 최신을 골랐다(동률이면 높은 버전). 선택: [runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/state-v2.json](../runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/state-v2.json); 형식 `n6-a-remeasure-aq-execute-v2`; SHA-256 `b737ae431fb3b61a58fa7a55dace24b069386130b96e0c052ab4301d61d9cfbe`. 상태 형식·경로만 확인하고 요청 점수나 결과 파일은 읽지 않았다. 재실행해도 현재 요청의 점수 비공개 원칙을 유지한다 ([선택 코드](../scripts/n6_j_filter_table_20261026.py):106, [형식 확인](../scripts/n6_j_filter_table_20261026.py):125).

## 근거

<a id="m"></a> **M — 고친 버전·위치 매핑**: [runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json](../runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json); [runs/n6-a1-2026-10-07/preparation-units.json](../runs/n6-a1-2026-10-07/preparation-units.json); [docs/n6_targets_a_2026-10-07.json](../docs/n6_targets_a_2026-10-07.json)

<a id="f01"></a> **F01 — aq-006-1680f955c185 후보**: [runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-006-1680f955c185-seed-2026100601/runs/02-pressure_retry/S/campaign/ledger.json](../runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-006-1680f955c185-seed-2026100601/runs/02-pressure_retry/S/campaign/ledger.json); [runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-006-1680f955c185-seed-2026100602/runs/02-pressure_retry/S/campaign/ledger.json](../runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-006-1680f955c185-seed-2026100602/runs/02-pressure_retry/S/campaign/ledger.json); [runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-006-1680f955c185-seed-2026100603/runs/02-pressure_retry/S/campaign/ledger.json](../runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-006-1680f955c185-seed-2026100603/runs/02-pressure_retry/S/campaign/ledger.json)

<a id="c01"></a> **C01 — 제약 수**: [runs/n6-a1b-2026-10-08/preflight-v3/preflight/aq-006-1680f955c185-seed-2026100601/W/compile/0000/stdout.log](../runs/n6-a1b-2026-10-08/preflight-v3/preflight/aq-006-1680f955c185-seed-2026100601/W/compile/0000/stdout.log)

<a id="f02"></a> **F02 — aq-007-0bb83f9eab0f 후보**: [runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-007-0bb83f9eab0f-seed-2026100601/runs/02-pressure_retry/S/campaign/ledger.json](../runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-007-0bb83f9eab0f-seed-2026100601/runs/02-pressure_retry/S/campaign/ledger.json); [runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-007-0bb83f9eab0f-seed-2026100602/runs/02-pressure_retry/S/campaign/ledger.json](../runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-007-0bb83f9eab0f-seed-2026100602/runs/02-pressure_retry/S/campaign/ledger.json); [runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-007-0bb83f9eab0f-seed-2026100603/runs/02-pressure_retry/S/campaign/ledger.json](../runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-007-0bb83f9eab0f-seed-2026100603/runs/02-pressure_retry/S/campaign/ledger.json)

<a id="c02"></a> **C02 — 제약 수**: [runs/n6-a1b-2026-10-08/preflight-v3/preflight/aq-007-0bb83f9eab0f-seed-2026100601/W/compile/0000/stdout.log](../runs/n6-a1b-2026-10-08/preflight-v3/preflight/aq-007-0bb83f9eab0f-seed-2026100601/W/compile/0000/stdout.log)

<a id="f03"></a> **F03 — aq-012-44d0df2ab46e 후보**: [runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-012-44d0df2ab46e-seed-2026100601/runs/01-primary/S/campaign/ledger.json](../runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-012-44d0df2ab46e-seed-2026100601/runs/01-primary/S/campaign/ledger.json); [runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-012-44d0df2ab46e-seed-2026100602/runs/01-primary/S/campaign/ledger.json](../runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-012-44d0df2ab46e-seed-2026100602/runs/01-primary/S/campaign/ledger.json); [runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-012-44d0df2ab46e-seed-2026100603/runs/01-primary/S/campaign/ledger.json](../runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-012-44d0df2ab46e-seed-2026100603/runs/01-primary/S/campaign/ledger.json)

<a id="c03"></a> **C03 — 제약 수**: [runs/n6-a1b-2026-10-08/preflight-v3/preflight/aq-012-44d0df2ab46e-seed-2026100601/W/compile/0000/stdout.log](../runs/n6-a1b-2026-10-08/preflight-v3/preflight/aq-012-44d0df2ab46e-seed-2026100601/W/compile/0000/stdout.log)

<a id="f04"></a> **F04 — aq-025-70328d3fd35e 후보**: [runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-025-70328d3fd35e-seed-2026100601/runs/01-primary/S/campaign/ledger.json](../runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-025-70328d3fd35e-seed-2026100601/runs/01-primary/S/campaign/ledger.json); [runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-025-70328d3fd35e-seed-2026100602/runs/01-primary/S/campaign/ledger.json](../runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-025-70328d3fd35e-seed-2026100602/runs/01-primary/S/campaign/ledger.json); [runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-025-70328d3fd35e-seed-2026100603/runs/01-primary/S/campaign/ledger.json](../runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-025-70328d3fd35e-seed-2026100603/runs/01-primary/S/campaign/ledger.json)

<a id="c04"></a> **C04 — 제약 수**: [runs/n6-a1b-2026-10-08/preflight-v3/preflight/aq-025-70328d3fd35e-seed-2026100601/W/compile/0000/stdout.log](../runs/n6-a1b-2026-10-08/preflight-v3/preflight/aq-025-70328d3fd35e-seed-2026100601/W/compile/0000/stdout.log)

<a id="f05"></a> **F05 — aq-035-8f826c822cb8 후보**: [runs/n6-a3-2026-10-08.noindex/pragma-b-execute-2.noindex/units/aq-035-8f826c822cb8-seed-2026100601/runs/01-primary/S/campaign/ledger.json](../runs/n6-a3-2026-10-08.noindex/pragma-b-execute-2.noindex/units/aq-035-8f826c822cb8-seed-2026100601/runs/01-primary/S/campaign/ledger.json); [runs/n6-a3-2026-10-08.noindex/pragma-b-execute-2.noindex/units/aq-035-8f826c822cb8-seed-2026100602/runs/01-primary/S/campaign/ledger.json](../runs/n6-a3-2026-10-08.noindex/pragma-b-execute-2.noindex/units/aq-035-8f826c822cb8-seed-2026100602/runs/01-primary/S/campaign/ledger.json); [runs/n6-a3-2026-10-08.noindex/pragma-b-execute-2.noindex/units/aq-035-8f826c822cb8-seed-2026100603/runs/01-primary/S/campaign/ledger.json](../runs/n6-a3-2026-10-08.noindex/pragma-b-execute-2.noindex/units/aq-035-8f826c822cb8-seed-2026100603/runs/01-primary/S/campaign/ledger.json)

<a id="c05"></a> **C05 — 제약 수**: [runs/n6-a3-2026-10-08.noindex/pragma/preflight/aq-035-8f826c822cb8-seed-2026100601/W/compile/0000/stdout.log](../runs/n6-a3-2026-10-08.noindex/pragma/preflight/aq-035-8f826c822cb8-seed-2026100601/W/compile/0000/stdout.log); [runs/n6-a3-2026-10-08.noindex/pragma/preflight/aq-035-8f826c822cb8-seed-2026100602/W/compile/0000/stdout.log](../runs/n6-a3-2026-10-08.noindex/pragma/preflight/aq-035-8f826c822cb8-seed-2026100602/W/compile/0000/stdout.log); [runs/n6-a3-2026-10-08.noindex/pragma/preflight/aq-035-8f826c822cb8-seed-2026100603/W/compile/0000/stdout.log](../runs/n6-a3-2026-10-08.noindex/pragma/preflight/aq-035-8f826c822cb8-seed-2026100603/W/compile/0000/stdout.log)

<a id="f06"></a> **F06 — aq-037-94fe3080fc18 후보**: [runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-037-94fe3080fc18-seed-2026100601/runs/01-primary/S/campaign/ledger.json](../runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-037-94fe3080fc18-seed-2026100601/runs/01-primary/S/campaign/ledger.json); [runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-037-94fe3080fc18-seed-2026100602/runs/01-primary/S/campaign/ledger.json](../runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-037-94fe3080fc18-seed-2026100602/runs/01-primary/S/campaign/ledger.json); [runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-037-94fe3080fc18-seed-2026100603/runs/01-primary/S/campaign/ledger.json](../runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-037-94fe3080fc18-seed-2026100603/runs/01-primary/S/campaign/ledger.json)

<a id="c06"></a> **C06 — 제약 수**: [runs/n6-a1b-2026-10-08/preflight-v3/preflight/aq-037-94fe3080fc18-seed-2026100601/W/compile/0000/stdout.log](../runs/n6-a1b-2026-10-08/preflight-v3/preflight/aq-037-94fe3080fc18-seed-2026100601/W/compile/0000/stdout.log)

<a id="f07"></a> **F07 — banyan-fixed 후보**: [runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/banyan-fixed-seed-2026100601/runs/01-primary/S/campaign/ledger.json](../runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/banyan-fixed-seed-2026100601/runs/01-primary/S/campaign/ledger.json); [runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/banyan-fixed-seed-2026100602/runs/01-primary/S/campaign/ledger.json](../runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/banyan-fixed-seed-2026100602/runs/01-primary/S/campaign/ledger.json); [runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/banyan-fixed-seed-2026100603/runs/01-primary/S/campaign/ledger.json](../runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/banyan-fixed-seed-2026100603/runs/01-primary/S/campaign/ledger.json)

<a id="c07"></a> **C07 — 제약 수**: [runs/n6-a1b-2026-10-08/preflight-v3/preflight/banyan-fixed-seed-2026100601/W/compile/0000/stdout.log](../runs/n6-a1b-2026-10-08/preflight-v3/preflight/banyan-fixed-seed-2026100601/W/compile/0000/stdout.log)

<a id="j0"></a> **J0 — banyan-fixed**: [runs/n6-j1-2026-10-09.noindex/request-index.json](../runs/n6-j1-2026-10-09.noindex/request-index.json); [runs/n6-j1-2026-10-09.noindex/j-execute.noindex/state.json](../runs/n6-j1-2026-10-09.noindex/j-execute.noindex/state.json)

<a id="j2"></a> **J2 — banyan-fixed**: [runs/n6-a-remeasure-2026-10-25.noindex/prepared/request-index-v2.2.json](../runs/n6-a-remeasure-2026-10-25.noindex/prepared/request-index-v2.2.json); [runs/n6-a-remeasure-2026-10-25.noindex/j-v2.2/state.json](../runs/n6-a-remeasure-2026-10-25.noindex/j-v2.2/state.json); [runs/n6-a-remeasure-2026-10-25.noindex/aggregates/joins/v2.2-main-0002-7405b6ab638b269ce0c9165b549d14b21bbd0b2f1d693e9bd1a413c011c23d6f.json](../runs/n6-a-remeasure-2026-10-25.noindex/aggregates/joins/v2.2-main-0002-7405b6ab638b269ce0c9165b549d14b21bbd0b2f1d693e9bd1a413c011c23d6f.json); [runs/n6-a-remeasure-2026-10-25.noindex/aggregates/aggregate-0001.json](../runs/n6-a-remeasure-2026-10-25.noindex/aggregates/aggregate-0001.json)

<a id="j1"></a> **J1 — banyan-fixed**: [runs/n6-a-remeasure-2026-10-25.noindex/prepared/request-index-v1.json](../runs/n6-a-remeasure-2026-10-25.noindex/prepared/request-index-v1.json); [runs/n6-a-remeasure-2026-10-25.noindex/j-v1/state.json](../runs/n6-a-remeasure-2026-10-25.noindex/j-v1/state.json); [runs/n6-a-remeasure-2026-10-25.noindex/aggregates/joins/v1-main-0002-9ff5428f5261a5f098fd8b0de11670e83e892958f3ee4fdfc95f6cf4a680a91e.json](../runs/n6-a-remeasure-2026-10-25.noindex/aggregates/joins/v1-main-0002-9ff5428f5261a5f098fd8b0de11670e83e892958f3ee4fdfc95f6cf4a680a91e.json); [runs/n6-a-remeasure-2026-10-25.noindex/aggregates/aggregate-0001.json](../runs/n6-a-remeasure-2026-10-25.noindex/aggregates/aggregate-0001.json)

## 다시 실행

새 실행기·엔진을 돌리지 않는 읽기 전용 집계 명령이다. 기존 입력 경로는 모두 인자로 바꿀 수 있다.

```sh
nice -n 19 python3 -B /Users/miiz/Desktop/kwzzzz_zkfr/scripts/n6_j_filter_table_20261026.py --root /Users/miiz/Desktop/kwzzzz_zkfr --mapping runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json --main-queue runs/n6-a2b-2026-10-08.noindex/queue-a-v4.json --main-state runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/state.json --pragma-queue runs/n6-a3-2026-10-08.noindex/queue-a3b-pragma.json --pragma-state runs/n6-a3-2026-10-08.noindex/pragma-b-execute-2.noindex/state.json --size-reuse runs/n6-a2b-2026-10-08.noindex/preflight-reuse-a-v4.json --strict-index runs/n6-j1-2026-10-09.noindex/request-index.json --strict-state runs/n6-j1-2026-10-09.noindex/j-execute.noindex/state.json --banyan-index-v22 runs/n6-a-remeasure-2026-10-25.noindex/prepared/request-index-v2.2.json --banyan-state-v22 runs/n6-a-remeasure-2026-10-25.noindex/j-v2.2/state.json --banyan-index-v1 runs/n6-a-remeasure-2026-10-25.noindex/prepared/request-index-v1.json --banyan-state-v1 runs/n6-a-remeasure-2026-10-25.noindex/j-v1/state.json --banyan-joins runs/n6-a-remeasure-2026-10-25.noindex/aggregates/aggregate-0001.json --aq-state-dir runs/n6-a-remeasure-2026-10-25.noindex/aq-exec --aq-state auto --output /Users/miiz/Desktop/kwzzzz_zkfr/docs/n6_j_filter_table_2026-10-26.md --max-seconds 180
```

합성 검사(실제 상태·판정 입력을 열지 않음):

```sh
nice -n 19 python3 -B /Users/miiz/Desktop/kwzzzz_zkfr/scripts/n6_j_filter_table_20261026.py --self-test
```

## SHA-256

새 스크립트: `6e754cf2159a0572812182e11b9f718353c63f6c2c5dfdff7ebc08c4b6508be6`. 보고서 자체의 SHA-256은 재실행 시 표준 출력에 기록한다 (자기 해시를 본문에 포함하면 해시가 다시 달라지므로 본문에서 제외).

| 주요 입력 | SHA-256 |
|---|---|
| [runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json](../runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json) | `8ad5d43b51d5ceaab0d95dd83a229f45fdc2a2020485a21ccb3b1a43fb4aab85` |
| [runs/n6-a1-2026-10-07/preparation-units.json](../runs/n6-a1-2026-10-07/preparation-units.json) | `051f791f5a4f473f3afd3ae58b92fcb7bdcc112e8bb7b43066cbb59d22f903d9` |
| [docs/n6_targets_a_2026-10-07.json](../docs/n6_targets_a_2026-10-07.json) | `6410b49e50b4da6a565955f6b9a6fa3ed1cd996b7923d96710e28ddfa2cf6758` |
| [runs/n6-a2b-2026-10-08.noindex/queue-a-v4.json](../runs/n6-a2b-2026-10-08.noindex/queue-a-v4.json) | `2b9d7f1838048a3a776426fd26c38d47dd9363e030299e95519bb5602d612754` |
| [runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/state.json](../runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/state.json) | `864d714d32b6ce4201bd6ca8151531d6929570e880edbfcedb380b8ddb42e744` |
| [runs/n6-a3-2026-10-08.noindex/queue-a3b-pragma.json](../runs/n6-a3-2026-10-08.noindex/queue-a3b-pragma.json) | `c91e572aaa91582bd46d88b54e9e1bb9a5ce34509af286b65f41aaf22983fc4f` |
| [runs/n6-a3-2026-10-08.noindex/pragma-b-execute-2.noindex/state.json](../runs/n6-a3-2026-10-08.noindex/pragma-b-execute-2.noindex/state.json) | `feb98923232336f79684d5773c1c1b80d4f685b88b13a7ad5c6ee776d258dd32` |
| [runs/n6-j1-2026-10-09.noindex/request-index.json](../runs/n6-j1-2026-10-09.noindex/request-index.json) | `35ed44c86545fc3e56d3a671cbe45eae5db69c1d970f5e453c1db60e52225f3c` |
| [runs/n6-j1-2026-10-09.noindex/j-execute.noindex/state.json](../runs/n6-j1-2026-10-09.noindex/j-execute.noindex/state.json) | `6bfeb70743608235bbf9d7125f84c2aadf2fd8d9e95a461de8a9572411cb0e73` |
| [runs/n6-a-remeasure-2026-10-25.noindex/prepared/request-index-v2.2.json](../runs/n6-a-remeasure-2026-10-25.noindex/prepared/request-index-v2.2.json) | `e7290c40fa9404f743c734044263e9f911f6d26f0548cc0b9c9e0b97e114b690` |
| [runs/n6-a-remeasure-2026-10-25.noindex/j-v2.2/state.json](../runs/n6-a-remeasure-2026-10-25.noindex/j-v2.2/state.json) | `b93aa42a0e9f9224f172d4ee6a88530e80e0104d6a092df7d2437a92756e0247` |
| [runs/n6-a-remeasure-2026-10-25.noindex/prepared/request-index-v1.json](../runs/n6-a-remeasure-2026-10-25.noindex/prepared/request-index-v1.json) | `94faefbe435d779cbd84e212e78b27446ff992131efc1b399ba0f1a16c05a7da` |
| [runs/n6-a-remeasure-2026-10-25.noindex/j-v1/state.json](../runs/n6-a-remeasure-2026-10-25.noindex/j-v1/state.json) | `32a62c2d9dc572688c5e900d5598ae0bef030b334ed1f2291ba485fc5f9b0c2a` |
| [runs/n6-a-remeasure-2026-10-25.noindex/aggregates/aggregate-0001.json](../runs/n6-a-remeasure-2026-10-25.noindex/aggregates/aggregate-0001.json) | `82b91a1c525167667a7ec80dc6555839a5e7af7ca1acad14db81e0607066c683` |

읽은 입력 목록의 경로·해시 정렬 JSON SHA-256: `72136716c71d9ed2c30d97f65c30743497be1edcd972c3873eac356ca5b5fa33`.

## 확인한 것

- 고친 버전 범위, 세 seed의 S 후보, 기존 컴파일 stdout의 비선형+선형 제약 합을 원본에서 다시 셌다 ([M](#m), F01–F07, C01–C07).
- banyan-fixed의 탐색층 배제와 엄격층 준비 실패를 해시·경로 연결까지 확인했다 ([J0](#j0), [J2](#j2), [J1](#j1)).
- aq 상태 파일은 최신 수정 시각으로 자동 선택한다. aq 점수, 후보 값, 실행 중인 프로세스는 확인·변경하지 않았다.

## 추정한 것

- 고친 대조군의 후보를 거짓 경보로 보는 것은 이 표의 비교 정의이며 독립적인 무버그 증명은 아니다.
- 대응 가능한 생성템플릿 수로 실제 위반 위치를 확정하지 않았다. aq 판정 결과는 모두 대기다.
