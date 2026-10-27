# N6-B6d: B unit 스테이징과 템플릿 입력 동치 대조

작성: 2026-10-20 KST. **E1·E3·E4는 통과했으나 E2가 3/17쌍, 9/107요청에서 실패했다.** 지시 3절의 중단 조건에 따라 새 B 요청 index·요청 파일·시범/전체 실행 명령·N5 개정 기록은 확정하거나 만들지 않았다. J 판정 실행 0건, B 후보 값·판정 값·J 작업 폴더 내용 열람 0건이다. 기존 출력, 원본 clone·S wrapper, 고정 엔진·판정 규칙은 변경하지 않았다.

## 1. 지시와 읽은 자료

지시 전문은 `runs/handoff/n6_b6d_instruction_2026-10-20.md`에 보존했다. SHA-256: `13c7a996d0c0cafda254d196b989c834fbead456e665aeae36c7990d0445741b`. 경로는 저장소 루트 기준이다. 아래 plan 해시는 이번 종료 상태 갱신 **전** 값이다. B 결과 파일은 이번 작업에서 열지 않았다.

| 읽은 파일 | SHA-256 |
| --- | --- |
| `AGENTS.md` | `b0db6aa11075f472931c495f8db3f9156e4e64a153e66ac374777acd38f78f02` |
| `reports/START_HERE.md` | `04761b76a9cb61540dc6873ac6970996f894981cbba0df86801dca1c6f6a5f56` |
| `docs/plan_revision_2026-10-01.md` (종료 갱신 전) | `426f8b8d57b46b2fcf25c6ea0e9df060b480c4364eb6f99a2a214d3b073186a3` |
| `runs/handoff/n6_b6c_instruction_2026-10-19.md` | `7ab08c1cb6dc024cabc3f8eed33bde35fbd992461280a5661e60225a4cf8a739` |
| `docs/n6_b6c_staging_fix_2026-10-19.md` | `033fa7133ec9e2f427e24e41650496cd6a3f15886f4b071776f2b6fdde6eea84` |
| `runs/n6-b6b-2026-10-19.noindex/batch1x-prep.noindex/request-index-v1.json` | `1bfcb71d728fe77ccdec0e8897a5a085ea9d286ed658ea160f6cc9fe1fe83b65` |
| `runs/n6-j1-2026-10-09.noindex/request-index.json` | `35ed44c86545fc3e56d3a671cbe45eae5db69c1d970f5e453c1db60e52225f3c` |
| `scripts/n6_b6b_static_preflight.py` | `cb102e2f1a47380a9200bcd76516daa12d3254a0c5c49b75cefecc9d3e00916c` |
| `scripts/run_n6_j1.py` | `af23186151e1162f352d1a27f9020e3054e20bc461404791846fbb245077bd7c` |
| `scripts/n6_j1_summarize.py` | `6a02f7f6e4c74a3403bd1dc6b2604ff6c15e4f811d86cf4035016ed8910688e8` |
| `scripts/n6_b5_format_pilot.py` | `3b2c7b39dc58dc1bb5aaf86a622b5278848fc590350c99234a79386eb4ae8e48` |
| 고정 v2.2 `8065e2b7:src/targets.rs` | `6dcb6b38ea5c7f01e2fce6846200cab466e51a415251492c63071f9aa3c3b889` |
| 고정 v2.2 `8065e2b7:src/candidate_review/lifting/mod.rs` | `ce89724b7a89031921df38957118f5c5d4a7a1cf3b166746a4e502560daf1d66` |
| 고정 v2.2 `8065e2b7:src/candidate_review/lifting/source.rs` | `b96f8afb5fbcd8bdf8947f7809ad8e3f2b6b1fcf10f689f65947c3bb63bd9a2b` |

고정 엔진의 닫힘 해석은 `targets.rs:989-1035,2923-2967,3015-3043`의 canonical 경로와 include 파일 부모 → 프로젝트 루트 → 순서가 보존된 `-l` 탐색을 사용한다. 템플릿 선언 비교는 `lifting/source.rs:79-125`, main tie-break는 `lifting/mod.rs:1261-1374`에 근거한다. 새 대조기는 닫힘 계산에 고정 Rust 함수 `targets::discovery_dependency_paths`를 직접 호출하고 템플릿 이름 추출은 `source.rs`를 Python으로 모사했다. 엔진 자체는 고치지 않았다.

## 2. 새 스테이징과 바뀐 include

A 원본 index가 지목한 unit의 `project/`, `preparation/` 형식을 따라 17쌍을 `/Volumes/zkfdo-jcache/n6-b6d-batch1x/units/<쌍 id>/`에 일반 파일로 새로 만들었다. `source_root`는 각 unit 폴더다. 107개 요청이 17쌍을 공유한다. 프로젝트 `.circom` 3,872개는 원본과 바이트 SHA가 같고 프로젝트 내부의 원본 clone 절대 include 수정은 **0건**이다. wrapper 사본은 쌍마다 1개, 총 17개이며 원본 clone을 가리킨 절대 include 문자열만 3행에서 unit `project/` 경로로 바꿨다. 줄 수와 다른 모든 줄의 바이트 동일성을 프로그램으로 확인했다. 새 unit 소스 트리의 symlink는 0개다. 고정 엔진의 hint workspace 복사는 `lifting/mod.rs:3908-3931`에서 일반 `.circom` 파일을 복사하고 symlink는 확장자와 관계없이 symlink로 다시 만든다. clone 밖의 변경하지 않은 `-l` 트리는 이 unit symlink 검사 대상이 아니다. 닫힘에 포함되는 비 `.circom` 의존은 발견되지 않았다. 단, 닫힘 밖 Vota 소스의 `.jaz` include 참조 2개는 원본에서도 대상 파일이 없으며 OS 파일 열람 추적은 수행하지 않았다.

