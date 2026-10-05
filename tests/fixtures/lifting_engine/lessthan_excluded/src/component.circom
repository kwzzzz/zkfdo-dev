pragma circom 2.2.3;

// Synthetic comparator, unrelated to any project. zkFuzz attaches its integer-comparison
// condition to any template named LessThan.
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
    component c = LessThan(8);
    c.in[0] <== a;
    c.in[1] <== b;
    lt <== c.out;
}
