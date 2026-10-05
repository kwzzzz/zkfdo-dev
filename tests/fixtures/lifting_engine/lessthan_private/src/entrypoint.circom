pragma circom 2.2.3;
include "component.circom";

// As lessthan_reachable, but every input is private: a reach changes no public input.
template Top() {
    signal input x;
    signal input y;
    signal output o;
    component cmp = Compare();
    cmp.a <== x;
    cmp.b <== y;
    o <== cmp.lt;
}

component main = Top();
