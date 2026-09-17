"""Read-only audit of supplied evidence; outputs and reruns stay in this directory."""
import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

E = Path('/Users/miiz/Desktop/zkfDO_검수자료')
O = Path(__file__).resolve().parent
F = E / 'files'
R = F / 'runs/xorwords-original-followup-2026-09-15'
X = F / 'experiments/evidence/xorwords-2026-09-15'
P = 21888242871839275222246405745257275088548364400416034343698204186575808495617
def digest(b): return hashlib.sha256(b).hexdigest()
def objhash(kind, b): return hashlib.sha1(kind.encode() + b' ' + str(len(b)).encode() + b'\0' + b).hexdigest()
def read(p): return json.loads(p.read_text())
def snapshot(): return {str(p.relative_to(E)): digest(p.read_bytes()) for p in E.rglob('*') if p.is_file()}
before = snapshot()
report = {}

# Check byte identity separately from mathematical validity.
checksums = {}
for line in (E/'SHA256SUMS').read_text().splitlines():
    h, name = line.split('  ', 1)
    assert name not in checksums
    assert before[name] == h, name
    checksums[name] = h
manifest = read(E/'FILE_MANIFEST.json')
for entry in manifest['files']:
    b = (E/entry['path']).read_bytes()
    assert digest(b) == entry['sha256'] and len(b) == entry['bytes'], entry['path']
duplicates = {}
for p in E.iterdir():
    if p.is_file() and p.name not in checksums and p.name != 'SHA256SUMS':
        matches = [q for q in F.rglob(p.name) if q.is_file() and q.read_bytes() == p.read_bytes()]
        assert matches, p.name
        duplicates[p.name] = [str(q.relative_to(E)) for q in matches]
assert digest((E/'zksecurity-reclaimprotocol.pdf').read_bytes()) == manifest['audit_pdf']['sha256']
report['integrity'] = {'checksum_entries':len(checksums), 'manifest_entries':len(manifest['files']),
                       'all_supplied_files':len(before), 'unlisted_top_level_copies_equal':duplicates}

# Bind source bytes to content responses, tree entries, and saved commit records.
prov = read(E/'source-provenance.json')
parent, fix, tree = [read(R/n) for n in ['parent-commit.json','fix-commit.json','parent-tree.json']]
assert [v['sha'] for v in fix['parents']] == [parent['sha']]
assert not tree['truncated']
tree_entries = {v['path']:v for v in tree['tree']}
def treehash(folder):
    prefix = folder + '/' if folder else ''
    children = [(p[len(prefix):],v) for p,v in tree_entries.items()
                if p.startswith(prefix) and '/' not in p[len(prefix):]]
    raw = b''
    for name,v in sorted(children, key=lambda nv:(nv[0]+('/' if nv[1]['type']=='tree' else '')).encode()):
        h = treehash(prefix+name) if v['type']=='tree' else v['sha']
        assert h == v['sha']
        raw += v['mode'].lstrip('0').encode()+b' '+name.encode()+b'\0'+bytes.fromhex(h)
    return objhash('tree',raw)
recomputed_tree = treehash('')
assert recomputed_tree == parent['commit']['tree']['sha']
source_checks = []
for entry in prov['sources']:
    api = read(F/entry['local_api_response'])
    b = base64.b64decode(api['content'])
    assert api['encoding']=='base64' and api['path']==entry['path']
    assert objhash('blob',b)==api['sha']==entry['git_blob_sha1']
    assert digest(b)==entry['sha256'] and len(b)==entry['size_bytes']==api['size']
    assert entry['revision'] in api['url']
    if entry['revision']==parent['sha']:
        assert tree_entries[entry['path']]['sha']==api['sha']
    else:
        assert entry['revision']==fix['sha']
        assert next(v for v in fix['files'] if v['filename']==entry['path'])['sha']==api['sha']
    matches = [p.name for p in R.iterdir() if p.is_file() and p.read_bytes()==b]
    assert matches
    source_checks.append({'path':entry['path'],'revision':entry['revision'],'matching_raw_files':matches})
for saved in prov['commits']:
    raw = parent if saved['sha']==parent['sha'] else fix
    assert saved['sha']==raw['sha'] and saved['tree']==raw['commit']['tree']['sha']
    assert saved['parents']==[v['sha'] for v in raw['parents']]
