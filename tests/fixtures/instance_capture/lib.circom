pragma circom 2.1.6;

// Synthetic templates, unrelated to any project. They use the constructs the F-01
// interpreter could not evaluate: array variables and arguments, an array computed by a
// function, a constant taken from an array, integer division in lengths, loop bounds and
// indices, a multi-dimensional component array, a pass-through array parameter, and
// anonymous components inside a loop.

function CONSTS(t) {
    var c[6] = [11, 12, 13, 14, 15, 16];
    var out[3];
    for (var i = 0; i < 3; i++) {
        out[i] = c[i + t];
    }
    return out;
}

template Scale(k, table) {
    signal input in;
    signal output out;
    out <== in * (k + table[1]);
}

template Pass(table) {
    signal input in;
    signal output out;
    component inner = Scale(2, table);
    inner.in <== in;
    out <== inner.out;
}

template Square() {
    signal input in;
    signal output out;
    out <== in * in;
}

template Body(n) {
    signal input in;
    signal output out;
    var ROUNDS[3] = [2, 3, 4];
    var r = ROUNDS[n - 1];
    var table[3] = CONSTS(n);
    var grid[2][2] = [[1, 2], [3, 4]];
    component scales[r \ 2 + 1];
    component cells[2][2];
    for (var i = 0; i < r \ 2 + 1; i++) {
        scales[i] = Scale(i, table);
        scales[i].in <== in;
    }
    for (var i = 0; i < 2; i++) {
        for (var j = 0; j < 2; j++) {
            cells[i][j] = Scale(grid[i][j], grid[i]);
            cells[i][j].in <== in;
        }
    }
    component pass = Pass(table);
    pass.in <== in;
    signal sq[2];
    for (var i = 0; i < 2; i++) {
        sq[i] <== Square()(scales[i].out);
    }
    out <== sq[0] + sq[1] + pass.out + cells[1][1].out;
}
