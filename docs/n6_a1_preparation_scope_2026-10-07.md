# N6-A1 준비 범위 고정 (2026-10-07)

- 담당: miiz
- 대상 목록: `docs/n6_targets_a_2026-10-07.json`, SHA-256 `6410b49e50b4da6a565955f6b9a6fa3ed1cd996b7923d96710e28ddfa2cf6758`
- 분모: zkbugs Circom 70건 전부. 준비 대상은 A-D 개발 단위와 A-Q 1단계 24건의 수정 전·후 및 필요한 leave-one-out 리비전이다. A-Q 2단계 21건과 수정 커밋 없는 20건은 이번 준비에서 실행하지 않지만 목록 분모에 남긴다.
- entrypoint: `zkbugs_vars.sh`의 `CIRCOM_CIRCUIT_ORIGINAL`과 Original 입력만 사용한다. Direct는 참고 메타데이터이며 대체 실행하지 않는다.
- 중복 제거: `(프로젝트, 소스 리비전 또는 패치 트리, Original entrypoint, 실행을 바꾸는 library 설정)`이 같은 항목은 한 준비·실행 단위로 묶고 결함 라벨을 모두 연결한다.
- 리비전: 기존 clone을 `cp -c`로 복제한 뒤 checkout한다. 필요한 commit이 기존 clone에 없을 때만 네트워크로 가져온다. lockfile이 동일하면 기존 `node_modules`의 APFS 복제를 재사용하고, 다르면 E-01의 스크립트 비활성화 설치 정책을 적용한다.
- leave-one-out: 공유 fix revision에서 해당 항목의 위치와 겹치는 수정 hunk만 역적용한다. diff, 파일·hunk 범위와 SHA-256을 기록한다. 다른 결함의 수정은 유지한다.
- 도구: F-01 `zkfDO` SHA-256 `f8c9f64defd3993ebd845279bc0a245857e23a1ae759ce175e94f369cdd9f4c1`; circom 2.2.3. instance capture 탐색 상한 900초, capture 600초, wrapper compile 60초, prepare 300초, plan 30초.
- spec: 실행기 v3, W/S 각각 T=600초, 조각 시도 상한 30초, seed `2026100601`, `2026100602`, `2026100603`. 이번 작업은 `preflight-all`까지만 수행한다.
- 외부 include: workspace 밖에서 해석되는 각 파일의 경로와 SHA-256을 기록한다. Original이 없거나 compile·prepare·preflight가 실패해도 Direct로 바꾸지 않고 분모에 실패 사유를 남긴다.
- 측정: 각 단계 시작·종료 UTC 시각과 load average를 기록한다. 다른 무거운 작업을 동시에 시작하지 않는다.
- 디스크: 새 리비전 시작 전 여유가 40 GiB 미만이면 중단한다. capture 값 저장을 확인한 뒤 진단 사본과 `.r1cs/.wasm/.cpp/.dat/.o`를 해시·크기 기록 후 정리한다. clone, 실제 `node_modules`, 통과한 조각 snapshot, JSON과 로그는 보존한다.
- 중단: 대상 목록·고정 도구 해시 불일치, 규칙으로 해결할 수 없는 entrypoint/리비전 선택, 40 GiB 디스크 가드, 원본 자료 변경 감지 때 새 단위를 시작하지 않는다.
- 금지: zkFuzz 실행, 후보 열람·판정, held-out 실행, 프로젝트별 수동 수선, `src/` 변경, commit/push/PR.
