`cd /Users/miiz/Desktop/kwzzzz_zkfr && caffeinate -dimsu python3 scripts/n6_b6h_pair_runner.py --action execute-pairs --v1-index-sha256 08421ec900fedbce6f4e55b7fcba64df1c48886030fb094a50b3719e13101f1c --v2-2-index-sha256 2b1825ca2cce94cd08967a5bf16e5a56f9d045c6435a9b03d8625f52af505f39 --v1-static-preflight-sha256 eb8241575399399ad46125452ff41bc21949d53df5bc8c5a93cf22ff5b6368cd --v2-2-static-preflight-sha256 88c4a92bd627e138d2d77699e6a879e9f5a73729b3a241b6fafff89f966433d5 --first-lead-review-sha256 9de9eb4aaf1626eb9c14bb0437d1b43e3478f983396910623d0df3805a68193e --second-lead-review-sha256 4bc7f83da1f70c3ab523a38e56ef501f89508ba22e8dab674843d3995a9f60d6 --observed-request-peak-bytes 300647710720 --no-new-request-after 2026-10-29T14:59:00Z --order-sha256 65e8fb9de41f171d96b40917e2c23d4d9ad690f00aefa3a83a23439081c9f8f8`
`cd /Users/miiz/Desktop/kwzzzz_zkfr && caffeinate -dimsu python3 scripts/n6_b6h_result_gate.py --v1-index-sha256 08421ec900fedbce6f4e55b7fcba64df1c48886030fb094a50b3719e13101f1c --v2-2-index-sha256 2b1825ca2cce94cd08967a5bf16e5a56f9d045c6435a9b03d8625f52af505f39 --order-sha256 65e8fb9de41f171d96b40917e2c23d4d9ad690f00aefa3a83a23439081c9f8f8 --no-new-request-after 2026-10-29T14:59:00Z --output /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-b6h-2026-10-24.noindex/deadline-result-gate-v1.json`

# B6h 디스크 정리와 쌍 순서 재개 (2026-10-24)

위 두 줄은 miiz가 키티에서 각각 실행할 명령이다. 첫 줄은 같은 B6g 결과·state 경로를 이어 쓰고, 준비된 순서 SHA를 매번 확인한다. 공간 관문에 걸리면 종료 코드 3과 `stop_kind=space`를 기록한다. 둘째 줄은 실행이 `space` 또는 마감 `time`으로 멈춘 뒤, 혹은 모두 끝난 뒤 한 번만 실행한다. 이 문서를 작성하는 동안 B J와 B 결과 관문은 실행하지 않았다.

## 지시와 읽은 자료

- 원지시: `runs/handoff/n6_b6h_instruction_2026-10-24.md`, SHA-256 `71bc863629b90308823d20f619131eba9cf058e2d22da664c30ff00ac0e9c527`.
- 최종 추가 지시 전문: `runs/handoff/n6_b6h_followup_2026-10-24.md`, SHA-256 `6fe2931519c130e53b67dfaa8f8b01f571108d129b6f9ba6940b6656a16138b7`.
- 상속 규칙: `runs/handoff/n6_b6g_instruction_2026-10-23.md` 0절. N5 개정·프로토콜과 B6g 보고서, `scripts/n6_b6g_j_runner.py`, `scripts/n6_b6g_runtime_paths.py`, `scripts/n6_b6g_result_gate.py`, `scripts/run_n6_j1.py`, `src/candidate_review/lifting/{mod,predicate,instances}.rs`, 두 엔진의 고정 `predicate.rs`를 읽었다.
- B의 경우 고정된 v2.2 `state.json`에서는 최상위 status와 요청 번호·status·완료 수만, 39번 `attempt-0001.metrics.json`에서는 종료 코드·시간·RSS만 확인했다. stdout과 결과의 판정 필드, 후보·witness·작업 폴더·캐시·인스턴스 저장소의 내용은 열지 않았다. SSD 자료는 `du`와 파일 경로 목록의 SHA-256으로만 조사했다. `runs/n6-b6h-2026-10-24.noindex/precleanup-inventory.json` 및 아래 기록을 읽었고, `runs/` 전체 검색은 하지 않았다.

## 39번 원인과 공간 사용

- B6g의 40 GiB 검사는 매 요청 시작 전 한 번만 한다(`scripts/n6_b6g_j_runner.py:645-660`). 이후 엔진이 한 요청 안에서 SSD의 작업 폴더와 캐시를 계속 쓰며 감시는 없다. B6g는 결과 복사 후에도 외장 raw를 남겼다(`scripts/n6_b6g_runtime_paths.py:49-71`). 엔진은 `raw/hint-workspace`에 소스 사본을 만들고(`src/candidate_review/lifting/mod.rs:811-845,3851-3876`), 캐시의 key별 디렉터리 끝에 `complete`를 쓴다(`:3677-3707,3739-3769`). 전체 캐시 디렉터리의 원자적 교체는 아니다. 미완성 key는 다음 접근 시 지우고 다시 만든다.
- 39번 `attempt-0001` 종료 코드는 1, stderr 크기는 0 B, result는 없고 state는 `engine_failed`, `next_queue_order=39`다. 종료 기록은 2026-10-24 06:46:07 KST, 벽시계 19,582초(5시간 26분 22초), max RSS 기록 없음. stdout은 열지 않았다. 시스템 로그에서 종료 전후 06:40–06:48 KST의 ENOSPC 문구를 찾지 못했다. 당시 SSD 여유 관측치는 약 266 MiB였으나 종료 순간의 동시 계측은 없다. 따라서 **디스크 고갈로 추정**하며 엔진 오류 문구까지 확정하지 않는다.
- 39번 반쯤 쓴 작업 폴더는 103.509 GiB/389,835파일, 39번 시작 뒤 생성된 캐시 조각은 176.293 GiB/656경로였다. 합계 279.802 GiB를 올림한 **280 GiB(300,647,710,720 B)**를 관문 기준으로 고정했다. 남은 rev5 캐시는 32.959 GiB다. 38번 작업 폴더는 20.104 GiB, 처리 시간은 74분이다. 앞 네 리비전 37건은 약 1시간이었다.
- 재시작 시 39번의 내부 metrics/log는 보존한다. 외장 반쪽 폴더와 해당 시도의 캐시 조각만 사전 기록 후 삭제했고 result는 원래 없었다. 새 실행기는 기존 attempt 번호를 검사해 새 번호로 처음부터 수행한다(`scripts/n6_b6h_j_runner.py:527-541`).

