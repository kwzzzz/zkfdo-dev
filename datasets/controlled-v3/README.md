# controlled-v3 working corpus

Only `circomlib-decoder` and `unirep-big-less-than` belong to the checked-in
development compatibility corpus described by
`../manifest.controlled-v3-development.json`. They were used while extending
target inspection, so they are not a held-out performance set.

The BigLessThan projects preserve the exact vulnerable and fixed source blobs.
The relative `packages/circuits/circuits/circomlib` symlink only recreates the
dependency layout expected by the source's `./circomlib/...` includes. It points
to the copied, hash-recorded circomlib dependency directory and does not alter
the reviewed source.

The other local directories were candidate surveys that did not pass the v3
selection review. They are ignored to prevent accidental publication and are
preserved byte-for-byte in the ignored pre-freeze checkpoint recorded by the
v3 preflight report. Do not count them as selected cases or backend attempts.
