# A inference 자동 조각 준비 운영 시험

2026-10-29. A 개발 회로 `inference-original`의 원본 소스 사본에서 기존 F-01 `targets → manifest_for → experiment prepare → experiment plan`을 다시 실행한다. 퍼징·J·판정은 하지 않는다. 이전 W/S 결과를 본 개발 자료이며, 22개 조각 재현과 준비 시간·공간만 점검한다.

소스 트리 SHA, F-01 준비 바이너리, Circom, 설정 파일, worker를 실행 전 JSON 계획에 고정한다. 원본 프로젝트는 읽기 전용이고 새 출력은 `runs/n7-allcost-2026-10-28/a-s-prep-20261029/`에만 쓴다. `nice 19`, 전체 180초, tree RSS 10 GiB, 시작 내장 30 GiB 이상·실행 중 18 GiB 미만 중지, 단일 무거운 실행으로 감독한다. 기록이 불완전하면 대상 수를 0으로 치환하지 않는다.
