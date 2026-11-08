# N6-B6g 전체 J 실행기 첫 요청 경로 보정과 A 실엔진 스모크

2026-10-23 KST. 작업 저장소: `/Users/miiz/Desktop/kwzzzz_zkfr`. 이 보고서는 B 전체 실행 명령의 준비와 A 스모크 검증 결과다. B J 전체 실행과 B 결과 관문은 수행하지 않았다.

## 1. 지시 보존과 확인한 자료

- 이번 지시 전문: `runs/handoff/n6_b6g_instruction_2026-10-23.md`; SHA-256 `38d25319bc375d6cedef7a4ef4bde3c5fd61a7b7ac0b825ae250aef525c288d4`.
- 지시와 작업 기준: `AGENTS.md` (`b0db6aa11075f472931c495f8db3f9156e4e64a153e66ac374777acd38f78f02`), `reports/START_HERE.md` (`04761b76a9cb61540dc6873ac6970996f894981cbba0df86801dca1c6f6a5f56`), `docs/plan_revision_2026-10-01.md`(읽기 당시 `10a5edcaaa35d391ad9b9250cfe1c6a02014699d5329e596abd00dd09df9bb50`), `runs/handoff/n6_b6f_instruction_2026-10-20.md` (`3f6ce67cf5ce345dea40a5b5054b5254945a50b140bbf1aa7408baa8b1811e26`), `docs/n6_b6f_pilot_check_2026-10-20.md` (`0cef5ad7bd1e1bbad165247440c8057ebabbb6106dfbfe1b4efd70bbbaafcbb7`).
- 실행 경로와 판정 형식: `scripts/n6_b6f_j_runner.py` (`4dfbff11c73bfc7d1b772bc70892259c431d689eaa84c655eece406d1e236259`), `scripts/n6_b6b_runtime_paths.py` (`996ec9c4d85bea83d4f49dda9eb53955013c4a92e28530c203a0395545645f37`), `scripts/run_n6_j1.py` (`af23186151e1162f352d1a27f9020e3054e20bc461404791846fbb245077bd7c`), `scripts/n6_b6f_format_pilot.py` (`e0ade9572227059f317623a835195b78afd6219a20aca7324087a7ea582c5dee`), `scripts/n6_b6f_result_gate.py` (`603cda37e60c2d69d1e079629a490596a74eb8ae2539f3de590fb51d2b2098ad`), 엔진 lifting 소스 (`ce89724b7a89031921df38957118f5c5d4a7a1cf3b166746a4e502560daf1d66`)와 판정 소스 (`19cbf00493345219545979432b3f4edbc2051ba2b86512b93ce1dfe583bef532`).
- A 원본의 index·state·선택한 102/103/104번 요청 및 해당 결과만 비교했다. v1 원본 index/state SHA-256은 `35ed44c86545fc3e56d3a671cbe45eae5db69c1d970f5e453c1db60e52225f3c` / `6bfeb70743608235bbf9d7125f84c2aadf2fd8d9e95a461de8a9572411cb0e73`; v2.2는 `d1102d837e5d78116cb44a2b67f5a9796f57bbc2a6733d712205eb1d528ceed8` / `fa1da116b317d7833a60bec52826c2119a79f50dbec27616f4cbce2932a8a1f6`이다. B 입력은 값 대신 존재·해시만 대조했다.

## 2. 원인과 수정 범위

`n6_b6f_j_runner.py:575`는 `request_dir` 경로만 계산했다. 첫 요청은 이전 결과가 없어 `:621-625`에서 곧바로 `runner.run_lift`로 갔다. 설치된 SSD 라우터는 `n6_b6b_runtime_paths.py:112-114`에서 로그 이름을 아직 없는 그 `request_dir` 아래에 만들었고, 관측된 `time-l` 분기의 `:124`에서 `stdout_path.open("x")`가 `ENOENT`를 냈다. 이 `open`은 `:125`의 엔진 호출보다 먼저 수행된다. 라우터의 `external_output.parent.mkdir`(`:51`)는 SSD 쪽 부모만 만들므로 내장 디스크의 로그 부모를 만들지 못했다. 원래 `run_n6_j1.py:448`의 부모 생성은 라우터가 `run_lift`를 교체하며 적용되지 않았다. 따라서 첫 엔진 프로세스는 시작하지 못했고, set -e로 이어지는 v1도 시작되지 않았다.

새 `n6_b6g_j_runner.py:657`에서 첫 요청 디렉터리를 먼저 만들었다. 이어서 재시작 중 남은 시도 산출물과 SSD 로그를 확인해 새 시도 번호를 쓰게 했다(`:519-550, :658, :727-733`). 새 `n6_b6g_runtime_paths.py:49,78,101,111-125,138-170`는 hint workspace, 인스턴스 저장소, lift/join 로그를 SSD로 보낸다. 엔진별 `full-*.noindex` 구획으로 나누어 두 엔진이 같은 상대 경로를 재사용하지 않게 했다. 내장 결과 트리에는 작은 `result.json`, 요청/리비전 상태, 메트릭, 합친 결과만 남고 raw 디렉터리의 symlink는 만들지 않는다. `--workspace-root`와 `--instance-root`를 필수 인자로 추가하고 B용 고정 경로와 일치시킨다. B6f의 판정 규칙·사유 분류, 비환경 검사 실패 5건째 중단, 환경 사유 즉시 중단, 끝난 요청 건너뛰기 분기는 변경하지 않았다. 새 결과 관문은 B6f의 107건 분모와 검증을 유지하고 새 출력 경로를 가리킨다.

