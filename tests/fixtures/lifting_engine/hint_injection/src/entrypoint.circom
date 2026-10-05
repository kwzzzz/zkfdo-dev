pragma circom 2.2.3;
include "component.circom";

// Quotient and remainder by 4 with no range check on the remainder: the constraint
// admits r = 100, but the honest hints never compute it.
template Split() {
    signal input in;
    signal output q;
    signal output r;
    q <-- in \ 4;
    r <-- in % 4;
    in === q * 4 + r;
}

template Top() {
    signal input a;
    signal output out;
    component split = Split();
    split.in <== a;
    component child = Step();
    child.x <== split.r;
    out <== child.out;
}

component main {public [a]} = Top();
