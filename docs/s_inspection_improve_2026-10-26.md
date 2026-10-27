# S fragment 검사 범위 개선 — 2026-10-26

A 개발셋의 오프라인 검사 통과 수가 aq-024 **187→910/975**, aq-017 **191→914/979**로 늘었다. 기존 적격 1,270개와 두 단위의 기존 검사 통과 378개에 대한 명세·래퍼 보존 비교는 모두 통과했다. 새 컴파일을 하지 않았으므로 아래 검사 통과 수를 완전한 준비 적격 수로 해석하지 않는다.

**기준·변경 범위.** 기준 HEAD는 `8065e2b7e165ef3f4c1523f240f5d34ecaefdb22`. 시작 시 작업 트리는 깨끗하지 않았지만 `src/`는 동결 v2.2 소스 `8065e2b`와 같았다([baseline.json](../runs/s-inspection-improve-2026-10-26/baseline.json)). 기존 변경은 [preexisting-tracked.diff](../runs/s-inspection-improve-2026-10-26/preexisting-tracked.diff)에 별도 보존했다. 판정 규칙·동결 엔진·실행 기록·전환 프로세스는 변경하지 않았다. 활성 aq 폴더는 요청된 테스트 제외 목록 파일만 읽었다.

구현 전체 패치 [implementation.diff](../runs/s-inspection-improve-2026-10-26/implementation.diff)의 SHA-256은 `603642b7421cde0fe19865ec49dcf9d720e9aa35bbbc73b07f317141a06227ed`. 보고서·상태표 변경까지 포함한 이번 작업의 전체 패치는 [full.diff](../runs/s-inspection-improve-2026-10-26/full.diff), 그 SHA-256은 [full.diff.sha256](../runs/s-inspection-improve-2026-10-26/full.diff.sha256)에 기록한다. 보고서 자체를 포함하는 패치의 해시는 자기참조를 피하도록 별도 파일에 둔다. 작업 전 변경은 이번 패치에 섞지 않았다.

**변경과 남은 제한.** 배열→함수→컴포넌트 순서로 구현하고 각 단계에서 집중 단위 검사를 실행했다.