아래 부록에는 기존 판과 새 판의 `diff -U0`를 실었다. 문맥 줄 없이 변경 줄만 나타난다.

## 3. 저장 위치와 보존

| 항목 | 실제 위치 / 처리 |
| --- | --- |
| B6f 당시 full-v2.2 상태·첫 요청 폴더 | 2026-10-23 06:34:57Z 무렵 `runs/n6-b6f-2026-10-20.noindex/full-v2.2.noindex` 아래에 생김. 멈춘 출력은 수정·삭제하지 않았다. |
| 새 B 결과·state·메트릭·합친 결과 | `/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-b6g-2026-10-23.noindex/full-{v2.2,v1}.noindex/` (내장 디스크 `/dev/disk3s5`). 현재 새 B 출력은 아직 생성되지 않았다. |
| 새 B 캐시 | `/Volumes/zkfdo-jcache/n6-b6g-batch1x/cache/full-{v2.2,v1}` |
| 새 B hint workspace·lift/join 로그 | `/Volumes/zkfdo-jcache/n6-b6g-batch1x/hint-workspaces/full-{v2.2,v1}.noindex/...` |
| 새 B 인스턴스 저장소 | `/Volumes/zkfdo-jcache/n6-b6g-batch1x/instance-stores/full-{v2.2,v1}.noindex/...` |
| A 최종 스모크 | `/Volumes/zkfdo-jcache/n6-b6g-smoke/routed/`; 같은 라우팅을 실제로 관측. SSD는 `/dev/disk8s1`. 두 결과 트리의 symlink는 0건. |

처음 A 스모크에서 두 엔진이 SSD의 동일 상대 경로를 쓰는 점이 드러났다. 그 판의 출력은 `/Volumes/zkfdo-jcache/n6-b6g-smoke/`에 보존했다. 엔진별 구획을 추가한 뒤 새 `/routed/` 폴더에서 스모크 전체를 다시 돌렸다. 최종 스모크의 캐시 12 GiB, workspace 906 MiB, 인스턴스 저장소 24 KiB는 SSD에 있으며 결과 트리는 v2.2 132 KiB, v1 92 KiB다. 실행 완료 후 SSD 가용 공간은 263 GiB, 내장 디스크 가용 공간은 74 GiB였다.

## 4. A 실엔진 스모크

A 원본의 `main/inference-c9221e8d`, S 방식 요청 102·103·104를 각 엔진별 3건 index로 복제했다. 요청 본문·후보 해시·엔진·Circom·소스는 원본에 고정하고 새 index에서 queue 번호만 0·1·2로 다시 매겼다. 모두 준비 실패가 아닌 원본 완료 건이다. 두 번째 요청 103은 양쪽 엔진에서 repair 미지원 오류 형식을 포함해 재시작 검사에 적합했다. B 전용 107건·시범·출력 경로 관문만 A 래퍼가 메모리에서 3건/SSD 경로로 바꾸고, 동일한 `n6_b6g_j_runner.main`/`execute`와 동일한 CLI 인자 형태를 사용했다. B 요청이나 판정 값은 읽지 않았다.

두 엔진의 `validate-only`는 각각 `valid` 3건, `execute-all`은 각각 `completed` 3건, 인스턴스 합치기 1건, 검사 실패 0건이었다. 시간은 완료된 엔진 lift 시도의 `wall_seconds`이고 v2.2 두 번째 요청의 중단된 첫 시도 시간은 포함하지 않는다.

| A 원본 queue | 새 queue | 엔진 | 상태/시도 | lift 초 | 원본 A와 판정 대조 |
| ---: | ---: | --- | --- | ---: | --- |
| 102 | 0 | v2.2 | completed / 1 | 10.598 | `excluded_in_context` · `constant_input_mismatch`, 일치 |
| 103 | 1 | v2.2 | completed / 2 | 70.958 | `unknown` · `budget_exhausted`, injection·repair 미지원 오류 포함, 일치 |
| 104 | 2 | v2.2 | completed / 1 | 102.334 | `unknown` · `abort_on_constraint_unresolved`, injection 미지원 오류 포함, 일치 |
| 102 | 0 | v1 | completed / 1 | 10.690 | `excluded_in_context` · `constant_input_mismatch`, 일치 |
| 103 | 1 | v1 | completed / 1 | 44.010 | `unknown` · `budget_exhausted`, repair 오류 포함, 일치 |
| 104 | 2 | v1 | completed / 1 | 61.746 | `unknown` · `abort_on_constraint_unresolved`, 일치 |

v2.2 execute-all의 두 번째 요청이 시작돼 SSD에 `attempt-0001.stdout.log`가 생긴 뒤 프로세스 그룹에 SIGTERM을 보냈다(첫 실행 종료 코드 -15). 동일한 execute-all 명령을 다시 실행했다. 첫 요청의 SHA-256 `8cca96630b9af13e902c4dea617e73e17a6773587724faf2938dbd1cdfe04c2e`와 시도 번호 1은 그대로였고, 두 번째는 보존된 첫 시도를 건드리지 않고 시도 2로 완료했으며 세 번째는 시도 1로 완료했다. 재실행 종료 코드는 0이었다. 증거: `/Volumes/zkfdo-jcache/n6-b6g-smoke/routed/interrupt-resume-v2.2.json` (SHA-256 `80ad41b7f0e0bc3e3979dfb66cbf1b9bef58202089c8555bd84f783abc29d889`). A 대조 관문은 요청 판정과 method limit 6/6, 상태·해시·합친 결과·재시작 증거를 확인하고 `passed`를 냈다. `/Volumes/zkfdo-jcache/n6-b6g-smoke/routed/result-gate-v1.json` SHA-256 `b34a378c0c80ae51b957eb18710edfd7fd1b20e5a1d8da414c256c7f4bf78313`.

