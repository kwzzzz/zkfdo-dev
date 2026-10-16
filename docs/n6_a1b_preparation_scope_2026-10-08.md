# N6-A1b A 재준비 범위 (2026-10-08)

담당은 miiz다. 이 문서는 재준비 결과를 열기 전에 대상·절차·중단 조건을 고정한다.

- 고정 대상 목록은 `docs/n6_targets_a_2026-10-07.json`, SHA-256 `6410b49e50b4da6a565955f6b9a6fa3ed1cd996b7923d96710e28ddfa2cf6758`이다. 70건 배치와 A-D 12개·A-Q 1단계 41개 revision 단위는 바꾸지 않는다.
- 준비 우선순위는 zkbugs `scripts/download_sources.sh`의 공식 clone·checkout·호환 패치·의존성·Original entrypoint 생성 절차다. 저장소 설치 스크립트는 실행하지 않는다. 공식 절차 실패 때만 E-01 자동 설치 정책을 사용한다.
- commit은 full SHA 직접 fetch를 허용한다. 원격에서 해석되지 않는 Panther의 짧은 fix 11개는 `fix_commit_unretrievable`로 보존하고 vulnerable revision만 RQ1에 포함한다. 수정 전·후 쌍이 없으므로 RQ-C에서는 제외한다.
- 각 단위는 materialization, setup, discovery·prepare·plan, W/S preflight 상태와 준비 절차 종류를 기록한다. 공식 patch, 생성 entrypoint, 설치 결과와 workspace 밖 include는 경로·SHA-256으로 고정한다.
- F-01 `zkfDO` SHA-256은 `f8c9f64defd3993ebd845279bc0a245857e23a1ae759ce175e94f369cdd9f4c1`, circom 2.2.3 SHA-256은 `8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227`이다. discovery 상한 900초, prepare 300초, plan 30초를 유지한다.
- W/S spec은 T=600초, S 시도 상한 30초, seed `2026100601`, `2026100602`, `2026100603`을 유지한다. 새 queue는 `preflight-all`까지만 실행하며 후보 탐색과 campaign `execute`를 하지 않는다.
- A1의 W preflight 실패 7개와 discovery 오류 8개는 기존 stderr와 새 stderr의 핵심 오류 코드·파일·줄을 비교한다. 조사로 프로젝트 소스를 고치지 않는다.
- 새 revision 준비 전 여유 공간이 40 GiB 미만이면 중단한다. capture 값 저장을 확인한 컴파일 산출물과 진단 사본만 경로·SHA-256·크기 기록 후 지운다. clone, 실제 `node_modules`, 통과한 조각 snapshot, JSON·로그는 보존한다.
- 결과를 보고 대상·예산·seed를 바꾸지 않는다. `src/`, N6-A1 고정 목록·보고서·원시 기록을 수정하지 않고 commit·push·PR을 하지 않는다.
