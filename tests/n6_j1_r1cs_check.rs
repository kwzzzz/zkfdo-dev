//! Reuse the repository's Rust R1CS and WTNS parsers to check one honest witness.
//! The executable test is invoked only by the N6-J1 base-input selector.

mod candidate_review {
    pub mod schema {
        #[derive(Clone, Debug, Eq, PartialEq)]
        pub struct R1csShape {
            pub wires: usize,
            pub labels: u64,
            pub public_outputs: usize,
            pub public_inputs: usize,
            pub private_inputs: usize,
            pub constraints: usize,
        }
    }

    pub mod r1cs {
        include!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/src/candidate_review/r1cs.rs"
        ));
    }
}

mod wtns {
    include!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/src/candidate_review/lifting/wtns.rs"
    ));
}

#[test]
#[ignore = "requires N6-J1 input files"]
fn check_current_witness() {
    let r1cs_path = std::env::var("N6_J1_R1CS").expect("N6_J1_R1CS");
    let witness_path = std::env::var("N6_J1_WTNS").expect("N6_J1_WTNS");
    let r1cs_bytes = std::fs::read(&r1cs_path).expect("read R1CS");
    let r1cs = candidate_review::r1cs::R1cs::parse(&r1cs_bytes).expect("parse R1CS");
    let values =
        wtns::read_wtns(std::path::Path::new(&witness_path), &r1cs.prime).expect("read witness");
    let failures = r1cs.failed_constraint_indices(&values).expect("check R1CS");
    assert!(failures.is_empty(), "witness violates original R1CS");
}