| 리비전 | 요청 범위 | 요청 작업 폴더 합계 | 캐시·저장소 | 관측 |
|---|---:|---:|---:|---|
| 1 Vota | 0–8 | 0.001 GiB 미만 | 0.001 GiB 미만 | 준비 실패 다수 |
| 2 iden3 | 9–12 | 2.458 GiB | 35.191 GiB + 저장소 20 KiB | 리비전 캐시 재사용 |
| 3 panther | 13–24 | 0.983 GiB | 2.316 GiB | 리비전 캐시 재사용 |
| 4 anon-aadhaar | 25–36 | 3.679 GiB | 2.467 GiB | 리비전 캐시 재사용 |
| 5 rarimo | 37–39 | 123.613 GiB | 요청39 이전 32.959 GiB + 이후 176.293 GiB | 37·38 완료, 39 미완료 |

아래 수치는 정리 전 `du` 기준이며 원시 내용은 읽지 않았다. 파일별 숫자와 목록 해시는 사전 목록에 남겼다.

| 요청 번호 | 작업 폴더 GiB | 요청 번호 | 작업 폴더 GiB | 요청 번호 | 작업 폴더 GiB | 요청 번호 | 작업 폴더 GiB |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | <0.001 | 1 | <0.001 | 2 | <0.001 | 3 | <0.001 |
| 4 | <0.001 | 5 | <0.001 | 6 | <0.001 | 7 | <0.001 |
| 8 | <0.001 | 9 | 1.888 | 10 | 0.570 | 11 | <0.001 |
| 12 | <0.001 | 13 | 0.166 | 14 | 0.063 | 15 | 0.064 |
| 16 | 0.034 | 17 | 0.167 | 18 | 0.063 | 19 | 0.064 |
| 20 | 0.034 | 21 | 0.167 | 22 | 0.063 | 23 | 0.064 |
| 24 | 0.034 | 25 | 0.577 | 26 | <0.001 | 27 | 0.359 |
| 28 | 0.291 | 29 | 0.577 | 30 | <0.001 | 31 | 0.359 |
| 32 | 0.291 | 33 | 0.577 | 34 | <0.001 | 35 | 0.359 |
| 36 | 0.291 | 37 | <0.001 | 38 | 20.104 | 39 | 103.509 |

## 원칙에 따른 결정과 실행기 수정

