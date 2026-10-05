pragma circom 2.2.3;

// Synthetic templates, unrelated to any project.
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

template Double() {
    signal input x;
    signal output y;
    y <== x * 2;
}
