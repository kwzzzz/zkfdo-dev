import subprocess,json,pathlib,re,sys,time,shutil
W=pathlib.Path('/private/tmp/controlled-v3-work')
R=pathlib.Path('runs/t6a-compile-reuse-2026-09-26')  # preserved binaries in R/'bin'
# Reruns write under a separate directory so the preserved measure-*.json are never overwritten.
OUT=R/'reproduction'
LIB=pathlib.Path('.external/zkbugs/dataset/circom/dependencies').resolve()
CIRCOM=shutil.which('circom')
variant=sys.argv[1]; projects=sys.argv[2].split(',')
roots={'zkemail':W/'zkemail/vulnerable','moonsong':W/'moonsong/vulnerable','inference':W/'inference/vulnerable'}
# Pinned inputs: refuse to measure anything but the recorded, unmodified revisions.
EXPECTED={'zkemail':'fc9949763858ca363a73a2764d9c1d26ef227478','inference':'d310309c141d36504b3486cebd96ed70ef3a4fdf','moonsong':'27cda6e74492fbad4aa3ca37ff5084ed391b534b'}
for name in projects:
    head=subprocess.run(['git','-C',str(roots[name]),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
    dirty=subprocess.run(['git','-C',str(roots[name]),'status','--porcelain'],capture_output=True,text=True,check=True).stdout
    assert head==EXPECTED[name] and not dirty, f'{name}: expected clean {EXPECTED[name]}, found {head} (dirty={bool(dirty)})'
out=[]
for name in projects:
    root=roots[name]
    mains=[f for f in sorted(root.rglob('*.circom')) if 'node_modules' not in f.parts and re.search(r'^\s*component\s+main\b',f.read_text(errors='ignore'),re.M)]
    for m in mains:
        t=time.time()
        r=subprocess.run([str(R/'bin'/f'zkfDO-{variant}'),'targets','--project',str(root),'--entrypoint',str(m),'--library-path',str(LIB),'--output',str(OUT/variant),'--circom-bin',CIRCOM,'--compile-timeout-seconds','600'],capture_output=True,text=True)
        wall=time.time()-t
        rep=json.loads(r.stdout)
        comp=[t['compile'] for t in rep['targets'] if t.get('compile')]
        # before: one capture per call site; after: one per unit (shared captures are identical objects)
        if variant=='after':
            caps=[u['compile'] for u in rep.get('compile_units',[]) if u.get('compile')]
        else:
            caps=comp
        statuses={t['identity']:t['wrapper_status'] for t in rep['targets']}
        out.append({'project':name,'entrypoint':str(m.relative_to(root)),'discovery_id':rep['discovery_id'],'wall_seconds':wall,
                    'call_sites':len(rep['targets']),'compile_invocations':len(caps),
                    'compile_seconds':sum(c['elapsed_seconds'] for c in caps),
                    'timeouts':sum(1 for c in caps if c['timed_out']),
                    'statuses':statuses})
        print(name, m.name, 'call_sites',len(rep['targets']),'invocations',len(caps),'compile_s=%.1f'%sum(c['elapsed_seconds'] for c in caps),'wall=%.1f'%wall, flush=True)
OUT.mkdir(parents=True,exist_ok=True)
json.dump(out,open(OUT/f'measure-{variant}.json','w'),indent=1)