- 결과 관문은 내부 `state.json`, 결과와 join만 읽고 외장 작업 폴더·캐시·저장소를 다시 읽지 않는다(`scripts/n6_b6g_result_gate.py:24-54,69-179,208-234`; `src/candidate_review/lifting/instances.rs:70-78,88-136,173-192`). A 실행기는 join 뒤 리비전 캐시를 정리한다(`scripts/run_n6_j1.py:692-699`). 그 조건에 맞춰 완결 리비전의 증거·캐시·저장소를 결과·SHA·join을 기록한 뒤 정리한다(`scripts/n6_b6h_j_runner.py:628-677`).
- 그러나 고정 v2.2 엔진은 이전 요청의 저장소를 읽으면서 기록된 **원래 절대 증거 경로를 재해시**한다(`src/candidate_review/lifting/predicate.rs:370-385,685-704,763-803`). 증거 파일은 `input.json`, `honest.wtns`, `class-o0.wtns`, `found-input.json`, `found.wtns`, `exclusion-{0,1}.smt2`, `exclusion-{0,1}.z3.log`다(`predicate.rs:763-787`, `mod.rs:1979-1999`). 이 이름과 경로 패턴은 원래 위치에 보존하고 나머지 파일만 요청별로 정리한다(`scripts/n6_b6h_cleanup.py:140-149,169-245`). 보존량은 다음 요청의 공간 관문에 누적한다(`scripts/n6_b6h_j_runner.py:560-575`). v1 고정 소스(`cb40e3e06c27bfed2dcb19245f5d6b82d1860404:src/candidate_review/lifting/predicate.rs:96-111,576-590`)에는 `evidence_files`가 없고 저장소 JSON의 key·instance만 확인하므로 요청별 전량 정리한다.
- 처음 A 진단에서 폴더를 통째로 지우자 두 번째 같은 리비전 요청의 상위 판정은 같았지만 공유 사유가 달라졌다. 원래 `instance_verdict_shared`였던 요청이 `predicate_cone_unsat`로 처리됐다. 그 후 선택 보존으로 고쳐 최종 A 스모크를 다시 했다. 이는 판정 경로를 바꿀 수 있는 파일을 남긴 결정이다.
- SSD 관문은 매 신규 요청 전에 `max(40 GiB, 2×(280 GiB + 이전 요청의 보존 증거 + 다른 엔진의 캐시 증가분 177 GiB))`, 내장 관문은 20 GiB다(`scripts/n6_b6h_cleanup.py:36-67`). 선행 v1 단독 요청에는 상대 엔진 증가분을 더하지 않고, 쌍 단계에는 더한다(`scripts/n6_b6h_j_runner.py:856-868`). 177 GiB는 v2.2의 39번 캐시 증가 176.293 GiB를 올림한 다른 엔진 대리치다. 아직 B v1 rarimo 실측은 없으므로 보수적인 추정이라고 기록한다. 요청 중 공간 사용량의 엄밀한 상한은 엔진에 없으므로 이 관문은 실측 최대의 2배 안전 여유다.
- 쌍 명령의 내부 `execute-one` 호출은 `--cache-root`, `--workspace-root`, `--instance-root`를 모두 `/Volumes/zkfdo-jcache/n6-b6g-batch1x/` 아래로 명시하고, `--output`은 기존 `runs/n6-b6g-2026-10-23.noindex/full-{engine}.noindex`를 가리킨다(`scripts/n6_b6h_pair_runner.py:272-301`, `scripts/n6_b6h_j_runner.py:742-754`).
- 새 쌍 실행기는 B state의 번호·상태만 투영하고, v2.2에서 이미 끝난 39건을 v1로 먼저 처리한다. 나머지 68건은 요청 ID 정렬 뒤 `random.Random(20261024).shuffle`하여 각 요청마다 v2.2→v1로 수행한다(`scripts/n6_b6h_pair_runner.py:68-112,119-151,331-360`). `runs/n6-b6h-2026-10-24.noindex/pair-order-v1.json`을 실행 전에 단 한 번 기록했고 SHA-256은 `65e8fb9de41f171d96b40917e2c23d4d9ad690f00aefa3a83a23439081c9f8f8`다. 총 175개 엔진·요청 작업이며 재시작마다 파일 SHA와 seed 재계산을 확인한다(`:207-231`). 마감 `2026-10-29T14:59:00Z` 이후 새 요청은 시작하지 않고 진행 중 요청은 끝낸다. 끝난 (엔진, 요청)은 재실행하지 않는다. 재시작 직전 `reconcile-cleanup`으로 결과 기록과 삭제 사이의 중단을 복구하고, join 직후 중단도 이미 끝난 요청의 replay만으로 복구한다(`scripts/n6_b6h_j_runner.py:680-740`, `scripts/n6_b6h_pair_runner.py:304-328,363-425`).
- 새 마감 관문은 엔진별 완료·미완료(시간/공간) 수를 분리하고, 두 엔진 모두 완료한 요청 중 판정 가능한 쌍에 한해 고정 엔진 `lift-instances`로 유효 인스턴스 판정을 합쳐 (가)(나)(다)를 센다(`scripts/n6_b6h_result_gate.py:49-62,95-122,152-193,225-296`). 미완료·준비 실패를 unknown 또는 음성 판정에 넣지 않는다. B에 관문은 실행하지 않았다.
- 엔진 코드·바이너리, 판정 규칙·사유 분류·5건 중단·환경 사유 즉시 중단은 수정하지 않았다. shuffle은 인스턴스 저장소의 최초 증명 요청을 바꿀 수 있어 `shared_from` 같은 순서 의존 메타데이터가 기존 index 순차 실행과 달라질 가능성이 있다(`predicate.rs:370-385`). 이는 miiz가 명시한 쌍 순서에 따른 결과이며, 두 엔진에 동일하게 고정한 seed·순서 파일을 적용한다.

## 승인된 정리 기록과 삭제

사전 목록: `runs/n6-b6h-2026-10-24.noindex/precleanup-inventory.json` (SHA-256 `a05e514967324846df0c826faac72b068da4d489bf10c34f85f05d99ed02bb25`), 835항목. 파일 목록 SHA는 내용이 아닌 상대 파일 경로를 정렬하여 NUL로 구분한 SHA-256이다. 허용 목록 `approved-targets.json` SHA `d6bfbd9f1b3600935288725a9f68f04fdb2c3548674b6b37f84f6deb203161d5`, 실제 중첩 저장소 보정 목록 `approved-targets-store-correction.json` SHA `9505e559e46bdba9e087c95468fd42a4a2a7da2cd743b4732f70c1947397deb9`. 각 대상은 삭제 전에 `runs/n6-b6h-2026-10-24.noindex/cleanup-records/<종류>/<id>.json`, 삭제 후 `<id>-deleted.json`으로 크기·파일 수·목록 SHA를 남겼다. 정확한 개별 경로는 그 기록과 `cleanup-cache39-batch.jsonl`(656개), `cleanup-completed-and-legacy-batch.jsonl`(46개)에 있다.

