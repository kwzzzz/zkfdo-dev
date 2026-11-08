# AWS 실행 설계 초안 — 2026-11-05

**설계만 작성했다. AWS 자원 생성·설치·실행은 0회다.** 후보 SKU의 사양은 확인했지만 리전, 최종 인스턴스 선택, AMI, 저장 용량, 요금은 아직 확정하지 않았다. 구체 가격은 공식 가격을 확인한 날짜·리전·과금 조건과 함께 후속 판에 기록한다. 이 문서는 N5 플랫폼 개정의 채택을 대신하지 않는다.

## 필요한 자원을 정하는 근거

| 근거 | 관측 | 설계에 반영할 점 |
|---|---|---|
| [N6-A2 중단:28](n6_a2_execute_results_2026-10-08.md) | **W zkFuzz 세 프로세스**가 각각 약15GB. ps RSS는0.2–0.3GB였고 swap41,818MB·CPU0% | 이 수치는 J의 메모리가 아니다. RSS만으로 물리 메모리 압박을 판정하지 않음. 단일 요청과 병렬 슬롯의 용량을 구별 |
| [B6h:19](n6_b6h_disk_cleanup_2026-10-24.md) | 한 미완료 J 요청의 작업103.509GiB + 캐시176.293GiB = **279.802GiB** | 한 요청의 관측 사용량. 엄밀한 최대 상한으로 해석하지 않음 |
| B6h:50·76 | paired 시작 관문 `2×(280GiB + 보존 증거 + 177GiB)` | 보존량0이어도 **914GiB 여유**가 필요했던 별도 운영 관문. 279.802GiB와 혼동하지 않음 |

메모리는 `동시 슬롯별 상한 합 + OS/감독기/도구 여유`로 산정하고 개발 fixture에서 실제 peak와 압박을 확인한다. 저장소는 원본·작업·cache·보존 증거·다른 엔진의 누적분·업로드 대기분을 따로 센다. 1TiB 볼륨이면 충분하다고 단정하지 않는다. B6h 관문을 그대로 적용하는 실행이라면 사용 중인 공간을 뺀 **free bytes**로 통과해야 한다.

## 비용 비교와 탐색의 운영 분리

| 모드 | 배치 | 해석 |
|---|---|---|
| `cost-comparison` | T 계열 미사용. 같은 비교 블록의 W와 S+J를 **같은 전용 인스턴스**에서 사전 고정 순서로 실행. 측정 중 다른 빌드·실험·worker 없음 | 같은 도구·설정·CPU 배치·메모리/디스크 정책과 캐시 조건으로 paired 비용 비교 |
| `discovery` | 서로 독립인 작업을 여러 worker에 병렬 배치 가능. 각 worker의 자원 제한·산출물 prefix 분리 | 탐색 처리량·운영 기록. 위 비용 비교의 속도·비용 우위 표와 합치지 않음 |

discovery는 한 인스턴스에 여러 작업을 함께 배치할 수도 있다. 각 작업의 CPU mask·메모리 상한·디스크/출력 폴더를 분리하고, 상한 합에 OS·감독기 여유를 더해 호스트 용량 안에 들어오는지 먼저 확인한다. 같은 인스턴스에서 cost-comparison 작업과 동시에 실행하지 않는다.

여기서 전용은 해당 실험에 다른 작업을 함께 배치하지 않는 운영 조건이다. AWS Dedicated Host 상품을 선택했다는 뜻은 아니다. 비용 비교용 인스턴스 유형·CPU 아키텍처·vCPU 수·RAM·storage 종류는 가격과 지원 조건을 확인한 뒤 고정한다. ARM/x86 또는 다른 인스턴스의 wall time을 같은 paired 표에 섞지 않는다. CPU 시간도 함께 비용으로 보고한다.

Linux affinity 목록의 번호는 **논리 CPU ID**다. 실행 전 CPU topology와 SMT sibling 관계를 기록하고, 실제 core 배치·sibling 공유 여부·affinity mask를 같은 비교 블록에서 고정한다. r7i.2xlarge의 8 vCPU를 물리 core 8개로 해석하지 않는다.

## 비용 견적의 입력 가정

