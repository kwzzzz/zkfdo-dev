# A 탐색층: aq 실행기 작성·검증 (2026-10-25)

담당 miiz. **새 실행기 작성 완료, aq J 실행 0회. `validate-only`는 소스 스냅샷 해시 불일치로 차단됐다.** 고정 자료를 수정하거나 검사를 우회하지 않았다. [입력 준비](n6_a_remeasure_aq_inputs_2026-10-25.md), [banyan 실행 방식](n6_a_remeasure_banyan_2026-10-25.md), [N5 개정 8절·10/25 A 기록](n5_amendment_b_judging_2026-10-17.md)을 따른다.

새 스크립트: [scripts/n6_a_remeasure_aq_execute.py](../scripts/n6_a_remeasure_aq_execute.py). SHA-256:

```text
8ad006d8de36cd771218815c171587b8b43255da66d5b13d9003f65235604d78
```

miiz가 나중에 실행할 정확한 명령이다. **현재 소스 해시 관문이 해소되기 전에는 이 명령도 J 시작 전에 중단된다.** 재개할 때 같은 명령을 쓴다.

```sh
cd /Users/miiz/Desktop/kwzzzz_zkfr
python3 scripts/n6_a_remeasure_aq_execute.py --action execute \
  --no-new-revision-after 2026-10-28T15:00:00Z \
  --revisions aq-025-70328d3fd35e aq-026-2bcd7ed6110f \
  aq-011-93343c3cd34c aq-012-44d0df2ab46e aq-016-0a7d49b1c135 \
  aq-017-9703bbce0c43 aq-024-6f6781246415 aq-037-94fe3080fc18 \
  aq-039-0ad3923f2f5b aq-040-da54d3e7bc8a aq-006-1680f955c185 \
  aq-007-0bb83f9eab0f aq-008-9c9e702d061d
python3 scripts/n6_a_remeasure_aq_execute.py --action aggregate
```

리비전 하나의 main·mem20 요청을 원래 queue 순서로 v2.2 전부→v1 전부 처리한 뒤, 원래 scope별 인스턴스 결합·캐시 정리·진행 JSON 한 줄을 기록한다. 두 엔진은 각각 `c7816631…`·`e5cb0184…`로 고정한다. 10/28 24:00 KST 이후 새 리비전을 시작하지 않으며 이미 시작한 리비전은 재개 시에도 끝낸다. 요청마다 저장소 파일시스템의 잔여 15 GiB와 외장 마운트를 확인하고, 공간 부족은 `stop_kind: "space"`로 기록한다.

큰 작업 폴더·캐시·인스턴스 저장소는 `/Volumes/zkfdo-jcache/n6-a-remeasure-aq/j/`, 상태·원본 바이트의 결과 JSON·계측 기록·`progress.jsonl`·`aggregates/`는 `runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/`에 둔다. 완료 요청의 입력·결과·계측 해시를 재검증해 건너뛰며, 계측 저장 직후 중단과 캐시 삭제 중 중단도 재개한다. 작업 폴더·인스턴스 증거는 외장에 보존하고 소유권 표식이 있는 캐시만 해시 목록 기록 후 삭제한다.

진행·집계는 banyan/B6h의 요청 분류를 재사용한다. L1 우선, 비L1 중 자기/실효 배제가 있으면 excluded, 나머지 완료 요청만 unknown이다. 준비 실패·오류·미실행은 별도다. 중단 시 이미 완료된 부분의 작은 JSON 결합은 수행할 수 있으며, 결합/무결성 검사 실패는 분류값을 `null`과 오류로 남긴다. wall 합·평균·최대는 요청별 최종 시도만 포함하고 이전 재시도·검증·결합·정리는 제외한다. 결과 표기는 **A 탐색층**, 배제는 구성 입력 기준이며, 요청 수는 회로 크기와 후보 수에 좌우된다. A 엄격층과 합치지 않는다.

검증 명령:

```sh
python3 -m py_compile scripts/n6_a_remeasure_aq_execute.py
python3 scripts/n6_a_remeasure_aq_execute.py --action validate-only
```

기본 계획은 지정 순서 13리비전, 엔진별 330요청(main 261·mem20 69, W 0·S 330), 합계 660요청이다. 순서별 요청 수/엔진은 `27, 27, 33, 24, 24, 21, 24, 6, 6, 12, 42, 42, 42`다. 입력 13개·준비 index/plan·고정 엔진·마운트 검사는 통과했다. 최종 [validate-only 출력](../runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/verification/validate-only.json)은 `status: invalid`, 종료 코드 2이며 두 엔진 모두 첫 aq-006 소스 트리 불일치에서 차단됐다. 검증 시 내부 잔여 24.88 GiB로 공간 관문은 충족했다. [별도 리비전별 소스 검사](../runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/verification/source-scan-v1.json)에서는 aq-006·007·008이 불일치했고 나머지 10개는 두 엔진 모두 통과했다.

세 불일치 모두 `.git/index`의 stat 캐시 갱신으로 확인했다. aq-006은 68개 경로·Git 객체 ID·mode·flags가 같고 25개 항목의 파일 상태 캐시만 다르다. 원래 materialization 소스의 index 바이트를 **메모리에서만** 대입하면 고정 트리 SHA `96f24705…`가 정확히 복원된다(현재 `251765b7…`). aq-007·008도 같은 대입으로 고정 해시가 복원된다. 기존 스냅샷은 수정하지 않았다. [006 진단](../runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/verification/aq-006-source-tree-drift-2026-10-25.json)·[007/008 진단](../runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/verification/aq-007-008-source-tree-drift-2026-10-25.json).

`py_compile`, 실제 프로세스 생성을 막은 합성 검사 10건(순서·재개·마감·공간·마운트·진행 로그·분류·집계·캐시 삭제 복구), `cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test` 통과. [검증 기록](../runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/verification/checks.json). 기존 스크립트·고정 프로토콜·실행 기록, B 데이터와 hunting 실행은 변경하지 않았다.
