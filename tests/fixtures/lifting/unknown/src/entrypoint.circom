pragma circom 2.2.3;
include "component.circom";

// Noncryptographic capability stub: only forward evaluation is supported
// by this fixture profile. No preimage hardness or nonexistence is claimed.
template ToyHash() {
    signal input preimage[2];
    signal output out;
    signal mid;
    mid <== preimage[0] * preimage[0] + preimage[1];
    out <== mid * mid + preimage[0];
}

template Top() {
    signal input preimage[2];
    signal output out;
    component hash = ToyHash();
    hash.preimage[0] <== preimage[0];
    hash.preimage[1] <== preimage[1];
    component child = Loose();
    child.x <== hash.out;
    out <== child.out;
}

component main {public [preimage]} = Top();