아래는 저장소 루트에서 실제 사용한 최종 판 명령 문자열이다. 중단 검사 도구는 `--` 뒤 execute-all 명령을 그대로 두 차례 호출했다.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/n6_b6g_build_a_smoke.py --out /Volumes/zkfdo-jcache/n6-b6g-smoke/routed/fixtures
PYTHONDONTWRITEBYTECODE=1 python3 scripts/n6_b6g_smoke_a_runner.py --engine v2.2 --index /Volumes/zkfdo-jcache/n6-b6g-smoke/routed/fixtures/request-index-v2.2.json --index-sha256 7b992af9500483655e5beaac4c93e59221222b137330bc40f5c0853502eb4dc5 --static-preflight /Volumes/zkfdo-jcache/n6-b6g-smoke/routed/fixtures/static-preflight-v2.2.json --static-preflight-sha256 5d6e488b509ba2a5407e9ecada00a6f51b44d06a84e941c2fbadf64f88a82884 --first-lead-review-sha256 9de9eb4aaf1626eb9c14bb0437d1b43e3478f983396910623d0df3805a68193e --second-lead-review-sha256 4bc7f83da1f70c3ab523a38e56ef501f89508ba22e8dab674843d3995a9f60d6 --cache-root /Volumes/zkfdo-jcache/n6-b6g-smoke/routed/cache/full-v2.2 --workspace-root /Volumes/zkfdo-jcache/n6-b6g-smoke/routed/hint-workspaces --instance-root /Volumes/zkfdo-jcache/n6-b6g-smoke/routed/instance-stores --output /Volumes/zkfdo-jcache/n6-b6g-smoke/routed/full-v2.2.noindex --action validate-only
PYTHONDONTWRITEBYTECODE=1 python3 scripts/n6_b6g_smoke_a_runner.py --engine v1 --index /Volumes/zkfdo-jcache/n6-b6g-smoke/routed/fixtures/request-index-v1.json --index-sha256 ce65b3be7844011ff691e60c0c15231a414966fc8721002dc1278b25b0d7d973 --static-preflight /Volumes/zkfdo-jcache/n6-b6g-smoke/routed/fixtures/static-preflight-v1.json --static-preflight-sha256 25cea8ff01da658bdb602aa64d2a5586e8557790e3275fc49bcca660229d4cb4 --first-lead-review-sha256 9de9eb4aaf1626eb9c14bb0437d1b43e3478f983396910623d0df3805a68193e --second-lead-review-sha256 4bc7f83da1f70c3ab523a38e56ef501f89508ba22e8dab674843d3995a9f60d6 --cache-root /Volumes/zkfdo-jcache/n6-b6g-smoke/routed/cache/full-v1 --workspace-root /Volumes/zkfdo-jcache/n6-b6g-smoke/routed/hint-workspaces --instance-root /Volumes/zkfdo-jcache/n6-b6g-smoke/routed/instance-stores --output /Volumes/zkfdo-jcache/n6-b6g-smoke/routed/full-v1.noindex --action validate-only
PYTHONDONTWRITEBYTECODE=1 python3 scripts/n6_b6g_interrupt_resume_a.py --timeout-seconds 300 -- python3 scripts/n6_b6g_smoke_a_runner.py --engine v2.2 --index /Volumes/zkfdo-jcache/n6-b6g-smoke/routed/fixtures/request-index-v2.2.json --index-sha256 7b992af9500483655e5beaac4c93e59221222b137330bc40f5c0853502eb4dc5 --static-preflight /Volumes/zkfdo-jcache/n6-b6g-smoke/routed/fixtures/static-preflight-v2.2.json --static-preflight-sha256 5d6e488b509ba2a5407e9ecada00a6f51b44d06a84e941c2fbadf64f88a82884 --first-lead-review-sha256 9de9eb4aaf1626eb9c14bb0437d1b43e3478f983396910623d0df3805a68193e --second-lead-review-sha256 4bc7f83da1f70c3ab523a38e56ef501f89508ba22e8dab674843d3995a9f60d6 --cache-root /Volumes/zkfdo-jcache/n6-b6g-smoke/routed/cache/full-v2.2 --workspace-root /Volumes/zkfdo-jcache/n6-b6g-smoke/routed/hint-workspaces --instance-root /Volumes/zkfdo-jcache/n6-b6g-smoke/routed/instance-stores --output /Volumes/zkfdo-jcache/n6-b6g-smoke/routed/full-v2.2.noindex --action execute-all
PYTHONDONTWRITEBYTECODE=1 python3 scripts/n6_b6g_smoke_a_runner.py --engine v1 --index /Volumes/zkfdo-jcache/n6-b6g-smoke/routed/fixtures/request-index-v1.json --index-sha256 ce65b3be7844011ff691e60c0c15231a414966fc8721002dc1278b25b0d7d973 --static-preflight /Volumes/zkfdo-jcache/n6-b6g-smoke/routed/fixtures/static-preflight-v1.json --static-preflight-sha256 25cea8ff01da658bdb602aa64d2a5586e8557790e3275fc49bcca660229d4cb4 --first-lead-review-sha256 9de9eb4aaf1626eb9c14bb0437d1b43e3478f983396910623d0df3805a68193e --second-lead-review-sha256 4bc7f83da1f70c3ab523a38e56ef501f89508ba22e8dab674843d3995a9f60d6 --cache-root /Volumes/zkfdo-jcache/n6-b6g-smoke/routed/cache/full-v1 --workspace-root /Volumes/zkfdo-jcache/n6-b6g-smoke/routed/hint-workspaces --instance-root /Volumes/zkfdo-jcache/n6-b6g-smoke/routed/instance-stores --output /Volumes/zkfdo-jcache/n6-b6g-smoke/routed/full-v1.noindex --action execute-all
PYTHONDONTWRITEBYTECODE=1 python3 scripts/n6_b6g_gate_a_smoke.py --smoke-root /Volumes/zkfdo-jcache/n6-b6g-smoke/routed --output /Volumes/zkfdo-jcache/n6-b6g-smoke/routed/result-gate-v1.json
```

## 5. 변경 파일 SHA-256과 검사

| 변경 파일 | SHA-256 |
| --- | --- |
| `runs/handoff/n6_b6g_instruction_2026-10-23.md` | `38d25319bc375d6cedef7a4ef4bde3c5fd61a7b7ac0b825ae250aef525c288d4` |
| `scripts/n6_b6g_j_runner.py` | `e0f102150de8653a0b9c2232e296dc76bdeeb97b9541465a096525138789c258` |
| `scripts/n6_b6g_runtime_paths.py` | `48f17b20613325176aa9d63f8aac7a8759dc7e1830fbfd8346f6e58bfe961270` |
| `scripts/n6_b6g_result_gate.py` | `fa9ac34cd5540e2d7b3dceca14973ff5b5017318d2abd2ecb4e5c2a8b65136cb` |
| `scripts/n6_b6g_build_a_smoke.py` | `adb9408fe515cefbd6d8bb84a284894555dc7ab45f1d4b95ff2013b1bdfaba3c` |
| `scripts/n6_b6g_smoke_a_runner.py` | `e353095896ff9b0044b21a06fad7a0b29ef045342ff5f20b9e035fc601afb457` |
| `scripts/n6_b6g_interrupt_resume_a.py` | `d7e76f51127f29cb698cdb8ccc72db6d94729daece0d95ad429c4b1239836f2a` |
| `scripts/n6_b6g_gate_a_smoke.py` | `05254353d3d3cfbe60366dca3b28a9ca34ff921ce5e00750e937984470f4f6bd` |
| `tests/n6_b6g_j_runner_test.py` | `9e4c997f6cf338f616eb33de590e29ad370e6f174a1ae932e76c4bc95034a1f4` |
| `tests/n6_b6g_result_gate_test.py` | `c698625dd7162e12ebe450697e2e71ac84645426576a2c536461a03b5dbc7c1d` |
| `docs/plan_revision_2026-10-01.md` (N6-B6g 상태 행 추가 후) | `e2ef69bfc2ae5b419d36bd6830c8fff6e6e8a339fb41fabe2fb6122cd9c7f67f` |

새 단위 검사는 빈 출력에서 첫 요청 폴더가 로그 생성 전에 만들어지는지, 첫 요청 결과가 복사되는지, SSD 로그·인스턴스 저장소 라우팅과 첫 요청 준비 실패 뒤 정상 요청·join까지 확인한다. 두 번째 검사는 중단 흔적의 로그/폴더를 보존하고 다음 시도 번호를 쓰는지 확인한다. B6g 실행기 2/2, B6g 결과 관문 9/9, 기존 B6f 시범 10/10, 기존 B6f 결과 관문 9/9로 합계 30/30 통과했다(`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/n6_b6g_j_runner_test.py tests/n6_b6g_result_gate_test.py tests/n6_b6f_pilot_runner_test.py tests/n6_b6f_result_gate_test.py`). Python 새 파일 9개의 AST 파싱 통과. `cargo fmt --check`, `CARGO_NET_OFFLINE=true cargo clippy --all-targets --all-features -- -D warnings`, `CARGO_NET_OFFLINE=true cargo test`도 종료 코드 0이었다. 엔진 소스는 수정하지 않았다.

## 6. miiz의 키티 B 명령

아래 첫 줄은 저장소로 이동한 뒤 caffeinate 아래에서 v2.2 검증·전체 실행, 이어서 v1 검증·전체 실행을 순서대로 수행한다. 각 판의 새 출력과 외장 캐시/workspace/store는 위 표의 경로다. 두 번째 줄은 전체 실행이 끝난 다음 별도로 실행하는 값 비열람 결과 관문이다. 이 작업에서는 두 줄 모두 실행하지 않았다.

```sh
cd /Users/miiz/Desktop/kwzzzz_zkfr && caffeinate -dimsu zsh -c 'set -e; O="$PWD/runs/n6-b6e-2026-10-20.noindex"; F="$PWD/runs/n6-b6g-2026-10-23.noindex"; X="/Volumes/zkfdo-jcache/n6-b6g-batch1x"; L1=9de9eb4aaf1626eb9c14bb0437d1b43e3478f983396910623d0df3805a68193e; L2=4bc7f83da1f70c3ab523a38e56ef501f89508ba22e8dab674843d3995a9f60d6; for E in v2.2 v1; do if [ "$E" = v2.2 ]; then I=2b1825ca2cce94cd08967a5bf16e5a56f9d045c6435a9b03d8625f52af505f39; P=88c4a92bd627e138d2d77699e6a879e9f5a73729b3a241b6fafff89f966433d5; else I=08421ec900fedbce6f4e55b7fcba64df1c48886030fb094a50b3719e13101f1c; P=eb8241575399399ad46125452ff41bc21949d53df5bc8c5a93cf22ff5b6368cd; fi; A=(--engine "$E" --index "$O/request-index-$E.json" --index-sha256 "$I" --static-preflight "$O/static-preflight-96mib-$E.json" --static-preflight-sha256 "$P" --first-lead-review-sha256 "$L1" --second-lead-review-sha256 "$L2" --cache-root "$X/cache/full-$E" --workspace-root "$X/hint-workspaces" --instance-root "$X/instance-stores" --output "$F/full-$E.noindex"); python3 scripts/n6_b6g_j_runner.py "${A[@]}" --action validate-only; python3 scripts/n6_b6g_j_runner.py "${A[@]}" --action execute-all; done'
cd /Users/miiz/Desktop/kwzzzz_zkfr && caffeinate -dimsu python3 scripts/n6_b6g_result_gate.py --v1-index-sha256 08421ec900fedbce6f4e55b7fcba64df1c48886030fb094a50b3719e13101f1c --v2-2-index-sha256 2b1825ca2cce94cd08967a5bf16e5a56f9d045c6435a9b03d8625f52af505f39 --output /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-b6g-2026-10-23.noindex/result-gate-v1.json
```

## 7. 지시와 다른 점 및 비열람 확인

- 요청에서 제시한 현재 디렉터리(`/Users/miiz/Desktop/GW_jeopardy`)에는 해당 저장소가 없어 실제 저장소 `/Users/miiz/Desktop/kwzzzz_zkfr`에서 작업했다.
- 멈춘 B6f 출력의 `state.json`에서 `running`, 측정 방식, 기록 건수 같은 실행 메타데이터를 한 번 확인했다. 이는 “B J 작업 폴더 내용 열람 금지”를 문자 그대로 적용하면 범위를 벗어난 확인이다. 이 파일을 수정하지 않았고, 그 폴더의 후보·판정 값은 열지 않았다. 좁은 `runs/handoff` 경로의 텍스트 검색 1회가 있었지만 `runs/` 전체 재귀 탐색은 하지 않았다.
- 최초 A 스모크의 엔진 간 SSD 상대 경로 재사용을 발견해 라우터를 고친 뒤 요청된 새 SSD 폴더 안의 `/routed/`에서 6건 전체를 다시 실행했다. 첫 스모크 출력은 보존했다.
- B 후보 값 열람 0건, B 판정 값 열람 0건, B J 실행 0건. 기존 B6f 멈춘 출력과 기존 A 출력의 삭제·덮어쓰기 0건. commit·push·PR 0건, symlink 생성 0건, 엔진·판정 규칙 변경 0건.

## 부록. 변경 줄만 표시한 diff

새 A 스모크 지원 파일과 단위 검사 파일에는 이전 판의 동명 파일이 없다. 아래는 실행기·라우터·결과 관문의 기준 파일 대비 변경 줄이다.

### `scripts/n6_b6f_j_runner.py` → `scripts/n6_b6g_j_runner.py`

```diff
--- scripts/n6_b6f_j_runner.py
+++ scripts/n6_b6g_j_runner.py
@@ -2 +2 @@
-"""Validate and (when miiz invokes it) run B6f's 107-request J index.
+"""Validate and run the B6g 107-request J index.
@@ -7 +7 @@
-The preparation step must never invoke execute-all.
+A smoke requests may be executed here; B J remains miiz-run.
@@ -21 +21 @@
-import n6_b6b_runtime_paths as external_paths
+import n6_b6g_runtime_paths as external_paths
@@ -33,2 +33,3 @@
-RUN_OUT = ROOT / "runs/n6-b6f-2026-10-20.noindex"
-EXTERNAL = Path("/Volumes/zkfdo-jcache/n6-b6f-batch1x")
+RUN_OUT = ROOT / "runs/n6-b6g-2026-10-23.noindex"
+PILOT_OUT = ROOT / "runs/n6-b6f-2026-10-20.noindex"
+EXTERNAL = Path("/Volumes/zkfdo-jcache/n6-b6g-batch1x")
@@ -429 +430 @@
-V22_RECHECK = RUN_OUT / "v2-2-pilot-recheck.json"
+V22_RECHECK = PILOT_OUT / "v2-2-pilot-recheck.json"
@@ -455 +456 @@
-    v1_pilot = RUN_OUT / "pilot-v1.noindex"
+    v1_pilot = PILOT_OUT / "pilot-v1.noindex"
@@ -517,0 +519,32 @@
+def _next_fresh_attempt(request_dir: Path, output: Path,
+                        workspace_root: Path) -> int:
+    """Keep every artifact from an interrupted attempt and use a new number."""
+    attempt = runner.next_attempt(request_dir)
+    while attempt <= 9999:
+        prefix = request_dir / f"attempt-{attempt:04d}"
+        local = (prefix, request_dir / f"attempt-{attempt:04d}.metrics.json")
+        external = workspace_root / output.name / prefix.relative_to(output)
+        logs = (external.with_suffix(".stdout.log"),
+                external.with_suffix(".stderr.log"))
+        if not any(path.exists() or path.is_symlink()
+                   for path in (*local, external, *logs)):
+            return attempt
+        attempt += 1
+    raise runner.RunnerError("B6g attempt numbers exhausted")
+
+
+def _next_fresh_join_attempt(revision_dir: Path, output: Path,
+                             workspace_root: Path) -> int:
+    """Preserve an interrupted instances join and its external logs."""
+    for attempt in range(1, 10000):
+        working = revision_dir / f"instances-attempt-{attempt:04d}.json"
+        metrics = revision_dir / f"instances-attempt-{attempt:04d}.metrics.json"
+        external = workspace_root / output.name / working.relative_to(output)
+        logs = (external.with_suffix(".stdout.log"),
+                external.with_suffix(".stderr.log"))
+        if not any(path.exists() or path.is_symlink()
+                   for path in (working, metrics, *logs)):
+            return attempt
+    raise runner.RunnerError("B6g instances attempt numbers exhausted")
+
+
@@ -519 +552,2 @@
-            output: Path) -> dict[str, Any]:
+            output: Path, workspace_root: Path,
+            instance_root: Path) -> dict[str, Any]:
@@ -522,2 +556,4 @@
-            output.is_absolute() and output == RUN_OUT / f"full-{_engine_label()}.noindex",
-            "B6f full J paths are not the prepared new paths")
+            output.is_absolute() and output == RUN_OUT / f"full-{_engine_label()}.noindex" and
+            workspace_root.is_absolute() and workspace_root == WORKSPACES and
+            instance_root.is_absolute() and instance_root == STORES,
+            "B6g full J paths are not the prepared new paths")
@@ -529,2 +565,2 @@
-    external_paths.require_external_root(WORKSPACES)
-    external_paths.require_external_root(STORES)
+    external_paths.require_external_root(workspace_root)
+    external_paths.require_external_root(instance_root)
@@ -534 +570 @@
-    external_paths.install_full(output, WORKSPACES, STORES)
+    external_paths.install_full(output, workspace_root, instance_root)
@@ -612 +648 @@
-                    runner.check_disk(WORKSPACES, STORES)
+                    runner.check_disk(workspace_root, instance_root)
@@ -621 +657,2 @@
-                attempt = runner.next_attempt(request_dir)
+                request_dir.mkdir(parents=True, exist_ok=True)
+                attempt = _next_fresh_attempt(request_dir, output, workspace_root)
@@ -690,2 +727,3 @@
-                working = revision_dir / "instances-attempt-0001.json"
-                require(not working.exists(), "B6f prior instance join artifact exists")
+                join_attempt = _next_fresh_join_attempt(revision_dir, output,
+                                                        workspace_root)
+                working = revision_dir / f"instances-attempt-{join_attempt:04d}.json"
@@ -694 +732,2 @@
-                runner.atomic_json(revision_dir / "instances-attempt-0001.metrics.json",
+                runner.atomic_json(revision_dir /
+                                   f"instances-attempt-{join_attempt:04d}.metrics.json",
@@ -717 +756,2 @@
-    require(len(state["requests"]) == 107, "B6f run did not cover all 107 requests")
+    require(len(state["requests"]) == index["request_count"],
+            "B6g run did not cover every indexed request")
@@ -740,0 +781,2 @@
+    parser.add_argument("--workspace-root", type=Path, required=True)
+    parser.add_argument("--instance-root", type=Path, required=True)
@@ -750 +792 @@
-            print(json.dumps({"status": "valid", "request_count": 107,
+            print(json.dumps({"status": "valid", "request_count": index["request_count"],
@@ -754 +796,2 @@
-                        args.cache_root, args.output)
+                        args.cache_root, args.output,
+                        args.workspace_root, args.instance_root)
@@ -760 +803 @@
-        print(f"B6f J runner refused: {error}", file=sys.stderr)
+        print(f"B6g J runner refused: {error}", file=sys.stderr)
```

### `scripts/n6_b6b_runtime_paths.py` → `scripts/n6_b6g_runtime_paths.py`

```diff
--- scripts/n6_b6b_runtime_paths.py
+++ scripts/n6_b6g_runtime_paths.py
@@ -2 +2 @@
-"""Route B6b hint files and instance stores to the external J volume.
+"""Route B6g hint files, logs, and instance stores to the external J volume.
@@ -23 +23 @@
-EXTERNAL = VOLUME / "n6-b6b-batch1x"
+EXTERNAL = VOLUME / "n6-b6g-batch1x"
@@ -49 +49 @@
-    external_output = workspace_root / relative
+    external_output = workspace_root / output_root.name / relative
@@ -59 +59 @@
-                   external_output == workspace_root / output_dir.relative_to(output_root) and
+                   external_output == workspace_root / output_root.name / output_dir.relative_to(output_root) and
@@ -70,3 +70,2 @@
-    raw = external_output / "raw"
-    if raw.is_dir():
-        (output_dir / "raw").symlink_to(raw, target_is_directory=True)
+    # The raw workspace remains at its recorded external path; no link is
+    # created in the results tree.
@@ -79 +78 @@
-    selected = instance_root / store.relative_to(output_root)
+    selected = instance_root / output_root.name / store.relative_to(output_root)
@@ -102 +101 @@
-                            instance_root / old.relative_to(output_root))
+                            instance_root / output_root.name / old.relative_to(output_root))
@@ -112 +111 @@
-        prefix = output_dir.parent / f"attempt-{attempt:04d}"
+        prefix = external_output.parent / f"attempt-{attempt:04d}"
@@ -138,0 +138,30 @@
+    def join_instances(result_paths: list[Path], output: Path,
+                       instance_path: Path,
+                       measurement_method: str) -> dict[str, Any]:
+        runner.require(result_paths and not instance_path.exists() and
+                       instance_path.is_relative_to(output_root),
+                       "invalid or existing instance output")
+        runner.require(measurement_method in {"time-l", "wait4"},
+                       "unknown measurement method")
+        relative = [str(path.relative_to(output)) for path in result_paths]
+        external_prefix = workspace_root / output_root.name / instance_path.relative_to(output_root)
+        external_prefix.parent.mkdir(parents=True, exist_ok=True)
+        stdout_path = external_prefix.with_suffix(".stdout.log")
+        stderr_path = external_prefix.with_suffix(".stderr.log")
+        command = [str(runner.ENGINE), "experiment", "lift-instances",
+                   "--result", *relative, "--output", str(instance_path)]
+        if measurement_method == "wait4":
+            metrics = runner.run_with_rusage(command, stdout_path,
+                                             stderr_path, cwd=output)
+        else:
+            started = time.monotonic()
+            with stdout_path.open("x") as stdout, stderr_path.open("x") as stderr:
+                process = subprocess.run([str(runner.TIME_BIN), "-l", *command],
+                                         cwd=output, stdout=stdout, stderr=stderr,
+                                         check=False)
+            metrics = {"exit_code": process.returncode,
+                       "wall_seconds": time.monotonic() - started,
+                       "max_rss_bytes": runner.max_rss_bytes(stderr_path)}
+        return {**metrics, "measurement_method": measurement_method,
+                "stdout_path": str(stdout_path), "stderr_path": str(stderr_path)}
+
@@ -140,0 +170 @@
+    runner.join_instances = join_instances
```

### `scripts/n6_b6f_result_gate.py` → `scripts/n6_b6g_result_gate.py`

```diff
--- scripts/n6_b6f_result_gate.py
+++ scripts/n6_b6g_result_gate.py
@@ -2 +2 @@
-"""Check both human-run B6f J states and write a value-free 107-row summary.
+"""Check both human-run B6g J states and write a value-free 107-row summary.
@@ -19 +19 @@
-import n6_b6f_j_runner as b6f
+import n6_b6g_j_runner as b6g
@@ -25 +25 @@
-    b6f.require(isinstance(path_text, str) and isinstance(digest, str) and
+    b6g.require(isinstance(path_text, str) and isinstance(digest, str) and
@@ -28 +28 @@
-    b6f.require(path.is_absolute() and path.resolve().is_relative_to(output.resolve()) and
+    b6g.require(path.is_absolute() and path.resolve().is_relative_to(output.resolve()) and
@@ -40 +40 @@
-    b6f.require(isinstance(rows, list) and len(rows) == 107 and
+    b6g.require(isinstance(rows, list) and len(rows) == 107 and
@@ -48 +48 @@
-                    b6f.ROOT / "scripts/n6_b6f_format_pilot.py") and
+                    b6g.ROOT / "scripts/n6_b6f_format_pilot.py") and
@@ -54 +54 @@
-                f"B6f {engine} completed state/index lock differs")
+                f"B6g {engine} completed state/index lock differs")
@@ -67,2 +67,2 @@
-    b6f.require(set(state["revisions"]) == expected_revision_keys,
-                f"B6f {engine} revision state coverage differs")
+    b6g.require(set(state["revisions"]) == expected_revision_keys,
+                f"B6g {engine} revision state coverage differs")
@@ -75 +75 @@
-            b6f.require(isinstance(item, dict) and
+            b6g.require(isinstance(item, dict) and
@@ -81 +81 @@
-                        f"B6f {engine} request identity differs at {order}")
+                        f"B6g {engine} request identity differs at {order}")
@@ -84 +84 @@
-                b6f.require(row["preparation_failure"] is None and
+                b6g.require(row["preparation_failure"] is None and
@@ -93 +93 @@
-                            f"B6f {engine} completed request metadata invalid at {order}")
+                            f"B6g {engine} completed request metadata invalid at {order}")
@@ -95 +95 @@
-                         output, f"B6f {engine} completed result {order}")
+                         output, f"B6g {engine} completed result {order}")
@@ -100 +100 @@
-                b6f.require(row["preparation_failure"] is None and
+                b6g.require(row["preparation_failure"] is None and
@@ -114 +114 @@
-                            not b6f.RESOURCE_DETAIL.search(
+                            not b6g.RESOURCE_DETAIL.search(
@@ -119 +119 @@
-                            f"B6f {engine} inspection failure metadata invalid at {order}")
+                            f"B6g {engine} inspection failure metadata invalid at {order}")
@@ -122 +122 @@
-                         f"B6f {engine} inspection artifact {order}")
+                         f"B6g {engine} inspection artifact {order}")
@@ -126 +126 @@
-            b6f.require(status == "preparation_failure" and
+            b6g.require(status == "preparation_failure" and
@@ -129 +129 @@
-                        f"B6f {engine} request status invalid at {order}")
+                        f"B6g {engine} request status invalid at {order}")
@@ -131,2 +131,2 @@
-            b6f.require(isinstance(reason, str) and reason,
-                        f"B6f {engine} preparation reason absent at {order}")
+            b6g.require(isinstance(reason, str) and reason,
+                        f"B6g {engine} preparation reason absent at {order}")
@@ -134 +134 @@
-                b6f.require(reason == row["preparation_failure"] ==
+                b6g.require(reason == row["preparation_failure"] ==
@@ -138 +138 @@
-                            f"B6f {engine} planned failure differs at {order}")
+                            f"B6g {engine} planned failure differs at {order}")
@@ -144 +144 @@
-                b6f.require(reason in b6f.INTRINSIC_REASONS and
+                b6g.require(reason in b6g.INTRINSIC_REASONS and
@@ -152 +152 @@
-                            not b6f.RESOURCE_DETAIL.search(item["preparation_detail"]) and
+                            not b6g.RESOURCE_DETAIL.search(item["preparation_detail"]) and
@@ -156 +156 @@
-                            f"B6f {engine} engine preparation failure invalid at {order}")
+                            f"B6g {engine} engine preparation failure invalid at {order}")
@@ -159 +159 @@
-                         f"B6f {engine} preparation artifact {order}")
+                         f"B6g {engine} preparation artifact {order}")
@@ -167 +167 @@
-        b6f.require(isinstance(revision_state, dict) and
+        b6g.require(isinstance(revision_state, dict) and
@@ -170 +170 @@
-                    f"B6f {engine} revision result count differs: {key}")
+                    f"B6g {engine} revision result count differs: {key}")
@@ -172,3 +172,3 @@
-            b6f.require(revision_state.get("status") == "joined",
-                        f"B6f {engine} joined revision status differs: {key}")
-            b6f.require(revision_state.get("instances_path") == str(
+            b6g.require(revision_state.get("status") == "joined",
+                        f"B6g {engine} joined revision status differs: {key}")
+            b6g.require(revision_state.get("instances_path") == str(
@@ -176 +176 @@
-                f"B6f {engine} instance join path differs: {key}")
+                f"B6g {engine} instance join path differs: {key}")
@@ -179 +179 @@
-                     f"B6f {engine} instance join {key}")
+                     f"B6g {engine} instance join {key}")
@@ -181 +181 @@
-            b6f.require(revision_state.get("status") == "no_results" and
+            b6g.require(revision_state.get("status") == "no_results" and
@@ -184,2 +184,2 @@
-                        f"B6f {engine} empty revision status differs: {key}")
-    b6f.require(state.get("inspection_failure_count") == inspection_failure and
+                        f"B6g {engine} empty revision status differs: {key}")
+    b6g.require(state.get("inspection_failure_count") == inspection_failure and
@@ -187,3 +187,3 @@
-                f"B6f {engine} inspection failure limit exceeded")
-    b6f.require(completed + planned + engine_preparation + inspection_failure == 107,
-                f"B6f {engine} denominator differs")
+                f"B6g {engine} inspection failure limit exceeded")
+    b6g.require(completed + planned + engine_preparation + inspection_failure == 107,
+                f"B6g {engine} denominator differs")
@@ -209 +209 @@
-    b6f.verify_both_pilots()
+    b6g.verify_both_pilots()
@@ -211,2 +211,2 @@
-        "v2.2_recheck": b6f.RUN_OUT / "v2-2-pilot-recheck.json",
-        "v1_pilot_state": b6f.RUN_OUT / "pilot-v1.noindex/state.json",
+        "v2.2_recheck": b6g.PILOT_OUT / "v2-2-pilot-recheck.json",
+        "v1_pilot_state": b6g.PILOT_OUT / "pilot-v1.noindex/state.json",
@@ -214 +214 @@
-    b6f.require(all(path.is_file() and not path.is_symlink()
+    b6g.require(all(path.is_file() and not path.is_symlink()
@@ -216 +216 @@
-                "B6f pilot evidence is missing or linked")
+                "B6g pilot evidence is missing or linked")
@@ -220,2 +220,2 @@
-        index_path = b6f.OUT / f"request-index-{engine}.json"
-        output = b6f.RUN_OUT / f"full-{engine}.noindex"
+        index_path = b6g.OUT / f"request-index-{engine}.json"
+        output = b6g.RUN_OUT / f"full-{engine}.noindex"
@@ -224,4 +224,4 @@
-        runner.checked_sha(index_path, index_sha, f"B6f {engine} index")
-        index = b6f.read_object(index_path)
-        b6f.verify_equivalence_gate(index)
-        state = b6f.read_object(state_path)
+        runner.checked_sha(index_path, index_sha, f"B6g {engine} index")
+        index = b6g.read_object(index_path)
+        b6g.verify_equivalence_gate(index)
+        state = b6g.read_object(state_path)
@@ -230 +230 @@
-                                             b6f.CACHE / f"full-{engine}")
+                                             b6g.CACHE / f"full-{engine}")
@@ -235 +235 @@
-    return {"schema_version": 1, "kind": "n6_b6f_value_free_result_gate",
+    return {"schema_version": 1, "kind": "n6_b6g_value_free_result_gate",
@@ -238,2 +238,2 @@
-            "equivalence_gate": str(b6f.GATE),
-            "equivalence_gate_sha256": runner.sha256(b6f.GATE),
+            "equivalence_gate": str(b6g.GATE),
+            "equivalence_gate_sha256": runner.sha256(b6g.GATE),
@@ -253,3 +253,3 @@
-        b6f.require(args.output.is_absolute() and
-                    args.output.parent == b6f.RUN_OUT and not args.output.exists(),
-                    "B6f result gate output must be new and in B6f output")
+        b6g.require(args.output.is_absolute() and
+                    args.output.parent == b6g.RUN_OUT and not args.output.exists(),
+                    "B6g result gate output must be new and in B6g output")
@@ -267 +267 @@
-        print(f"B6f result gate refused: {error}", file=sys.stderr)
+        print(f"B6g result gate refused: {error}", file=sys.stderr)
```

