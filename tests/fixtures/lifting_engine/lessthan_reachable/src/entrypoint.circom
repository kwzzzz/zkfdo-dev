pragma circom 2.2.3;
include "component.circom";

// No range check: any field element reaches the comparator.
template Top() {
    signal input x;
    signal input y;
    signal output o;
    component cmp = Compare();
    cmp.a <== x;
    cmp.b <== y;
    o <== cmp.lt;
}

component main {public [x, y]} = Top();
