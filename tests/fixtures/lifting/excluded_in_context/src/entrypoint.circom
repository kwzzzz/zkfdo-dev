pragma circom 2.2.3;
include "component.circom";

template Bits3() {
    signal input in;
    signal output bits[3];
    var sum = 0;
    for (var i = 0; i < 3; i++) {
        bits[i] <-- (in >> i) & 1;
        bits[i] * (bits[i] - 1) === 0;
        sum += bits[i] * (1 << i);
    }
    in === sum;
}

template Top() {
    signal input x;
    signal output out;
    component range = Bits3();
    range.in <== x;
    component child = RangeAssumed(3);
    child.x <== x;
    out <== child.out;
}

component main {public [x]} = Top();
