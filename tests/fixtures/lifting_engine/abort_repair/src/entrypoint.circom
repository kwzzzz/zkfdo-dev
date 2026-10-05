pragma circom 2.2.3;
include "component.circom";

// The quotient and remainder by 4 are hints; only the quotient is range-checked. For a = 100
// the honest quotient 50 fails the 4-bit check, but q = 15, r = 140 satisfies every
// constraint (r is unchecked).
template Top() {
    signal input a;
    signal output o;
    component d = Double();
    d.x <== a;
    signal q <-- d.y \ 4;
    signal r <-- d.y % 4;
    d.y === q * 4 + r;
    component rq = Num2Bits(4);
    rq.in <== q;
    o <== q;
}

component main {public [a]} = Top();
