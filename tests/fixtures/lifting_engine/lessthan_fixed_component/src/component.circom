pragma circom 2.2.3;

// The comparator of the other fixtures with the fix applied inside the component: both
// inputs are range-checked to 8 bits, so it can no longer wrap. Candidates found on the
// unfixed component are rejected by this one (its honest computation aborts).
template Num2Bits(n) {
    signal input in;
    signal output out[n];
    var lc = 0;
    var e2 = 1;
    for (var i = 0; i < n; i++) {
        out[i] <-- (in >> i) & 1;
        out[i] * (out[i] - 1) === 0;
        lc += out[i] * e2;
        e2 = e2 + e2;
    }
    lc === in;
}

template LessThan(n) {
    signal input in[2];
    signal output out;
    component n2b = Num2Bits(n + 1);
    n2b.in <== in[0] + (1 << n) - in[1];
    out <== 1 - n2b.out[n];
}

template Compare() {
    signal input a;
    signal input b;
    signal output lt;
    component ra = Num2Bits(8);
    ra.in <== a;
    component rb = Num2Bits(8);
    rb.in <== b;
    component c = LessThan(8);
    c.in[0] <== a;
    c.in[1] <== b;
    lt <== c.out;
}
