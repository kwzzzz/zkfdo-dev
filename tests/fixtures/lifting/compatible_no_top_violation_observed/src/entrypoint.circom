pragma circom 2.2.3;
include "component.circom";

template Top() {
    signal input x;
    signal output out;
    component child = Loose();
    child.x <== x;
    // The child's unconstrained output does not reach the top output.
    out <== 2 * x;
}

component main {public [x]} = Top();