1. `src/targets/compile_time.rs:54,95,266,373,417`: 배열 literal·중첩 인덱스·선언 배열·원소 할당, 큰 정수 상수의 보존·전달을 지원한다. `src/targets/inspection_fallback.rs:219,485`에서 배열 템플릿 인자를 기존 F-01 식별 형식으로 정규화한다. 산술은 bn128에서 정확성을 보장할 수 있는 i128 부분집합으로 제한한다. 나누어떨어지는 `/`만 허용하고, 정수 나눗셈 `\`, 음수 나머지·비트 연산, overflow·미초기화 값·불규칙/빈 배열·범위 밖 인덱스는 거부한다. Circom 연산자 순서는 로컬 파서 `.external/circomspect/parser/src/lang.lalrpop:474–544`와 대조했다. 배열 모양·중첩·대입·우선순위·정확하지 않은 산술 거부 테스트를 추가했다(`compile_time.rs:475`).
2. `src/targets/compile_time_functions.rs:72,130,169,352`: 소스에서 찾은 순수 함수의 배열 인자/반환, 산술, if/for/while 및 대입을 평가한다. log2Ceil 형태·중첩 호출·배열 반환·루프 및 악성/지원 밖 구문 거부 테스트를 추가했다(`:713`). 호출 관계 전체를 검사하며 미실행 분기의 signal/component/constraint/assert/log도 거부한다. 함수의 복수 var 선언, shadowing, 전위 증감, break/continue, 삼항식은 아직 미지원이다. 호출 깊이 32, 공유 실행 예산 100,000, 구문 깊이 64로 제한한다.
3. `src/targets/inspection_fallback.rs:256,325,466`: 반복문의 복수 카운터·offset 갱신과 서로 다른 component 배열 슬롯의 재바인딩을 처리한다. 슬롯은 범위 안에서 정확히 한 번만 초기화할 수 있다. 진짜 동일 슬롯 덮어쓰기, component 별칭/배열 전체 초기화, 템플릿 while은 거부한다. 반복문·분기 지역 변수의 수명과 익명 component 호출도 검증했다(`:647,728`).

기존 검사가 complete이면 그대로 반환하고 새 경로는 prime이 명시적으로 bn128인 경우에만 적용한다(`src/targets.rs:436,646`). F-01 capture가 있는 준비 경로는 기존 검사를 유지한다(`src/corpus.rs:568–583`). 보수적 선택 이유: 기존 대상의 의미와 바이트를 보존하고 확인되지 않은 필드 산술을 추측하지 않기 위해서다. wrapper 문자열 포맷은 그대로 추출하여 생산 코드와 비교 도구가 공유한다(`src/targets.rs:2662,2734`).

**두 단위 측정.** `examples/s_inspection_audit.rs:150`의 검사 전용 모드로 기존 prepared.json에 적힌 대상 전부를 읽었다. 컴파일·J·zkFuzz 호출은 0회다. 아래 전/후는 각각 [baseline/measurement.json](../runs/s-inspection-improve-2026-10-26/baseline/measurement.json), [after/measurement.json](../runs/s-inspection-improve-2026-10-26/after/measurement.json)의 집계다. 각 JSON에 입력 경로와 SHA-256, 단위별 상세 결과 경로를 기록했다.

| 단위 | 전체 대상 | 과거 prepared 적격 | 현재 기준 검사 통과 | 개선 후 검사 통과 | 과거 비검사 관문 기록까지 재사용한 조건부 적격 |
|---|---:|---:|---:|---:|---:|
| aq-024-6f6781246415 | 975 | 179 | 187 (19.18%) | 910 (93.33%) | 179→899 |
| aq-017-9703bbce0c43 | 979 | 183 | 191 (19.51%) | 914 (93.36%) | 183→903 |

과거 준비 적격과 이번 기준 검사 통과가 다른 이유는 컴파일·크기 관문을 새로 실행하지 않았기 때문이다. 기존 `compile-r1cs failed` 기록은 각각 39/40개이며 수정하거나 성공으로 간주하지 않았다. 새로 검사 통과한 대상 전체의 재렌더링 wrapper는 기존 파일과 일치했다(910/910, 914/914; 각 after 단위 JSON의 `rendered_matches_existing`).

아래는 주요 배제 사유의 **발생 수**다. 한 대상에 여러 사유가 있으므로 합계는 배제 대상 수와 다르다. 전체 문자열별 전/후 집계는 위 measurement.json의 `exclusion_reasons`에 있다.

| 검사 사유 | aq-024 전→후 | aq-017 전→후 |
|---|---:|---:|
| `unsupported expression token [` | 712→0 | 712→0 |
| compile-time 변수 배열 미지원 | 265→0 | 263→0 |
| unknown compile-time value 전체 | 829→1 | 654→1 |
| for 초기화 / 갱신 형식 | 25/4→0/0 | 24/3→0/0 |
| binding/component 재대입 / 같은 슬롯 중복 | 8/4→0/0 | 7/4→0/0 |
| component 배열 직접 초기화 | 53→0 | 53→0 |
| 함수 안 미지원 문장(새 진단) | 0→43 | 0→44 |
| 정수 나눗셈 `\` suffix(새 진단) | 0→18 | 0→18 |
| parsed root 없음 / identity root 없음 | 713/713→1/1 | 713/713→1/1 |

후속 잔여 진단은 `unknown compile-time value isZeroExternalAmounts` 각 1회, `nUtxoOut` 각 1회, 지원 밖 expression syntax 2/1회다. `\` suffix는 `\ 148 + 1` 11회, `\ 2` 5회, `\ 246 + 1` 2회씩이다. 함수 거부 문구를 signal 사용으로 단정하지 않는다. 실제 Poseidon 상수 함수는 미도달 fallback의 `assert(0)` 때문에도 거부된다.

**RQ-C 템플릿.** 원본 [rq-c-instance-map.json](../runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json)의 SHA-256은 `8ad5d43b51d5ceaab0d95dd83a229f45fdc2a2020485a21ccb3b1a43fb4aab85`. 아래 다섯 템플릿은 aq-024의 직접 매핑이고, aq-017에서는 같은 이름의 하위 조각이다. 수치는 각각 해당 단위의 baseline/after JSON에서 template 이름으로 집계했다.

| 템플릿 | aq-024 검사 통과 전→후 | aq-017 하위 조각 전→후 | 남은 제한 |
|---|---:|---:|---|
| ZAccountBlackListLeafInclusionProver | 0→0 | 0→0 | 함수 내부 assert 등 미지원 |
| DataEscrowElGamalEncryption | 0→0 | 0→0 | 정수 나눗셈 `\ 148 + 1` |
| RewardsExtended | 0→1 | 0→1 | 과거 컴파일 실패 기록, 재컴파일 안 함 |
| ZoneIdInclusionProver | 0→1 | 0→1 | 과거 컴파일 실패 기록, 재컴파일 안 함 |
| BabyJubJubSubOrderTag | 2→2 | 2→2 | 이미 검사 적격 |

aq-017의 직접 매핑은 `TrustProvidersKyt`와 `ZSwapV1`이며 둘 다 0→0이다(`ZSwapV1`은 두 버그 항목이 같은 템플릿을 가리킴). 따라서 직접 매핑 중 **새 검사 통과는 aq-024의 RewardsExtended·ZoneIdInclusionProver**다. 완전한 새 준비 적격성까지 확인됐다는 뜻은 아니다.

**보존·검증.** [differential-all-eligible.json](../runs/s-inspection-improve-2026-10-26/differential-all-eligible.json): 기존 prepared 적격 1,270개/16개 aq 단위, 차이 0. [differential-two-units.json](../runs/s-inspection-improve-2026-10-26/differential-two-units.json): 현재 기준 검사 적격 187+191=378개, 차이 0. 두 집합의 중복을 제거하면 1,286개를 보호했다. 다른 단위의 과거 부적격 대상 전체는 새 기준으로 재검사하지 않았다.

비교 대상은 definition·inspection·target_id·source_fingerprints를 직렬화한 결정적 fragment 명세와 기존/재생성 wrapper 바이트다(`examples/s_inspection_audit.rs:225–255`). 실행 시간·출력 폴더·컴파일 산출물은 명세 비교에서 제외한다. 원래 main 파일은 fragment wrapper와 형태가 다르므로 기존 main 바이트 및 전/후 렌더링 바이트 각각을 비교한다. 하나라도 명세/식별자/래퍼/적격성 차이가 나면 실패 종료한다(`scripts/s_inspection_measure_20261026.py:19,201`). 신규 통과 수가 실패를 덮지 않는다. 차이·누락을 넣은 15개 Python 합성 검사도 통과했다.

최종 `cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test` 통과. Rust 테스트 합계 **384 passed, 0 failed, 24 ignored, 24 filtered**. filtered 24개는 요청된 J 호출 테스트 목록 그대로이며 [cargo-command-reference.json](../runs/s-inspection-improve-2026-10-26/cargo-command-reference.json)에 보존했다. 검사 도구 example 테스트 4개도 통과했다. 단계별 집중 검사는 배열 모듈, 함수, 컴포넌트 순서로 통과했고 최종 전체 검사에 포함된다. 초기 clippy 경고 1건을 수정한 뒤 최종 재검사가 통과했다.

모든 cargo/측정 실행은 nice 19, 단일 cargo 작업·단일 테스트 스레드다. fmt에는 `-j` 옵션이 없어 `CARGO_BUILD_JOBS=1` 환경만 적용했다. 아래 시각은 **2026-10-26 UTC**이며 모두 활성 판정과 겹친 **CPU contention**으로 기록한다. 전체 cargo 19회 및 단위 측정 36회의 개별 시작/끝·명령·종료 상태·원본 SHA는 [timings.json](../runs/s-inspection-improve-2026-10-26/timings.json)에 있다.

| 최종 실행 / 측정 | 시작 UTC | 종료 UTC |
|---|---|---|
| fmt | 15:00:42 | 15:00:44 |
| clippy | 15:01:02 | 15:01:14 |
| cargo test (J 24개 제외) | 15:01:36 | 15:04:13 |
| example 테스트 | 15:04:28 | 15:04:30 |
| 최종 build | 15:05:35 | 15:05:37 |
| 기준 aq-024 / aq-017 | 14:34:01 / 14:36:30 | 14:36:30 / 14:38:53 |
| 개선 aq-024 / aq-017 | 15:06:04 / 15:10:03 | 15:10:03 / 15:13:59 |
| 전체 기존 적격 기준 / 개선 | 14:40:28 / 15:15:52 | 14:40:42 / 15:16:06 |

내장 디스크는 시작 24.64 GiB, 마무리 확인 약 23.8 GiB였다. 도구는 15 GiB 미만에서 중단하도록 검사한다. baseline의 큰 중복 진단 문자열은 이번 새 출력에서만 범주·횟수·원본 진단 SHA로 축약했다. 보존 비교 필드와 모든 적격 수의 불변은 각 baseline 폴더의 `compaction-receipt.json`에 기록했다. 기존 입력 파일은 변경하지 않았다.

**바이너리·재현.** 새 `target/debug/zkfDO` SHA-256: `30b839488f7f67849e3887bc997288fdad35ccd19bdfb4a102e79442dcff27f2`. 검사 도구 `target/debug/examples/s_inspection_audit`: `d9475d79b25d3e9d81782abf981a3de8621c27328452d2db7c91656301bcf699`. [binary-hashes.json](../runs/s-inspection-improve-2026-10-26/binary-hashes.json)에 기록했다. 새 바이너리는 **대상 검사/준비 전용**이며 판정에 사용하지 않는다. 판정에는 동결 v2.2 `runs/n6-j4c-2026-10-17.noindex/zkfDO-v2.2`(SHA-256 `c78166319c0e12a62d89697ec0b248ef916e236961db9f890ec992f53c59a835`)를 그대로 사용한다. 빌드 산출물은 target/에만 두었다.

저장소 루트에서 재실행한다. 아래 출력 이름은 새 폴더여야 한다. 입력 경로는 인자로 변경할 수 있다. 체크 래퍼는 지정된 24개 제외 목록·단일 작업·디스크 제한을 적용한다.

```sh
nice -n 19 python3 -B scripts/s_inspection_run_20261026.py --label rerun-fmt -- cargo fmt
nice -n 19 python3 -B scripts/s_inspection_run_20261026.py --label rerun-clippy -- cargo clippy -j 1 --all-targets --all-features -- -D warnings
nice -n 19 python3 -B scripts/s_inspection_run_20261026.py --label rerun-test -- cargo test -j 1
nice -n 19 python3 -B scripts/s_inspection_run_20261026.py --label rerun-example-test -- cargo test -j 1 --example s_inspection_audit
nice -n 19 python3 -B scripts/s_inspection_run_20261026.py --label rerun-build -- cargo build -j 1 --bins --example s_inspection_audit
nice -n 19 python3 -B scripts/s_inspection_measure_20261026.py self-test
nice -n 19 python3 -B scripts/s_inspection_measure_20261026.py measure --binary target/debug/examples/s_inspection_audit --preparation-summary runs/n6-a1b-2026-10-08/preparation-summary.json --mapping runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json --output runs/s-inspection-improve-2026-10-26/rerun-after
nice -n 19 python3 -B scripts/s_inspection_measure_20261026.py preserve-all --binary target/debug/examples/s_inspection_audit --output runs/s-inspection-improve-2026-10-26/rerun-preserve
nice -n 19 python3 -B scripts/s_inspection_measure_20261026.py compare --before runs/s-inspection-improve-2026-10-26/baseline/measurement.json --after runs/s-inspection-improve-2026-10-26/rerun-after/measurement.json --output runs/s-inspection-improve-2026-10-26/rerun-differential-two.json
nice -n 19 python3 -B scripts/s_inspection_measure_20261026.py compare --before runs/s-inspection-improve-2026-10-26/preserve-baseline/measurement.json --after runs/s-inspection-improve-2026-10-26/rerun-preserve/measurement.json --output runs/s-inspection-improve-2026-10-26/rerun-differential-all.json
```

**확인한 것**

- 두 단위 검사 통과 증가, 직접 매핑 템플릿 2종의 새 검사 통과, 명시된 기존 대상 전체의 명세·래퍼 바이트 보존, 필수 검사 통과를 확인했다.
- J·zkFuzz·새 회로 컴파일을 실행하지 않았고, 동결 바이너리 해시는 유지됐다. Git 쓰기·설치·runs 재귀 목록 조회를 하지 않았다.

**추정한 것**

- 조건부 적격 899/903은 과거 비검사 관문 기록을 재사용한 수치다. 새 컴파일 후의 준비 성공 수, 다른 aq 단위의 증가량, S 후보나 J 결과의 변화는 아직 확인하지 않았다.
- 실행 시간은 CPU contention과 디스크 상태의 영향을 받는다. 전/후 시간 차이를 구현 자체의 성능 차이로 해석하지 않는다.
