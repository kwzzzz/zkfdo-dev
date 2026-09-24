pragma circom 2.1.3;

include "source/templates/helpers/misc.circom";

template ControlledBase64DecodedLength() {
    signal input n;
    signal output decoded_len;

    component inRange = LessThan(4);
    inRange.in[0] <== n;
    inRange.in[1] <== 9;
    inRange.out === 1;

    component original = Base64DecodedLength(8);
    original.n <== n;
    decoded_len <== original.decoded_len;
}

component main = ControlledBase64DecodedLength();