| 대상 | 개수 | 정리 전 `du` GiB | 범위 |
|---|---:|---:|---|
| 39번 미완성 작업 폴더 | 1 | 103.509 | `.../main/0005/requests/000039` |
| 39번 뒤 생성된 캐시 조각 | 656 | 176.293 | `.../cache/full-v2.2/main/0005/{키,edits/키}` |
| 이미 완료된 요청 작업 폴더 | 39 | 27.224 | rev1–4의 37건, rarimo 37·38 |
| 완료된 리비전 캐시·저장소 | 4+1 | 39.974 | rev1–4 캐시, rev2의 실제 `store` |
| B5–B6f 시범 캐시·작업 폴더 | 4+3 | 62.680 | 아래 7개 경로 |
| **합계** | **708개 경로** | **409.681 GiB** | 원본 B6g 결과·state·로그 보존 |

시범 7개 경로는 `/Volumes/zkfdo-jcache/n6-b6f-batch1x/{cache,hint-workspaces}`, `/Volumes/zkfdo-jcache/n6-b6e-batch1x/{cache,hint-workspaces}`, `/Volumes/zkfdo-jcache/n6-b6b-batch1x/{cache,hint-workspaces}`, `/Volumes/zkfdo-jcache/n6-b6-batch1x/pilot-v2.2`다. 각각의 크기·파일 수·목록 SHA는 사전 목록과 삭제 완료 기록에 있다. A calibration `n6-b6-acal`, 구성 기준 입력, B6g 스모크와 `runs/` 결과는 삭제하지 않았다. APFS 공유 블록 때문에 실제 SSD 여유 증가는 약 292 GiB로 `du` 합계보다 작다.

## 내장 디스크와 SSD 이미지

- B6g 내부 결과 출력은 약 3.1 MiB였고 state/result만 내장에 둔다. 외장 경로 라우팅은 `scripts/n6_b6g_runtime_paths.py:49-52,55-71,74-82,104-117`에 있다. 작업 당시 내장 여유는 약 28.8–32 GiB로 20 GiB 스왑 여유 관문보다 크며, B가 내장에 수십 GiB를 쓰는 근거는 없었다.
- 조사 순서: 홈 폴더에서 `~/Library` 166.3 GiB(CloudDocs 84.8, Containers 38.1, Application Support 31.4, Caches 10.8), Downloads 13.9, `~/.cache` 3.9, `~/.codex` 1.8 GiB. repo cargo target 10.47 GiB와 `~/.cargo` 0.21 GiB. Docker.raw 컨테이너 26.8 GiB이나 수정 시각은 B6g 이전. APFS 로컬 스냅샷 없음. `/private/var/vm`은 오래된 sleepimage 약 2 GiB, 활성 swap 없음. `/private/tmp`은 miiz가 약 20 GB CTF 검수 폴더를 X9 Pro로 옮겨 지운 뒤 약 43.6 MiB. 확인된 감소분은 이 약 20 GB이고, 나머지 약 40 GiB의 시간별 원인은 현재 메타데이터만으로 확정하지 못했다. 내장 파일은 삭제하지 않았다.
- SSD 이미지는 500 GiB에서 `hdiutil resize -size 1000g`로 정확히 1000 GiB(약 1.0 TiB)로 확대됐다. X9 Pro는 내내 마운트했고 이미지 장치만 안전하게 detach/attach했다. 확대 직후 500.519 GiB 여유, 승인된 정리와 A 스모크 종료 뒤 2026-10-24 15:11 KST `df`에서 약 793.0 GiB 여유였다. X9 Pro 여유는 약 1.30 TiB다. 이미지는 승인 상한에 도달했으므로 더 키우지 않는다.
- 아직 v2.2에 68건, v1에 107건, 합계 175개 엔진 요청이 남아 있다. rarimo 68건은 v2.2에서 38번 74분·39번 5시간 26분을 보였으므로 요청당 1시간만 잡아도 두 엔진 136시간 이상이며, 마감까지 현재 약 129시간에서 선행 v1 39건 시간은 별도다. 39번의 실측 작업 폴더+캐시 증가 280 GiB, 쌍 단계의 상대 엔진 캐시 대리치 177 GiB를 더한 관문은 증거 보존량 0이어도 **914 GiB**다. 현재 여유 약 793 GiB보다 약 121 GiB 커서, 다른 승인된 공간 변화가 없다면 선행 v1 완료 뒤 첫 shuffle 요청은 시작 전에 `미완료(공간)`으로 멈출 것으로 예상한다. 1 TiB 이미지 상한과 삭제 승인 범위 안에서 엔진·판정 방식을 바꾸어 우회하지 않는다. 보존 증거 파일은 A 실측 36 KiB/첫 요청이며 B의 향후 요청별 크기는 실행 뒤 기록된다.

## A 실제 엔진 스모크와 검사

A 요청 97·102(같은 리비전), 115(다른 리비전)을 두 엔진에서 각각 실제로 실행했다. `/Volumes/zkfdo-jcache/n6-b6h-smoke-final/validate-only.json`(SHA-256 `83930546bc847cc27a483698f56545e6731eedf3cd1fe785dc194571e921fd54`)은 v2.2/v1 각 3/3 valid다. 두 엔진의 최종 state는 3/3 completed, 리비전 join 2/2, 요청 정리와 캐시·저장소 정리 완료다. v2.2 요청 97은 두 증거 파일 36,864 B를 리비전 끝까지 같은 절대 경로에 남겼고, 뒤이은 102의 `instance_verdict_shared/shared_from=97`이 기존 A 결과와 같았다. 115에서는 기존 A의 repair `tool_or_unsupported`가 유지됐다. 두 엔진의 상위 분류, 클래스 판정·사유, 제한 사유 모두 기존 A와 6/6 일치했다.

