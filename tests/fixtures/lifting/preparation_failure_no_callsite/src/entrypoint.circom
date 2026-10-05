pragma circom 2.2.3;
include "component.circom";

// Loose is in the source closure but is never instantiated at this entrypoint.
template TopWithoutChild() {
    signal input z;
    signal output out;
    out <== z + 7;
}

component main {public [z]} = TopWithoutChild();
