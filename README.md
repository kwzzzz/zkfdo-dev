# zkfDO 엔진 소스

Circom 회로를 대상으로 하는 퍼징 기반 취약점 탐지 도구의 소스입니다. 이 브랜치에는 판정 엔진, 대상 준비 코드, 범용 파이프라인 드라이버만 들어 있습니다. 보고서, 실험 기록, 평가 자료, 대상 목록은 포함하지 않습니다.

## 구성

- `src/candidate_review/lifting/` — 후보 판정 엔진. 원본 회로의 제약을 바탕으로 후보 신호를 검증하고 판정(위반, 호환, 배제, 판정불가)을 내립니다.
- `src/bin/zkfdo-j-v27.rs`, `src/bin/zkfdo-j-v28.rs` — 판정 엔진의 실행 파일입니다. v2.8은 판정 뒤에 부분 회로 탐색(probe)을 추가로 돌립니다.
- `src/targets.rs`, `src/structure.rs`, `src/candidate_review/` — 대상 준비와 회로 구조 분석입니다.
- `src/instance_capture.rs` — 컴파일러가 낸 인스턴스 정보를 읽는 모듈입니다.
- `src/main.rs`(`zkFDO`), `src/bin/relation_verifier.rs` — 기본 명령과 관계 검사 도구입니다.
- `scripts/run_sj_pipeline_v1.py` — 범용 S→J 파이프라인 드라이버입니다. 대상 준비, 퍼징, 판정, 외부 검사, 원본 보존, 상태표 작성을 한 출력 폴더에서 관리합니다.
- `scripts/run_sj_pipeline_v1_test.py` — 파이프라인 시험입니다.

## 빌드

Rust 도구 체인이 필요합니다.

```
cargo build --release
cargo test
```

## 외부 도구

이 저장소는 아래 도구를 포함하지 않습니다. 각각 따로 설치하고, 파이프라인에는 도구 목록 파일로 경로와 SHA-256을 알려 줍니다.

- circom 2.x
- snarkjs 0.7.x
- Node.js
- z3
- zkFuzz (상위 프로젝트)

도구 목록 파일의 형식은 다음과 같습니다.

```json
{
  "schema": "zkfdo-tools-v1",
  "platform": "darwin",
  "architecture": "arm64",
  "status": "ready",
  "tools": {
    "circom": {"path": "/absolute/path/circom", "sha256": "<64자리 16진수>", "version": "2.2.3", "role": "compiler", "optional": false}
  }
}
```

## 파이프라인 실행 예

```
python3 scripts/run_sj_pipeline_v1.py \
  --entrypoint <main.circom 경로> \
  --base-input <기준 입력 JSON> \
  --project-root <프로젝트 루트> \
  --library-path <라이브러리 경로> \
  --tools-manifest <도구 목록 JSON> \
  --out <새 출력 폴더> \
  --corpus-layer development \
  --dry-run
```

`--dry-run`은 계획만 기록하고 엔진을 시작하지 않습니다. 출력 폴더는 새 폴더여야 하며, 끝난 실행의 폴더는 재사용하지 않습니다. 같은 폴더는 중단된 실행을 이어 갈 때만 씁니다.

## 상태

연구 프로토타입입니다. 아직 정식 배포 버전이 아니고, 인터페이스와 출력 형식이 바뀔 수 있습니다. 실험 결과는 이 저장소에 포함하지 않습니다. 실행 시간은 개발 환경에서 잰 값이며 성능 결과로 쓸 수 없습니다.

## 라이선스

MIT 라이선스입니다. 자세한 내용은 `LICENSE` 파일을 봐 주세요.
