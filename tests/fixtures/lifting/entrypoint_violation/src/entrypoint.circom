pragma circom 2.2.3;
include "component.circom";

template Top() {
    signal input x;
    signal output out;
    component child = Loose();
    child.x <== x;
    out <== child.out;
}

component main {public [x]} = Top();