repo = read(R/'repository.json')
assert repo['full_name']==prov['recovered_repository']['full_name']
assert repo['parent']['full_name']==prov['recovered_repository']['api_parent']
assert repo['source']['full_name']==prov['recovered_repository']['api_source']
assert 'https://github.com/reclaimprotocol/circom-chacha20' in (R/'parent-readme.md').read_text()
for src,dest in [('parent-generics.circom','circuits/generics.circom'),('parent-xor32bits.circom','circuits/tests/xor32bits.circom')]:
    assert (R/src).read_bytes()==(R/'component-check'/dest).read_bytes()
report['provenance'] = {'parent':parent['sha'],'fix':fix['sha'],'parent_tree_recomputed':recomputed_tree,
                         'tree_response_top_level_sha':tree['sha'],
                         'sources_checked':source_checks,'scope':'Saved API records and source bytes; no new network retrieval or commit-object reconstruction.'}

# An independent binary decoder; no imports from the supplied verifier.
b = (R/'component-check/compiled/xor32bits.r1cs').read_bytes()
s = io.BytesIO(b)
def uint(stream,n):
    data=stream.read(n)
    assert len(data)==n
    return int.from_bytes(data,'little')
assert s.read(4)==b'r1cs' and uint(s,4)==1
sections={}
for _ in range(uint(s,4)):
    typ,size=uint(s,4),uint(s,8)
    assert typ not in sections
    sections[typ]=s.read(size)
    assert len(sections[typ])==size
assert s.read()==b'' and set(sections)=={1,2,3}
h=io.BytesIO(sections[1]); width=uint(h,4); prime=uint(h,width)
counts=dict(zip(['wires','public_outputs','public_inputs','private_inputs','labels','constraints'],[uint(h,n) for n in [4,4,4,4,8,4]]))
assert h.read()==b'' and width==32 and prime==P
c=io.BytesIO(sections[2]); constraints=[]
for row in range(counts['constraints']):
    terms={}
    for side in 'ABC':
        terms[side]={}
        for _ in range(uint(c,4)):
            wire,coeff=uint(c,4),uint(c,width)
            assert str(wire) not in terms[side] and wire<counts['wires'] and 0<coeff<P
            terms[side][str(wire)]=str(coeff)
    constraints.append({'index_zero_based':row,**terms})
assert c.read()==b''
labels=list(struct.unpack('<'+'Q'*counts['wires'],sections[3]))
sym=(R/'component-check/compiled/xor32bits.sym').read_text().splitlines()
readable=read(E/'R1CS_READABLE.json')
assert readable['counts']==counts and int(readable['prime'])==P
assert readable['constraints']==constraints and readable['wire_labels']==labels
assert readable['r1cs_sha256']==digest(b)
sym_keys=[k for k,v in readable.items() if v==sym]
assert len(sym_keys)==1

candidate=read(X/'original/counterexample.json')
original={k:int(v) for k,v in candidate['7_assignment'].items()}
assert all(0<=v<P for v in original.values())
named={}; consumed=set()
for name in ['a','b','out']:
    assert original['main.'+name]==original['main.xor.'+name]
    named['main.'+name+'[0]']=original['main.'+name]
    consumed.update(['main.'+name,'main.xor.'+name])
for short,long in [('abits','a_bits'),('bbits','b_bits'),('xors','xor_bits')]:
    values=[original[f'main.xor.{long}[{i}]'] for i in range(32)]
    for j,value in enumerate(reversed(values)): named[f'main.{short}[{j}]']=value
    consumed.update(f'main.xor.{long}[{i}]' for i in range(32))
assert consumed==set(original) and len(named)==99
w={0:1}; wire_for={}
for row in sym:
    label,wire,component,name=row.split(','); wire=int(wire)
    assert wire not in w and name not in wire_for and int(component)==0 and labels[wire]==int(label)
    w[wire]=named[name]; wire_for[name]=wire
assert set(w)==set(range(counts['wires'])) and set(wire_for)==set(named)

# Expand every compiled constraint into a polynomial and match source equations.
def canonical(poly): return {k:v%P for k,v in poly.items() if v%P}
def expanded(row):
    d={}
    for a,av in row['A'].items():
        for b,bv in row['B'].items():
            key=tuple(sorted(int(v) for v in [a,b] if int(v)!=0))
            d[key]=d.get(key,0)+int(av)*int(bv)
    for c,cv in row['C'].items():
        key=(int(c),) if int(c)!=0 else ()
        d[key]=d.get(key,0)-int(cv)
    return canonical(d)
