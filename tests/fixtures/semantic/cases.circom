pragma circom 2.0.0;

// Unit fixtures only; these are not the development project corpus.
template Plain() {
    signal input a;
    signal output out;
    out <== a;
}

template Assignment() {
    signal input a;
    signal output out;
    out <-- a;
}

template WeakIntermediate() {
    signal input a;
    signal intermediate;
    signal output out;
    intermediate <-- a;
    out <== intermediate;
}

template Division() {
    signal input a;
    signal input b;
    signal output out;
    out <-- a / b;
    out * b === a;
}

template IsZero() {
    signal input in;
    signal output out;
    signal inv;
    inv <-- in != 0 ? 1 / in : 0;
    out <== 1 - in * inv;
    in * out === 0;
}

template ProtectedDivision() {
    signal input a;
    signal input b;
    signal output out;
    component check = IsZero();
    check.in <== b;
    check.out === 0;
    out <-- a / b;
    out * b === a;
}

template UnusedOutput() {
    signal input a;
    signal output out;
    component child = Plain();
    child.a <== a;
    out <== a;
}

template ParameterAssertion(n) {
    assert(n > 0);
    signal input a;
    signal output out;
    out <== a;
}

template SignalAssertion() {
    signal input a;
    signal output out;
    assert(a != 0);
    out <== a;
}

template Num2Bits(n) {
    signal input in;
    signal output out[n];
    var sum = 0;
    for (var i = 0; i < n; i++) {
        out[i] <-- (in >> i) & 1;
        out[i] * (out[i] - 1) === 0;
        sum += out[i] * (2 ** i);
    }
    sum === in;
}

template LessThan(n) {
    signal input in[2];
    signal output out;
    component bits = Num2Bits(n + 1);
    bits.in <== in[0] + (2 ** n) - in[1];
    out <== 1 - bits.out[n];
}

template Comparison() {
    signal input a;
    signal input b;
    signal output out;
    component lt = LessThan(8);
    lt.in[0] <== a;
    lt.in[1] <== b;
    out <== lt.out;
}

template ProtectedComparison() {
    signal input a;
    signal input b;
    signal output out;
    component rangeA = Num2Bits(8);
    component rangeB = Num2Bits(8);
    rangeA.in <== a;
    rangeB.in <== b;
    component lt = LessThan(8);
    lt.in[0] <== a;
    lt.in[1] <== b;
    out <== lt.out;
}
