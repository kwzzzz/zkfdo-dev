use std::{fs, path::PathBuf};

use tempfile::tempdir;
use zkfdo::targets::inspect_entrypoint;

#[test]
fn inspection_includes_root_and_only_reachable_concrete_instances() {
    let project = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/target_discovery");
    let report = inspect_entrypoint(&project.join("main.circom"), &project).unwrap();
    assert!(report.complete, "{:?}", report.unsupported);
    let root = report.root.as_ref().unwrap();
    assert_eq!(root.template_name, "ProjectMain");
    assert_eq!(root.concrete_parameters, ["64"]);
    assert_eq!(report.instances.len(), 8);
    assert_eq!(report.scopes.len(), 6);
    assert_eq!(report.dependency_paths.len(), 3);
    let parameters = report
        .instances
        .iter()
        .filter(|i| i.template_name == "Bits")
        .map(|i| i.concrete_parameters.clone())
        .collect::<Vec<_>>();
    assert_eq!(parameters, [["256"], ["32"], ["8"]]);
    for scope in &report.scopes {
        let source = fs::read_to_string(&scope.path).unwrap();
        let lines = source.lines().collect::<Vec<_>>();
        assert!(
            lines[scope.start_line - 1].starts_with(&format!("template {}(", scope.template_name))
        );
        assert_eq!(lines[scope.end_line - 1], "}");
    }
    assert_eq!(
        report,
        inspect_entrypoint(&project.join("main.circom"), &project).unwrap()
    );
}

#[test]
fn unrelated_project_mains_and_unreachable_unsupported_bodies_are_excluded() {
    let project = tempdir().unwrap();
    fs::write(project.path().join("library.circom"), "template Root() { component child = Leaf(7); }\ntemplate Leaf(n) {}\ntemplate Uncalled() { component children[2]; for (var i = 0; i < 2; i++) { children[i] = Leaf(i); } }\n").unwrap();
    let selected = project.path().join("selected.circom");
    fs::write(
        &selected,
        "include \"library.circom\";\ncomponent main = Root();\n",
    )
    .unwrap();
    fs::write(
        project.path().join("other.circom"),
        "component main = Other(99);\n",
    )
    .unwrap();
    let report = inspect_entrypoint(&selected, project.path()).unwrap();
    assert!(report.complete, "{:?}", report.unsupported);
    assert_eq!(report.scopes.len(), 2);
    assert!(report
        .scopes
        .iter()
        .all(|scope| scope.template_name != "Uncalled"));
    assert!(report
        .dependency_paths
        .iter()
        .all(|path| !path.ends_with("other.circom")));
}

#[test]
fn reachable_arrays_and_control_flow_are_incomplete_without_guessed_children() {
    let project = tempdir().unwrap();
    let entry = project.path().join("main.circom");
    fs::write(&entry, "template Root() { component children[2]; for (var i=0; i<2; i++) { children[i] = Leaf(i); } }\ntemplate Leaf(n) {}\ncomponent main = Root();\n").unwrap();
    let report = inspect_entrypoint(&entry, project.path()).unwrap();
    assert!(!report.complete);
    assert_eq!(report.scopes.len(), 1);
    assert_eq!(report.scopes[0].template_name, "Root");
    assert!(report
        .unsupported
        .iter()
        .any(|u| u.reason.contains("component arrays")));
    assert!(report
        .unsupported
        .iter()
        .any(|u| u.reason.contains("inside control flow")));
}

#[test]
fn separate_component_assignment_and_constant_argument_expression_remain_supported() {
    let project = tempdir().unwrap();
    let entry = project.path().join("main.circom");
    fs::write(&entry, "template Root(n) { var width = n * 2; component child; child = Leaf(width + 1); }\ntemplate Leaf(n) {}\ncomponent main = Root(4);\n").unwrap();
    let report = inspect_entrypoint(&entry, project.path()).unwrap();
    assert!(report.complete, "{:?}", report.unsupported);
    assert_eq!(
        report
            .instances
            .iter()
            .find(|i| i.template_name == "Leaf")
            .unwrap()
            .concrete_parameters,
        ["9"]
    );
}

