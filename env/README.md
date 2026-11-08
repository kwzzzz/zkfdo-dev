# 실행 환경 기록과 Ubuntu 이식 초안

2026-11-05. macOS 도구는 실측했고 Linux manifest는 미작성 템플릿이다. Ubuntu 설치·Linux 실기 실행·AWS 자원 생성은 하지 않았다. 이 문서와 도구 manifest는 N5 플랫폼 개정의 채택 기록이 아니다.

## 현재 호스트와 도구

관측 원본은 `runs/robustness-aws-prep-2026-11-05/tool-environment-observation-v1.json`이다. SHA256은 `adda78b35cfff429a58285006f900ac983e946278e1c52925e9a8940e955090d`이며 관측 시각은 `2026-11-05T03:54:26.625712+00:00`이다. macOS 26.2(build 25C56), Darwin 25.2.0, arm64에서 버전 조회와 파일 해시를 확인했다.

추가 호스트 관측 `runs/robustness-aws-prep-2026-11-05/host-environment-v2.json`은 논리 CPU 10개, RAM 25,769,803,776 bytes(24GiB), `/dev/disk3s5`의 APFS·SSD(`solid_state=true`)·Apple Fabric을 기록한다. diskutil plist 해석은 Python libexpat 오류 뒤 `/usr/bin/plutil` 변환으로 성공했고 최초 오류도 보존했다. 당시 메모리 압박이 있었으므로 이번 tiny smoke의 시간을 성능 자료로 쓰지 않는다.

| 도구 키 | 관측 버전 | 빌드·출처에서 확인한 범위 |
|---|---|---|
| `prepare` | CLI 0.1.0 | F-01 supplement-var-scope 보존 release 바이너리. 정확한 source commit·빌드 명령은 불명 |
| `J` | J v2.3, CLI 0.1.0 | dev/unoptimized+debuginfo. 보존 빌드 명령 있음. 당시 rustc·완전한 source commit 결속은 불명 |
| `J_v24` | J v2.4, CLI 0.1.0 | 선택적 개발 버전. dev, rustc 1.94.1. 최종 소스 파일 해시 목록 있음. 정확한 최종 argv는 불명 |
| `circom` | 2.2.3 | 설치 당시 로컬 소스 경로가 현재 없음 |
| `zkfuzz` | 2.2.1 | 고정 바이너리 `ac2d9d16…ae4edd`, 기록된 소스 `072bf1fbbd1c9ecad58d4f6d2204c3b96e7fec17` |
| `node` | 26.0.0 | Homebrew bottle 설치 기록 |
| `snarkjs` | 0.7.6 | package.json과 CLI 출력 일치. `--version`은 help와 함께 exit 99 반환 |
| `z3` | 5.1.0 | Homebrew bottle 설치 기록 |
| `python` | 3.15.0 | Homebrew interpreter 경로와 해시 |
| `rustc` | 1.94.1 | 현재 toolchain의 `-vV` commit·target·LLVM 기록 |
| `cargo` | 1.94.1 | 현재 toolchain의 `-vV` commit·target 기록 |

전체 경로·SHA256·알 수 없는 값의 이유는 [macOS manifest](../configs/tools.darwin.json)에 있다. Rust shim 대신 실제 toolchain payload의 해시를 기록했다. 실행 파일 해시는 동적 라이브러리나 전체 npm/Python 의존 트리의 해시를 대신하지 않는다. 현재 rustc가 같다는 사실만으로 과거 바이너리의 빌드 당시 rustc를 확정하지 않는다.

보존 prepare/J/circom/zkFuzz는 macOS 바이너리다. Linux에는 플랫폼에 맞는 빌드와 새 해시가 필요하다. `.external/zkFuzz`의 HEAD는 위 기록과 같지만 `src/mutator/utils.rs`가 수정돼 있다. 현재 checkout을 그대로 빌드한 결과를 고정 baseline의 재현이라고 부르면 안 된다.

## manifest와 출력 경로