다음 표는 전체 17개 include 수정 목록이다. 원본/사본 전체 SHA는 wrapper 바이트 변경을 명시하며, 정확한 절대 경로와 옛·새 include 문자열은 결박된 manifest의 `pairs[].include_rewrites`에 있다.

| 쌍 ID | 수정 행·include 대상 (원본 clone → 새 unit) | 원본 wrapper SHA-256 | 사본 wrapper SHA-256 |
| --- | --- | --- | --- |
| `6079a717f929aaf04a04e329-11a97152d63e2cbf` | 3행 `clone/node_modules/circomlib/circuits/comparators.circom` → `project/node_modules/circomlib/circuits/comparators.circom` | `9b36c1488c7d4d6a17eb98ed84b51fd95c8648a0e460ac609d9f517e4f342faa` | `eb929f254b6785b1a131d5189934528c818a63ebda5f87ee38ffd3cfb47faa2f` |
| `6079a717f929aaf04a04e329-0d96bcca7368e8bc` | 3행 `clone/node_modules/circomlib/circuits/comparators.circom` → `project/node_modules/circomlib/circuits/comparators.circom` | `0ccfe5d769da339cfe2caff9b554c51a20af9d4248007493626019c80340d2bd` | `04284503a6f131e76c667e40ef4df5692bfc98b31fdf1c0e7a231852bc4fa6bf` |
| `6079a717f929aaf04a04e329-79916487f6fe1494` | 3행 `clone/node_modules/circomlib/circuits/comparators.circom` → `project/node_modules/circomlib/circuits/comparators.circom` | `738993e378e1ada8a5340ce162990261cc11bcfaedc70c5cf304490bf69d86ec` | `27ecce3a7ac8d7100fefa0a83a92afb22b67592a70ef3de39771b0fd1736a660` |
| `340107e1f1d8b0a45656cffa-25fbc4ac75c6f973` | 3행 `clone/circuits/maci/node_modules/circomlib/circuits/comparators.circom` → `project/circuits/maci/node_modules/circomlib/circuits/comparators.circom` | `cc9e160ed10ab5f8d15d9a57f4be3fcdd9d4bdf4ea9d6f390e99b0284b526083` | `a50ef0df61e4af890106c0305e0f8385d4def52c5d1e48ec9bb1acb8a87fc6cc` |
| `340107e1f1d8b0a45656cffa-8f76a896d13f52b1` | 3행 `clone/circuits/maci/power/trees/incrementalQuinTree.circom` → `project/circuits/maci/power/trees/incrementalQuinTree.circom` | `b835001b7f33c40f43306e197ef228456c30f2605abb7532933d92dc958295ae` | `c864607644b5779c00de1d2832f60bd62835f658e85ea864dddf97320566e1fb` |
| `b5b5cf5dacdeebd430b519f8-02875669a58dd8b0` | 3행 `clone/node_modules/circomlib/circuits/montgomery.circom` → `project/node_modules/circomlib/circuits/montgomery.circom` | `11129091b279a2dcbefca8d1838d9975a17533ba0544dc24ba7759acd5f2ca82` | `92b9bc8afeef04c978943dd87cf32c0f6a3e2261304b7f551ca4efd02ed528e9` |
| `b5b5cf5dacdeebd430b519f8-8c18dd3d620e25ca` | 3행 `clone/node_modules/circomlib/circuits/montgomery.circom` → `project/node_modules/circomlib/circuits/montgomery.circom` | `d0f2426e1178a56611ab1741da683b1076197ccabcc82bd4a84d513c091a2349` | `9197602021799d98314bea3a2adbb5b6010a79458abfb6dc21f9f42a782c4c95` |
| `b5b5cf5dacdeebd430b519f8-03692eab9963a4c9` | 3행 `clone/node_modules/circomlib/circuits/montgomery.circom` → `project/node_modules/circomlib/circuits/montgomery.circom` | `c658685e4be376f6b2802cda3ef917c29201787e3482106eae8660f1f1b18209` | `22cb1b35f221da487a9d2ad215e474469426ccc6ad69acd2a05f9f5736839c80` |
| `b5b5cf5dacdeebd430b519f8-263076088bed6123` | 3행 `clone/node_modules/circomlib/circuits/montgomery.circom` → `project/node_modules/circomlib/circuits/montgomery.circom` | `9f329284cc7778e33a2d087e12ccce3db4e18d63a39fa1451c0709ea2b98a043` | `11fb6231f5ab96b31176ebf8150c908a0ff8516db27ca92edf0c186ba9ca0462` |
| `4c221df76273c0d7cf18048c-25c4c01e8fb38d35` | 3행 `clone/circuits/node_modules/circomlib/circuits/montgomery.circom` → `project/circuits/node_modules/circomlib/circuits/montgomery.circom` | `50c23c9d7d511b06d3b63d739818b63d2be2d191c64f1d4d9bff8264fdc5ff7f` | `fb5cf7dca7b91ed99e5c7b7b30c5052274be67111fd98d7e8351bc56cdc26022` |
| `4c221df76273c0d7cf18048c-9e061fc9a7a273ca` | 3행 `clone/circuits/circuits/templates/utils.circom` → `project/circuits/circuits/templates/utils.circom` | `8b19ba018f1bdb37e361c9600a810b27577305a96fdbc60a0bcda88aeff63724` | `0a9307daa40bdcbdc7c578f590752597b530eba5a0ff16284b138b0a2caf23c7` |
| `4c221df76273c0d7cf18048c-d545fb4ebe62d3a0` | 3행 `clone/circuits/node_modules/circomlib/circuits/montgomery.circom` → `project/circuits/node_modules/circomlib/circuits/montgomery.circom` | `5352d81c6d0635a4092d1c6427ac77d6fe5f648094b5954209be71114046f368` | `c9fd9af32b33efa523d9bdd5a52062384082e4bcb39ecf3596c2a0265a0ff40c` |
| `4c221df76273c0d7cf18048c-6272f07ac3aa69a7` | 3행 `clone/circuits/node_modules/circomlib/circuits/montgomery.circom` → `project/circuits/node_modules/circomlib/circuits/montgomery.circom` | `64cfadc47dd7ff67e487f099d360afa901b8bee3ffafd434a3ffd340df2ff8bf` | `becf2fa502266639e35ed48eea890b254108821c0545d94042522a7cbf0623f6` |
| `a8b2aa9c2857e79c017805bb-cdd261dd082cb5b6` | 3행 `clone/circuits/lib/circuits/bigInt/bigIntHelpers.circom` → `project/circuits/lib/circuits/bigInt/bigIntHelpers.circom` | `e216dbdac1d48d4e8a6c1ab6a5e6b3f0a62c936c2ea5b7098c29f598b92f47a0` | `4316c04e703011e1f3b05bcd41576c3d226ef83f8e699d1399b07af43d2e1200` |
| `a8b2aa9c2857e79c017805bb-26a277bec7282fa3` | 3행 `clone/circuits/lib/circuits/int/arithmetic.circom` → `project/circuits/lib/circuits/int/arithmetic.circom` | `1dff77fb142bd9f1bdd48247cf98b15ddef8612ab4a276b14f40c53779de675b` | `0a4e51cd57013e1379f0b2fa5b7e6327527a92627c16874a2bba31eb0121c91f` |
| `a8b2aa9c2857e79c017805bb-b29ae7e59ef72113` | 3행 `clone/circuits/lib/circuits/bigInt/bigIntComparators.circom` → `project/circuits/lib/circuits/bigInt/bigIntComparators.circom` | `a8f38554a8dd8ccfbf8f50a28919aba3657d9372e2bc0c27f0606954369f259f` | `4e81169227cf0460c42742d4b51e441932d91a6fed363703e622b96a9b5946d8` |
| `a8b2aa9c2857e79c017805bb-120ff4b2122885f9` | 3행 `clone/circuits/lib/circuits/bigInt/bigIntComparators.circom` → `project/circuits/lib/circuits/bigInt/bigIntComparators.circom` | `a888df27d4b6b0753b59f566c5d838fd4ec0d7c8968f8a4aaa2f47d5bfbcd17b` | `9bba94b6a4e280849833bf5e0de50e1e21ed2a95c6d72b4ca7223cbb69c8dc8e` |

