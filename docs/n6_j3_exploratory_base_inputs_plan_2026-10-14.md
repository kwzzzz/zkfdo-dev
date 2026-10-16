# N6-J3 기준 입력 탐색층 계획 (2026-10-15 KST 작성)

상태: **계획만 작성**. 의존성 설치, 입력 재수집, witness 생성, J 재판정은 하지 않았다. [N6-J3 지시](../runs/handoff/n6_j3_instruction_2026-10-14.md)의 SHA-256 `ad045c202f810e308bec73df2b2dbf90135e7952bd175cc514a46723840aff5a`를 확인했다. 이 계획은 [N5 고정 프로토콜](n5_evaluation_protocol_v1_2026-10-06.md)의 결과를 고치지 않는다. 공식 A J의 `base_input_unavailable`과 B J의 향후 준비 실패는 원래 분모에 그대로 남긴다.

## 1. 범위와 근거

- 공식 기준 입력 순서는 (a) zkbugs `input.json`, (b) 같은 entrypoint의 L-시리즈 기준 입력, (c) 커밋 JSON, (d) 원본 프로젝트 테스트·입력 도구, (e) 모두 0 입력이다. 채택에는 정직 witness 생성과 원본 R1CS의 Rust·snarkjs 검사가 모두 필요하다. (d)의 설치 재시도는 N5 J 6항에 따라 **새 버전의 탐색층**에서만 한다.
- A의 최종 [기준 입력 index v3](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/index.json)(SHA-256 `18ad0bee4278fd77f94b11c354e531a31a4a5d2c0f96c9bd87d7e17c850d1508`)와 [리비전 manifest v2](../runs/n6-j1-2026-10-09.noindex/revision-manifest-v2.json)(SHA-256 `f059fe7d6aa21234168b7867537f069ec980c45c2c025184cbc12e169f687441`)를 대조했다. 27개 중 15개가 기준 입력 부재다. 아래 15개는 Banyan 2개와 A-Q 13개 전부다. 초기 `base-inputs/`가 아니라 최종 `base-inputs-v3/`를 근거로 썼으므로 aq-037·039·040도 포함한다.
- B 본 실행은 [결과](n6_b2_execute_results_2026-10-12.md)상 S 후보 107건 중 rarimo 70건(22/24/24), panther 12건(4/4/4)이다. 두 프로젝트의 B (d) 실패 가능성을 우선 조사한다. B의 실제 기준 입력 결과는 아직 없으므로 A 실패를 B 판정으로 옮기지 않는다. zk-regex는 이 범위에서 A 대상이다.
- `base-inputs-v3`의 `selection.json`에는 단계별 실패 코드와 프로젝트 명령·종료 코드·오류 종류가 남았지만 테스트 stdout/stderr의 원문은 보존되지 않았다. 따라서 아래 `module_missing`의 정확한 모듈명은 로그 한 줄의 직접 인용이 아니다. 원본 테스트의 import 경로와 로컬 파일 존재 여부를 별도 정적 근거로 적는다. 새 탐색층도 원문 대신 종료 코드·오류 종류만 값 없이 보존한다.

## 2. A 판정 불가 15개: 단계별 원인과 다음 조치

표의 (c) `키 불일치`는 발견된 커밋 JSON의 최상위 키가 main 입력 키와 달랐다는 뜻이다. (e)의 `witness 실패`는 0 입력으로 정직 witness를 만들지 못한 것이며 회로의 결함 판정은 아니다. 모든 행의 현재 상태는 `base_input_unavailable`이다. 각 근거는 해당 [최종 선택 기록 디렉터리](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/)의 `<리비전>/selection.json`이다.

