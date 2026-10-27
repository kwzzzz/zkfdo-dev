# A aq 실행기 v2 준비·검증 (2026-10-26)

miiz의 10월 26일 승인에 따른 **작성·검증만 완료**했다. 실제 J·퍼징·실제 작업 폴더 삭제·설치·git 쓰기 작업은 하지 않았다. 기존 실행기·state.json·결과·metrics·join 37개 파일의 해시를 보존 확인했다. B 자료와 실행 중인 작업은 건드리지 않았다.

실행 명령(사람이 저장소 루트에서 실행):

```sh
cd /Users/miiz/Desktop/kwzzzz_zkfr
python3 -B scripts/n6_a_remeasure_aq_execute_v2.py \
  --action execute \
  --no-new-revision-after 2026-10-28T15:00:00Z
```

검증만 하려면 `--action execute`를 `--action validate-only`로 바꾼다. 마감은 10월 29일 00:00 KST이며 실행 중인 **엔진/리비전**은 끝낸다. 원래 상태를 읽어 `aq-exec/state-v2.json`으로 재개하고 원래 파일은 덮어쓰지 않는다. 완료 결과·metrics·join의 SHA를 재검사해 완료 16건을 재사용하며, 실패 2185는 aq-025 차례에 한 번 재시도한다. 첫 재개 때 원래 J 상태가 실행 중이면 거부한다.

순서는 각 엔진 안에서 `024 → 017 → 011 → 016 → 026 → 040 → 008 → 025 → 012 → 037 → 039 → 006 → 007`, **v2.2 전체 뒤 v1 전체**다. 리비전 안에서는 RQ-C 매핑 하위 위치 요청을 먼저, 각 묶음에서는 기존 큐 순서를 유지한다. 실제 660요청 모두 계산했고 엔진당 mapped 195·나머지 135다. 명시 위치가 없으면 해시 고정 wrapper·discovery·capture의 소스/템플릿/인자로 가능한 인스턴스 전체를 연결한다. 공유 wrapper의 복수 위치는 우선순위 메타데이터이며 단일 결함 귀속이 아니다. 순서·mapped·위치 목록 해시·출처를 `request-order-v2.json`에 기록한다.

결과·metrics를 저장·해시 확인한 뒤 `workspace-cleanup/`에 파일/링크 수·할당 바이트·보존 목록 SHA를 기록하고 정리한다. 링크는 따라가지 않고 링크 자체만 지운다. v2.2 고정 소스 `8065e2b7e165ef3f4c1523f240f5d34ecaefdb22`의 `src/candidate_review/lifting/predicate.rs:698–704,764–798`은 저장소 증거를 다시 해시하므로 B6h의 정확한 보존 규칙을 재사용한다. v1 `cb40e3e06c27bfed2dcb19245f5d6b82d1860404`의 같은 파일 `:97–112,586–590`에는 그 증거 재읽기가 없지만 동일한 보존 규칙을 보수적으로 적용한다. 두 판의 `instances.rs:70–136,195–199` 결합은 결과 JSON만 읽으므로 **엔진/리비전 종료 즉시** 보존 증거·캐시·store를 정리한다. 결합 실패 때도 재결합용 결과/metrics는 남긴다.

시작 관문은 이미지 여유 `2 × max(60 GiB, 관측 최대 요청 작업 폴더) + 보존 증거`, 내부 여유 15 GiB다. 기존 정리 기록의 최대는 **399.689 GiB**로, 초기 필요 여유는 최소 **799.379 GiB + 보존 증거**다. 부족하면 기록 후 5분마다 다시 확인한다. 별도 aq-025 정리의 before만 있고 완료 기록이 없으면 기다린다. 검증 모드는 읽기 전용이며 공간 대기·삭제를 실행하지 않는다.

요청 실패는 원인·상세를 남기고 다음 요청으로 간다. 실패 직후 이미지 여유가 1 GiB 미만이면 관문 통과 후 한 번만 재시도하며 재개 후에도 횟수를 유지한다. 같은 원인으로 요청 5개 연속 실패 시 `repeated_request_failure`, 리비전 2개 연속 실패 시 `repeated_failure`로 중단한다. `progress-v2.jsonl`에는 완료/실패/L1/배제/미판정, 최종 시도 wall 통계, 작업 폴더와 캐시/store 해제 바이트를 분리 기록한다. 이전 시도 시간은 history와 `attempts-v2.jsonl`에 보존한다. 엔진/리비전마다 기존 경량 RQ-C 채점기를 exploratory로 실행해 `rqc/`의 새 파일과 SHA를 연결하고, 채점 오류는 판정 진행을 막지 않는다. L1·판정 규칙은 기존 함수를 그대로 사용한다.

| 파일 | SHA-256 |
|---|---|
| [실행기](../scripts/n6_a_remeasure_aq_execute_v2.py) | `83b1d03cdbee08e2ef65c78479d00a18420550e37122e3cd44d935aec9dd0c34` |
| [정리 함수](../scripts/n6_a_remeasure_aq_cleanup_v2.py) | `32ca7ca8bb4efbec773ac9e51d8b9245f532bf2f05f84b2fc76f1c7642ffa46a` |
| [순서 계산](../scripts/n6_a_remeasure_aq_order_v2.py) | `874767f2b8099aea6abecfaa23c149da6023da8f60816b846822d5717b08f125` |

**검증:** 새 코드·테스트 py_compile, 합성/통합 **57건 통과**. 링크·삭제 중단 복구·디스크 대기·순서·실패 계속/재시도/중단·해시 변조 거부·재개·채점 오류 격리를 확인했다. `cargo fmt`, 지정 `cargo clippy`, `cargo test --no-run` 통과. 실제 J 호출 금지에 따라 J 호출 테스트 24개를 `--skip`한 `cargo test`는 **352 passed, 24 ignored, 24 filtered**다([정확한 검사 명령](../runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/validation-v2-20261026/cargo-test-command.json)).

실제 상태 [최종 validate-only](../runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/validation-v2-20261026/validate-final.json)는 **valid**, 소스 오류 0건이다. 지정 엔진 2개·index 2개·문서에 고정된 구성 입력 **13/13**과 요청 660개의 소스 연결을 확인했고, 재개 완료 **16건**·실패 **1건**의 저장 해시를 재검증했다. 검증 결과에 전체 계산 순서와 mapped 플래그가 들어 있다. [검증 기록 폴더](../runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/validation-v2-20261026/)에 첫/최종 검증, Python/Cargo 로그, 원래 파일 보존 해시를 분리했다.
