pragma circom 2.2.2;

include "source/templates/helpers/base64url.circom";

template ControlledBase64DecodedLength() {
    signal input n;
    signal output decoded_len;

    component inRange = LessThan(4);
    inRange.in[0] <== n;
    inRange.in[1] <== 9;
    inRange.out === 1;

    component original = Base64UrlDecodedLength(8);
    original.m <== n;
    decoded_len <== original.decoded_len;
}

component main = ControlledBase64DecodedLength();
