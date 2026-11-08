# A inference 원본 준비 가능성 시험

2026-10-29. **A 개발 자료의 준비·검증 운영 시험**이다. W/S+J의 탐색·효능·비용 우위를 평가하지 않는다. 기존 N5 본 기록·판정을 변경하지 않는다.

대상은 `runs/n6-a1b-2026-10-08/units/inference-original/project/src/circuit.circom`과 `runs/n6-j1-2026-10-09.noindex/base-inputs-v3/inference-original/selected-input.json`이다. 이름이 지정된 프로젝트만 읽기 전용으로 연다. 입력 값은 출력·문서에 남기지 않는다. 컴파일은 Circom O0에서 `--r1cs --sym --wasm`을 사용하고, 생성한 기준 witness를 원본 R1CS에 대해 snarkjs로 검사한다. 기존 O0 쌍 영수증의 R1CS SHA와 같아야 한다.

새 작업 폴더는 `runs/n7-allcost-2026-10-28/a-feasibility-20261029/` 아래다. 설치·Docker·aq 이미지/캐시·B는 사용하지 않는다. `nice 19`, 전체 wall 120초, 관측 프로세스 tree RSS 10 GiB, 시작 내장 여유 30 GiB·실행 중 18 GiB 이상, 단일 무거운 실행. 감독기 출력에 종료·후손 정리·peak·시작/끝 여유를 남긴다. 실패·상한 종료는 준비 불가로만 기록하며 후보 0이나 안전 판정으로 해석하지 않는다.