#[test]
fn unknown_arguments_and_unresolved_includes_are_explicit() {
    let project = tempdir().unwrap();
    let entry = project.path().join("main.circom");
    fs::write(
        &entry,
        "include \"missing.circom\";\ntemplate Root(n) {}\ncomponent main = Root(unknown);\n",
    )
    .unwrap();
    let report = inspect_entrypoint(&entry, project.path()).unwrap();
    assert!(!report.complete);
    assert!(report.root.is_none());
    assert!(report
        .unsupported
        .iter()
        .any(|u| u.reason.contains("include could not")));
    assert!(report
        .unsupported
        .iter()
        .any(|u| u.reason.contains("not concrete")));
}

#[test]
fn included_sources_cannot_escape_project_root() {
    let directory = tempdir().unwrap();
    let project = directory.path().join("project");
    fs::create_dir(&project).unwrap();
    fs::write(
        directory.path().join("outside.circom"),
        "template Outside() {}\n",
    )
    .unwrap();
    let entry = project.join("main.circom");
    fs::write(
        &entry,
        "include \"../outside.circom\";\ncomponent main = Outside();\n",
    )
    .unwrap();
    let report = inspect_entrypoint(&entry, &project).unwrap();
    assert!(!report.complete);
    assert!(report
        .unsupported
        .iter()
        .any(|u| u.reason.contains("outside the inspection project root")));
    assert!(report
        .dependency_paths
        .iter()
        .all(|p| p.starts_with(fs::canonicalize(&project).unwrap())));
}

#[test]
fn selected_external_wrapper_can_include_project_sources() {
    let directory = tempdir().unwrap();
    let project = directory.path().join("project");
    fs::create_dir(&project).unwrap();
    fs::write(project.join("library.circom"), "template Library(n) {}\n").unwrap();
    let wrapper = directory.path().join("wrapper.circom");
    fs::write(
        &wrapper,
        format!(
            "include \"{}\";\ncomponent main = Library(8);\n",
            project.join("library.circom").display()
        ),
    )
    .unwrap();
    let report = inspect_entrypoint(&wrapper, &project).unwrap();
    assert!(report.complete, "{:?}", report.unsupported);
    assert_eq!(report.root.unwrap().concrete_parameters, ["8"]);
    assert_eq!(report.dependency_paths.len(), 2);
}

#[test]
fn later_binding_changes_cannot_publish_stale_concrete_arguments() {
    for mutation in [
        "width = 7;",
        "width += 1;",
        "width++;",
        "if(n > 0) { width = 7; }",
    ] {
        let project = tempdir().unwrap();
        let entry = project.path().join("main.circom");
        fs::write(&entry, format!("template Root(n) {{ var width = n; {mutation} component child = Leaf(width); }}\ntemplate Leaf(n) {{}}\ncomponent main = Root(4);\n")).unwrap();
        let report = inspect_entrypoint(&entry, project.path()).unwrap();
        assert!(!report.complete, "{mutation}");
        assert_eq!(
            report.instances.len(),
            1,
            "must not publish guessed child arguments"
        );
        assert!(report
            .unsupported
            .iter()
            .any(|u| u.reason.contains("reassignment")));
    }
}

#[test]
fn multiple_definitions_on_one_line_are_not_precise_warning_scopes() {
    let project = tempdir().unwrap();
    let entry = project.path().join("main.circom");
    fs::write(
        &entry,
        "template Root() {} template Uncalled() {}\ncomponent main = Root();\n",
    )
    .unwrap();
    let report = inspect_entrypoint(&entry, project.path()).unwrap();
    assert!(!report.complete);
    assert!(report.unsupported.iter().any(|u| u
        .reason
        .contains("line-based warning attribution is ambiguous")));
}

#[test]
fn recursive_concrete_instantiation_is_not_complete() {
    let project = tempdir().unwrap();
    let entry = project.path().join("main.circom");
    fs::write(
        &entry,
        "template Root(n) { component child = Root(n); }\ncomponent main = Root(4);\n",
    )
    .unwrap();
    let report = inspect_entrypoint(&entry, project.path()).unwrap();
    assert!(!report.complete);
    assert_eq!(report.scopes.len(), 1);
    assert!(report
        .unsupported
        .iter()
        .any(|u| u.reason.contains("recursive concrete")));
}
