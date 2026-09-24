pragma circom 2.1.6;

include "./helpers.circom";

template ProjectMain(word_bits) {
    signal input in;
    signal output out;

    component rsa = RSA(word_bits * 32);
    component hash = Hash(word_bits);
    component bits8 = Bits(8);
    component bits32 = Bits(32);
    component bits256 = Bits(word_bits * 4);

    rsa.in <== in;
    hash.in <== rsa.out;
    bits8.in <== hash.out;
    bits32.in <== bits8.out;
    bits256.in <== bits32.out;
    out <== bits256.out;
}

template RSA(modulus_bits) {
    signal input in;
    signal output out;

    var limb_bits = 64;
    component bigint = BigInt(modulus_bits / limb_bits, limb_bits);
    component range = RangeCheck(modulus_bits / 8);

    bigint.in <== in;
    range.in <== bigint.out;
    out <== range.out;
}

template Hash(width) {
    signal input in;
    signal output out;
    out <== in + width - width;
}

template Bits(width) {
    signal input in;
    signal output out;
    out <== in + width - width;
}
