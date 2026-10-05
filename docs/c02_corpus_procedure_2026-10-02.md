# C-02 프로젝트 선정·정상 준비 조사 절차 v1

담당 miiz · 기한 2026-10-10 · 고정일 2026-10-02. 저장소 검색·선정·컴파일 결과를 보기 전에 작성한다. 고정 시각과 이 파일의 SHA-256은 ignored `runs/c02-corpus-2026-10-02/procedure-lock.json`에 기록한다. 절차 변경이 필요하면 새 버전을 만들고 기존 분모를 보존한다.

1. 출처: (a) GitHub 검색 language:Circom, 별 수 순 상위 200개 저장소, (b) zkbugs 데이터셋의 프로젝트 목록, (c) 2026 SoK(runs/literature 참고)의 프로젝트 목록. 검색 시각과 쿼리를 기록한다.
2. 포함 조건: 최근 커밋이 2025-01-01 이후, main 컴포넌트가 있는 .circom 파일이 하나 이상, 라이선스가 명시됨.
3. 출처별 층을 분리해 기록한다. 기존 개발 자료(inference, zk-email, controlled v1~v3 프로젝트)와 zkbugs/SoK에 실려 있는 "알려진 결함 노출" 프로젝트, 어느 쪽에도 없는 "미노출" 프로젝트를 구분한다.
4. 조건을 만족하는 저장소는 성공·실패와 관계없이 전부 기록한다. 실패도 결과다.

검색은 GitHub repository search `q=language:Circom&sort=stars&order=desc&per_page=100&page=1,2`의 응답 순서를 사용하며 응답 원문·시각·해시를 남긴다. 기본 검색의 fork 처리 등을 임의로 바꾸지 않는다. 200건 미만이면 실제 전체를 쓰고 검색 실패·잘림은 분모 미확정으로 기록한다. zkbugs와 SoK는 프로젝트 URL/저장소 목록만 추출하며 결함 재현·후보·witness는 열지 않는다. 저장소의 canonical URL로 중복 제거하되 각 출처 membership·검색 순위와 프로젝트 계열을 보존한다. 날짜는 조회 시점 default branch HEAD commit의 committer date(UTC, `2025-01-01T00:00:00Z` 이상), 코드는 그 SHA로 고정한다. 라이선스 API와 명시적 license 파일/선언을 근거로 하며 불명은 `unknown`으로 남긴다. 주석을 제외한 `component main` 선언의 모든 경로를 entrypoint 분모로 남기고 test/example/vendor 여부도 경로 정보로 보존한다. 확인 불가·제외 저장소도 이유와 함께 목록에 둔다.

노출은 독립적인 `development_used`·`known_bug_listed` 플래그를 보존한다. 요약의 배타적 층은 개발 사용 → 알려진 결함 목록 → 목록상 미노출 순으로 정하고, 출처/계열 식별이 불명확하면 `unknown`으로 둔다. 여기서 미노출은 지정 목록과 기존 노출 기록에서 일치가 없다는 뜻이며 세계적으로 알려지지 않은 결함·독립 일반화를 보장하지 않는다. 이번 소스 준비 열람도 새 노출 이력으로 남긴다.

정상 준비는 수정·의존성 설치 없는 기준 실행이다. 저장소 checkout, 그 안에 이미 존재하는 `node_modules`와 `node_modules/circomlib/circuits`를 고정된 include 후보로 사용하고 그 목록을 기록한다. 소스·include 수동 수선이나 설치를 수행하면 별도 재시도·수동 개입으로 남기며 최초 결과를 대체하지 않는다. Circom 2.2.3 기본 최적화(O1), bn128에서 원본 `--r1cs` → 기존 `targets` 자동 탐색/고유 wrapper 생성 → `experiment prepare --strategy small-first` → `experiment plan --strategy small-first` 순으로 실행한다. zkFuzz와 분석기 경로는 존재하지 않는 차단 경로로 지정하며 run/lift/후보 생성·semantic 분석은 호출하지 않는다. wrapper validation과 prepare의 재컴파일 비용·호출 위치 수·고유 컴파일 단위 수를 구분한다.

수집/clone 호출 상한 120초, 원본 컴파일 120초, targets/prepare 각각 entrypoint당 wall 300초(내부 도구당 60초), plan 30초, 동시 entrypoint 작업은 최대 2개다. timeout·미시작·불명은 성공으로 바꾸지 않고 보존한다. 메모리/디스크 부족이나 외부 API 제한은 정확한 차단 단계로 기록하며 대상을 성공 사례로 교체하지 않는다. 명시적 컴파일 성공 분모는 전체 포함 entrypoint, 완전 자동 준비 성공은 탐색 미지원 없음·전체 고유 단위 준비·plan 성공을 모두 요구한다. 부분 준비는 별도 상태다. 저장소별 any/all 성공률과 entrypoint 성공률, 출처/노출 층별 분모, 제약 수(10만 이상 포함) 및 결측을 함께 보고한다. 컴파일 가능한 집합에만 조건부로 계산한 비율은 전체 비율과 구분한다.

클론·산출물·원문·원시 로그는 ignored `runs/c02-corpus-2026-10-02/`, 공유 요약·값 없는 JSON은 `docs/c02_corpus_results_2026-10-02.{md,json}`에 쓴다. zkFuzz는 이번 작업에서 한 번도 실행하지 않는다. `src/candidate_review/lifting/`, 고정 자료·기존 판정은 수정하지 않으며 commit/push/PR도 하지 않는다.
