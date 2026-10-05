pragma circom 2.2.3;
include "component.circom";

template TopBus() {
    input Payload() payload;
    signal output out;
    component child = LooseBus();
    child.payload <== payload;
    out <== child.out;
}

component main {public [payload]} = TopBus();
