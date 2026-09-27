use std::{fs, path::PathBuf, process::Command};

use tempfile::tempdir;
use zkfdo::targets::inspect_entrypoint;

fn assert_circom_compiles_when_available(entry: &std::path::Path, output: &std::path::Path) {
    if Command::new("circom").arg("--version").output().is_err() {
        return;
    }
    let compilation = Command::new("circom")
        .arg(entry)
        .arg("--r1cs")
        .arg("--O2")
        .arg("-o")
        .arg(output)
        .output()
        .expect("run circom");
    assert!(
        compilation.status.success(),
        "{}",
        String::from_utf8_lossy(&compilation.stderr)
    );
}

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
fn expands_reachable_component_arrays_with_concrete_loop_bounds() {
    let project = tempdir().unwrap();
    let entry = project.path().join("main.circom");
    fs::write(&entry, "template Root() { component children[2]; for (var i=0; i<2; i++) { children[i] = Leaf(i); } }\ntemplate Leaf(n) {}\ncomponent main = Root();\n").unwrap();
    let report = inspect_entrypoint(&entry, project.path()).unwrap();
    assert!(report.complete, "{:?}", report.unsupported);
    assert_eq!(report.instances.len(), 3);
    let leaf_parameters = report
        .instances
        .iter()
        .filter(|instance| instance.template_name == "Leaf")
        .map(|instance| instance.concrete_parameters.clone())
        .collect::<Vec<_>>();
    assert_eq!(leaf_parameters, [["0"], ["1"]]);
}

#[test]
fn expands_only_the_concretely_selected_if_branch() {
    let project = tempdir().unwrap();
    let entry = project.path().join("main.circom");
    fs::write(
        &entry,
        "template Root(n) { if (n == 3) { component selected = Leaf(n + 1); } else { component skipped = Other(); } }\ntemplate Leaf(n) {}\ntemplate Other() {}\ncomponent main = Root(3);\n",
    )
    .unwrap();
    let report = inspect_entrypoint(&entry, project.path()).unwrap();
    assert!(report.complete, "{:?}", report.unsupported);
    assert_eq!(report.instances.len(), 2);
    assert!(report
        .instances
        .iter()
        .any(|instance| instance.template_name == "Leaf" && instance.concrete_parameters == ["4"]));
    assert!(report
        .instances
        .iter()
        .all(|instance| instance.template_name != "Other"));
}

#[test]
fn mutually_exclusive_branches_can_initialize_the_same_component() {
    for (parameter, selected_argument) in [(0, "2"), (1, "1")] {
        let project = tempdir().unwrap();
        let entry = project.path().join("main.circom");
        fs::write(
            &entry,
            format!(
                "pragma circom 2.0.0;\ntemplate Choice(value) {{ signal output out; out <== value; }}\ntemplate Root(n) {{ component child; if (n == 1) {{ child = Choice(1); }} else {{ child = Choice(2); }} }}\ncomponent main = Root({parameter});\n"
            ),
        )
        .unwrap();

        if Command::new("circom").arg("--version").output().is_ok() {
            let compilation = Command::new("circom")
                .arg(&entry)
                .arg("--r1cs")
                .arg("--O2")
                .arg("-o")
                .arg(project.path())
                .output()
                .expect("run circom");
            assert!(
                compilation.status.success(),
                "{}",
                String::from_utf8_lossy(&compilation.stderr)
            );
        }

        let report = inspect_entrypoint(&entry, project.path()).unwrap();

        assert!(report.complete, "{:?}", report.unsupported);
        assert_eq!(report.instances.len(), 2);
        assert!(report
            .instances
            .iter()
            .any(|instance| instance.template_name == "Choice"
                && instance.concrete_parameters == [selected_argument]));
    }
}

#[test]
fn selected_branch_recognizes_parallel_component_assignment() {
    let project = tempdir().unwrap();
    let entry = project.path().join("main.circom");
    fs::write(
        &entry,
        "pragma circom 2.0.0;\ntemplate Leaf(value) { signal output out; out <== value; }\ntemplate Root(n) {\n  component child;\n  if (n == 1) { child = parallel Leaf(7); }\n  else { child = parallel Leaf(8); }\n}\ncomponent main = Root(1);\n",
    )
    .unwrap();
    assert_circom_compiles_when_available(&entry, project.path());

    let report = inspect_entrypoint(&entry, project.path()).unwrap();

    assert!(report.complete, "{:?}", report.unsupported);
    assert_eq!(report.instances.len(), 2);
    assert!(report.instances.iter().any(|instance| {
        instance.template_name == "Leaf" && instance.concrete_parameters == ["7"]
    }));
}

#[test]
fn array_loop_recognizes_parallel_component_assignments() {
    let project = tempdir().unwrap();
    let entry = project.path().join("main.circom");
    fs::write(
        &entry,
        "pragma circom 2.0.0;\ntemplate Leaf(value) { signal output out; out <== value; }\ntemplate Root() {\n  component children[2];\n  for (var i = 0; i < 2; i++) { children[i] = parallel Leaf(i); }\n}\ncomponent main = Root();\n",
    )
    .unwrap();
    assert_circom_compiles_when_available(&entry, project.path());

    let report = inspect_entrypoint(&entry, project.path()).unwrap();

    assert!(report.complete, "{:?}", report.unsupported);
    assert_eq!(report.instances.len(), 3);
    assert_eq!(
        report
            .instances
            .iter()
            .filter(|instance| instance.template_name == "Leaf")
            .map(|instance| instance.concrete_parameters.clone())
            .collect::<Vec<_>>(),
        [["0"], ["1"]]
    );
}