| 리비전 | (a) zkbugs | (b) L | (c) 커밋 JSON | (d) 프로젝트 테스트·도구 | (e) 0 입력 | 필요한 조치 |
| --- | --- | --- | --- | --- | --- | --- |
| `banyan-vulnerable` | 연결 항목 없음 | 같은 경로 입력 없음 | Git/커밋 provenance 없음 | 같은 main 테스트·도구 없음 | witness 실패 | 원본 입력과 취약 커밋의 검증 가능한 연결을 먼저 확보하고, 같은 entrypoint 검사를 새 탐색층에서만 수행. |
| `banyan-fixed` | 연결 항목 없음 | 같은 경로 입력 없음 | Git/커밋 provenance 없음 | 같은 main 테스트·도구 없음 | witness 실패 | 수정 커밋의 출처·입력 연결을 독립 확인한 뒤 같은 검사. 취약판 입력을 무검증 전용하지 않음. |
| `aq-006-1680f955c185` (JWT) | `input.json` 없음(1항목) | 없음 | 키 불일치 2·JSON 무효 2 | `tooling/cli.ts` exit 1; 필수 비밀 환경값 5개 부재 | witness 실패 | 비밀값 제공이 필요하므로 이번 설치·재수집 대상에서 제외. 출처·권한을 갖춘 별도 절차가 생길 때만 새 판 검토. |
| `aq-007-0bb83f9eab0f` (JWT) | `input.json` 없음(1항목) | 없음 | 키 불일치 2·JSON 무효 2 | 같은 도구 exit 1·환경값 부재 | witness 실패 | `aq-006`과 같은 제외 조건을 이 리비전에서 별도 확인. |
| `aq-008-9c9e702d061d` (JWT) | `input.json` 없음(2항목) | 없음 | 키 불일치 2·JSON 무효 2 | 같은 도구 exit 1·환경값 부재 | witness 실패 | 두 항목의 입력 provenance를 확인하되 비밀값을 만들거나 문서에 넣지 않음. |
| `aq-011-93343c3cd34c` (Panther) | `input.json` 없음(2항목) | 없음 | 키 불일치 170 | `crypto` 원본 build exit 127, `yarn` 없음 | witness 실패 | 복사본에 고정 Yarn 1과 두 lock 기반 의존성을 설치하고 원본 build·테스트를 재시도. |
| `aq-012-44d0df2ab46e` (Panther) | `input.json` 없음(1항목) | 없음 | 키 불일치 167 | 같은 build exit 127 | witness 실패 | 해당 커밋의 lock 해시를 고정하고 `mainZSwapV1`에 맞는 테스트 재수집. |
| `aq-016-0a7d49b1c135` (Panther) | `input.json` 없음(1항목) | 없음 | 키 불일치 167 | 같은 build exit 127 | witness 실패 | 해당 커밋 복사본에서 `mainZSwapV1` 테스트 재수집. |
| `aq-017-9703bbce0c43` (Panther) | `input.json` 없음(3항목) | 없음 | 키 불일치 170 | 같은 build exit 127 | witness 실패 | 해당 커밋 복사본에서 `mainZSwapV1` 테스트 재수집. |
| `aq-024-6f6781246415` (Panther) | `input.json` 없음(6항목) | 없음 | 키 불일치 170 | 같은 build exit 127 | witness 실패 | 해당 커밋 복사본에서 `mainZTransactionV1` 테스트 재수집. |
| `aq-025-70328d3fd35e` (Rarimo) | `input.json` 없음(1항목) | 없음 | 키 불일치 9 | `queryIdentityTests.js` exit 1, `module_missing` | witness 실패 | lock 기반 npm 의존성을 설치해 재확인. 테스트의 `./tester`가 원본 같은 디렉터리에 없어 설치만으로 해결되지 않을 수 있음; 원본에 있는 대응 테스트를 찾지 못하면 v1 실패로 남김. |
| `aq-026-2bcd7ed6110f` (Rarimo) | `input.json` 없음(1항목) | 없음 | 키 불일치 9 | 같은 테스트 exit 1, `module_missing` | witness 실패 | 해당 리비전에서도 로컬 `./tester` 부재를 별도 확인하고 원본 테스트 provenance를 복구. 임의 링크·입력 수리는 v1에 넣지 않음. |
| `aq-037-94fe3080fc18` (zk-regex) | `input.json` 없음(2항목) | 없음 | 키 불일치 52 | `from_addr.test.js` exit 1, `module_missing` | witness 실패 | npm lock 의존성과 `packages/apis/pkg`, `packages/compiler/pkg` 원본 build 산출물을 복사본에서 준비한 뒤 재수집. |
| `aq-039-0ad3923f2f5b` (zk-regex) | `input.json` 없음(1항목) | 없음 | 키 불일치 52 | 같은 테스트 exit 1, `module_missing` | witness 실패 | 동일 커밋이라도 이 리비전의 선택 기록·검사를 별도 남김. |
| `aq-040-da54d3e7bc8a` (zk-regex) | `input.json` 없음(2항목) | 없음 | 키 불일치 55 | 같은 테스트 exit 1, `module_missing` | witness 실패 | 다른 커밋의 lock과 생성 산출물을 별도 고정해 검사. |

JWT 도구가 요구하는 환경변수 이름은 원본 `tooling/generate-input.ts`의 `RAW_JWT`, `JWK_MODULOUS`, `SALT`, `NONCE_CONTENT`, `BLINDING_FACTOR`다. 값·예시값은 수집하거나 기록하지 않는다. Banyan은 설치 문제가 아니라 항목·커밋 provenance와 동일 main 입력 출처의 부재다. 두 그룹 모두 이번 `v1` 설치 실행 대상에서 제외한다.

