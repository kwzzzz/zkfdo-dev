# 문제 있음 — 자동 RQ-C는 프로토콜 SHA 불일치로 실패; 현재 상태 경로 설계는 정상

담당 miiz. 2026-10-26, Python nice 19·내장 여유 15 GiB 관문으로 코드와 기존 메타데이터만 확인했다. aq 판정 점수는 기재하지 않는다.

## 코드와 입력 경로

- v2는 현재 메모리 상태를 복사·정규화한 새 스냅샷을 `--state`로 준다: `scripts/n6_a_remeasure_aq_execute_v2.py:782`·`:783`·`:785`·`:791`. 상태 저장 경로는 같은 파일 `:456`의 state-v2.json이다.
- v3도 현재 상태를 복사해 정규화한다: `scripts/n6_a_remeasure_aq_execute_v3.py:919`·`:920`·`:922`·`:928`. state-v3.json 저장은 `:409`–`:410`; 초기 v2 승계는 `:487`–`:507`이다. 이후 v3 결과가 빠지는 옛 상태 고정 구조는 아니다.
- 리비전/구간 종료 시 최신 완료 결과 join을 먼저 갱신한다: v2 `:874`→`:891`→`:838`, v3 `:1042`→`:1070`→`:991`. 두 호출은 `--index prepared-aq/request-index-{engine}.json --engine {engine} --layer exploratory`를 사용한다(v2 `:786`–`:792`, v3 `:923`–`:929`).
- 재채점기는 protocol 해시부터 검사한다(`scripts/n6_light_rqc_20261026.py:16`, `:138`). 예상 `ad6cf87b80223436db35d8a43c30659075fbc05423f1ade93f8fd8b830fad3e7`와 현재 문서 `18bc531d0c863515a2fc7abc6411187161dd5b98c9fe5e481863ba075afb2ddd`가 다르다. 원래 자동 호출도 같은 첫 관문에서 실패한다.
- raw v2/v3 상태는 원래 CLI가 직접 정규화하지 않는다(`scripts/n6_light_rqc_20261026.py:120`–`:133`). 자동 호출은 이 변환을 미리 하므로 경로 설계 자체는 정상이다. 외부 복사본의 join 상대 경로는 원래 상태 부모 기준 절대 경로로 보존했다(`:186`–`:188`, `:254`).

## 현재 v2 드라이런과 별도 래퍼

- 원래 함수·동일 인자 형식 드라이런: **실패**, protocol SHA mismatch. 기준 완료 요청 28, 결과 파일 읽기 0, 산출 반영 0. 근거 `/private/tmp/n6-a-rqc-input-dryrun-20261026-01/audit-receipt.json`.
- 새 래퍼: **성공**, 완료 요청 28 중 저장된 join이 덮는 16요청 반영, 아직 join이 없는 12요청 보류. 판정 점수는 쓰지 않는다. 근거 `/private/tmp/n6-a-rqc-compat-20261026/v2.2-20261026T093354.934009Z/audit-receipt.json`.
- 두 검사의 원본 상태: `/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/state-v2.json`, SHA-256 `b737ae431fb3b61a58fa7a55dace24b069386130b96e0c052ab4301d61d9cfbe`. snapshot 한 번 읽기로 실행 중 갱신과 분리했다.
- **보수적 선택:** 새 래퍼는 현재 문서 SHA와 원래 scorer 코드 SHA를 각각 고정하고, 이 새 프로세스에서만 protocol 버전 상수를 바꾼다. 분류 함수·map·engine 해시 검증은 그대로다. 저장된 join 없는 완료 요청은 보류하며 J나 새 join을 실행하지 않는다.
- 현재 L1·정답 대조 정의 근거: `docs/n5_evaluation_protocol_v1_2026-10-06.md:78`·`:81`·`:85`–`:89`·`:222`; 개정의 정의 불변은 `docs/n5_amendment_b_judging_2026-10-17.md:31`·`:99`·`:136`–`:138`. 과거 pin 사용 기록은 `docs/n6_light_tasks_2026-10-26.md:71`이다. 옛 원문 전체 바이트 사본이 없어 전체 변경 범위까지 같다고 주장하지 않는다.

## 리비전/구간이 끝날 때 사람이 재실행할 명령

세 알려진 상태 파일만 stat하여 수정시각이 가장 최신인 파일을 선택한다(동률이면 v3 우선). 같은 명령을 반복해도 매번 새 출력 폴더를 만든다. 완료 join이 없는 요청은 자동 보류한다. 현재 프로토콜이나 원래 scorer가 바뀌면 중단한다.

