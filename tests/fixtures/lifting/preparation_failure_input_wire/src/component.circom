pragma circom 2.2.3;

// A real O0 wire exists for payload.x. The direct-main input-name resolver
// does not recognize a dotted bus member as a top-level component input.
bus Payload() {
    signal x;
}

template LooseBus() {
    input Payload() payload;
    signal output out;
    signal square;
    square <== payload.x * payload.x;
    out <-- payload.x + 1;
}
