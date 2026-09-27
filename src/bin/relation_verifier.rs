//! Pinned external clean relation-exclusion verifier for unique-propagation certificates.
//!
//! Invoked by the review engine as `zkfdo-relation-verifier CONTEXT RESULT` with an empty
//! environment. It writes only the result file; any failure is reported by exit status.

fn main() {
    let arguments = std::env::args_os().skip(1).collect::<Vec<_>>();
    let succeeded = match arguments.as_slice() {
        [context, result] => {
            zkfdo::injection::run_relation_verifier(context.as_ref(), result.as_ref()).is_ok()
        }
        _ => false,
    };
    std::process::exit(if succeeded { 0 } else { 1 });
}