### (d) 의존성의 구체적 근거와 고정점

| 그룹·리비전 | 기존 실패 근거 | 준비할 것·제약 | 기존 lock SHA-256 |
| --- | --- | --- | --- |
| Panther `aq-011/017/024` | `selection.json`: `project_build_failed`, `project_package_manager_unavailable`, `crypto/package.json`, exit 127. 원본 build 스크립트가 `yarn build:types && yarn build:ts`를 호출 | Yarn Classic 1.22.22를 도구 위치에 고정; 복사본의 root `yarn.lock`·`circuits/yarn.lock`을 변경 없이 사용. 원본 `crypto`→`circuits` build·테스트 순서 보존 | root `6fa31a8c8ce76de4a8f3f9f00578e602fed87c7740be723239e958d5a57f9301`; circuits `edf4b7df5e83d8886b309d7009f3f3178413f30844be466066de2a313f84e23d` |
| Panther `aq-012/016` | 같은 오류와 build 위치 | 각 리비전의 root lock 사용 | root `80b3ccf01329aff4d01449c5f6d8593f9d08d0bc0cd4f527dfa091264a740f54`; circuits `edf4b7df5e83d8886b309d7009f3f3178413f30844be466066de2a313f84e23d` |
| Rarimo `aq-025/026` | `selection.json`: 테스트 exit 1, `module_missing`. `queryIdentityTests.js`는 `./tester`를 import하지만 그 위치에 파일이 없고 `tests/wasm/tester.js`만 존재 | `package-lock.json` v3로 `npm ci --ignore-scripts` 후 같은 오류인지 확인. 로컬 상대경로 문제는 dependency install로 고쳐졌다고 주장하지 않음 | `cc81f91f1f8773fa226caaea5bbcf4f788ad4914f54f1e99742e12fc93da8a12` |
| zk-regex `aq-037/039/040` | `selection.json`: 테스트 exit 1, `module_missing`. 테스트 import `../../apis/pkg`, `../../compiler/pkg`의 두 생성 디렉터리가 없음 | root `package-lock.json` v3로 `npm ci --ignore-scripts`; 복사본에서 Rust/WASM 원본 build. 두 crate에 원본 `Cargo.lock`이 없으므로 복사본에서 lock 생성·SHA 고정 후 재현 빌드 | `31ee744f016e169be2a2ec3ce5b594459a19c1cc8097d6643c7b9dd9132a20a0` |

Rarimo와 zk-regex의 **정확한** 최초 누락 모듈명은 이전 실행의 stderr가 폐기되어 직접 확인할 수 없다. 위 상대경로 부재는 소스와 파일 존재 검사의 별도 근거다. 설치 후에도 테스트가 실패하면 새 탐색층의 오류를 그대로 기록한다. 원본 테스트를 수정하거나 입력을 손으로 만드는 일은 별도 `exploratory-v2` 절차와 diff·근거 없이는 하지 않는다.

## 3. miiz 터미널 절차 초안 — 이 문서에서는 실행하지 않음

이 명령은 네트워크를 사용한다. **mem20 B가 완료되고 리드가 탐색층 실행 범위를 결정한 뒤** miiz가 자기 터미널에서 수행할 절차다. 기존 source checkout, N5 문서, `base-inputs-v3`, A J 결과는 변경하지 않는다. 새 파일은 무시되는 `runs/n6-j3-2026-10-14.noindex/base-inputs-exploratory-v1/`에만 둔다. 아래 명령의 `cp -cR`은 APFS 복사본을 만들며 복사 대상이 이미 있으면 중단한다.

```sh
REPO=/Users/miiz/Desktop/kwzzzz_zkfr
EXP="$REPO/runs/n6-j3-2026-10-14.noindex/base-inputs-exploratory-v1"
mkdir -p "$EXP/projects" "$EXP/tools" "$EXP/logs"
IDS='aq-011-93343c3cd34c aq-012-44d0df2ab46e aq-016-0a7d49b1c135 aq-017-9703bbce0c43 aq-024-6f6781246415 aq-025-70328d3fd35e aq-026-2bcd7ed6110f aq-037-94fe3080fc18 aq-039-0ad3923f2f5b aq-040-da54d3e7bc8a'
for id in $IDS; do
  src="$REPO/runs/n6-a1b-2026-10-08/units/$id/project"
  test ! -e "$EXP/projects/$id" || exit 1
  cp -cR "$src" "$EXP/projects/$id" || exit 1
done
for id in $IDS; do
  for rel in yarn.lock circuits/yarn.lock package-lock.json; do
    file="$EXP/projects/$id/$rel"
    test ! -f "$file" || shasum -a 256 "$file"
  done
done > "$EXP/source-lockfiles.sha256"
shasum -a 256 -c "$EXP/source-lockfiles.sha256"
```