#[test]
fn duplicate_component_assignment_on_one_selected_path_fails_closed() {
    let project = tempdir().unwrap();
    let entry = project.path().join("main.circom");
    fs::write(
        &entry,
        "template First() {}\ntemplate Second() {}\ntemplate Root() { component selected; selected = First(); selected = Second(); }\ncomponent main = Root();\n",
    )
    .unwrap();

    let report = inspect_entrypoint(&entry, project.path()).unwrap();

    assert!(!report.complete);
    assert!(report
        .unsupported
        .iter()
        .any(|issue| issue.reason.contains("assigned more than once")));
}

#[test]
fn else_if_chain_does_not_consume_a_following_component() {
    for (parameter, selected) in [(1, "A"), (2, "B"), (3, "C")] {
        let project = tempdir().unwrap();
        let entry = project.path().join("main.circom");
        fs::write(
            &entry,
            format!(
                "template A() {{}}\ntemplate B() {{}}\ntemplate C() {{}}\ntemplate D() {{}}\ntemplate Root(n) {{\n  if (n == 1) {{ component a = A(); }}\n  else if (n == 2) {{ component b = B(); }}\n  else {{ component c = C(); }}\n  component d = D();\n}}\ncomponent main = Root({parameter});\n"
            ),
        )
        .unwrap();
        let report = inspect_entrypoint(&entry, project.path()).unwrap();
        assert!(report.complete, "{:?}", report.unsupported);
        assert!(report
            .instances
            .iter()
            .any(|instance| instance.template_name == selected));
        assert!(report
            .instances
            .iter()
            .any(|instance| instance.template_name == "D"));
        assert_eq!(report.instances.len(), 3);
    }
}

#[test]
fn unbraced_nested_if_binds_each_else_to_the_right_branch() {
    for (outer, inner, expected) in [(0, 0, "3"), (1, 0, "2"), (1, 1, "1")] {
        let project = tempdir().unwrap();
        let entry = project.path().join("main.circom");
        fs::write(
            &entry,
            format!(
                "pragma circom 2.0.0;\ntemplate Leaf(n) {{ signal output out; out <== n; }}\ntemplate Tail() {{ signal output out; out <== 9; }}\ntemplate Root(a,b) {{\n  signal output out;\n  component child;\n  if (a) if (b) child = Leaf(1); else child = Leaf(2); else child = Leaf(3);\n  out <== child.out;\n  component tail = Tail();\n}}\ncomponent main = Root({outer},{inner});\n"
            ),
        )
        .unwrap();
        assert_circom_compiles_when_available(&entry, project.path());

        let report = inspect_entrypoint(&entry, project.path()).unwrap();
        assert!(report.complete, "{:?}", report.unsupported);
        assert_eq!(report.instances.len(), 3);
        assert!(report.instances.iter().any(|instance| {
            instance.template_name == "Leaf" && instance.concrete_parameters == [expected]
        }));
        assert!(report
            .instances
            .iter()
            .any(|instance| instance.template_name == "Tail"));
    }
}

#[test]
fn a_for_update_of_another_variable_cannot_publish_stale_arguments() {
    let project = tempdir().unwrap();
    let entry = project.path().join("main.circom");
    fs::write(
        &entry,
        "template Leaf(n) {}\ntemplate Root() {\n  var width = 4;\n  for (var i = 0; i < 2; width++) { i = i + 1; }\n  component child = Leaf(width);\n}\ncomponent main = Root();\n",
    )
    .unwrap();
    let report = inspect_entrypoint(&entry, project.path()).unwrap();
    assert!(!report.complete);
    assert_eq!(report.instances.len(), 1);
    assert_eq!(report.instances[0].template_name, "Root");
    assert!(report
        .unsupported
        .iter()
        .any(|issue| issue.reason.contains("reassignment")));
}

#[test]
fn nested_loops_share_a_total_expansion_budget() {
    let project = tempdir().unwrap();
    let entry = project.path().join("main.circom");
    fs::write(
        &entry,
        "template Leaf() {}\ntemplate Root() {\n  component selected;\n  for (var i = 0; i < 317; i++) {\n    for (var j = 0; j < 317; j++) {\n      if (i == 316 && j == 316) { selected = Leaf(); }\n    }\n  }\n}\ncomponent main = Root();\n",
    )
    .unwrap();
    let report = inspect_entrypoint(&entry, project.path()).unwrap();
    assert!(!report.complete);
    assert_eq!(report.instances.len(), 1);
    assert_eq!(report.instances[0].template_name, "Root");
    assert!(report
        .unsupported
        .iter()
        .any(|issue| issue.reason.contains("total target expansion exceeded")));
}

