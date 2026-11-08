# 교수님 터미널 시연: inference 원본 반례

2026-10-29. **A 개발 사례의 보존 반례를 실제로 재검증하는 시연**이다. 새 반례 발견이나 독립 성능 평가로 소개하지 않는다. 기존 소스·witness·판정·실행 기록은 변경하지 않는다.

**지금 가능한 핵심 시연**

같은 최상위 입력 2,825개에서 정상 출력은 `13000000`, 이탈 출력은 `12999998`이다. 두 witness는 원본 O0 **401,664제약**을 모두 통과한다. 같은 이탈 witness는 IntDiv의 `out <-- quot`를 `out <== quot`로 한 줄 바꾼 제약에서는 거부된다.

예행연습에서 snarkjs 세 검사는 각각 **1.808초 / 1.568초 / 0.735초**, 합 **4.112초**였다. 설명까지 포함하면 3–5분 시연으로 구성하기 좋다. 다음 실행 시간의 보장은 아니다. [예행연습 영수증](../runs/professor-terminal-demo-2026-10-29/rehearsal-20261029T064339Z/receipt.json)

교수님께 먼저 이렇게 말한다.

> “큰 회로에서 S와 J가 찾아 저장한 반례입니다. 지금은 로그를 보여주는 데서 끝내지 않고, 같은 입력에서 다른 출력이 원본 제약을 실제로 통과하는지 다시 검사하겠습니다. 이어서 제약을 한 줄 보완하면 같은 이탈 답안이 거부되는지도 보여드리겠습니다.”

**입력과 출력의 실제 값 비교**

다음 명령은 원본 R1CS와 두 WTNS를 직접 읽고, 저장 영수증의 해시와 대조한 뒤 입력·출력 wire를 비교한다. 파일을 변경하지 않는다.

```sh
cd /Users/miiz/Desktop/kwzzzz_zkfr
nice -n 19 python3 - <<'PY'
from pathlib import Path
import hashlib, json, struct
root=Path('/Users/miiz/Desktop/kwzzzz_zkfr')
pair=root/'runs/n5-equal-cost-2026-10-28/o0-pair'
original=pair/'compile/circuit.r1cs'
honest=pair/'honest-o0.wtns'
deviated=root/'runs/n6-j1-2026-10-09.noindex/j-execute.noindex/main/0001/requests/000021/attempt-0001/raw/site-003/deviated-o0.wtns'
receipt=json.loads((pair/'o0_pair_receipt_v2.json').read_text())
for path,key in [(original,'original_o0_r1cs_sha256'),(honest,'honest_o0_wtns_sha256'),(deviated,'deviated_o0_wtns_sha256')]:
    assert hashlib.sha256(path.read_bytes()).hexdigest()==receipt[key],path

def sections(path,magic):
    data=path.read_bytes()
    assert data[:4]==magic
    version,count=struct.unpack_from('<II',data,4)
    pos=12
    result={}
    for _ in range(count):
        kind,size=struct.unpack_from('<IQ',data,pos)
        pos+=12
        result[kind]=data[pos:pos+size]
        pos+=size
    assert pos==len(data)
    return result

r=sections(original,b'r1cs')[1]
width=struct.unpack_from('<I',r)[0]
wires,outputs,pub,prv,labels,constraints=struct.unpack_from('<IIIIQI',r,4+width)
a=sections(honest,b'wtns')
b=sections(deviated,b'wtns')
assert a[1]==b[1]
w=struct.unpack_from('<I',a[1])[0]
assert struct.unpack_from('<I',a[1],4+w)[0]==wires
assert len(a[2])==len(b[2])==wires*w
get=lambda raw,i:int.from_bytes(raw[i*w:(i+1)*w],'little')
in_diff=[i for i in range(1+outputs,1+outputs+pub+prv) if get(a[2],i)!=get(b[2],i)]
out_diff=[i for i in range(1,outputs+1) if get(a[2],i)!=get(b[2],i)]
assert not in_diff and out_diff==[1]
print('원본 O0 제약:',constraints)
print('최상위 입력:',pub+prv,'개 모두 동일')
print('다른 최상위 출력 wire:',out_diff)
print('정상 출력:',get(a[2],1))
print('이탈 출력:',get(b[2],1))
PY
```

**원본 제약과 한 줄 수정본 검사**

첫 두 명령은 `WITNESS IS CORRECT`, 마지막 명령은 `WITNESS IS NOT CORRECT`와 제약 번호 `163432`를 보여야 한다. 마지막 거부와 종료 코드 1은 시연 오류가 아니라 **수정한 제약이 이 반례를 차단했다는 기대 결과**다.