| 엔진 | 원래 A 요청 | 새 순서 | 상태 | 마지막 성공 시도 시간 | 시도 번호 | 기존 A 대조 |
|---|---:|---:|---|---:|---:|---|
| v2.2 | 97 | 0 | completed | 11.117초 | 1 | 판정·사유 일치 |
| v2.2 | 102 | 1 | completed | 3.173초 | 2 | 판정·공유 사유 일치 |
| v2.2 | 115 | 2 | completed | 71.811초 | 1 | 판정·repair 사유 일치 |
| v1 | 97 | 0 | completed | 10.595초 | 1 | 판정·사유 일치 |
| v1 | 102 | 1 | completed | 2.350초 | 1 | 판정·공유 사유 일치 |
| v1 | 115 | 2 | completed | 46.238초 | 1 | 판정·repair 사유 일치 |

A 순서 파일은 prefix `[0]`, seed 20261024의 나머지 `[1,2]`이고 SHA-256 `64ffd09162b53c97843e08d0897249ca4cedf06b36f5fd7d2fbf1d116322c070`이다. 명령 9줄 전체는 SSD의 `/Volumes/zkfdo-jcache/n6-b6h-smoke-final/commands.txt`(SHA-256 `815b65ca0872f078bd57f3457ebc00873ba06ac47579832e53de026ce1615613`)에 그대로 저장했다. 다음은 실제 실행한 문자열이다.

