pragma circom 2.2.3;
include "component.circom";

template Top() {
    signal input x;
    signal input y;
    signal output out;
    signal intermediate;
    intermediate <== 3 * x + y + 5;
    component child = Loose();
    child.x <== intermediate;
    out <== child.out;
}

component main {public [x, y]} = Top();
