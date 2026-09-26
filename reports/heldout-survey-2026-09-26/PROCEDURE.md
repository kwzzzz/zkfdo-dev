# 독립 평가 후보 조사 공통 절차 (T2b)

작성일: 2026-09-26. **어떤 평가 후보의 소스도 열기 전에** 작성했다. 선정 기준은 고정된 [기준 문서](../../docs/heldout_selection_rubric.md)(SHA-256 `12ba462a…`)를 그대로 따르고, 이 문서는 기준 문서 4단계가 요구하는 "고정 버전 의존성 설치와 기록"을 실제로 어떻게 하는지만 정한다. 선정 기준을 바꾸지 않는다.

## 0. 사전 확인

[preflight.json](preflight.json)에 기록했다. 기준 문서, 제외 목록, 조사용 zkfDO 바이너리, circom, zkFuzz의 SHA-256과 zkbugs revision(`a0eed744…`, `dataset/circom` 변경 없음)이 모두 고정값과 일치했다. 실행 환경은 Node v26.0.0, npm 11.12.1이고, Corepack·Yarn·pnpm은 설치돼 있지 않다.

## 1. 소스 확보

1. zkbugs 설정의 `Project` 주소(원래 저장소)를 `runs/heldout-survey-2026-09-26/repos/<조직>/<저장소>`에 clone한다. 이 clone은 수정하지 않는다.
2. `Commit`과 `Fix Commit`을 `git rev-parse --verify <해시>^{commit}`으로 전체 해시로 푼다. 축약 해시가 여러 커밋에 해당하면 기록하고 2단계에서 탈락시킨다.
3. **공식 패치 판정:** 원래 저장소의 기본 브랜치(`git symbolic-ref refs/remotes/origin/HEAD`)에서 `git merge-base --is-ancestor <fix> origin/<기본 브랜치>`가 성공하거나, `git tag --contains <fix>`에 release tag가 있으면 공식 패치다. 둘 다 아니면 제안 패치로 기록한다. 사용한 브랜치·tag와 명령 결과를 남긴다.
4. 조사할 사본은 `git worktree add --detach runs/heldout-survey-2026-09-26/work/<사례>/vulnerable <취약 커밋>`으로 만든다. 설치는 이 사본에서만 한다. 설치 뒤 `git status --porcelain --untracked-files=no`가 비어 있어야 한다. 추적되는 파일이 바뀌면 그 사실을 기록하고 사본을 다시 만든다.

## 2. 패키지 매니저와 버전 판정

**종류:** 취약 커밋의 lockfile로 정한다.

| lockfile | 종류 |
|---|---|
| `package-lock.json`, `npm-shrinkwrap.json` | npm |
| `yarn.lock` (첫 줄 `# yarn lockfile v1`) | Yarn Classic (1.x) |
| `yarn.lock` (`__metadata:` 항목 있음) | 최신 Yarn (2 이상) |
| `pnpm-lock.yaml` | pnpm |

**정확한 버전의 근거는 아래 순서로 찾고, 처음 찾은 근거를 쓴다.**

1. 취약 커밋 루트 `package.json`의 `packageManager` 필드
2. 최신 Yarn: `.yarnrc.yml`의 `yarnPath`가 가리키는, 저장소에 커밋된 Yarn 실행 파일
3. 취약 커밋의 CI 설정(예: `.github/workflows/*`)에 명시된 매니저 버전
4. lockfile 형식으로 알 수 있는 계열(예: pnpm `lockfileVersion`, Yarn `__metadata.version`, npm `lockfileVersion`)만 알 때는, **그 계열에서 취약 커밋 날짜 이전에 공개된 가장 최신 릴리스**를 쓰고 "추정"으로 표시한다. 날짜와 근거를 기록한다.

- 근거가 하나도 없으면 `dependency-unresolved`(매니저 버전 근거 없음)로 기록한다. **근거 없이 최신 버전을 고르지 않는다.**
- **이 맥에 매니저가 설치돼 있지 않다는 이유만으로 탈락시키지 않는다.** 정해진 버전을 아래 방법으로 내려받아 실행한다.
- lockfile이 없고 저장소에 바이트 고정 사본(예: 커밋된 `circomlib` 디렉터리)도 없으면 `dependency-unresolved`(lockfile 없음)로 기록한다.

**Node:** 이 맥의 Node v26.0.0을 쓰고, 프로젝트가 선언한 Node 버전(`engines.node`, `.nvmrc`, `.node-version`, CI 설정)을 함께 기록한다. Node 버전 때문에만 설치가 실패하면 그 사유를 기록하고, miiz의 확인을 받아 선언된 Node 주 버전으로 한 번 다시 시도한다. 그래도 실패하면 `dependency-unresolved`(Node 비호환)로 기록한다.

## 3. 설치 명령 (설치 스크립트 차단)

처음 보는 저장소의 설치 스크립트는 이 맥에서 임의의 코드를 실행할 수 있으므로 모두 막는다. 매니저마다 막는 방법이 다르다.

| 종류 | 명령 |
|---|---|
| npm | `npx -y npm@<버전> ci --ignore-scripts` |
| Yarn Classic | `npx -y yarn@<1.x 버전> install --frozen-lockfile --ignore-scripts --non-interactive` |
| 최신 Yarn | 커밋된 실행 파일이 있으면 `node <yarnPath> install --immutable --mode=skip-build`, 없으면 `npx -y corepack@<버전> yarn@<버전> install --immutable --mode=skip-build`. Corepack 버전은 처음 필요할 때 한 번 정해 기록하고 모든 사례에 같은 버전을 쓴다 |
| pnpm | `npx -y pnpm@<버전> install --frozen-lockfile --ignore-scripts` |

- 최신 Yarn이 Plug'n'Play로 설정돼 있으면 패키지가 zip 안에 있어 circom이 읽을 수 없다. 이때는 `YARN_NODE_LINKER=node-modules`로 설치하고 그 사실을 기록한다. 버전과 lockfile은 바꾸지 않는다.
- **스크립트를 막아서 필요한 파일이 생성되지 않았다면**(예: include 대상이 설치 스크립트로 만들어지는 파일), 탈락 사유를 `dependency-unresolved`(설치 스크립트 차단)로 남기고 어떤 include와 어떤 패키지의 스크립트가 관련되는지 기록한다. 스크립트를 허용해서 다시 설치하지 않는다.

## 4. 탐색 명령

기준 문서 1절의 조사 명령만 쓴다. `--library-path`에는 설치된 `node_modules` 디렉터리를 적은 순서대로 넣는다(모노레포는 루트, 그다음 해당 패키지). 조사 중에는 zkFuzz, `experiment prepare`, `experiment plan`을 쓰지 않는다.

## 5. 사례마다 기록할 것

기준 문서 5절의 항목에 더해 다음을 `survey.json`에 남긴다.

- 원래 저장소 주소, clone 시점의 기본 브랜치와 HEAD, 취약·패치 커밋의 전체 해시, 공식/제안 패치 판정 근거
- lockfile 경로와 SHA-256, 매니저 종류·버전·버전 근거(1~4번 중 무엇인지), 선언된 Node 버전과 사용한 Node 버전
- 설치 명령 전체, 환경 변수, 종료 코드, 소요 시간, 표준 출력·에러 로그의 SHA-256, 설치된 `node_modules`의 파일 목록 해시
- `--library-path` 순서, 탐색 보고서 경로와 SHA-256

소스 사본, `node_modules`, 설치 로그, 탐색 산출물은 ignored `runs/heldout-survey-2026-09-26/`에 두고, Git에는 해시와 판정만 남긴다.