```sh
nice -n 19 python3 -B /Users/miiz/Desktop/kwzzzz_zkfr/scripts/n6_a_rqc_compat_20261026.py --state auto --engine v2.2 --output-root /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a-rqc-manual-20261026.noindex
nice -n 19 python3 -B /Users/miiz/Desktop/kwzzzz_zkfr/scripts/n6_a_rqc_compat_20261026.py --state auto --engine v1 --output-root /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a-rqc-manual-20261026.noindex
```

원래 경로의 실패를 다시 확인하는 명령(새 임시 폴더 필요):

```sh
nice -n 19 python3 -B /Users/miiz/Desktop/kwzzzz_zkfr/scripts/n6_a_rqc_input_audit_20261026.py --state /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/state-v2.json --engine v2.2 --out-dir /private/tmp/n6-a-rqc-input-dryrun-20261026-02
```

## 읽은 입력 경로와 SHA-256

| 경로 | SHA-256 |
|---|---|
| `/Users/miiz/Desktop/kwzzzz_zkfr/docs/n5_evaluation_protocol_v1_2026-10-06.md` | `18bc531d0c863515a2fc7abc6411187161dd5b98c9fe5e481863ba075afb2ddd` |
| `/Users/miiz/Desktop/kwzzzz_zkfr/docs/n6_targets_a_2026-10-07.json` | `6410b49e50b4da6a565955f6b9a6fa3ed1cd996b7923d96710e28ddfa2cf6758` |
| `/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/aggregates/joins/v2.2/main/0009/join-0001.json` | `4515bf59c6148b36be03af979df224bce53a7b06fe9815db194b2c60429c978e` |
| `/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/state-v2.json` | `b737ae431fb3b61a58fa7a55dace24b069386130b96e0c052ab4301d61d9cfbe` |
| `/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/v2.2/requests/002169/attempt-0001.result.json` | `4d24a846214e3440a9673760bb63a0bd4c956b9c7b6770e620638097d1d1e8d7` |
| `/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/v2.2/requests/002170/attempt-0001.result.json` | `079f99e9a5bd6232f341a5daf9b9ac0067fdea6677692aa97a21d1a32a7c0bba` |
| `/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/v2.2/requests/002171/attempt-0001.result.json` | `90c2263c4c7c7d0774edd76aff9a2e9df2b549d7939f66473b80f728c728238c` |
| `/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/v2.2/requests/002172/attempt-0001.result.json` | `636163ef9e48abc0771dfeedbeb6c09d08b89c1f4fa47d72580758c82a581e04` |
| `/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/v2.2/requests/002173/attempt-0001.result.json` | `abf82ff5f9c3ec1c23ec423e33d7cd9e5369f11459a2740576980fb4ff4ee746` |
| `/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/v2.2/requests/002174/attempt-0001.result.json` | `dcddacf46f1c2b5cec53d7f14e1bd41a13dcdd2fdb1aed0005d56555778735a4` |
| `/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/v2.2/requests/002175/attempt-0001.result.json` | `6b9e61b01238741539bf03eab990b05851bbae1ad4ad7dfcd86fef309d8686e9` |
| `/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/v2.2/requests/002176/attempt-0001.result.json` | `3d4eba2ebcf92a8d2713111f8cc125082b4cfc4eb1a7c5a7f8107a53fef0d482` |
| `/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/v2.2/requests/002177/attempt-0001.result.json` | `1fa60d8c428b548c9781047d6c813d8409ae3486995f0d96ce5821692de31661` |
| `/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/v2.2/requests/002178/attempt-0001.result.json` | `b463b0fc035899bcedd419fc07f85de425f21ffd8cb746389fb5d7fec92baf04` |
| `/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/v2.2/requests/002179/attempt-0001.result.json` | `5d113e57bc348019d74c6fdfe0949b76e97158691ac6b035c3923b3f65d4bdea` |
| `/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/v2.2/requests/002180/attempt-0001.result.json` | `d2bc6a1ba0cc729f68265618acbdd792a24ddc8895957f580bf730b9da6562d2` |
| `/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/v2.2/requests/002181/attempt-0001.result.json` | `2c8da2aac9ee94ad008af13d29c454b9b084edafbb22b34e6872b830ba86d97b` |
| `/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/v2.2/requests/002182/attempt-0001.result.json` | `093f9af7897cf9fa7209c745b1d25b4f400ea64b0cdb4f6a3ecde88f1c3d7658` |
| `/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/v2.2/requests/002183/attempt-0001.result.json` | `97c9edfef40128762017d6f093286a68bf635de95030ae2bfe3e4ceee6f621d7` |
| `/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/v2.2/requests/002184/attempt-0001.result.json` | `ce8591f3428c77c0e935e8508879848bf53696a34451fad5e304ebed440d9774` |
| `/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a-remeasure-2026-10-25.noindex/prepared-aq/request-index-v2.2.json` | `1d0ea66aa677ad319dea34034af771fddc6fe19a57dddf2360f0ddb5aabc6f72` |
| `/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a1-2026-10-07/preparation-units.json` | `051f791f5a4f473f3afd3ae58b92fcb7bdcc112e8bb7b43066cbb59d22f903d9` |
| `/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json` | `8ad5d43b51d5ceaab0d95dd83a229f45fdc2a2020485a21ccb3b1a43fb4aab85` |
| `/private/tmp/n6-a-rqc-compat-20261026/v2.2-20261026T093354.934009Z/join-0000.json` | `f86950f0272b860967404ff41e4aa2051cec35106026beb003d19b7ca61c5b74` |
| `/private/tmp/n6-a-rqc-compat-20261026/v2.2-20261026T093354.934009Z/normalized-state.json` | `c1263ae7dfa2ad5e3f435f00769d66fe62d1031b111563da33622d281d44e8e5` |