설치 도구도 탐색층 하위에 고정한다. Node·npm·Rust·circom·snarkjs·wasm-pack의 경로, 버전, 바이너리 SHA와 설치 전후 lock SHA를 실행 기록에 넣는다. 아래 `wasm-pack` 0.13.1은 **탐색층의 제안 고정 버전**이며 원본 프로젝트가 요구한 버전으로 오인하지 않는다. 호환되지 않으면 버전을 조용히 바꾸지 말고 새 탐색층 판을 만든다. npm/yarn 설치와 Cargo crate 조회에는 네트워크가 필요할 수 있다. root의 `install`·`postinstall`을 자동 실행하지 않도록 `--ignore-scripts`를 쓴다.

```sh
npm install --prefix "$EXP/tools" --no-save --ignore-scripts --no-audit --no-fund yarn@1.22.22
export PATH="$EXP/tools/node_modules/.bin:$PATH"
for id in aq-011-93343c3cd34c aq-012-44d0df2ab46e aq-016-0a7d49b1c135 aq-017-9703bbce0c43 aq-024-6f6781246415; do
  (cd "$EXP/projects/$id" && yarn install --frozen-lockfile --ignore-scripts --non-interactive) || exit 1
done
for id in aq-025-70328d3fd35e aq-026-2bcd7ed6110f aq-037-94fe3080fc18 aq-039-0ad3923f2f5b aq-040-da54d3e7bc8a; do
  (cd "$EXP/projects/$id" && npm ci --ignore-scripts --no-audit --no-fund) || exit 1
done
shasum -a 256 -c "$EXP/source-lockfiles.sha256"
cargo install wasm-pack --version 0.13.1 --locked --root "$EXP/tools"
export PATH="$EXP/tools/bin:$PATH"
rustup target add wasm32-unknown-unknown
for id in aq-037-94fe3080fc18 aq-039-0ad3923f2f5b aq-040-da54d3e7bc8a; do
  for crate in apis compiler; do
    (cd "$EXP/projects/$id/packages/$crate" && cargo generate-lockfile && cargo build --locked && npm run build) || exit 1
  done
done
for id in aq-037-94fe3080fc18 aq-039-0ad3923f2f5b aq-040-da54d3e7bc8a; do
  for crate in apis compiler; do
    shasum -a 256 "$EXP/projects/$id/packages/$crate/Cargo.lock"
  done
done > "$EXP/generated-cargo-lockfiles.sha256"
shasum -a 256 -c "$EXP/generated-cargo-lockfiles.sha256"
```

재수집 전에 manifest v2의 **27행을 보존한 새 사본**을 만들고, 위 10개 행에서 원본 `project_root` 아래의 절대경로만 복사본으로 치환한다. `entrypoint_sha256`과 원본 commit은 같아야 한다. `git_repository_path`도 복사본 `.git`로 연결한다. 프로젝트 바깥의 `-l` 경로는 읽기 전용 원래 경로를 유지한다. 리비전별 원본 entrypoint 해시와 lock 목록을 재검산하고 새 manifest의 SHA-256을 기록한다. 그 뒤 동일 [기준 입력 수집기](../scripts/n6_j1_base_inputs.py)(SHA-256 `85674a2fb79dc2791a44b5b3f2daa8a9d8c83b4e080a5890474d9e2de2a97e54`)를 새 출력에만 호출한다. 수집기는 단계 (a)~(e)를 다시 적용하며 선택 입력·witness의 내용은 결과 문서에 적지 않는다.