expected=[]
for j in range(32):
    a,b,x=[wire_for[f'main.{n}[{j}]'] for n in ['abits','bbits','xors']]
    expected.append(canonical({(a,):-1,(b,):-1,(x,):1,tuple(sorted([a,b])):2}))
for operand,bits in [('a','abits'),('b','bbits')]:
    a=wire_for[f'main.{operand}[0]']; terms={(a,a):1}
    for j in range(32): terms[tuple(sorted([a,wire_for[f'main.{bits}[{j}]']]))]=-(1<<(31-j))
    expected.append(canonical(terms))
terms={(wire_for['main.out[0]'],):1}
for j in range(32): terms[(wire_for[f'main.xors[{j}]'],)]=-(1<<(31-j))
expected.append(canonical(terms))
assert [expanded(c) for c in constraints]==expected
rows=[]
for row in constraints:
    a,b,c=[sum(int(v)*w[int(k)] for k,v in row[side].items())%P for side in 'ABC']
    rows.append({'index':row['index_zero_based'],'A':str(a),'B':str(b),'C':str(c),'residual':str((a*b-c)%P)})
failures=[row for row in rows if int(row['residual'])]

# Direct source arithmetic, independently of coefficient evaluation.
a,b,out=[named[f'main.{n}[0]'] for n in ['a','b','out']]
packed={n:sum(named[f'main.{n}[{j}]']*(1<<(31-j)) for j in range(32))%P for n in ['abits','bbits','xors']}
xor_ok=all((named[f'main.xors[{j}]']-named[f'main.abits[{j}]']-named[f'main.bbits[{j}]']+2*named[f'main.abits[{j}]']*named[f'main.bbits[{j}]'])%P==0 for j in range(32))
direct=[(a-packed['abits'])*a%P,(b-packed['bbits'])*b%P]
assert xor_ok and packed['xors']==out and out!=(a^b)
assert [r['index'] for r in failures]==[32,33] and [int(r['residual']) for r in failures]==direct
recorded=read(E/'component-check.json')
assert counts==recorded['r1cs_counts']
assert recorded['r1cs_sha256']==digest((R/'component-check/compiled/xor32bits.r1cs').read_bytes())
assert recorded['sym_sha256']==digest((R/'component-check/compiled/xor32bits.sym').read_bytes())
assert recorded['candidate_sha256']==digest((X/'original/counterexample.json').read_bytes())
assert recorded['nonzero_mapped_assignment']=={k:str(v) for k,v in named.items() if v}
assert [int(v['A_times_B_minus_C_mod_p']) for v in recorded['failed_constraints']]==direct
report['independent_math']={'prime':str(P),'counts':counts,'all_35_source_polynomials_match_binary':True,
    'readable_matches_binary':True,'mapped_signals':len(named),'unmapped_signals':[],
    'packed':{k:str(v) for k,v in packed.items()},'expected_xor':a^b,'actual_output':str(out),
    'xor_equations_satisfied':xor_ok,'satisfied':len(rows)-len(failures),'failed':failures,'all_rows':rows}

# The original script overwrites build outputs, so execute an exact copy only.
runroot=O/'isolated-rerun'
assert not runroot.exists(), 'Refusing to reuse or overwrite prior rerun evidence'
shutil.copytree(F,runroot)
for name,relative in [('fixture','experiments/evidence/xorwords-2026-09-15/verify.py'),
                      ('component','experiments/evidence/xorwords-original-followup-2026-09-15/check_r1cs.py')]:
    command=[sys.executable,str(runroot/relative)]
    r=subprocess.run(command,cwd=runroot,capture_output=True,text=True)
    (O/f'{name}-rerun.stdout.txt').write_text(r.stdout)
    (O/f'{name}-rerun.stderr.txt').write_text(r.stderr)
    report[name+'_rerun']={'exit_code':r.returncode,'command':command}
    if name=='component' and r.returncode==0:
        result=json.loads(r.stdout)
        changed=[key for key in recorded if result[key]!=recorded[key]]
        report[name+'_rerun'].update({'compiler':result['compiler_version'],'differences_from_recorded':changed,
             'satisfied':result['satisfied_constraints'],'failed':len(result['failed_constraints'])})
        assert not changed
assert snapshot()==before, 'Evidence was changed during review'
report['preservation']={'all_original_files_unchanged':True,'files_checked':len(before)}
(O/'evidence-before.json').write_text(json.dumps(before,indent=2)+'\n')
(O/'independent-results.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:({x:v for x,v in value.items() if x!='all_rows'} if isinstance(value,dict) else value) for k,value in report.items()},indent=2))