## 새 파일 SHA-256

보고서 자기 해시는 최종 응답에 기록한다. 임시 score.json은 저장만 했고 점수는 이 보고서에 옮기지 않았다.

| 파일 | SHA-256 |
|---|---|
| `/Users/miiz/Desktop/kwzzzz_zkfr/scripts/n6_a_rqc_input_audit_20261026.py` | `3bea1a118a186f516b7b651737d44cf06fb05b1347fc22af86c400c199b0c720` |
| `/Users/miiz/Desktop/kwzzzz_zkfr/scripts/n6_a_rqc_compat_20261026.py` | `3e79db1541d0c5de703335f4773283017dd15dba5ee5d9e163aa8bf5cb790af3` |
| `/private/tmp/n6-a-rqc-input-dryrun-20261026-01/audit-receipt.json` | `f88ac0abf96754f614cac70087fc12ca32ad9c9fa8043e4d1a76b094270103e4` |
| `/private/tmp/n6-a-rqc-input-dryrun-20261026-01/join-0000.json` | `f86950f0272b860967404ff41e4aa2051cec35106026beb003d19b7ca61c5b74` |
| `/private/tmp/n6-a-rqc-input-dryrun-20261026-01/normalized-state.json` | `aace4e84ea24284d15b4246eb80b36319257d59f8d28a29ef502cfcbfae078a9` |
| `/private/tmp/n6-a-rqc-compat-20261026/v2.2-20261026T093354.934009Z/audit-receipt.json` | `d88e050325324c2a01bd070e1715a905c15056a56e9f6016a96ff516168209fb` |
| `/private/tmp/n6-a-rqc-compat-20261026/v2.2-20261026T093354.934009Z/join-0000.json` | `f86950f0272b860967404ff41e4aa2051cec35106026beb003d19b7ca61c5b74` |
| `/private/tmp/n6-a-rqc-compat-20261026/v2.2-20261026T093354.934009Z/normalized-state.json` | `c1263ae7dfa2ad5e3f435f00769d66fe62d1031b111563da33622d281d44e8e5` |
| `/private/tmp/n6-a-rqc-compat-20261026/v2.2-20261026T093354.934009Z/score.json` | `374edcffb7a1c6b28efc53fa6939b75afdfe2f2ee9aba1d0a56fdda744aaf3ce` |
| `/Users/miiz/Desktop/kwzzzz_zkfr/scripts/n6_light_followup_checks_20261026.py` | `d48c2f8882ced48dadb02aa023b54946199ead64b185dc65cc89c7c5e30b8ea9` |

합성 검증: 상태 선택·v2/v3 정규화·미조인 요청 보류·경로 및 해시 관문 15개 통과. 재실행: `nice -n 19 python3 -B /Users/miiz/Desktop/kwzzzz_zkfr/scripts/n6_light_followup_checks_20261026.py`.

## 확인한 것

- 현재 상태→정규화 스냅샷→요청 result/join 경로와 protocol hash 실패를 확인했다. 새 래퍼는 저장된 join 범위에서 실행에 성공했다.
- 원래 실행기·재채점기·전환 스크립트·aq-exec 파일은 변경하지 않았다. J·퍼징·Rust는 실행하지 않았다.

## 추정한 것

- 중간 상태에서 보류한 요청은 향후 join 저장 뒤 포함될 것으로 예상한다. 그 시각이나 최종 점수는 추정하지 않는다.
- 옛 프로토콜 전체 바이트의 변경 내역은 확인하지 못했다. 현재 정의와 새 pin만 명시적으로 대조했다.
