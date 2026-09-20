pragma circom 2.0.5;

include "circuits/bitify.circom";
include "circuits/binsum.circom";
include "source/constants.circom";
include "source/pairing/bigint_func.circom";
include "source/pairing/bigint.circom";
include "source/pairing/field_elements_func.circom";
include "source/pairing/fp.circom";
include "source/hash_to_field.circom";

template ControlledArrayXOR() {
    signal input a[4];
    signal input b[4];
    signal output out[4];

    component aRange[4];
    component bRange[4];
    for (var i = 0; i < 4; i++) {
        aRange[i] = Num2Bits(8);
        aRange[i].in <== a[i];
        bRange[i] = Num2Bits(8);
        bRange[i].in <== b[i];
    }

    component original = ArrayXOR(4);
    for (var i = 0; i < 4; i++) {
        original.a[i] <== a[i];
        original.b[i] <== b[i];
    }
    for (var i = 0; i < 4; i++) {
        out[i] <== original.out[i];
    }
}

component main = ControlledArrayXOR();
