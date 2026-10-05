use std::{path::Path, process::Command};

#[test]
fn synthetic_lifting_fixtures_compile_and_match_scoped_expectations() {
    run_fixture_suite("lifting_fixture_test.py");
}

#[test]
fn followup_lifting_fixtures_have_valid_candidates_and_independent_oracles() {
    run_fixture_suite("lifting_fixture_followup_test.py");
}

fn run_fixture_suite(script: &str) {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let result = Command::new("python3")
        .arg(root.join("tests").join(script))
        .current_dir(root)
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .output()
        .expect("lifting fixture checks require python3, circom 2.2.3, node and snarkjs");
    assert!(
        result.status.success(),
        "synthetic lifting fixture checks failed\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&result.stdout),
        String::from_utf8_lossy(&result.stderr)
    );
}
