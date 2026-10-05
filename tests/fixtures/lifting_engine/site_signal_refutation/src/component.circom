pragma circom 2.2.3;

// Synthetic one-hot flag with an unconstrained "all zero" assignment.
template Flag() {
    signal input inp;
    signal output out;
    signal output success;
    out <-- inp == 1 ? 1 : 0;
    out * (inp - 1) === 0;
    success <== out;
    success * (success - 1) === 0;
}