| 설정 | 동작 |
|---|---|
| `--tools-manifest` | 실행에서 명시한 manifest를 사용 |
| `ZKFDO_TOOLS_MANIFEST` | CLI에서 생략한 경우 선택할 manifest |
| 기본 manifest | 호스트에 따라 `configs/tools.darwin.json` 또는 `configs/tools.linux.json` |
| `ZKFDO_RUNS` | 실행 산출물 루트. 생략하면 저장소의 `runs/` |
| `--output` | 위 루트 아래의 새 작업 경로. 기존 완료 기록을 덮어쓰지 않음 |

manifest의 schema는 `zkfdo-tools-v1`이다. `status=template`, 호스트 플랫폼/아키텍처 불일치, 누락된 도구, 실제 SHA 불일치는 실행 전에 거부한다. [Linux manifest](../configs/tools.linux.json)의 경로·해시·버전은 모두 `null`이며 실행에 사용할 수 없다.

현재 `target`은 `/Volumes/X9 Pro/zkfdo-target-moved-20261027/target`을 가리키는 로컬 symlink다. 이 링크나 macOS 절대 경로를 Ubuntu 배포물에 그대로 넣지 않는다.

## zkFuzz 설정을 실제 입력으로 고정하기

[기본 프로필](../configs/zkfuzz_defaults_2.2.1_v1.json)은 고정 바이너리와 `main.rs`, `input_user.rs`, `mutation_config.rs`의 SHA를 연결한다. 실행기는 소스 기본값 29개에 spec의 base 설정을 적용하고 해당 pass의 seed만 덮어써 **29개 전체가 있는 JSON**을 실제 `--path_to_mutation_setting`에 전달한다. 파일 SHA와 전체 설정을 영수증에 남긴다.

- `seed=0`은 실제 seed를 임의로 정하므로 재현 실행에서 거부한다. zkFuzz에는 `--seed` CLI 옵션이 없다.
- 잘못되거나 없는 설정 파일, 알 수 없는 옵션·필드, 잘못된 타입은 조용히 기본값으로 대체하지 않는다.
- 기본 whitelist는 `IsZero`, `Num2Bits`다. 사용자 파일의 공백·빈 줄을 포함한 실제 줄과 SHA를 기록한다. 엔진이 사용하는 집합의 원소로 비교한다.
- `search_mode != off`이면 unused-output 검사가 실행된다. LessThan·constraint-assert의 실제 비활성화 flags도 기록한다. `--show_stats_of_ast`처럼 퍼징 전에 반환하는 모드는 이 실행 설정 해석기가 지원하지 않아 거부한다.
- 입력 설정과 후보에 기록된 **실행 후 설정**은 별개다. 엔진은 실행 중 ranges/probabilities 등을 바꿀 수 있다. 후보가 없으면 실행 후 값은 미관측으로 남긴다.

seed-only 입력과 명시적 29필드 입력의 합성 대조에서 flag·target output·assignment·실행 후 config가 같았다. 근거는 `runs/robustness-aws-prep-2026-11-05/settings-paired-probe-v1.json`이다. 출력 전에 바뀐 ranges/probabilities 두 필드까지 constructor 기본값을 실측했다고 주장하지 않는다. 합성 개발 확인이며 N5 사례나 성능 측정이 아니다.

## v5 실행 예시와 비교 범위

아래는 인터페이스 예시다. 이 문서를 작성하면서 실행하지 않았다. spec·공간 상한·출력 루트를 먼저 정해야 한다.

```sh
export ZKFDO_RUNS=/absolute/path/to/run-root
export ZKFDO_TOOLS_MANIFEST=/absolute/path/to/configs/tools.darwin.json
python3 -B scripts/run_policy_a_engine_v5.py \
  --spec /absolute/path/to/w.json \
  --peer-spec /absolute/path/to/sj.json \
  --purpose cost-comparison \
  --max-disk-bytes "${JOB_DISK_CAP_BYTES:?set the declared disk cap}" \
  --output w-seed01-v1
```

`--purpose`는 필수다. `cost-comparison`은 `--peer-spec`도 요구하며 initial seed·seed 규칙과 pass별 29개 설정, binary SHA, prime·debug prime·whitelist·검사 flags를 비교한다. 회로·library·파일 배치 경로는 별도 기록한다. peer 영수증은 **해당 pass에 선언된 peer 설정**의 동등성 근거이며 peer를 실제 실행했다는 증거가 아니다.