```text
v2.2 validate-only: cd /Users/miiz/Desktop/kwzzzz_zkfr && PYTHONDONTWRITEBYTECODE=1 caffeinate -dimsu python3 scripts/n6_b6h_smoke_a_runner.py --engine v2.2 --index /Volumes/zkfdo-jcache/n6-b6h-smoke-final/fixtures-97-102-115/request-index-v2.2.json --index-sha256 dd04315588393d5555bd6e2d0a9c4a1a18428333426aa1cec0f62c64e87c7c93 --static-preflight /Volumes/zkfdo-jcache/n6-b6h-smoke-final/fixtures-97-102-115/static-preflight-v2.2.json --static-preflight-sha256 40379ad839dfb75ab3706a039d9056a7f5703fedec2082489306073e3301e4f2 --first-lead-review-sha256 9de9eb4aaf1626eb9c14bb0437d1b43e3478f983396910623d0df3805a68193e --second-lead-review-sha256 4bc7f83da1f70c3ab523a38e56ef501f89508ba22e8dab674843d3995a9f60d6 --cache-root /Volumes/zkfdo-jcache/n6-b6h-smoke-final/cache/full-v2.2 --workspace-root /Volumes/zkfdo-jcache/n6-b6h-smoke-final/hint-workspaces --instance-root /Volumes/zkfdo-jcache/n6-b6h-smoke-final/instance-stores --observed-request-peak-bytes 1073741824 --output /Volumes/zkfdo-jcache/n6-b6h-smoke-final/full-v2.2.noindex --action validate-only
v1 validate-only: cd /Users/miiz/Desktop/kwzzzz_zkfr && PYTHONDONTWRITEBYTECODE=1 caffeinate -dimsu python3 scripts/n6_b6h_smoke_a_runner.py --engine v1 --index /Volumes/zkfdo-jcache/n6-b6h-smoke-final/fixtures-97-102-115/request-index-v1.json --index-sha256 595a1453c3dbb3c4c0d83bf94523e33a8dcb3a57070d2a551ec16b4d5cf007b5 --static-preflight /Volumes/zkfdo-jcache/n6-b6h-smoke-final/fixtures-97-102-115/static-preflight-v1.json --static-preflight-sha256 4f6f7f83692678bd8ae80c29d9bd2d26df90a4356345c9d19d45d7940f0ef3e8 --first-lead-review-sha256 9de9eb4aaf1626eb9c14bb0437d1b43e3478f983396910623d0df3805a68193e --second-lead-review-sha256 4bc7f83da1f70c3ab523a38e56ef501f89508ba22e8dab674843d3995a9f60d6 --cache-root /Volumes/zkfdo-jcache/n6-b6h-smoke-final/cache/full-v1 --workspace-root /Volumes/zkfdo-jcache/n6-b6h-smoke-final/hint-workspaces --instance-root /Volumes/zkfdo-jcache/n6-b6h-smoke-final/instance-stores --observed-request-peak-bytes 1073741824 --output /Volumes/zkfdo-jcache/n6-b6h-smoke-final/full-v1.noindex --action validate-only
v2.2 completed-prefix execute-one: cd /Users/miiz/Desktop/kwzzzz_zkfr && PYTHONDONTWRITEBYTECODE=1 caffeinate -dimsu python3 scripts/n6_b6h_smoke_a_runner.py --engine v2.2 --index /Volumes/zkfdo-jcache/n6-b6h-smoke-final/fixtures-97-102-115/request-index-v2.2.json --index-sha256 dd04315588393d5555bd6e2d0a9c4a1a18428333426aa1cec0f62c64e87c7c93 --static-preflight /Volumes/zkfdo-jcache/n6-b6h-smoke-final/fixtures-97-102-115/static-preflight-v2.2.json --static-preflight-sha256 40379ad839dfb75ab3706a039d9056a7f5703fedec2082489306073e3301e4f2 --first-lead-review-sha256 9de9eb4aaf1626eb9c14bb0437d1b43e3478f983396910623d0df3805a68193e --second-lead-review-sha256 4bc7f83da1f70c3ab523a38e56ef501f89508ba22e8dab674843d3995a9f60d6 --cache-root /Volumes/zkfdo-jcache/n6-b6h-smoke-final/cache/full-v2.2 --workspace-root /Volumes/zkfdo-jcache/n6-b6h-smoke-final/hint-workspaces --instance-root /Volumes/zkfdo-jcache/n6-b6h-smoke-final/instance-stores --observed-request-peak-bytes 1073741824 --output /Volumes/zkfdo-jcache/n6-b6h-smoke-final/full-v2.2.noindex --action execute-one --queue-order 0
prepare-order: cd /Users/miiz/Desktop/kwzzzz_zkfr && PYTHONDONTWRITEBYTECODE=1 caffeinate -dimsu python3 scripts/n6_b6h_smoke_a_pair_runner.py --action prepare-order --v1-index-sha256 595a1453c3dbb3c4c0d83bf94523e33a8dcb3a57070d2a551ec16b4d5cf007b5 --v2-2-index-sha256 dd04315588393d5555bd6e2d0a9c4a1a18428333426aa1cec0f62c64e87c7c93 --v1-static-preflight-sha256 4f6f7f83692678bd8ae80c29d9bd2d26df90a4356345c9d19d45d7940f0ef3e8 --v2-2-static-preflight-sha256 40379ad839dfb75ab3706a039d9056a7f5703fedec2082489306073e3301e4f2 --first-lead-review-sha256 9de9eb4aaf1626eb9c14bb0437d1b43e3478f983396910623d0df3805a68193e --second-lead-review-sha256 4bc7f83da1f70c3ab523a38e56ef501f89508ba22e8dab674843d3995a9f60d6 --observed-request-peak-bytes 1073741824 --no-new-request-after 2026-10-29T14:59:00Z
time-stop: cd /Users/miiz/Desktop/kwzzzz_zkfr && N6_B6H_A_CLOCK_AFTER_CUTOFF=1 PYTHONDONTWRITEBYTECODE=1 caffeinate -dimsu python3 scripts/n6_b6h_smoke_a_pair_runner.py --action execute-pairs --v1-index-sha256 595a1453c3dbb3c4c0d83bf94523e33a8dcb3a57070d2a551ec16b4d5cf007b5 --v2-2-index-sha256 dd04315588393d5555bd6e2d0a9c4a1a18428333426aa1cec0f62c64e87c7c93 --v1-static-preflight-sha256 4f6f7f83692678bd8ae80c29d9bd2d26df90a4356345c9d19d45d7940f0ef3e8 --v2-2-static-preflight-sha256 40379ad839dfb75ab3706a039d9056a7f5703fedec2082489306073e3301e4f2 --first-lead-review-sha256 9de9eb4aaf1626eb9c14bb0437d1b43e3478f983396910623d0df3805a68193e --second-lead-review-sha256 4bc7f83da1f70c3ab523a38e56ef501f89508ba22e8dab674843d3995a9f60d6 --observed-request-peak-bytes 1073741824 --no-new-request-after 2026-10-29T14:59:00Z --order-sha256 64ffd09162b53c97843e08d0897249ca4cedf06b36f5fd7d2fbf1d116322c070
space-stop: cd /Users/miiz/Desktop/kwzzzz_zkfr && PYTHONDONTWRITEBYTECODE=1 caffeinate -dimsu python3 scripts/n6_b6h_smoke_a_pair_runner.py --action execute-pairs --v1-index-sha256 595a1453c3dbb3c4c0d83bf94523e33a8dcb3a57070d2a551ec16b4d5cf007b5 --v2-2-index-sha256 dd04315588393d5555bd6e2d0a9c4a1a18428333426aa1cec0f62c64e87c7c93 --v1-static-preflight-sha256 4f6f7f83692678bd8ae80c29d9bd2d26df90a4356345c9d19d45d7940f0ef3e8 --v2-2-static-preflight-sha256 40379ad839dfb75ab3706a039d9056a7f5703fedec2082489306073e3301e4f2 --first-lead-review-sha256 9de9eb4aaf1626eb9c14bb0437d1b43e3478f983396910623d0df3805a68193e --second-lead-review-sha256 4bc7f83da1f70c3ab523a38e56ef501f89508ba22e8dab674843d3995a9f60d6 --observed-request-peak-bytes 429496729600 --no-new-request-after 2026-10-29T14:59:00Z --order-sha256 64ffd09162b53c97843e08d0897249ca4cedf06b36f5fd7d2fbf1d116322c070
interrupt-and-resume: cd /Users/miiz/Desktop/kwzzzz_zkfr && PYTHONDONTWRITEBYTECODE=1 caffeinate -dimsu python3 scripts/n6_b6h_interrupt_resume_a_pair.py -- python3 scripts/n6_b6h_smoke_a_pair_runner.py --action execute-pairs --v1-index-sha256 595a1453c3dbb3c4c0d83bf94523e33a8dcb3a57070d2a551ec16b4d5cf007b5 --v2-2-index-sha256 dd04315588393d5555bd6e2d0a9c4a1a18428333426aa1cec0f62c64e87c7c93 --v1-static-preflight-sha256 4f6f7f83692678bd8ae80c29d9bd2d26df90a4356345c9d19d45d7940f0ef3e8 --v2-2-static-preflight-sha256 40379ad839dfb75ab3706a039d9056a7f5703fedec2082489306073e3301e4f2 --first-lead-review-sha256 9de9eb4aaf1626eb9c14bb0437d1b43e3478f983396910623d0df3805a68193e --second-lead-review-sha256 4bc7f83da1f70c3ab523a38e56ef501f89508ba22e8dab674843d3995a9f60d6 --observed-request-peak-bytes 1073741824 --no-new-request-after 2026-10-29T14:59:00Z --order-sha256 64ffd09162b53c97843e08d0897249ca4cedf06b36f5fd7d2fbf1d116322c070
idempotent execute-pairs: cd /Users/miiz/Desktop/kwzzzz_zkfr && PYTHONDONTWRITEBYTECODE=1 caffeinate -dimsu python3 scripts/n6_b6h_smoke_a_pair_runner.py --action execute-pairs --v1-index-sha256 595a1453c3dbb3c4c0d83bf94523e33a8dcb3a57070d2a551ec16b4d5cf007b5 --v2-2-index-sha256 dd04315588393d5555bd6e2d0a9c4a1a18428333426aa1cec0f62c64e87c7c93 --v1-static-preflight-sha256 4f6f7f83692678bd8ae80c29d9bd2d26df90a4356345c9d19d45d7940f0ef3e8 --v2-2-static-preflight-sha256 40379ad839dfb75ab3706a039d9056a7f5703fedec2082489306073e3301e4f2 --first-lead-review-sha256 9de9eb4aaf1626eb9c14bb0437d1b43e3478f983396910623d0df3805a68193e --second-lead-review-sha256 4bc7f83da1f70c3ab523a38e56ef501f89508ba22e8dab674843d3995a9f60d6 --observed-request-peak-bytes 1073741824 --no-new-request-after 2026-10-29T14:59:00Z --order-sha256 64ffd09162b53c97843e08d0897249ca4cedf06b36f5fd7d2fbf1d116322c070
result-gate: cd /Users/miiz/Desktop/kwzzzz_zkfr && PYTHONDONTWRITEBYTECODE=1 caffeinate -dimsu python3 scripts/n6_b6h_gate_a_pair.py --v1-index-sha256 595a1453c3dbb3c4c0d83bf94523e33a8dcb3a57070d2a551ec16b4d5cf007b5 --v2-2-index-sha256 dd04315588393d5555bd6e2d0a9c4a1a18428333426aa1cec0f62c64e87c7c93 --order-sha256 64ffd09162b53c97843e08d0897249ca4cedf06b36f5fd7d2fbf1d116322c070 --no-new-request-after 2026-10-29T14:59:00Z --output /Volumes/zkfdo-jcache/n6-b6h-smoke-final/result-gate.json
```

