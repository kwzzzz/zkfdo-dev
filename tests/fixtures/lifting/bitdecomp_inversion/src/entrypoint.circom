pragma circom 2.2.3;
include "component.circom";

template Bits(n) {
    signal input in;
    signal output bits[n];
    var sum = 0;
    for (var i = 0; i < n; i++) {
        bits[i] <-- (in >> i) & 1;
        bits[i] * (bits[i] - 1) === 0;
        sum += bits[i] * (1 << i);
    }
    in === sum;
}

template Top() {
    signal input x;
    signal output out;
    signal intermediate;
    component range = Bits(4);
    range.in <== x;
    // Reverse four bits so the public input is not merely aliased to child.x.
    intermediate <== range.bits[3] + 2*range.bits[2] + 4*range.bits[1] + 8*range.bits[0];
    component child = Loose();
    child.x <== intermediate;
    out <== child.out;
}

component main {public [x]} = Top();
