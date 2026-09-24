pragma circom 2.1.6;

template BigInt(limbs, limb_bits) {
    signal input in;
    signal output out;
    out <== in + limbs + limb_bits - limbs - limb_bits;
}

template RangeCheck(bits) {
    signal input in;
    signal output out;
    out <== in + bits - bits;
}