#[test]
fn deeply_nested_large_loops_do_not_publish_partial_instances() {
    let project = tempdir().unwrap();
    let entry = project.path().join("main.circom");
    let depth = 8;
    let mut source = "template Leaf() {}\ntemplate Root() {\n  component selected;\n".to_string();
    for index in 0..depth {
        source.push_str(&format!(
            "  for (var i{index} = 0; i{index} < 100000; i{index}++) {{\n"
        ));
    }
    let condition = (0..depth)
        .map(|index| format!("i{index} == 99999"))
        .collect::<Vec<_>>()
        .join(" && ");
    source.push_str(&format!("    if ({condition}) {{ selected = Leaf(); }}\n"));
    for _ in 0..depth {
        source.push_str("  }\n");
    }
    source.push_str("}\ncomponent main = Root();\n");
    fs::write(&entry, source).unwrap();

    let report = inspect_entrypoint(&entry, project.path()).unwrap();

    assert!(!report.complete);
    assert_eq!(report.instances.len(), 1);
    assert_eq!(report.instances[0].template_name, "Root");
    assert!(report
        .unsupported
        .iter()
        .any(|issue| issue.reason.contains("total target expansion exceeded")));
}

#[test]
fn binary_tree_expansion_budget_clears_partial_instances() {
    let project = tempdir().unwrap();
    let entry = project.path().join("main.circom");
    fs::write(
        &entry,
        "template Tree(depth, path) {\n  if (depth > 0) {\n    component left = Tree(depth - 1, path * 2);\n    component right = Tree(depth - 1, path * 2 + 1);\n  }\n}\ncomponent main = Tree(16, 1);\n",
    )
    .unwrap();

    let report = inspect_entrypoint(&entry, project.path()).unwrap();
    assert!(!report.complete);
    assert_eq!(report.instances.len(), 1);
    assert_eq!(report.instances[0].template_name, "Tree");
    assert!(report
        .unsupported
        .iter()
        .any(|issue| issue.reason.contains("total target expansion exceeded")));
}

#[test]
fn unknown_loop_bound_is_rejected_without_publishing_children() {
    let project = tempdir().unwrap();
    let entry = project.path().join("main.circom");
    fs::write(&entry, "template Root() { component children[2]; for (var i=0; i<unknown; i++) { children[i] = Leaf(i); } }\ntemplate Leaf(n) {}\ncomponent main = Root();\n").unwrap();
    let report = inspect_entrypoint(&entry, project.path()).unwrap();
    assert!(!report.complete);
    assert_eq!(report.instances.len(), 1);
    assert_eq!(report.instances[0].template_name, "Root");
    assert!(report
        .unsupported
        .iter()
        .any(|issue| issue.reason.contains("loop condition is not concrete")));
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
fn repeated_loop_counter_declarations_are_scoped_declarations() {
    let project = tempdir().unwrap();
    let entry = project.path().join("main.circom");
    fs::write(
        &entry,
        "template Root() { component children[4]; for (var x = 0; x < 2; x++) { children[x] = Leaf(x); } for (var x = 2; x < 4; x++) { children[x] = Leaf(x); } }\ntemplate Leaf(n) {}\ncomponent main = Root();\n",
    )
    .unwrap();

    let report = inspect_entrypoint(&entry, project.path()).unwrap();

    assert!(report.complete, "{:?}", report.unsupported);
    assert_eq!(
        report
            .instances
            .iter()
            .filter(|instance| instance.template_name == "Leaf")
            .map(|instance| instance.concrete_parameters.clone())
            .collect::<Vec<_>>(),
        [["0"], ["1"], ["2"], ["3"]]
    );
}

#[test]
fn irrelevant_compile_time_values_are_not_evaluated_for_target_resolution() {
    let project = tempdir().unwrap();
    let entry = project.path().join("main.circom");
    fs::write(
        &entry,
        "template Root() { var b = (1 << 128) - 1; component child = Leaf(); }\ntemplate Leaf() {}\ncomponent main = Root();\n",
    )
    .unwrap();

    let report = inspect_entrypoint(&entry, project.path()).unwrap();

    assert!(report.complete, "{:?}", report.unsupported);
    assert_eq!(report.instances.len(), 2);
    assert!(report
        .instances
        .iter()
        .any(|instance| instance.template_name == "Leaf"));
}

#[test]
fn transitively_required_compile_time_values_still_fail_closed() {
    let project = tempdir().unwrap();
    let entry = project.path().join("main.circom");
    fs::write(
        &entry,
        "template Root() { var base = 1 << 128; var width = base + 1; component children[width]; for (var x = 0; x < width; x++) { children[x] = Leaf(); } }\ntemplate Leaf() {}\ncomponent main = Root();\n",
    )
    .unwrap();

    let report = inspect_entrypoint(&entry, project.path()).unwrap();

    assert!(!report.complete);
    assert_eq!(report.instances.len(), 1);
    assert!(report.unsupported.iter().any(|issue| issue
        .reason
        .contains("compile-time variable is not supported")));
    assert!(report.unsupported.iter().any(|issue| issue
        .reason
        .contains("component array length is not concrete")));
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
