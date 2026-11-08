# 플랫폼별 zkFuzz 기본설정 프로필

`scripts/zkfdo_zkfuzz_config_v2.py`는 manifest의 `tools.zkfuzz.defaults_profile_path`를 읽는다. 선택적으로 `defaults_profile_sha256`도 검사한다. Linux에서는 명시 경로가 필수이며 Mac 기본 파일로 대체하지 않는다. `arm64/aarch64`, `amd64/x86_64`는 같은 아키텍처 이름으로 처리한다.

`tools.linux-aarch64_v2.json`과 `zkfuzz_defaults_2.2.1_linux-aarch64_v1.json`은 **실행 불가인 빈 틀**이다. 2026-11-08 확인 당시 Docker `desktop-linux`의 `/Users/miiz/.docker/run/docker.sock`이 없었다. daemon 시작·이미지 pull·새 Linux probe는 실행하지 않았다. `runs/docker-linux-2026-11-05/out/`의 예전 임시 프로필은 Mac probe를 유지한 사본이므로 Linux attestation으로 승격하지 않는다.

다음 Linux 검증에서는 기존 파일을 고치지 않고 새 버전을 만든다.

1. Linux 안에서 실행할 zkFuzz 바이너리와 실제 소스 3개(`main.rs`, `input_user.rs`, `mutation_config.rs`)의 SHA256을 기록한다. 네이티브 바이너리·소스 기본값·기본 whitelist·semantic defaults를 같은 프로필에 결속한다.
2. 합성 fixture에 같은 비영 seed를 사용해 seed-only 입력과 기본값 29필드를 모두 명시한 입력을 각각 실행한다. 원시 후보·로그·설정·관측은 새 ignored `runs/` 경로에 둔다. 두 관측은 `status=completed`, `measurement_valid=true`, `cleanup_complete=true`여야 한다.
3. `zkfuzz-settings-paired-probe-v2` 영수증에 `platform`, `architecture`, `binary_sha256`, `equivalent=true`, `checks`의 `5_flag`, `6_target_output`, `7_assignment`, `runtime_config` 네 개 성공 여부를 기록한다. `observations`에는 두 관측의 `{path, sha256}`, `settings`에는 seed-only·expanded 순서로 두 설정의 `{path, sha256}`을 둔다. 관측마다 `binary.sha256`과 단일 합성 후보의 `{path, sha256, mutation_config}`를 넣는다. validator가 영수증뿐 아니라 후보의 비교 필드·runtime 설정도 다시 확인한다.
4. 새 `zkfuzz-defaults-v2` 프로필의 `status=ready`, `attestation.status=passed`, `attestation.binary_sha256`, `attestation.paired_probe={path, sha256}`를 채운다. 프로필의 플랫폼·아키텍처·바이너리는 probe와 같아야 한다. `constructor_defaults_fully_attested`처럼 증명하지 않은 주장은 추가하지 않는다.
5. 새 measured tools manifest에서 `tools.zkfuzz.defaults_profile_path`와 `defaults_profile_sha256`을 그 프로필에 연결한다. v5.1의 설정 hook은 v2의 `resolve_configuration`, `materialize_settings`, `compare_w_s`를 사용한다. v5와 config v1은 역사 경로로 보존한다.

예시 연결 구조 (null은 실측값으로 채우기 전 실행 금지):

```json
{
  "tools": {
    "zkfuzz": {
      "path": null,
      "sha256": null,
      "defaults_profile_path": "configs/zkfuzz_defaults_2.2.1_linux-aarch64_v2.json",
      "defaults_profile_sha256": null
    }
  }
}
```

원래 Darwin arm64 프로필은 원래 파일 경로에서만 v1 호환으로 읽는다. 이 호환은 다른 플랫폼으로 복사한 v1 프로필을 허용하지 않는다. 새 프로필 준비와 N5 플랫폼 개정 채택은 별개다.