```sh
cd /Users/miiz/Desktop/kwzzzz_zkfr
demo_original='runs/n5-equal-cost-2026-10-28/o0-pair/compile/circuit.r1cs'
demo_honest='runs/n5-equal-cost-2026-10-28/o0-pair/honest-o0.wtns'
demo_deviated='runs/n6-j1-2026-10-09.noindex/j-execute.noindex/main/0001/requests/000021/attempt-0001/raw/site-003/deviated-o0.wtns'
demo_fixed='runs/rq1-causal-review-2026-10-28/intdiv_fix_pilot/compile-fixed/circuit.r1cs'

nice -n 19 /opt/homebrew/bin/snarkjs wtns check "$demo_original" "$demo_honest"
nice -n 19 /opt/homebrew/bin/snarkjs wtns check "$demo_original" "$demo_deviated"
nice -n 19 /opt/homebrew/bin/snarkjs wtns check "$demo_fixed" "$demo_deviated"
```

한 줄의 소스 차이도 보여줄 수 있다. `diff`가 차이를 찾을 때 종료 코드 1을 반환하는 것은 정상이다.

```sh
diff -u runs/rq1-causal-review-2026-10-28/intdiv_fix_pilot/original/src/integerDivision.circom runs/rq1-causal-review-2026-10-28/intdiv_fix_pilot/fixed/src/integerDivision.circom
```

“원래 제약이 다른 답을 받아들였고, 이 특정 반례는 출력 등식을 추가하면 거부됩니다”라고 설명한다. 수정본 전체의 안전성 증명으로 확대하지 않는다. 기존 실행의 Rust 검사와 이번 실시간 snarkjs 재검사는 구분한다. 이번 예행연습에서 Rust 판정기를 새로 실행한 것은 아니다.

**선택: 처음부터 새로 탐색하는 시연**

새 탐색 명령도 있다. 이번 점검에서는 실행하지 않았다. 기존 실행의 원본 복사·준비·퍼징·J·원본 검사 실측은 **209.2 / 831.4 / 134.6초**였다. 같은 seed도 후보가 달라졌으므로 현장에서 2분 안에 성공한다고 약속하면 안 된다. 시연용 seed 선택은 성능 비교가 아니다.

기존 출력 폴더는 보존하고 새 폴더를 지정한다. 아래 폴더에 같은 seed가 이미 있으면 실행기가 덮어쓰기를 거부한다.

```sh
cd /Users/miiz/Desktop/kwzzzz_zkfr
nice -n 19 python3 -u scripts/n7_a_sj_cold_e2e_20261029.py --seed 2026100603 --cap 1600 --no-replay --output-root runs/professor-terminal-demo-2026-10-29/live-discovery-01
```

실행기는 진행을 터미널에 거의 출력하지 않고 `result.json`과 단계별 로그에 저장한다. 두 번째 터미널에서 다음 명령을 필요할 때 다시 실행하면 진행을 확인할 수 있다.

```sh
cd /Users/miiz/Desktop/kwzzzz_zkfr
python3 - <<'PY'
from pathlib import Path
import json
p=Path('runs/professor-terminal-demo-2026-10-29/live-discovery-01/2026100603/result.json')
if not p.exists():
    print('아직 첫 단계 기록 전입니다.')
else:
    r=json.loads(p.read_text())
    print('상태:',r['status'])
    print('완료 단계:',[s['stage'] for s in r['stages']])
    print('후보:',len(r['candidates']),'J 요청:',len(r['judgements']))
    first=r.get('first_verified')
    print('첫 원본 반례 시간:',first.get('recorded_offset_seconds') if first else '아직 없음')
PY
```

인정 예산은 1,600초, 즉 26분40초다. 모든 하위 준비 작업에 OS 강제종료가 보장되는 것은 아니므로 정확한 종료시각 보장으로 설명하지 않는다. `--no-replay`는 시간 밖의 추가 수정본 재생을 생략한다. 이 옵션이 없으면 별도 최대 1,800초의 재생 작업이 붙을 수 있다.

시작에는 내장 여유 30GiB가 필요하고 기존 산출물은 seed당 최대 약 10GB였다. 이번 점검 여유는 약 44.9GiB지만 시연 직전에 다시 확인해야 한다. 다른 무거운 작업과 겹쳐 실행하지 않는다. 보존 폴더에 `--replay-only`를 쓰면 기존 결과를 갱신하므로 쓰지 않는다.

**추천 발표 순서**

1. W/S/J 그림으로 S의 조각 탐색과 J의 원본 연결 역할을 1분 설명한다.
2. 같은 입력·다른 출력 비교와 snarkjs 세 검사를 실제로 실행한다.
3. 한 줄 수정 차이와 기대한 거부를 설명한다.
4. 기존 cold 3회 시간과 W 후보 0은 과거 기록으로 보여준다.
5. 시간이 충분할 때만 새 탐색을 별도로 실행한다. 핵심 원본 반례 시연은 이미 마친 상태다.

**확인한 것:** 필요한 파일·도구가 있고 입력 동일성·출력 차이 및 세 검사가 실제 재현됐다. **보장하지 않는 것:** 새 탐색의 현장 성공 시간, 일반 우위, 독립 원인 수, 수정본 전체 안전성.