후보 `r7i.2xlarge`는 **8 vCPU, 64GiB RAM, EBS-only**다. 기본 CPU 구성은 4 core × 2 thread다. 2026-11-05에 확인한 [AWS R7i 사양](https://aws.amazon.com/ec2/instance-types/memory-optimized/)과 [CPU 옵션 표](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/cpu-options-supported-instances-values.html)를 근거로 적었다. 이 후보의 가격이나 실제 작업 완료시간을 확인한 것은 아니다.

| 단계 | 후보 인스턴스 | 대수 | 대당 예상 시간 | 합계 instance-hour | compute 비용 |
|---|---|---:|---:|---:|---|
| 작은 요청 사전 검증 | r7i.2xlarge | 1 | 2시간 | 2 | `2 × 리전별 시간당 요금` — 가격 확인 필요 |
| W 대 S+J 비용 비교 | r7i.2xlarge | 1 | 8시간 | 8 | `8 × 리전별 시간당 요금` — 가격 확인 필요 |
| 독립 discovery | r7i.2xlarge | 2 | 8시간 | 16 | `16 × 리전별 시간당 요금` — 가격 확인 필요 |
| 모두 시행하는 경우 | 같은 후보 | — | — | **26** | `26 × 시간당 요금 + 저장/전송 등` |

시간과 대수는 **예산 산식용 예시 가정**이다. 8시간 안에 대상 전부가 완료된다는 약속이나 실측 ETA가 아니다. discovery 두 대는 비용 비교가 진행 중인 인스턴스에 작업을 얹는 구성이 아니다. EBS 용량/성능·보존 기간, S3·요청·전송, build/idle/재시도 비용은 별도로 견적한다. EBS-only 사양에 데이터 디스크가 이미 포함돼 있다고 계산하지 않는다.

W/S의 29개 초기 mutation 설정, 실제 pass seed, whitelist, prime/debug prime, static checks와 binary SHA를 비교한다. v5의 peer 설정 영수증은 선언 동등성 검증이며, 두 arm의 실제 실행 영수증이 모여야 paired 결과가 된다. 동적 runtime config는 후보가 있을 때 별도로 관측한다.

## 작업 전달과 결과 보존

```text
사전 고정 job JSON + source/tool/input manifest
                 ↓
동일성·플랫폼·자원·공간 관문을 검사하는 worker
                 ↓
v5 supervisor → 고정 순서 W / S+J
                 ↓
attempt별 상태·자원·설정·판정·파일 SHA manifest
                 ↓
job별 S3 prefix에 산출물과 영수증 보존
```

worker와 S3 업로드 연동은 향후 구현 항목이다. job JSON의 최소 설계는 다음과 같다. `null`은 미확정 값이며 이 예시는 실행할 수 없다.

```json
{
  "schema": "zkfdo-cloud-job-draft-v1",
  "job_id": "development-paired-example",
  "purpose": "cost-comparison",
  "exposure_layer": "development",
  "spec_reference": null,
  "peer_spec_reference": null,
  "source_snapshot_sha256": null,
  "tools_manifest_sha256": null,
  "settings_profile_sha256": null,
  "ubuntu_release": null,
  "architecture": null,
  "ami_id": null,
  "instance_type": null,
  "initial_seed": 2026100601,
  "seed_rule": null,
  "cpu_affinity": null,
  "memory_max_bytes": null,
  "max_disk_bytes": null,
  "max_request_disk_bytes": null,
  "min_free_bytes": null,
  "request_cap_seconds": null,
  "output_s3_prefix": null
}
```

각 spec·input·소스 파일은 경로와 SHA를 연결하고 worker가 시작 전에 검증한다. 현재 작업 트리에는 tracked 수정과 untracked 코드가 있어 HEAD만 옮기면 부족하다. [inventory](uncommitted_inventory_2026-11-05.md)에 따라 새 스냅샷을 만들고 원래 작업 트리는 보존한다. 캐시·instance store는 해당 실행 정책의 단위로 격리한다. 개발 cold 비용 비교의 arm별 격리와 N5의 리비전 단위 공유를 같은 정책으로 취급하지 않는다.

업로드 대상에는 job/attempt 식별자, 도구·소스·입력 해시, argv, 실제29필드 설정과 파일 SHA, stdout/stderr, wall/CPU/peak·감시 값, 종료 사유, 후손 정리 결과, result와 검증 증거를 포함한다. 후보·witness 원문은 제한된 산출물 저장소에 두고 Git에는 경로·해시·판정·시간만 남긴다. 다음 요청이 다시 읽는 증거의 경로·수명은 기존 instance-store 정책에 맞춘다.

파일 해시 확인과 마지막 완료 영수증 저장이 끝나기 전에는 업로드 완료로 표시하지 않는다. 재시도는 새 attempt/prefix를 사용하고 기존 기록을 덮어쓰지 않는다. 감독기 중단·instance 손실·디스크 부족을 정상 완료로 바꾸지 않는다. 연결이 끊긴 작업은 실행 여부·비용이 확정되지 않은 상태로 남겨 조사한다.

현재 v5는 실행 내부 checkpoint 재개를 지원하지 않는다. 대기열은 완료 job을 건너뛰고 미완료 job만 사전 재시도 규칙에 따라 **새 출력에서** 시작하는 방식으로 설계한다. seed·순서·횟수·대표 결과 선택 규칙은 결과 전에 고정하고 모든 시도를 보존한다.

## 비용 기록과 실행 전 결정

가격을 확인할 때 compute의 실행·idle·빌드·재시도 시간, storage 용량/기간과 별도 IOPS·처리량 항목, S3 보존·요청·전송 비용을 나눠 적는다. 비용 비교에는 준비·W/S·J·정리·업로드 구간과 CPU도 포함한다. 시간 상한이나 저장소 정책을 낮춰 빨라진 값을 알고리즘 효과로 보고하지 않는다.

| 실행 전 항목 | 현재 상태 |
|---|---|
| 인스턴스·리전·AMI·가격·계정 예산 | 확인 필요, 자원 미생성 |
| Ubuntu setup와 Linux measured manifest | 초안/템플릿, 실제 설치·빌드 미실행 |
| native 도구와 source snapshot의 완전한 결속 | 준비/J 및 일부 외부 도구의 출처 공백 해결 필요 |
| affinity·메모리 상한·시계·디스크·후손 회수 실기 | Ubuntu에서 확인 필요 |
| worker·S3 업로드·완료/미완료 재개 | 설계 단계 |
| 개발 fixture → 허용된 A → N5 적용 | 앞 단계 확인 후 진행. N5는 별도 사람 채택 필요 |

구체 자원·요금·상한이 정해지기 전까지 이 설계로 AWS 실행을 시작하지 않는다.
