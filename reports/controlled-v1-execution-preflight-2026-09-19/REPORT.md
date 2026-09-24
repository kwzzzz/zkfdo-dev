# controlled-v1 실행 전 점검

상태: **실행 전 중단**. 계획 생성·zkFuzz 실행 0회. 발견 수와 시간은 여전히 미측정이다.

[`controlled_v1_evaluation_protocol.md`](../../docs/controlled_v1_evaluation_protocol.md)는 plan/run/evaluate 실행 파일의 SHA-256을 `83c5e1ca1d9f4abed46c01b567fa0d8345c5133897f3ee73041f93339020a6d0`으로 고정한다. 현재 `target/debug/zkfDO`는 `85f00150520f1b2cd38cb0418529e6bb62900def2ac83a5405bb8f7df637544b`이다. 프로젝트 빌드 산출물 및 관련 로컬 백업·임시 경로에서 고정 해시의 실행 파일을 찾지 못했다.

고정 구현 커밋 `9a8bb0319a8b4e127f73be5f1fa279eafb9156db`을 격리 디렉터리에서 다시 빌드한 파일은 `022d4e073a50830d2c330671ee91955ad1b25d569c8edaf2681d6104c4dfc6d7`이었다. 원래 프로젝트 경로에서도 미커밋 소스와 기존 실행 파일을 백업하고 해당 커밋의 두 변경 소스 파일을 임시로 사용해 빌드했으나 `7dd7675ed5f5b91d5e441945af7bbd225499a3d9bfd7d1e715c4b44480238611`이었다. 백업 파일은 복원했고 복원 후 `src/corpus.rs` (`c4cd888f…`), `src/experiment.rs` (`77456a2b…`), `target/debug/zkfDO` (`85f00150…`)의 SHA-256을 재검산했다. 기존 미커밋 변경 및 실험 파일은 유지했다.

manifest·계약·prepared report·랭킹 설정과 두 target 소스·wrapper, zkFuzz·Circom·Circomspect의 해시가 고정값과 일치했다. 두 target은 prepared report에서 eligible이고 컴파일에 성공했다. 장비·OS·전원 조건도 일치했다. 사전 검사 스크립트에 현재 실행 파일을 전달한 결과 해시 불일치에서 종료했으며 `runs/controlled-v1` 디렉터리도 생성되지 않았다.

따라서 현재 실행 파일이나 새 빌드의 결과를 **고정된 controlled-v1 결과에 합칠 수 없다**. 실행을 계속하려면 원래 `83c5e1ca…` 파일을 회수하거나, 결과를 보기 전에 실행 파일만 새로 고정하는 별도 실행 프로토콜을 승인해야 한다. 반복 수·대상·전략·예산·seed·판정 기준은 변경할 근거가 없다.
