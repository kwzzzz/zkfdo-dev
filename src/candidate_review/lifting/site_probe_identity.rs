//! Conservative parameter identity for the separate site signal observations.

use std::{collections::BTreeSet, path::Path, path::PathBuf};

use anyhow::{ensure, Result};

/// The source inspector enumerates concrete template tuples, without executing tools.
/// A unique tuple is sufficient for every occurrence of that template. Multiple tuples
/// require an instance mapping that this path deliberately does not guess.
pub(super) fn concrete_parameters(
    entrypoint: &Path,
    source_root: &Path,
    libraries: &[PathBuf],
    prime: &str,
    template_name: &str,
) -> Result<Vec<String>> {
    let inspection = crate::targets::inspect_entrypoint_with_libraries_and_prime(
        entrypoint,
        source_root,
        libraries,
        prime,
    )?;
    ensure!(
        inspection.complete,
        "instance parameter inspection incomplete: {:?}",
        inspection.unsupported
    );
    let choices = inspection
        .instances
        .into_iter()
        .filter(|instance| instance.template_name == template_name)
        .map(|instance| instance.concrete_parameters)
        .collect::<BTreeSet<_>>();
    ensure!(
        choices.len() == 1,
        "instance parameters for {template_name} are missing or ambiguous: {choices:?}"
    );
    Ok(choices.into_iter().next().expect("one checked tuple"))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn inspect(body: &str, template: &str) -> Result<Vec<String>> {
        let directory = tempfile::tempdir()?;
        let entrypoint = directory.path().join("main.circom");
        std::fs::write(&entrypoint, body)?;
        concrete_parameters(&entrypoint, directory.path(), &[], "bn128", template)
    }

    #[test]
    fn repeated_instances_have_one_parameter_identity() {
        let source = "pragma circom 2.2.3;\n\
            template Child(n) {\n signal output out;\n out <== n;\n }\n\
            template Top() {\n component a = Child(2 + 3);\n component b = Child(5);\n }\n\
            component main = Top();\n";
        assert_eq!(inspect(source, "Child").unwrap(), ["5"]);
    }

    #[test]
    fn distinct_tuples_do_not_guess_the_representative() {
        let source = "pragma circom 2.2.3;\n\
            template Child(n) {\n signal output out;\n out <== n;\n }\n\
            template Top() {\n component a = Child(2);\n component b = Child(3);\n }\n\
            component main = Top();\n";
        let error = inspect(source, "Child").unwrap_err().to_string();
        assert!(error.contains("ambiguous"), "{error}");
    }

    #[test]
    fn no_parameters_are_an_explicit_empty_tuple() {
        let source = "pragma circom 2.2.3;\n\
            template Child() {\n signal output out;\n out <== 1;\n }\n\
            component main = Child();\n";
        assert!(inspect(source, "Child").unwrap().is_empty());
    }

    #[test]
    fn missing_template_is_not_an_empty_tuple() {
        let source = "pragma circom 2.2.3;\n\
            template Child() {\n signal output out;\n out <== 1;\n }\n\
            component main = Child();\n";
        assert!(inspect(source, "Missing").is_err());
    }
}