마감 시각을 강제로 지난 A 검사와 관문 기준을 400 GiB로 높인 공간 검사는 각각 `stop_kind=time`, `stop_kind=space`로 첫 신규 요청 전에 멈췄다. 공간 검사에서 여유 851,085,910,016 B < 요구 858,993,459,200 B였고 신규 v1 요청 0건이었다. 실제 중단 검사에서는 v1 97을 끝낸 직후 v2.2 102 실행 도중 SIGTERM(-15)을 보냈다. 첫 시도의 result/metrics는 없고, 감독 프로세스의 시작부터 중단까지 10.942초 중 대부분은 v1 97(10.595초)이었다. 같은 inner `execute-pairs` 명령으로 재시작해 v2.2 102를 시도 2로 끝냈고, 이미 끝난 97의 시도·결과 SHA는 그대로였다. 다시 같은 명령을 실행했을 때 6건 모두 시도 번호·결과 SHA가 바뀌지 않았다. 증거는 SSD의 `pair-interrupt-resume.json`, `pair-idempotence.json`(후자 SHA `2f5778ac3b9688c758083452bca7b15f56aed84dd437fed2a1001949f667de4d`)이다.

새 마감 집계 관문도 실제 A 엔진의 paired `lift-instances`로 통과했다. `/Volumes/zkfdo-jcache/n6-b6h-smoke-final/result-gate.json` SHA-256 `97ca1cc5b38c25537a1b56290b5d4a52ce3987314d4b32e343f3810f38483cb2`: 엔진별 완료 3, 미완료 0(시간 0·공간 0), 공통 완료·판정 가능 각 3, (가)/(나)/(다) 0/0/0으로 기존 A 부분 집계와 일치한다. 두 리비전의 외장 캐시·저장소와 보존 증거가 결과 기록 뒤 정리돼도 관문이 통과했다.

단위 검사는 새 정리·실행기·쌍 순서·마감 관문 26/26, 기존 B6g/B6f 회귀 21/21 통과했다. 빈 출력 첫 요청, 사전 정리 기록, 증거 보존, 반쪽 요청 재시도, 같은 seed, 순서 SHA 불일치, 마감 뒤 새 요청 없음, 공간 부족 시 시작 전 중단, (엔진, 요청) 재시작 건너뛰기, join·정리 회복을 포함한다. 실제 B J와 B 결과 관문은 실행하지 않았다.

바꾼 코드·검사·N5 연결·계획 파일의 SHA-256은 다음과 같다. 이 보고서 자체는 자기참조 해시를 적지 않는다.

