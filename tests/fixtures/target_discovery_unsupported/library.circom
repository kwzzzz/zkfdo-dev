pragma circom 2.1.6;

template Root(n) {
    signal input in[n];
    signal output out;

    component leaves[n];
    for (var i = 0; i < n; i++) {
        leaves[i] = Leaf(i);
        leaves[i].in <== in[i];
    }
    out <== Leaf(n)(in[0]);
}

template Leaf(index) {
    signal input in;
    signal output out;
    out <== in + index - index;
}
