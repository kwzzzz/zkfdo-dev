pragma circom 2.2.3;

// The caller is expected to restrict x to n bits. This toy deliberately
// omits the output relation; it is not the standard LessThan implementation.
template RangeAssumed(n) {
    assert(n == 3);
    signal input x;
    signal output out;
    signal square;
    square <== x * x;
    out <-- x + 1;
}