`discovery`는 peer가 없는 탐색용이다. 여러 탐색 worker를 병렬 배치할 수 있지만 비용 비교 표와 합치지 않는다. `--cpu-affinity`, `--memory-max-bytes`, `--cgroup-root`, 요청별 시간·공간 상한은 실행 전에 정하고 영수증에 남긴다. 메모리 상한에는 자동 기본값이 없다. Linux에서 CPU affinity는 감독기의 scoped 적용으로 복사·해시와 자식 작업까지 포함한다. cgroup 메모리 상한은 command tree에 적용하며 감독기는 OOM 뒤 정리를 위해 밖에 남는다. 영수증의 scope를 보고 해석한다. IMDS 관측은 `--include-imds`를 명시했을 때만 요청한다.

현재 v5는 실행 도중 checkpoint부터 이어지는 in-place resume를 제공하지 않는다. 중단 기록을 보존하고 새 출력 경로에서 새 작업을 시작한다. 완료한 작업과 미완료 작업을 외부 대기열에서 구분하는 재개 방식은 [AWS 설계](../docs/aws_execution_plan_2026-11-05.md)에 적었다.

## Ubuntu 준비 상태

[setup_ubuntu.sh](setup_ubuntu.sh)는 **설치 명령이 있는 미실행 초안**이다. 이 작업에서는 `bash -n`으로 shell 문법만 검사했다. Ubuntu 설치·다운로드·빌드는 실행하지 않았고, 실제 호스트에서 동작이 검증됐다는 뜻이 아니다. 기본 호출은 거부하며 `--apply /absolute/path/to/setup-pins.json`을 명시해야 설치 경로에 들어간다. 필요한 값이나 로컬 소스 SHA가 없거나 틀리면 다운로드·apt·설치 전에 멈춘다. 현재는 완성된 pins 파일이 없으므로 실행할 수 없다.

설치 순서는 고정 archive 다운로드·SHA 확인 → 정확한 apt 패키지 버전 설치 → Python 버전 확인 → 고정 Rust toolchain → Node archive → lock 고정 snarkjs → 명시한 소스 사본의 native build다. apt는 `package=version`, Rust는 정확한 `x.y.z`, Cargo는 `--locked --profile dev|release`, npm은 `ci --ignore-scripts`를 사용한다. 원본 checkout을 빌드하거나 소스를 자동으로 추정하지 않는다. 완료 후에도 Linux fixture와 새 measured manifest 검토가 남으며, `configs/tools.linux.json`을 자동으로 measured로 바꾸지 않는다.

별도로 준비·검토할 pins JSON의 schema는 `zkfdo-ubuntu-setup-pins-v1`이다. 아래 모든 값이 필수이며 `null`, 빈 문자열, `TODO`, floating `latest`는 실행 값이 아니다.

| 키 | 필요한 값 |
|---|---|
| `ubuntu_release`, `architecture` | 실제 Ubuntu VERSION_ID, `x86_64` 또는 `aarch64`. 호스트와 정확히 대조 |
| `workspace`, `min_free_bytes` | 존재하는 부모 아래의 새 절대 경로, 설치·빌드용 여유 공간 관문. 이전 설치 디렉터리는 재사용하지 않음 |
| `apt_packages` | 패키지명→정확한 버전. `ca-certificates`, `git`, `curl`, `build-essential`, `pkg-config`, `libssl-dev`, `cmake`, `python3`, `python3-venv` 필수. 소스에 필요한 추가 패키지도 명시 |
| `python` | 설치 후 interpreter 절대 `path`와 아래 공통 version 필드. 설치기 bootstrap에는 이미 Python 3.12 이상이 필요 |
| `rust` | `toolchain`, `target`, `rustup_init:{url,sha256}`, `rustc`·`cargo` 각각의 공통 version 필드. rustup archive URL도 정확한 판과 target을 선택 |
| `node` | `version`, 공식 archive `url`, `sha256`, `archive_root`, `npm_version`. archive root는 선택한 Linux architecture와 일치 |
| `snarkjs` | `version`, `package_json:{path,sha256}`, `package_lock:{path,sha256}`, 공통 version 필드. root dependency는 해당 snarkjs 정확한 버전 하나. lock v2/3의 의존성 URL·integrity 필요 |
| `source_tools` | `prepare`, `J`, `circom`, `zkfuzz`, `z3` 필수, `J_v24` 선택. 각 도구의 입력은 아래 참조 |

