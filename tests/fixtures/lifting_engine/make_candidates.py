"""Writes candidate.json for the L-05 fixtures: the honest O0 witness of the component for
fixed inputs, named by the .sym file. Requires circom and node. Run from the repository root."""
import json, os, subprocess, sys, tempfile

P = 21888242871839275222246405745257275088548364400416034343698204186575808495617
ROOT = 'tests/fixtures/lifting_engine'
INPUTS = {
    # a = p - 1 makes the 8-bit comparator wrap: out = 1 although a >= b as integers.
    'lessthan_excluded': {'a': str(P - 1), 'b': '3'},
    'lessthan_reachable': {'a': str(P - 1), 'b': '3'},
    'lessthan_search': {'a': str(P - 1), 'b': '3'},
    'abort_repair': {'x': '100'},
}


def read_wtns(path):
    data = open(path, 'rb').read()
    n8 = int.from_bytes(data[24:28], 'little')
    count = int.from_bytes(data[28 + n8:32 + n8], 'little')
    start = 32 + n8 + 12
    return [int.from_bytes(data[start + i * n8:start + (i + 1) * n8], 'little') for i in range(count)]


for name, inputs in INPUTS.items():
    folder = os.path.join(ROOT, name)
    with tempfile.TemporaryDirectory() as out:
        subprocess.run(['circom', os.path.join(folder, 'src/standalone.circom'), '--O0', '--sym', '--wasm',
                        '-o', out, '-l', os.path.join(folder, 'src')], check=True, capture_output=True)
        js = os.path.join(out, 'standalone_js')
        json.dump(inputs, open(os.path.join(out, 'in.json'), 'w'))
        subprocess.run(['node', os.path.join(js, 'generate_witness.js'), os.path.join(js, 'standalone.wasm'),
                        os.path.join(out, 'in.json'), os.path.join(out, 'w.wtns')], check=True, capture_output=True)
        witness = read_wtns(os.path.join(out, 'w.wtns'))
        candidate = {}
        for line in open(os.path.join(out, 'standalone.sym')):
            _, wire, _, signal = line.strip().split(',', 3)
            if int(wire) >= 0:
                candidate[signal] = str(witness[int(wire)])
    json.dump(candidate, open(os.path.join(folder, 'candidate.json'), 'w'), indent=1, sort_keys=True)
    print(name, len(candidate), 'signals')
