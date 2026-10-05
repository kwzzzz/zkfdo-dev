pragma circom 2.2.3;
include "component.circom";

// The second input is the constant 5, so a candidate with another value there is excluded,
// but the first input is unchecked and can still make the comparison wrap.
template Top() {
    signal input x;
    signal output o;
    component cmp = Compare();
    cmp.a <== x;
    cmp.b <== 5;
    o <== cmp.lt;
}

component main {public [x]} = Top();
