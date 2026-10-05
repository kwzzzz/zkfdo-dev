pragma circom 2.2.3;
include "component.circom";

// The caller range-checks both inputs to 8 bits, so the comparator never wraps.
template Top() {
    signal input x;
    signal input y;
    signal output o;
    component rx = Num2Bits(8);
    rx.in <== x;
    component ry = Num2Bits(8);
    ry.in <== y;
    component cmp = Compare();
    cmp.a <== x;
    cmp.b <== y;
    o <== cmp.lt;
}

component main {public [x, y]} = Top();