공통 version 필드는 `version_args`(`--version`, `-V`, `-vV`, `-version` 중 하나), `version_output_contains`, `version_exit_code`다. 예컨대 현재 snarkjs 관측은 exit 99였지만 Linux 설치 후 기대값은 선택한 패키지로 다시 확인한다. 설치 뒤 각 실제 바이너리의 SHA·출력·빌드 argv는 새 workspace의 `install-observation.json`에 기록한다. 최초 native 빌드의 결과 SHA는 새 관측값이며 Mac SHA를 복사하지 않는다.

각 source tool에는 `source_dir`, `source_manifest:{path,sha256}`, `source_commit`(불명일 때 `null`과 `source_commit_reason`), `build_profile`, `build_commands`(정확한 argv 배열의 목록), `artifact_path`(사본 내부 상대 경로), 공통 version 필드가 필요하다. 파일 manifest 형식은 아래와 같다. 포함할 모든 소스·lock·local dependency·빌드 스크립트를 열거하고 symlink는 배포 전에 실제 내용으로 처리한다. 설치기는 이 목록의 파일만 도구별 새 사본에 복사하므로 목록 밖 로컬 의존성을 자동으로 끌어오지 않는다.

```json
{
  "schema": "zkfdo-source-files-v1",
  "files": [{"path": "Cargo.lock", "sha256": "실제 64자리 SHA256"}]
}
```

위는 형식 예시이며 단일 Cargo.lock만으로 빌드할 수 없다. Cargo 도구의 명령 형식은 `[["cargo", "build", "--locked", "--profile", "dev", "--bin", "실제대상"]]`처럼 적고 profile과 artifact 경로를 맞춘다. z3의 source snapshot과 정확한 CMake/Make 명령 역시 필수다. 현재 준비/J/circom의 출처 공백, dirty zkFuzz 변경의 반영 여부, Linux 패키지 버전은 미확정이다. 이 공백을 임의의 upstream 최신 버전으로 채우지 않는다. 빌드 argv는 사람이 검토할 입력이며, 명령 배열 자체가 sandbox는 아니다.

현재 초안은 직접 지정한 apt 패키지 버전과 source/archive/npm lock을 고정한다. apt의 전이 의존성·저장소 snapshot, Rust 배포물 closure, 시스템 라이브러리 전체까지 폐쇄적으로 고정한 이미지가 아니다. 엄격한 재현 이미지에는 Ubuntu repository snapshot/AMI·전이 패키지 목록과 결과 해시를 추가로 결속해야 한다. 실패한 설치 workspace와 영수증은 보존하고 재시도는 새 경로를 사용한다.

필요한 순서는 소스 스냅샷 확보 → 의존성 버전/배포물 고정 → Ubuntu native build → 도구 버전/해시 관측 → 합성 fixture 확인 → 새 Linux measured manifest다. `git archive HEAD`만으로는 현재 untracked 도구·실행기와 dirty 변경을 포함할 수 없다. [변경 파일 목록](../docs/uncommitted_inventory_2026-11-05.md)을 기준으로 전체 파일 목록·해시, tracked diff, HEAD, Cargo.lock, 심볼릭 링크 처리를 기록한 별도 스냅샷이 필요하다.

Linux 계측은 RSS·호스트 메모리·cgroup 값을 구별하고 누락된 값을 0으로 바꾸지 않는다. macOS 물리 footprint와 같은 수치라고 간주하지 않는다. 시계는 UTC·monotonic·suspend-aware 경과를 분리한다. Linux 실기와 cgroup/affinity 강제 적용은 실제 Ubuntu에서 확인할 항목으로 남아 있다. N5에 적용하려면 [플랫폼 개정 초안](../docs/n5_amendment_platform_draft_2026-11-05.md)의 사람 채택이 선행해야 한다.

Linux native zkFuzz는 바이너리 SHA가 달라지므로 macOS 기본 설정 프로필의 ready 표식을 그대로 쓸 수 없다. 같은 source 기본값·입력 29필드와 새 바이너리를 결속한 별도 프로필 및 합성 probe 영수증이 필요하다.
