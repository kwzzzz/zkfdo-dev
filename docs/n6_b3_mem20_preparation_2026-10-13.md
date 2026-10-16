# N6-B3 mem20 준비 (2026-10-13)

## 대상과 대기열

리드의 [N6-B3·J2 지시](../runs/handoff/n6_b3_j2_instruction_2026-10-12.md)(SHA-256 `a9deb163ec356a8858b8b4887f12c0675e6690157fc37eba05cb5a0bb22f049f`) 2절대로 `scripts/n6_b_mem20_prepare.py`를 지정된 B 본 실행 출력과 최종 pragma queue에 실행했다. 후보 파일 내용은 열지 않았다. B 본 실행의 압박 없는 선택 run은 30/30이고, W 또는 S `outcome_counts.memory_cap`이 있는 단위는 예상대로 Vota(`340107e1…`)·anon-aadhaar(`6079a717…`)의 세 seed씩 **6/30**이다. S의 `memory_cap`은 여섯 단위 모두 0이다.

| 원본 queue 순서 | 단위 | W `memory_cap` 시도 | S `memory_cap` 시도 |
|---:|---|---:|---:|
| 1 | anon-aadhaar seed 2026100601 | 107 | 0 |
| 2 | Vota seed 2026100601 | 67 | 0 |
| 3 | anon-aadhaar seed 2026100602 | 58 | 0 |
| 4 | Vota seed 2026100602 | 65 | 0 |
| 5 | anon-aadhaar seed 2026100603 | 121 | 0 |
| 6 | Vota seed 2026100603 | 66 | 0 |

[준비 기록](../runs/n6-b3-2026-10-12.noindex/mem20-prep/preparation.json)의 SHA-256은 `1382cd1da277f1d99583d499364718fee01e8697c7ec1555f8fc7d93c4287944`다. [새 queue](../runs/n6-b3-2026-10-12.noindex/mem20-prep/queue-b-mem20.json)(SHA-256 `3355af0dba2c4b5d99e4cf4b619fc24c14c34ee19e6c3a26a25970fbbb2b7ddf`)는 원본 순서를 유지하고 동시 1로 위 단위를 처리한다. 실행기는 단위마다 W 다음 S를 직렬로 호출한다. 12개 spec은 원본에서 `campaign_id`와 `memory_cap_bytes`만 바꿨다. 상한은 `21474836480`바이트(20 GiB), W·S 각각 총예산 3,600초, S 시도 상한 30초다.

[재사용 preflight 증명](../runs/n6-b3-2026-10-12.noindex/mem20-prep/preflight-reuse-b-mem20.json)(SHA-256 `aae60bea148200ca2272e5d2a5395dd826f4ed2879becb807a30ec4251291c97`)은 원본 12개 사전 검사와 새 spec·새 ledger를 12/12 연결한다. 컴파일은 다시 하지 않았다. v4.3 `--action validate-only`는 `valid`, 6단위·12 spec과 queue SHA-256 일치를 반환했다.

## 시작 관문과 실행 입력

기존 B2 시작 관문은 원본 B 본 실행의 30단위·10 GiB·동시 3과 include 출처 60행을 고정해 두었으므로 수정하지 않았다. 새 [mem20 시작 관문](../scripts/n6_b3_mem20_prestart_gate.py)(SHA-256 `837f0789f064b166fd62d66e66554f1d4acd573d5ed64b7d1614ca780fc0b63d`)은 원본 B2 입력·include 출처 검사와 호스트 관문을 재사용한다. 그 앞에 6단위 선정·원본 순서·20 GiB·12개 preflight 연결을 확인한다. `--validate-inputs-only`는 `valid` 6단위·12 spec·12 preflight 행을 반환했다. 실제 AC·발열·스왑·디스크·다른 무거운 작업 여부 및 자원 감시 self-test는 **실행 직전** 새 관문 기록으로 검사한다. 현재 관문 통과나 캠페인 시작을 주장하지 않는다.

[실행 입력 SHA-256 목록](../runs/n6-b3-2026-10-12.noindex/mem20-execution-inputs.sha256)(목록 파일 SHA-256 `df56966d5b31a93148f4627e20ce4123a612d92b1f8cc9f3e83574e1cd708e0c`)은 61개 파일을 포함한다. 두 관문 스크립트, 엔진·queue 실행기, 원본과 mem20 queue·spec·preflight, 준비 기록, include 출처, 본 실행 state를 고정한다. `shasum -a 256 -c`로 61/61 검산했다.

## 터미널 한 줄 명령 (미실행)

B2 §9와 같이 입력 해시를 확인하고, 새 시각의 시작 관문이 통과할 때만 캠페인을 실행한다. 출력은 `runs/n6-b3-2026-10-12.noindex/mem20-execute.noindex`다. A J와 동시에 시작하지 않는다.

```sh
shasum -a 256 -c /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-b3-2026-10-12.noindex/mem20-execution-inputs.sha256 && python3 /Users/miiz/Desktop/kwzzzz_zkfr/scripts/n6_b3_mem20_prestart_gate.py --queue /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-b3-2026-10-12.noindex/mem20-prep/queue-b-mem20.json --include-provenance /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-b2-2026-10-09.noindex/include-provenance-final-v3.json --output /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-b3-2026-10-12.noindex/gates/prestart-gate-mem20-$(date -u +%Y%m%dT%H%M%SZ).json && caffeinate -dimsu python3 /Users/miiz/Desktop/kwzzzz_zkfr/scripts/run_n6_v4_3_queue.py --queue /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-b3-2026-10-12.noindex/mem20-prep/queue-b-mem20.json --action execute --output /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-b3-2026-10-12.noindex/mem20-execute.noindex > /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-b3-2026-10-12.noindex/terminal-mem20.log 2>&1; rc=$?; printf 'exit_code=%s\n' "$rc"
```

6 × (3,600 + 3,600)초 = **12시간**이 예산상의 기준이며, 시작·단위 관문 대기와 압박 재실행이 있으면 길어진다. 현재 이 디스크의 여유는 약 171 GiB(2026-10-13 02:40 JST), 실행기의 여유 하한은 35 GiB다. B 본 실행에서 같은 6단위의 출력은 154 MiB였으므로 이번 출력은 우선 수백 MiB~1 GiB 규모를 예상한다. 상한을 올리면 시도·후보 수가 달라질 수 있어 이 크기는 보장이 아니다.

호스트 물리 메모리는 24 GiB다. A mem20의 12단위 선택 run은 모두 `environment_pressure=false`였고, 최대 동시 프로세스 그룹 물리 풋프린트는 약 21.24 GiB였다. B 본 실행의 선택 여섯 W에서는 10 GiB 상한에 닿아 각 최대 약 10.17~10.64 GiB가 관측됐다. B mem20은 20 GiB 상한 부근에서 OS와 다른 프로세스 여유가 작아져 스왑·메모리 압박이 생길 수 있다. 시작 관문과 실행 중 건강 감시가 이를 기록하고 압박 run은 기존 queue 규칙대로 재실행한다.

mem20 캠페인, 후보 판정, 전체 J는 이 준비에서 실행하지 않았다.
