pragma circom 2.2.3;
include "component.circom";

// Both inputs are range-checked to 8 bits and their sum (at most 510) reaches the comparator
// against the constant 0. The comparator cannot wrap, but proving it needs the sum's interval,
// which follows from the two decompositions through the linear constraint s = x + y.
template Top() {
    signal input x;
    signal input y;
    signal output o;
    component rx = Num2Bits(8);
    rx.in <== x;
    component ry = Num2Bits(8);
    ry.in <== y;
    signal s;
    s <== x + y;
    component cmp = Compare();
    cmp.a <== s;
    cmp.b <== 0;
    o <== cmp.lt;
}

component main {public [x, y]} = Top();
