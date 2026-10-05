pragma circom 2.2.3;

// Deliberately incomplete synthetic output relation, unrelated to any project.
template Loose() {
    signal input x;
    signal output out;
    signal square;
    square <== x * x;
    out <-- x + 1;
}