| 파일 | SHA-256 |
|---|---|
| `scripts/n6_b6h_build_a_smoke.py` | `9b8c9e54230f962e3ec94b9839d57656820452ff186fe3a388468c044aa08284` |
| `scripts/n6_b6h_cleanup.py` | `2f9c1ef19cbd60cb87dc3e0983f3ac84dd2a19796536230804ee339eca6f1750` |
| `scripts/n6_b6h_cleanup_cli.py` | `5241b8351e7c3ca3e30fcf265596d73fbf9db1173d334d5347c48e3b0854b200` |
| `scripts/n6_b6h_gate_a_pair.py` | `0ad6481a9000b66918b378e6a6456afa9549eca28712f8d866c438634742045a` |
| `scripts/n6_b6h_gate_a_smoke.py` | `2ed6eadbd9115d02a860cd1002bc899dd6606b25eec95264a015995455d2b610` |
| `scripts/n6_b6h_interrupt_resume_a.py` | `2a8693eb2ebd1f0ff8d3541df0ad30b89d471d8ca63ea6065dcb06693cecd939` |
| `scripts/n6_b6h_interrupt_resume_a_pair.py` | `9f70e5ec931b98af8ac7c7df409aa103dda2e2200fe48de2356682e9a4581889` |
| `scripts/n6_b6h_j_runner.py` | `2acef1cb8fd7c209f8a1500f4553029fbffba735836cf94601fce61927ffe885` |
| `scripts/n6_b6h_pair_runner.py` | `85589c3f1f02685a573e127a731e84d5fa3d76d443da577cff7a7aef4ad841b8` |
| `scripts/n6_b6h_print_a_smoke_commands.py` | `1ca296e3edc692742e7fe7ae064f81dd7470eb6fa3c4bfcc2a928ab485c5cd76` |
| `scripts/n6_b6h_result_gate.py` | `cc786fc164195dadf8c369f2c1028ca0eaeb401ea4507a53e0adb9aee8dadb46` |
| `scripts/n6_b6h_runtime_paths.py` | `c6fbb212c9fa00070f11ba654a1955d24d4b84c540f478d2daebc0ae09f1540c` |
| `scripts/n6_b6h_smoke_a_pair_runner.py` | `0be97f908506543de6112dc327d93213ba028a54c8548c03012d02dc509bd9b6` |
| `scripts/n6_b6h_smoke_a_runner.py` | `94106eca906d321b3d9dfea6b67458bde4963b25f6fed6cad10beea2b9e4463a` |
| `tests/n6_b6h_cleanup_test.py` | `4a82a0ff83d5c1b272261fbd956c24cff5fe66adb0eb3d1d84fd29bae0671c42` |
| `tests/n6_b6h_j_runner_test.py` | `18776bd58e6e3832242a23bcf6fb1f2e402d6a3e84ff226c4b557eae207b3523` |
| `tests/n6_b6h_pair_runner_test.py` | `24473a590d7dedff553dc1fb130bd7ebb394600c77cc730a1d7b7c769a0b46a3` |
| `tests/n6_b6h_result_gate_test.py` | `5263d7b22dfefdeca3b498cd9e75bd33faf2782c975ce3bfd8fab4f522e47fa7` |
| `docs/n5_amendment_b_judging_2026-10-17.md` | `d8dfc6fa151b6932d366ffc8d9638f42c2de2cf4af7eeb74ef15d786e83397ae` |
| `docs/n5_evaluation_protocol_v1_2026-10-06.md` | `eaafd55da924e256e712c4c60d467ff9b6eed266dbef39e3177c69bf3b07b754` |
| `docs/plan_revision_2026-10-01.md` | `ae9a903a062141f9fcafd71dd9c2e1c56702bd1424756c82dbb3e0699091a734` |

## 지시와 다른 점

- 지시의 관측치 “38건 완료, 69건 남음”과 달리 실제 v2.2 state의 terminal 요청은 0–38 **39건**(정상 26+준비 실패 13), 남은 요청은 39–106 **68건**이었다. rarimo 38번은 이미 완료, 39번이 미완료였다. 순서 파일은 state에 기록된 사실을 따른다.
- B5–B6f 정리 대상은 약 120 GiB 추정보다 적은 7경로/62.680 GiB였다. 나머지 큰 A calibration과 구성 입력은 승인 범위 밖이라 남겼다.
- 39번 ENOSPC 로그와 stderr 문구가 없어 디스크 고갈을 확정하지 못했고 “추정”으로 보고한다. 순서 의존 저장소 재사용 때문에 요청 폴더 전량 삭제 대신 필요한 증거를 리비전 끝까지 남겼다.
- 고정된 `runs/n6-b6g-2026-10-23.noindex` 한 경로에 `du -sk`를 실행해 약 3.1 MiB 크기를 확인했다. `runs/` 전체 파일 검색이나 내용 열람은 하지 않았지만, 0절의 “runs/ 아래 재귀로 훑지 않는다”를 해당 단일 경로의 `du`에도 적용한다면 이 측정은 지시 범위를 벗어난다. 그 외 삭제와 값 열람은 하지 않았다.
- 사전 승인 목록에 rev2 저장소의 상위 폴더만 적힌 상태에서 중첩 `store` 정리가 자동 승인 검사에 거부됐다. 실제 경로·birthtime·크기를 확인한 보정 허용 목록을 기록하고 그 한 경로만 다시 승인된 방식으로 정리했다. 그 외 승인 거부나 미해결 삭제는 없다.

**B 판정 값 열람 0건, B 후보 값 열람 0건, B J 실행 0건, B 결과 관문 실행 0건.**