```sh
EXP=/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-j3-2026-10-14.noindex/base-inputs-exploratory-v1
MANIFEST="$EXP/revision-manifest-exploratory-v1.json"
python3 - <<'PY'
import hashlib, json
from pathlib import Path
repo = Path('/Users/miiz/Desktop/kwzzzz_zkfr')
exp = repo / 'runs/n6-j3-2026-10-14.noindex/base-inputs-exploratory-v1'
src = repo / 'runs/n6-j1-2026-10-09.noindex/revision-manifest-v2.json'
dst = exp / 'revision-manifest-exploratory-v1.json'
assert not dst.exists()
assert hashlib.sha256(src.read_bytes()).hexdigest() == 'f059fe7d6aa21234168b7867537f069ec980c45c2c025184cbc12e169f687441'
ids = set('aq-011-93343c3cd34c aq-012-44d0df2ab46e aq-016-0a7d49b1c135 aq-017-9703bbce0c43 aq-024-6f6781246415 aq-025-70328d3fd35e aq-026-2bcd7ed6110f aq-037-94fe3080fc18 aq-039-0ad3923f2f5b aq-040-da54d3e7bc8a'.split())
manifest = json.loads(src.read_text())
assert len(manifest['rows']) == 27
assert ids <= {row['identifier'] for row in manifest['rows']}
for row in manifest['rows']:
    if row['identifier'] not in ids:
        continue
    old = Path(row['project_root'])
    new = exp / 'projects' / row['identifier']
    assert (new / '.git').exists()
    def remap(value):
        path = Path(value)
        return str(new / path.relative_to(old)) if path.is_relative_to(old) else value
    for key in ('project_root', 'entrypoint_absolute', 'git_repository_path'):
        if row.get(key):
            row[key] = remap(row[key])
    row['preflight_library_paths'] = [remap(path) for path in row['preflight_library_paths']]
    assert hashlib.sha256(Path(row['entrypoint_absolute']).read_bytes()).hexdigest() == row['entrypoint_sha256']
dst.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
PY
shasum -a 256 "$MANIFEST"
for id in aq-011-93343c3cd34c aq-012-44d0df2ab46e aq-016-0a7d49b1c135 aq-017-9703bbce0c43 aq-024-6f6781246415 aq-025-70328d3fd35e aq-026-2bcd7ed6110f aq-037-94fe3080fc18 aq-039-0ad3923f2f5b aq-040-da54d3e7bc8a; do
  python3 /Users/miiz/Desktop/kwzzzz_zkfr/scripts/n6_j1_base_inputs.py --revision-manifest "$MANIFEST" --output-root "$EXP" --identifier "$id" || exit 1
done
shasum -a 256 "$EXP/index.json"
```

새 manifest 자체와 위 재수집 명령·도구 버전의 SHA 목록을 함께 보존한다. 수집기의 기존 27행 관문을 임의로 끄지 않는다. B용 manifest는 B 본 실행 및 mem20 B의 완료된 선택 run과 원본 프로젝트 SHA로 별도 생성한다. A manifest를 B에 전용하지 않는다. B의 공식 기준 입력 수집은 mem20 B의 `state.json.status=completed` 확인 뒤 N5 순서로 먼저 처리하고, 탐색층 비교는 그 공식 결과가 난 뒤에만 한다.

탐색층 실행 기록에는 원본 lock과 생성 Cargo lock의 SHA, 도구 SHA, 새 manifest SHA, 각 리비전의 (a)~(e) 실패·통과, 명령·종료 코드·벽시계, witness/R1CS 두 검사 결과, 출력 파일 경로·SHA만 기록한다. 비밀정보·후보값·입력값·witness값은 보고서에 쓰지 않는다. 재수집 성공이 A J의 준비 실패 2,161건이나 B J의 공식 분모를 줄이지 않는다. 탐색층 J를 별도로 수행하려면 새로운 요청 index·실행 범위·해시를 선행 고정해야 하며 이 계획은 그 실행을 승인하거나 지시하지 않는다.

## 4. N5 부록 문안 초안 — 미반영

> N6-J3의 공식 J 결과 이후, 기준 입력 부재를 설명하기 위한 `base-inputs-exploratory-v1`을 별도로 계획한다. 대상은 A의 Panther 5, Rarimo 2, zk-regex 3리비전과 B에서 같은 계열의 (d) 실패가 실제 확인된 리비전이다. 원본 source·N5 입력 index·공식 J verdict는 변경하지 않는다. 네트워크 의존성은 복사본에 lock 해시와 도구 버전을 고정한 뒤 설치하고, N5의 (a)~(e) 순서 및 정직 witness·Rust·snarkjs 검사를 적용한다. 설치 뒤 얻은 기준 입력과 후속 판정은 탐색층 `v1`로만 보고하며 공식 성능 분모·K5a·RQ-C 결과에 합치지 않는다. JWT의 비밀 환경변수 5개가 필요한 3리비전과 출처 연결이 없는 Banyan 2리비전은 이 설치 범위에서 제외하고 공식 준비 실패로 유지한다. Rarimo의 누락된 로컬 테스트 모듈처럼 설치만으로 복구되지 않는 경우는 실패를 보존하고 수정 절차는 새 판으로 기록한다.

리드 검토·승인 전에는 이 문안을 고정 N5 파일에 추가하지 않는다. 승인하더라도 N5 원본을 덮어쓰지 않고 새 versioned 부록 파일과 그 해시를 연결해야 한다.
