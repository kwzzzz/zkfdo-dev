# E-02 배포 main 컴파일·준비 절차 v2 (2026-10-05)

상태: 실행 전 고정. 담당: miiz. 기한: 2026-10-08. 입력은 E-01 `recovery-v2`의 9개 저장소·329개 entrypoint와 같은 commit, checkout, 설치 결과이다. 의존성을 다시 설치하거나 프로젝트 파일을 고치지 않고 zkFuzz는 실행하지 않는다.

## 사전 역할 분류

entrypoint의 저장소 상대 경로(설정 생성 항목은 설정 파일 경로와 항목명)를 소문자로 정규화한다. 경로 구성요소가 `test`, `tests`, `__tests__`, `test-circuits`, `mock`, `mocks`, `fixture`, `fixtures`, `benchmark`, `bench`, `example`, `examples` 중 하나이거나, 파일명에서 구분자 `-_.`로 분리된 token이 `test`, `mock`, `fixture`, `example`이거나 파일명에 `_tester`가 있으면 `test_mock_harness`이다. 나머지는 `deployment_main`이다. 이 강한 경로 규칙은 측정 결과로 바꾸지 않는다.

`package.json`, `circomkit.json`, `hardhat*.{js,ts,json}`, `Makefile`, `*.mk`, `*.sh`, `*.yml`, `*.yaml`에서 entrypoint 경로 또는 파일명이 나온 위치를 배포 설정·빌드 참조 근거로 별도 기록한다. 참조 유무는 강한 test/mock 판정을 뒤집지 않는다. 모든 329개를 분모에 남긴다.

## 라이브러리 경로 자동 도출

원본 checkout의 위 파일만 정적으로 읽고 실행하지 않는다. Circom 명령의 `-l PATH`, `--library PATH`, `--library-path PATH` literal과 `circomkit.json`의 `include` 문자열 배열을 수집한다. 셸 변수, command substitution, glob, 존재하지 않는 경로는 적용하지 않고 이유를 기록한다. 상대 literal은 설정 파일 디렉터리, 가장 가까운 `package.json` 디렉터리, 저장소 루트를 후보 기준점으로 삼고, 실제 디렉터리만 정규화·중복 제거한다. 근거 파일·줄·literal·기준점을 entrypoint마다 남긴다. 설정 파일 범위 아래 entrypoint에는 그 범위의 경로를 적용하고, 명시적으로 entrypoint를 참조한 명령의 경로도 적용한다. E-01이 이미 자동 생성한 저장소 루트·`node_modules`·회로 디렉터리 경로는 보존한다. 저장소 이름이나 실패 메시지에 따른 예외 경로를 추가하지 않는다.

## 측정과 상한

E-01 120초 compile이 실패 또는 timeout인 `deployment_main`을 같은 Circom 2.2.3, O0 R1CS 옵션과 기존+자동 도출 라이브러리 경로로 120초 재측정한다. setup 상태가 failure여도 그 checkout에서 적어도 한 entrypoint가 E-01 compile에 성공했다면 설치의 부분 산출물을 재사용하되 상태를 `partial_environment_reused`로 명시한다. 성공 entrypoint가 하나도 없는 setup failure 저장소는 `excluded_setup_failure`로 보존한다. E-02의 120초 재측정에서 timeout인 모든 배포 main은 같은 조건으로 600초도 별도 측정한다. E-01에서 이미 timeout이었던 항목도 이 집합에 포함한다. 600초 결과는 120초 열을 대체하지 않는다.

E-02에서 새로 compile 성공한 배포 main은 고정 F-01 바이너리로 instance capture를 포함한 discovery(상한 900초, capture 600초), prepare(300초), plan(30초)을 수행한다. prepare가 300초 timeout이면 동일 discovery·manifest에 대해 새 출력 경로로 900초 민감도를 추가 측정한다. M-01에서 유일한 10만 제약 이상 배포 main으로 분류되고 prepare 300초 timeout이었던 entrypoint도 900초 민감도를 수행한다. 기존 compile 성공 중 이 조건 밖의 항목은 E-01/M-01 결과를 재사용하며 새 성공으로 세지 않는다.

고정 도구는 Circom SHA-256 `8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227`, F-01 zkfDO SHA-256 `f8c9f64defd3993ebd845279bc0a245857e23a1ae759ce175e94f369cdd9f4c1`이다. 원시 출력은 `runs/e02-production-mains-2026-10-05/`에 둔다. 어느 단계도 후보를 생성·실행하지 않는다.

## 중단·정리·보고

도구 해시, 329개 분모, commit 또는 E-01 참조 해시가 다르면 실행 전에 중단한다. 한 entrypoint 실패는 해당 단계의 실패 유형으로 남기고 다른 entrypoint를 계속한다. 경로를 추측하거나 수동 보정하지 않는다.

측정 후 이번 실행이 만든 `.r1cs`, `.wasm`, `.cpp`, `.dat`, `.o`와 `diagnostic-copy` 디렉터리 전체는 경로·SHA-256·크기를 먼저 manifest에 기록한다. diagnostic 사본은 `instance-capture.json`과 `instance-args.json`에 캡처 값이 저장된 경우에만 지운다. E-01 원본 clone과 그 `node_modules`, JSON, log, `.sym`, 고정 바이너리는 보존한다. 결과는 배포 main의 compile/구조 준비 적용성이고 탐지 성능·의미 동등성의 근거가 아니다.