`-l`의 순서는 17쌍 모두 보존했다. 원본 clone 안의 항목 57개는 unit 안의 같은 상대 위치로 바꿨고, clone 밖 항목 48개는 경로를 그대로 두었다. 다음은 clone 밖 `-l`의 **순서가 보존된 전체 목록**이다. 같은 경로가 다른 쌍에 나타나더라도 그 쌍의 순서를 따로 적었다. 이 경로는 B 후보·판정 값이 아니다.

- `6079a717f929aaf04a04e329-11a97152d63e2cbf`: 원래 `-l` 6개, clone 안 재배치 3개, 외부 유지 3개
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/e02-production-mains-2026-10-05/preparation-measurements/6079a717f929aaf04a04e329/cap-900/prepared/prepare-b877c53f-2ffe-4e61-9719-f7eacb6df405/targets/0185/sources`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/e02-production-mains-2026-10-05/preparation-measurements/6079a717f929aaf04a04e329/cap-900/prepared/prepare-b877c53f-2ffe-4e61-9719-f7eacb6df405/targets/0185/sources/e01-setup-2026-10-03/recovery-v2/repositories/anon-aadhaar__anon-aadhaar/clone`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/e02-production-mains-2026-10-05/preparation-measurements/6079a717f929aaf04a04e329/cap-900/prepared/prepare-b877c53f-2ffe-4e61-9719-f7eacb6df405/targets/0185/sources/e01-setup-2026-10-03/recovery-v2/repositories/anon-aadhaar__anon-aadhaar/clone/node_modules`
- `6079a717f929aaf04a04e329-0d96bcca7368e8bc`: 원래 `-l` 6개, clone 안 재배치 3개, 외부 유지 3개
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/e02-production-mains-2026-10-05/preparation-measurements/6079a717f929aaf04a04e329/cap-900/prepared/prepare-b877c53f-2ffe-4e61-9719-f7eacb6df405/targets/0164/sources`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/e02-production-mains-2026-10-05/preparation-measurements/6079a717f929aaf04a04e329/cap-900/prepared/prepare-b877c53f-2ffe-4e61-9719-f7eacb6df405/targets/0164/sources/e01-setup-2026-10-03/recovery-v2/repositories/anon-aadhaar__anon-aadhaar/clone`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/e02-production-mains-2026-10-05/preparation-measurements/6079a717f929aaf04a04e329/cap-900/prepared/prepare-b877c53f-2ffe-4e61-9719-f7eacb6df405/targets/0164/sources/e01-setup-2026-10-03/recovery-v2/repositories/anon-aadhaar__anon-aadhaar/clone/node_modules`
- `6079a717f929aaf04a04e329-79916487f6fe1494`: 원래 `-l` 6개, clone 안 재배치 3개, 외부 유지 3개
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/e02-production-mains-2026-10-05/preparation-measurements/6079a717f929aaf04a04e329/cap-900/prepared/prepare-b877c53f-2ffe-4e61-9719-f7eacb6df405/targets/0167/sources`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/e02-production-mains-2026-10-05/preparation-measurements/6079a717f929aaf04a04e329/cap-900/prepared/prepare-b877c53f-2ffe-4e61-9719-f7eacb6df405/targets/0167/sources/e01-setup-2026-10-03/recovery-v2/repositories/anon-aadhaar__anon-aadhaar/clone`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/e02-production-mains-2026-10-05/preparation-measurements/6079a717f929aaf04a04e329/cap-900/prepared/prepare-b877c53f-2ffe-4e61-9719-f7eacb6df405/targets/0167/sources/e01-setup-2026-10-03/recovery-v2/repositories/anon-aadhaar__anon-aadhaar/clone/node_modules`
- `340107e1f1d8b0a45656cffa-25fbc4ac75c6f973`: 원래 `-l` 7개, clone 안 재배치 4개, 외부 유지 3개
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/340107e1f1d8b0a45656cffa/prepared/prepare-91ad847b-a802-42ca-a9e4-aeac420a3856/targets/0266/sources`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/340107e1f1d8b0a45656cffa/prepared/prepare-91ad847b-a802-42ca-a9e4-aeac420a3856/targets/0266/sources/c03-corpus-2026-10-02/recovery-v3/repositories/DoraFactory__Vota-Circuits/clone`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/340107e1f1d8b0a45656cffa/prepared/prepare-91ad847b-a802-42ca-a9e4-aeac420a3856/targets/0266/sources/c03-corpus-2026-10-02/recovery-v3/repositories/DoraFactory__Vota-Circuits/clone/circuits/maci/node_modules`
- `340107e1f1d8b0a45656cffa-8f76a896d13f52b1`: 원래 `-l` 7개, clone 안 재배치 4개, 외부 유지 3개
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/340107e1f1d8b0a45656cffa/prepared/prepare-91ad847b-a802-42ca-a9e4-aeac420a3856/targets/0270/sources`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/340107e1f1d8b0a45656cffa/prepared/prepare-91ad847b-a802-42ca-a9e4-aeac420a3856/targets/0270/sources/c03-corpus-2026-10-02/recovery-v3/repositories/DoraFactory__Vota-Circuits/clone`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/340107e1f1d8b0a45656cffa/prepared/prepare-91ad847b-a802-42ca-a9e4-aeac420a3856/targets/0270/sources/c03-corpus-2026-10-02/recovery-v3/repositories/DoraFactory__Vota-Circuits/clone/circuits/maci/node_modules`
- `b5b5cf5dacdeebd430b519f8-02875669a58dd8b0`: 원래 `-l` 6개, clone 안 재배치 3개, 외부 유지 3개
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/b5b5cf5dacdeebd430b519f8/prepared/prepare-427fc6af-dec2-4a3f-8411-6c200317b183/targets/0377/sources`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/b5b5cf5dacdeebd430b519f8/prepared/prepare-427fc6af-dec2-4a3f-8411-6c200317b183/targets/0377/sources/c03-corpus-2026-10-02/recovery-v3/repositories/iden3__circuits/clone`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/b5b5cf5dacdeebd430b519f8/prepared/prepare-427fc6af-dec2-4a3f-8411-6c200317b183/targets/0377/sources/c03-corpus-2026-10-02/recovery-v3/repositories/iden3__circuits/clone/node_modules`
- `b5b5cf5dacdeebd430b519f8-8c18dd3d620e25ca`: 원래 `-l` 6개, clone 안 재배치 3개, 외부 유지 3개
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/b5b5cf5dacdeebd430b519f8/prepared/prepare-427fc6af-dec2-4a3f-8411-6c200317b183/targets/0382/sources`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/b5b5cf5dacdeebd430b519f8/prepared/prepare-427fc6af-dec2-4a3f-8411-6c200317b183/targets/0382/sources/c03-corpus-2026-10-02/recovery-v3/repositories/iden3__circuits/clone`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/b5b5cf5dacdeebd430b519f8/prepared/prepare-427fc6af-dec2-4a3f-8411-6c200317b183/targets/0382/sources/c03-corpus-2026-10-02/recovery-v3/repositories/iden3__circuits/clone/node_modules`
- `b5b5cf5dacdeebd430b519f8-03692eab9963a4c9`: 원래 `-l` 6개, clone 안 재배치 3개, 외부 유지 3개
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/b5b5cf5dacdeebd430b519f8/prepared/prepare-427fc6af-dec2-4a3f-8411-6c200317b183/targets/0380/sources`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/b5b5cf5dacdeebd430b519f8/prepared/prepare-427fc6af-dec2-4a3f-8411-6c200317b183/targets/0380/sources/c03-corpus-2026-10-02/recovery-v3/repositories/iden3__circuits/clone`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/b5b5cf5dacdeebd430b519f8/prepared/prepare-427fc6af-dec2-4a3f-8411-6c200317b183/targets/0380/sources/c03-corpus-2026-10-02/recovery-v3/repositories/iden3__circuits/clone/node_modules`
- `b5b5cf5dacdeebd430b519f8-263076088bed6123`: 원래 `-l` 6개, clone 안 재배치 3개, 외부 유지 3개
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/b5b5cf5dacdeebd430b519f8/prepared/prepare-427fc6af-dec2-4a3f-8411-6c200317b183/targets/0376/sources`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/b5b5cf5dacdeebd430b519f8/prepared/prepare-427fc6af-dec2-4a3f-8411-6c200317b183/targets/0376/sources/c03-corpus-2026-10-02/recovery-v3/repositories/iden3__circuits/clone`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/b5b5cf5dacdeebd430b519f8/prepared/prepare-427fc6af-dec2-4a3f-8411-6c200317b183/targets/0376/sources/c03-corpus-2026-10-02/recovery-v3/repositories/iden3__circuits/clone/node_modules`
- `4c221df76273c0d7cf18048c-25c4c01e8fb38d35`: 원래 `-l` 7개, clone 안 재배치 4개, 외부 유지 3개
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/4c221df76273c0d7cf18048c/prepared/prepare-d9d5741e-1eed-4d44-98b1-d11344c4b146/targets/0006/sources`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/4c221df76273c0d7cf18048c/prepared/prepare-d9d5741e-1eed-4d44-98b1-d11344c4b146/targets/0006/sources/c03-corpus-2026-10-02/recovery-v3/repositories/pantherfoundation__panther-core/clone`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/4c221df76273c0d7cf18048c/prepared/prepare-d9d5741e-1eed-4d44-98b1-d11344c4b146/targets/0006/sources/c03-corpus-2026-10-02/recovery-v3/repositories/pantherfoundation__panther-core/clone/circuits/node_modules`
- `4c221df76273c0d7cf18048c-9e061fc9a7a273ca`: 원래 `-l` 8개, clone 안 재배치 4개, 외부 유지 4개
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/4c221df76273c0d7cf18048c/prepared/prepare-d9d5741e-1eed-4d44-98b1-d11344c4b146/targets/0022/sources`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/4c221df76273c0d7cf18048c/prepared/prepare-d9d5741e-1eed-4d44-98b1-d11344c4b146/targets/0022/sources/c03-corpus-2026-10-02/recovery-v3/repositories/pantherfoundation__panther-core/clone`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/4c221df76273c0d7cf18048c/prepared/prepare-d9d5741e-1eed-4d44-98b1-d11344c4b146/targets/0022/sources/c03-corpus-2026-10-02/recovery-v3/repositories/pantherfoundation__panther-core/clone/circuits/circuits`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/4c221df76273c0d7cf18048c/prepared/prepare-d9d5741e-1eed-4d44-98b1-d11344c4b146/targets/0022/sources/c03-corpus-2026-10-02/recovery-v3/repositories/pantherfoundation__panther-core/clone/circuits/node_modules`
- `4c221df76273c0d7cf18048c-d545fb4ebe62d3a0`: 원래 `-l` 7개, clone 안 재배치 4개, 외부 유지 3개
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/4c221df76273c0d7cf18048c/prepared/prepare-d9d5741e-1eed-4d44-98b1-d11344c4b146/targets/0011/sources`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/4c221df76273c0d7cf18048c/prepared/prepare-d9d5741e-1eed-4d44-98b1-d11344c4b146/targets/0011/sources/c03-corpus-2026-10-02/recovery-v3/repositories/pantherfoundation__panther-core/clone`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/4c221df76273c0d7cf18048c/prepared/prepare-d9d5741e-1eed-4d44-98b1-d11344c4b146/targets/0011/sources/c03-corpus-2026-10-02/recovery-v3/repositories/pantherfoundation__panther-core/clone/circuits/node_modules`
- `4c221df76273c0d7cf18048c-6272f07ac3aa69a7`: 원래 `-l` 7개, clone 안 재배치 4개, 외부 유지 3개
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/4c221df76273c0d7cf18048c/prepared/prepare-d9d5741e-1eed-4d44-98b1-d11344c4b146/targets/0009/sources`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/4c221df76273c0d7cf18048c/prepared/prepare-d9d5741e-1eed-4d44-98b1-d11344c4b146/targets/0009/sources/c03-corpus-2026-10-02/recovery-v3/repositories/pantherfoundation__panther-core/clone`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/4c221df76273c0d7cf18048c/prepared/prepare-d9d5741e-1eed-4d44-98b1-d11344c4b146/targets/0009/sources/c03-corpus-2026-10-02/recovery-v3/repositories/pantherfoundation__panther-core/clone/circuits/node_modules`
- `a8b2aa9c2857e79c017805bb-cdd261dd082cb5b6`: 원래 `-l` 5개, clone 안 재배치 3개, 외부 유지 2개
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/a8b2aa9c2857e79c017805bb/prepared/prepare-c9431b7b-64a6-4de3-b31f-8bb5a53886b7/targets/0037/sources`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/a8b2aa9c2857e79c017805bb/prepared/prepare-c9431b7b-64a6-4de3-b31f-8bb5a53886b7/targets/0037/sources/c03-corpus-2026-10-02/recovery-v3/repositories/rarimo__passport-zk-circuits/clone`
- `a8b2aa9c2857e79c017805bb-26a277bec7282fa3`: 원래 `-l` 5개, clone 안 재배치 3개, 외부 유지 2개
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/a8b2aa9c2857e79c017805bb/prepared/prepare-c9431b7b-64a6-4de3-b31f-8bb5a53886b7/targets/0010/sources`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/a8b2aa9c2857e79c017805bb/prepared/prepare-c9431b7b-64a6-4de3-b31f-8bb5a53886b7/targets/0010/sources/c03-corpus-2026-10-02/recovery-v3/repositories/rarimo__passport-zk-circuits/clone`
- `a8b2aa9c2857e79c017805bb-b29ae7e59ef72113`: 원래 `-l` 5개, clone 안 재배치 3개, 외부 유지 2개
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/a8b2aa9c2857e79c017805bb/prepared/prepare-c9431b7b-64a6-4de3-b31f-8bb5a53886b7/targets/0023/sources`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/a8b2aa9c2857e79c017805bb/prepared/prepare-c9431b7b-64a6-4de3-b31f-8bb5a53886b7/targets/0023/sources/c03-corpus-2026-10-02/recovery-v3/repositories/rarimo__passport-zk-circuits/clone`
- `a8b2aa9c2857e79c017805bb-120ff4b2122885f9`: 원래 `-l` 5개, clone 안 재배치 3개, 외부 유지 2개
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/a8b2aa9c2857e79c017805bb/prepared/prepare-c9431b7b-64a6-4de3-b31f-8bb5a53886b7/targets/0022/sources`
  - `/Users/miiz/Desktop/kwzzzz_zkfr/runs/f01-2026-10-03/measurements/a8b2aa9c2857e79c017805bb/prepared/prepare-c9431b7b-64a6-4de3-b31f-8bb5a53886b7/targets/0022/sources/c03-corpus-2026-10-02/recovery-v3/repositories/rarimo__passport-zk-circuits/clone`

정확한 원래/새 `-l` 전체 배열과 각 project 파일 SHA는 `unit-staging-manifest.json`의 `pairs[].original_library_paths`, `library_paths`, `project_files`에 있다. 외부 경로가 닫힘에 들어온 것은 E1의 허용 예외로 표시했으며, E2 실패의 핵심이기도 하다. hint workspace·인스턴스 저장소·캐시는 unit 밖 SSD의 별도 새 폴더로 지정했다. B6b preflight의 경로 겹침·`.circom` 수·크기 상한 검사는 새 실행기 설정에 유지했지만 최종 index가 없어 이번에는 그 index에 대한 107행 preflight를 실행하지 않았다.

## 3. E1–E4 정적·컴파일 대조

E1은 B6 제자리 배치의 원본 S wrapper+원본 entrypoint와 새 unit의 wrapper+entrypoint 닫힘 합집합을 canonical 경로 1:1로 대조했다. 원본 파일과 새 파일의 SHA는 wrapper의 허용된 include 행 이외에 같다. 새 닫힘 경로는 unit 안 또는 위 목록의 clone 밖 `-l`에서 왔다. E2는 각 닫힘의 선언 이름별 canonical 파일 수를 비교하고 wrapper `component main`의 템플릿 이름이 **정확히 1파일**인지 검사했다. E3은 고정 Circom SHA-256 `8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227`, 원래 옵션 `--r1cs --sym --prime bn128 --wasm --O0`, 새 `-l` 순서로 사본 wrapper를 컴파일했다. 17회 모두 macOS `sandbox-exec`로 원본 clone 읽기를 막았고 별도 차단 검사도 17/17 확인했다. E4는 project 파일과 wrapper의 비 include 행 바이트를 검사했다.

| B 리비전 | 요청/쌍 | E1 닫힘 (원본→unit) | E2 main 유일 통과 | E3 R1CS 일치 | E4 바이트 | 결론 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `340107e1f1d8b0a45656cffa` | 4/2 | 35→35; 2/2 | 2/2 | 2/2 | 2/2 | 리비전 관문 통과 |
| `4c221df76273c0d7cf18048c` | 12/4 | 35→35; 4/4 | 4/4 | 4/4 | 4/4 | 리비전 관문 통과 |
| `6079a717f929aaf04a04e329` | 9/3 | 43→43; 3/3 | 0/3 | 3/3 | 3/3 | 중단: E2 실패 |
| `a8b2aa9c2857e79c017805bb` | 70/4 | 70→70; 4/4 | 4/4 | 4/4 | 4/4 | 리비전 관문 통과 |
| `b5b5cf5dacdeebd430b519f8` | 12/4 | 41→41; 4/4 | 4/4 | 4/4 | 4/4 | 리비전 관문 통과 |
| **합계** | **107/17** | **17/17** | **14/17** | **17/17** | **17/17** | **전체 중단** |

E2 실패는 `6079a717f929aaf04a04e329`(anon-aadhaar)의 queue 0–8, 세 GreaterThan wrapper이다. 원본과 새 unit 모두 닫힘이 43파일, main `GreaterThan` 선언 파일이 **2개**다. 원본 clone의 `node_modules/circomlib/circuits/comparators.circom`과 원본 preparation snapshot을 가리키는 외부 `-l` 쪽의 동명 파일이 각각 canonical 파일로 들어온다. 두 파일의 내용 SHA는 모두 `fd0c7723ee56e1467df1861131157cbb108e156fe2d9ec64895c8e68de14db20`이고 `template GreaterThan(n)` 선언은 각각 118행이다. 중복 템플릿 이름 15개는 `AliasCheck`, `BinSum`, `Bits2Num`, `Bits2Num_strict`, `CompConstant`, `ForceEqualIfEnabled`, `GreaterEqThan`, `GreaterThan`, `IsEqual`, `IsZero`, `LessEqThan`, `LessThan`, `Num2Bits`, `Num2BitsNeg`, `Num2Bits_strict`다. 원본과 unit에서 같은 이름·같은 파일 수(각 2)로 유지된다. 즉 이번 unit 복사가 만든 새 중복은 아니다. 그러나 지시의 E2는 원본에도 2개이면 실패하도록 정했으므로 통과 처리할 수 없다. 이 9건의 실제 J 준비나 판정 결과를 추정하지 않았다.

A 원본 index의 실제 `source_root`, wrapper, entrypoint에도 **같은 검사기**를 적용했다. 아래 `통과 쌍`은 main 템플릿 파일 수 1인 쌍이다. `엔진 호출`은 전체 요청에서 사전 `base_input_unavailable` 행을 뺀 수이며, 실제 호출된 765건은 모두 유일했다. A 관측 `template_ambiguous=0`과 모순이 없다.

| A 리비전 | 요청 | 엔진 호출 | 통과 쌍/고유 쌍 |
| --- | ---: | ---: | ---: |
| `aq-006-1680f955c185` | 42 | 0 | 7/7 |
| `aq-007-0bb83f9eab0f` | 42 | 0 | 7/7 |
| `aq-008-9c9e702d061d` | 42 | 0 | 7/7 |
| `aq-011-93343c3cd34c` | 33 | 0 | 11/11 |
| `aq-012-44d0df2ab46e` | 24 | 0 | 8/8 |
| `aq-016-0a7d49b1c135` | 24 | 0 | 8/8 |
| `aq-017-9703bbce0c43` | 21 | 0 | 7/7 |
| `aq-024-6f6781246415` | 24 | 0 | 8/8 |
| `aq-025-70328d3fd35e` | 27 | 0 | 9/9 |
| `aq-026-2bcd7ed6110f` | 27 | 0 | 9/9 |
| `aq-035-8f826c822cb8` | 12 | 12 | 1/1 |
| `aq-036-6d7df64759b6` | 604 | 604 | 2/2 |
| `aq-037-94fe3080fc18` | 6 | 0 | 1/1 |
| `aq-039-0ad3923f2f5b` | 6 | 0 | 1/1 |
| `aq-040-da54d3e7bc8a` | 12 | 0 | 1/1 |
| `banyan-fixed` | 24 | 0 | 1/1 |
| `banyan-vulnerable` | 1807 | 0 | 2/3 |
| `inference-c771c61c-p` | 3 | 3 | 1/1 |
| `inference-c79f42ee` | 9 | 9 | 3/3 |
| `inference-c9221e8d` | 15 | 15 | 4/4 |
| `inference-loo-clamp` | 6 | 6 | 2/2 |
| `inference-loo-dfs` | 3 | 3 | 1/1 |
| `inference-original` | 69 | 69 | 10/10 |
| `inference-r-intdiv` | 26 | 26 | 7/7 |
| `zkemail-fpmul-fixed` | 9 | 9 | 1/1 |
| `zkemail-fpmul-vulnerable` | 9 | 9 | 1/1 |
| **합계** | **2,926** | **765** | **120/121** |

A의 예외 1쌍은 `banyan-vulnerable`의 `Blake3NovaTreePath_CheckDepth`가 두 파일에 있는 경우다. 그 쌍의 56요청은 모두 엔진 호출 전 `base_input_unavailable`로 표시되었고, 실제 엔진 호출은 0건이다. A E1·E3·E4는 **원본 A 스테이징과 새 스테이징의 대조 대상이 없으므로 해당 없음**이며, 이 표는 요청된 A의 실제 배치에 대한 E2 기준선 검사다. A를 재실행하거나 A 판정 값을 재분류하지 않았다.

## 4. 새 실행기 초안과 준비 실패 사유

`scripts/n6_b6d_j_runner.py`와 형식 시범 어댑터는 **미활성 초안**이다. 새 index와 통과 상태의 SHA 결박 E1–E4 gate가 없으면 실행을 거부한다. 고정 v2.2 `8065e2b7:src/candidate_review/lifting/mod.rs`의 preparation reason 문자열 29종을 다음처럼 나눴다. v1 고정판에도 같은 reason 집합이 있다. `preparation.status/reason/detail`만 저장하고 후보·판정 값을 로그에 추가하지 않는다.

| 처리 | 고정 v2.2 파일:줄과 reason |
| --- | --- |
| 기록 후 다음 요청 (회로·후보 사유) | `:517,562 candidate_invalid`; `:556,1424 candidate_missing_signals`; `:607 candidate_violates_component_constraints`; `:531 component_compile_failed`; `:543 component_inputs_unresolved`; `:550 component_outputs_unresolved`; `:1231 deviation_not_hint_assigned`; `:733,745 entrypoint_compile_failed`; `:869 hint_changes_constraints`; `:1189 hint_index_shape`; `:1163 hint_unsupported`; `:851 hinted_compile_failed`; `:781 no_call_site`; `:1168 reverse_hint_unsupported`; `:635 source_closure_unresolved`; `:642 source_parse_failed`; `:1368 template_ambiguous`; `:1366 template_unmatched` (18종) |
| 즉시 중단 (환경·입력 파일 사유) | `:515 base_input_invalid`; `:512 base_input_missing`; `:536 component_artifacts_invalid`; `:575 component_witness_failed`; `:496 component_wrapper_missing`; `:750,755 entrypoint_artifacts_invalid`; `:499 entrypoint_missing`; `:564,587,641,757-759,821,836,852-862,915-925 io`; `:493 library_missing`; `:504 source_outside_root`; `:487 source_root_missing` (11종) |

알려지지 않은 reason, 예상 밖 status, 결과 형식 불일치는 중단한다. `component_compile_failed`, `entrypoint_compile_failed`, `hinted_compile_failed`, `source_closure_unresolved`에는 회로 오류뿐 아니라 도구/호스트 장애가 포장될 수도 있어 reason 문자열만으로 완전히 구분할 수 없다. 이 혼합 사유의 detail 분류를 향후 실제 활성화 전에 검토해야 한다. 현재 E2 차단으로 실제 처리된 B 준비 실패는 0건이다.

새 실행기는 원래 index의 요청 ID·순서·후보 SHA·구성 입력 SHA를 새 index에 결박하고 원본/사본 wrapper SHA, 요청 경로, `-l`만 허용된 변화인지 검사하도록 작성했다. 원래 wrapper SHA 검사 위치는 `scripts/run_n6_j1.py:54-68,265-293`의 요청 검증이며, 엔진 준비 실패에 대한 기존 중단 근거는 `:368-370,620-638`이다. 새 wrapper 결박은 새 생성기 `scripts/n6_b6d_b_requests.py:599-627`, 새 실행기 `scripts/n6_b6d_j_runner.py:128-177`에 대응한다. E3의 17/17 R1CS SHA 일치는 원본·사본 **회로**의 동치 근거이며, 후보 ID·SHA 및 요청 필드 보존은 새 index가 만들어질 경우 `verify_original_index()`와 `runner.validate_index()`가 별도로 검사한다. 구성 입력 index와 두 `lead-input-review.json`의 결박은 `scripts/n6_b6d_j_runner.py:198-222`의 `configure()`에 있다. `scripts/n6_b6d_source_bindings.py`는 W/S 경로·SHA, 라이브러리 순서, unit 파일을 검사한다. A 요약기 `scripts/n6_j1_summarize.py:195-224,251-271,494-512`와 같이 107 전체를 분모로 두고 엔진의 회로·후보 사유 비성공 preparation status를 reason별 별도 `preparation_failure` 칸으로 기록하며 J `unknown`으로 옮기지 않는 설계다. 여기에는 두 내재 사유에서 엔진이 `preparation.status=unknown`을 반환하는 경우도 포함된다. 시범 어댑터는 `preparation.status=ok`를 요구하고 최대 제약 queue 9, 최소 queue 25의 기존 선택 규칙을 유지한다. **실제 형식 검사나 B J 집계는 수행하지 않았다.**

## 5. 산출물, 검사, 실행 준비 상태

| 새 산출물 | SHA-256 |
| --- | --- |
| `runs/n6-b6d-2026-10-20.noindex/unit-staging-manifest.json` | `148425dd95eaf137d34b56b8c8868d410db3431ef7d18ae053346597f0e387f0` |
| `runs/n6-b6d-2026-10-20.noindex/b-closure-equivalence-v1.json` | `046e7b2b474e884b2faa50f8b77c1868efea03a2d9ff5b4531fbc08c0f9a5088` |
| `runs/n6-b6d-2026-10-20.noindex/a-closure-audit-v2.json` | `8e79ebc9b761f73eb664866c9ae27e0b08e350790a008ba9e8b47318dab5ec39` |
| `runs/n6-b6d-2026-10-20.noindex/r1cs-equivalence.json` | `47977c59d634a877b1b871280c7a8eb00d1454cba09d42907b40d10a6e863eec` |
| `runs/n6-b6d-2026-10-20.noindex/source-copy-audit.json` | `dd85a9c3d85a52874f79cbcda81cecbcc76ee4402daabd39134691401cf3b46d` |
| `scripts/n6_b6d_b_requests.py` | `de6ef1ee3254a3414043eb8f4aa6e4ff01071149d53011216652cc485456427a` |
| `scripts/n6_b6d_closure_equivalence.py` | `9649f7e68f28ec002c9918af7ac663f32c0f07e49832002ae067b248b892dc60` |
| `scripts/n6_b6d_source_bindings.py` | `52923a553111a95c573ac55b7d4be7410d168cfb18606c78c9c7cc06442aef70` |
| `scripts/n6_b6d_j_runner.py` | `6c927293a6a95dd5503a0d3fca565ee628684c9bebcb883ecfc5cf16b01b4d1e` |
| `scripts/n6_b6d_format_pilot.py` | `210433d6a778b4e3cb7c83afe1d76c796b43d1214a7eea2647581a63fc8717b3` |
| `tests/n6_b6d_b_requests_test.py` | `12ba028de43645f0428c0fd95b2b94605fd1514c6b4c300d0477a865c6ccdaee` |
| `tests/n6_b6d_closure_equivalence_test.py` | `f4f8fe4e9b36d56ab41efe118ba9ae2d2535b5730f5f4264d94f48bded94133e` |
| `tests/n6_b6d_j_runner_test.py` | `d6050c707e3fcf75514a5cf4f32253a71389b2b88eb47bba29988bf3c0c2284d` |

검사 결과: B 닫힘 17/17·107/107 E1 통과, A 실제 배치 2,926/2,926 감사, E3 17/17, E4 project 3,872개·wrapper 17개 통과, 원본 clone 접근 차단 17/17. Python 단위 검사 19/19 통과. 필수 `cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test` 모두 통과했고 `git diff --check`도 통과했다. 코드 변경은 새 Python 파일뿐이며 Rust 엔진 소스는 변경하지 않았다.

**새 요청 index SHA-256: 없음.** E2 실패 때문에 `equivalence-gate-v1.json`, 새 index·요청 파일을 생성하지 않았다. 따라서 새 index에 대한 B6b preflight, 새 시범, 전체 실행도 시작하지 않았다. 제약 수 규칙상의 대상 queue 9·25는 유지했으나 E1–E4 gate가 없어 활성 시범 대상으로 확정하지 않았다. miiz용 `caffeinate -dimsu` 시범/execute-all 명령 역시 지금 실행 가능한 형태로 제시하지 않는다. 이 결정은 지시의 “하나라도 실패하면 새 index를 쓰지 않고 멈춘다”를 따른다.

## 6. 시간 계획과 지시와 다른 점

시간 근거는 기존 Vota v2.2 queue 9 시범의 wall `105.940235`초(약 106초)뿐이다. 이 한 건으로 107×2 전체 시간이나 디스크 용량을 수치 추정하지 않는다. E2를 해결하고 **새 시범을 실제로 완료한 뒤** 시간·디스크 계획을 다시 계산해야 한다. 이전 runs/ 복사 오류의 4,459초는 근거에서 제외한다.

- A의 `source_root`는 대부분 unit이지만 A3 root나 `circuits/`, 일부 `project/`도 있다. 실제 A index의 경로를 검사했고 모든 A가 unit이었다고 가정하지 않았다.
- 원본 clone 밖 `-l`을 그대로 둬야 한다는 지시와 “한 파일은 한 사본” 목표가 anon-aadhaar의 외부 preparation snapshot에서 충돌한다. 원본 B6 배치에도 이미 같은 선언 파일 2개가 있다. E1의 경로 예외는 성립하지만 E2의 main 유일 조건은 실패한다. 외부 `-l`을 임의로 지우거나 바꾸면 원래 해석 순서·닫힘 동치가 달라지므로 수행하지 않았다.
- E2 차단에 따라 새 index와 두 실행 명령, N5 개정 기록·N5 연결 SHA 갱신을 하지 않았다. 기존 `docs/n5_amendment_b_judging_2026-10-17.md` SHA-256은 `08025e7d12a5f28b5641b03122c81cc96170881ccce822e7a7a2b6c9fb2d6cda`, `docs/n5_evaluation_protocol_v1_2026-10-06.md` SHA-256은 `5fb86ac3baa2d9429c0776968cc1083d0ae6822c12f7a31a80e158fc43474c6c`로 유지했다.
- 고정 엔진에 준비 전용 공개 진입점이 없어서 E1–E4는 후보에 의존하는 실제 준비 성공을 보장하지 않는다. B J 준비·판정 결과라고 부르지 않는다.
- B6c 6절의 `a-observed-preparation-audit-v2.json`과 `-v3.json`에 같은 SHA-256이 적힌 것은 맞다. 두 파일을 직접 해시해 모두 `654099ae181e09144d84465278b427ad1888916e80444667da3f81c2806cc372`로 확인했다.

B 판정 값·후보 값·witness 값 및 J 작업 폴더 내용은 열지 않았고, B J 시범·전체 실행, zkFuzz 재실행, 의존성 설치, commit·push·PR은 하지 않았다. 기존 결과·스테이징은 삭제하거나 덮지 않았다.
