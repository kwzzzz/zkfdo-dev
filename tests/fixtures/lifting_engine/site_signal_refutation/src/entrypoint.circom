pragma circom 2.2.3;
include "component.circom";

// The caller requires success, which rules out the all-zero assignment.
template Top() {
    signal input sel;
    signal output result;
    component flag = Flag();
    flag.inp <== sel;
    flag.success === 1;
    result <== flag.out * 5;
}

component main {public [sel]} = Top();
