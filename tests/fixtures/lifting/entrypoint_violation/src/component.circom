pragma circom 2.2.3;

// Deliberately incomplete toy relation; no external project is represented.
template Loose() {
    signal input x;
    signal output out;
    signal square;
    square <== x * x;
    out <-- x + 1;
}
