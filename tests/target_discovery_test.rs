use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
    time::{Duration, Instant},
};

use tempfile::tempdir;
use zkfdo::targets::{
    discover_project_targets, discover_project_targets_with, inspect_entrypoint, DiscoveryOptions,
    EntrypointStatus, WrapperStatus,
};

fn fixture(name: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures")
        .join(name)
}

#[test]
fn discovers_reachable_concrete_targets_and_generates_wrappers() {
    let output = tempdir().expect("output dir");
    let report = discover_project_targets(fixture("target_discovery"), output.path(), None)
        .expect("target discovery");

    assert_eq!(report.entrypoint_status, EntrypointStatus::Found);
    assert_eq!(report.entrypoints.len(), 1);
    assert_eq!(
        report.entrypoints[0].template_name.as_deref(),
        Some("ProjectMain")
    );
    assert_eq!(report.entrypoints[0].parameters, ["64"]);
    assert_eq!(report.targets.len(), 7);
    assert_eq!(report.generated_wrapper_count, 7);
    assert_eq!(report.compile_succeeded_count, 0);
    assert!(report.unsupported.is_empty(), "{:?}", report.unsupported);

    let mut bits_parameters = report
        .targets
        .iter()
        .filter(|target| target.template_name == "Bits")
        .map(|target| target.concrete_parameters.clone())
        .collect::<Vec<_>>();
    bits_parameters.sort();
    assert_eq!(bits_parameters, [["256"], ["32"], ["8"]]);

    let bigint = report
        .targets
        .iter()
        .find(|target| target.template_name == "BigInt")
        .expect("nested BigInt target");
    assert_eq!(bigint.concrete_parameters, ["32", "64"]);
    assert_eq!(bigint.origin.parent_template, "RSA");
    assert_eq!(bigint.origin.parent_parameters, ["2048"]);
    assert_eq!(bigint.origin.component_name, "bigint");

    for target in &report.targets {
        assert_eq!(target.wrapper_status, WrapperStatus::Generated);
        let wrapper_path = target
            .generated_wrapper_path
            .as_ref()
            .expect("generated wrapper path");
        let wrapper = fs::read_to_string(wrapper_path).expect("wrapper source");
        assert!(wrapper.contains("include \""));
        assert!(wrapper.contains(&format!(
            "component main = {}({});",
            target.template_name,
            target.concrete_parameters.join(", ")
        )));
    }

    let persisted: serde_json::Value = serde_json::from_slice(
        &fs::read(report.work_dir.join("discovery.json")).expect("discovery report"),
    )
    .expect("valid discovery JSON");
    assert_eq!(persisted["entrypoint_status"], "found");
    assert_eq!(persisted["targets"].as_array().map(Vec::len), Some(7));
}

#[test]
fn validates_generated_library_wrappers_with_circom_when_available() {
    if Command::new("circom").arg("--version").output().is_err() {
        return;
    }

    let output = tempdir().expect("output dir");
    let report = discover_project_targets(
        fixture("target_discovery"),
        output.path(),
        Some(PathBuf::from("circom").as_path()),
    )
    .expect("target discovery");

    assert_eq!(report.generated_wrapper_count, 7);
    assert_eq!(report.compile_succeeded_count, 7);
    assert!(report.targets.iter().all(|target| {
        target.wrapper_status == WrapperStatus::CompileSucceeded
            && target
                .compiler_stdout_path
                .as_ref()
                .is_some_and(|path| path.exists())
            && target
                .compiler_stderr_path
                .as_ref()
                .is_some_and(|path| path.exists())
    }));
}

#[test]
fn expands_concrete_array_and_anonymous_targets() {
    let output = tempdir().expect("output dir");
    let report =
        discover_project_targets(fixture("target_discovery_unsupported"), output.path(), None)
            .expect("target discovery");

    assert_eq!(report.entrypoint_status, EntrypointStatus::Found);
    assert_eq!(report.targets.len(), 4);
    assert_eq!(
        report
            .targets
            .iter()
            .take(3)
            .map(|target| target.origin.component_name.as_str())
            .collect::<Vec<_>>(),
        ["leaves[0]", "leaves[1]", "leaves[2]"]
    );
    assert!(report.targets[3]
        .origin
        .component_name
        .starts_with("@anonymous:"));
    assert!(report.unsupported.is_empty(), "{:?}", report.unsupported);
    assert_eq!(report.targets[3].template_name, "Leaf");
    assert_eq!(report.targets[3].concrete_parameters, ["3"]);
}

#[test]
fn anonymous_calls_in_loops_and_nested_signal_arguments_are_reachable() {
    let project = tempdir().expect("project");
    fs::write(
        project.path().join("main.circom"),
        "pragma circom 2.1.6;\n\
         template Child(k) { signal input in; signal output out; out <== in + k; }\n\
         template Outer() { signal input in; signal output out; out <== in; }\n\
         template Root(n) {\n\
           signal input in[n]; signal output out[n];\n\
           for (var i = 0; i < n; i++) { out[i] <== Outer()(Child(i)(in[i])); }\n\
         }\n\
         component main = Root(3);\n",
    )
    .expect("source");
    let output = tempdir().expect("output");
    let report = discover_project_targets(project.path(), output.path(), None)
        .expect("anonymous target discovery");

    assert!(report.unsupported.is_empty(), "{:?}", report.unsupported);
    assert_eq!(report.targets.len(), 6);
    let child_parameters = report
        .targets
        .iter()
        .filter(|target| target.template_name == "Child")
        .map(|target| target.concrete_parameters.clone())
        .collect::<Vec<_>>();
    assert_eq!(child_parameters, [["0"], ["1"], ["2"]]);
    assert_eq!(
        report
            .targets
            .iter()
            .map(|target| target.identity.as_str())
            .collect::<std::collections::HashSet<_>>()
            .len(),
        6
    );
    let inspection = inspect_entrypoint(&project.path().join("main.circom"), project.path())
        .expect("anonymous entrypoint inspection");
    assert!(inspection.complete, "{:?}", inspection.unsupported);
    // Inspection lists unique concrete template/parameter combinations, not call-site copies.
    assert_eq!(inspection.instances.len(), 5);
}

#[test]
fn anonymous_call_with_unresolved_template_parameter_is_not_guessed() {
    let project = tempdir().expect("project");
    fs::write(
        project.path().join("main.circom"),
        "template Root() { signal input in; signal output out; out <== Child(unknown)(in); }\n\
         template Child(n) { signal input in; signal output out; out <== in + n; }\n\
         component main = Root();\n",
    )
    .expect("source");
    let output = tempdir().expect("output");
    let report = discover_project_targets(project.path(), output.path(), None)
        .expect("anonymous target discovery");

    assert!(report.targets.is_empty());
    assert!(report
        .unsupported
        .iter()
        .any(|case| case.reason.contains("template parameters are not concrete")));
}

#[test]
fn anonymous_call_sites_on_the_same_line_remain_distinct() {
    let project = tempdir().expect("project");
    fs::write(
        project.path().join("main.circom"),
        "template Child(k) { signal input in; signal output out; out <== in + k; }\n\
         template Root(n) { signal input in[n]; signal output left[n]; signal output right[n]; for (var i = 0; i < n; i++) { left[i] <== Child(i)(in[i]); } for (var i = 0; i < n; i++) { right[i] <== Child(i)(in[i]); } }\n\
         component main = Root(2);\n",
    )
    .expect("source");
    let output = tempdir().expect("output");
    let report = discover_project_targets(project.path(), output.path(), None)
        .expect("anonymous target discovery");

    assert!(report.unsupported.is_empty(), "{:?}", report.unsupported);
    assert_eq!(report.targets.len(), 4);
    assert_eq!(
        report
            .targets
            .iter()
            .map(|target| target.identity.as_str())
            .collect::<std::collections::HashSet<_>>()
            .len(),
        4
    );
    assert_eq!(
        report
            .targets
            .iter()
            .filter(|target| target.concrete_parameters == ["0"])
            .count(),
        2
    );
    assert_eq!(
        report
            .targets
            .iter()
            .filter(|target| target.concrete_parameters == ["1"])
            .count(),
        2
    );
}

#[test]
fn compiles_wrapper_for_anonymous_target_when_circom_is_available() {
    if Command::new("circom").arg("--version").output().is_err() {
        return;
    }

    let project = tempdir().expect("project");
    fs::write(
        project.path().join("lib.circom"),
        "pragma circom 2.1.6;\n\
         template Child(k) { signal input in; signal output out; out <== in + k; }\n\
         template Root() { signal input in; signal output out; out <== Child(7)(in); }\n",
    )
    .expect("library");
    fs::write(
        project.path().join("main.circom"),
        "pragma circom 2.1.6;\ninclude \"lib.circom\";\ncomponent main = Root();\n",
    )
    .expect("entrypoint");
    let output = tempdir().expect("output");
    let report = discover_project_targets(
        project.path(),
        output.path(),
        Some(PathBuf::from("circom").as_path()),
    )
    .expect("anonymous target discovery");

    assert!(report.unsupported.is_empty(), "{:?}", report.unsupported);
    assert_eq!(report.targets.len(), 1);
    assert_eq!(report.targets[0].template_name, "Child");
    assert_eq!(report.targets[0].concrete_parameters, ["7"]);
    assert_eq!(
        report.targets[0].wrapper_status,
        WrapperStatus::CompileSucceeded
    );
}

#[test]
fn rejects_unknown_loop_bounds_without_guessing_targets() {
    let project = tempdir().expect("project");
    fs::write(
        project.path().join("main.circom"),
        "template Root() { component leaves[2]; for (var i=0; i<unknown; i++) { leaves[i] = Leaf(i); } }\ntemplate Leaf(n) {}\ncomponent main = Root();\n",
    )
    .expect("source");
    let output = tempdir().expect("output");
    let report =
        discover_project_targets(project.path(), output.path(), None).expect("target discovery");

    assert!(report.targets.is_empty());
    assert!(report
        .unsupported
        .iter()
        .any(|case| case.reason.contains("loop condition is not concrete")));
}

#[test]
fn nested_loops_share_the_discovery_expansion_budget() {
    let project = tempdir().expect("project");
    fs::write(
        project.path().join("main.circom"),
        "template Leaf() {}\ntemplate Root() {\n  component selected;\n  for (var i = 0; i < 317; i++) {\n    for (var j = 0; j < 317; j++) {\n      if (i == 316 && j == 316) { selected = Leaf(); }\n    }\n  }\n}\ncomponent main = Root();\n",
    )
    .expect("source");
    let output = tempdir().expect("output");
    let report =
        discover_project_targets(project.path(), output.path(), None).expect("target discovery");

    assert!(report.targets.is_empty());
    assert!(report
        .unsupported
        .iter()
        .any(|case| case.reason.contains("total target expansion exceeded")));
}

#[test]
fn repeated_binary_subtrees_emit_unique_concrete_targets() {
    let project = tempdir().expect("project");
    fs::write(
        project.path().join("tree.circom"),
        "template Tree(depth) {\n  if (depth > 0) {\n    component left = Tree(depth - 1);\n    component right = Tree(depth - 1);\n  }\n}\n",
    )
    .expect("source");
    fs::write(
        project.path().join("main.circom"),
        "include \"tree.circom\";\ncomponent main = Tree(10);\n",
    )
    .expect("entrypoint");
    let output = tempdir().expect("output");
    let report =
        discover_project_targets(project.path(), output.path(), None).expect("target discovery");

    assert!(report.unsupported.is_empty(), "{:?}", report.unsupported);
    assert_eq!(report.targets.len(), 20);
    assert_eq!(report.generated_wrapper_count, 20);
    let identities = report
        .targets
        .iter()
        .map(|target| target.identity.as_str())
        .collect::<std::collections::HashSet<_>>();
    assert_eq!(identities.len(), report.targets.len());
    for depth in 0..10 {
        assert_eq!(
            report
                .targets
                .iter()
                .filter(|target| target.concrete_parameters == [depth.to_string()])
                .count(),
            2,
            "left and right origins must remain distinct for Tree({depth})"
        );
    }
}

#[test]
fn binding_mutations_cannot_publish_stale_discovery_targets() {
    let project = tempdir().expect("project");
    fs::write(
        project.path().join("main.circom"),
        "template Root(n) { var width = n; width = 7; component child = Leaf(width); }\ntemplate Leaf(n) {}\ncomponent main = Root(4);\n",
    )
    .expect("source");
    let output = tempdir().expect("output");

    let report =
        discover_project_targets(project.path(), output.path(), None).expect("target discovery");

    assert!(report.targets.is_empty());
    assert!(report
        .unsupported
        .iter()
        .any(|case| case.reason.contains("reassignment")));
}

#[test]
fn reports_missing_and_multiple_entrypoints_explicitly() {
    let missing_project = tempdir().expect("missing-main project");
    fs::write(
        missing_project.path().join("library.circom"),
        "pragma circom 2.1.6; template Library() {}",
    )
    .expect("library source");
    let missing_output = tempdir().expect("missing-main output");
    let missing = discover_project_targets(missing_project.path(), missing_output.path(), None)
        .expect("missing-main discovery");
    assert_eq!(missing.entrypoint_status, EntrypointStatus::Missing);
    assert!(missing.targets.is_empty());
    assert!(missing
        .unsupported
        .iter()
        .any(|case| case.reason.contains("no top-level component main")));

    let multiple_project = tempdir().expect("multiple-main project");
    fs::write(
        multiple_project.path().join("one.circom"),
        "pragma circom 2.1.6; template One() {} component main = One();",
    )
    .expect("first main");
    fs::write(
        multiple_project.path().join("two.circom"),
        "pragma circom 2.1.6; template Two() {} component main = Two();",
    )
    .expect("second main");
    let multiple_output = tempdir().expect("multiple-main output");
    let multiple = discover_project_targets(multiple_project.path(), multiple_output.path(), None)
        .expect("multiple-main discovery");
    assert_eq!(multiple.entrypoint_status, EntrypointStatus::Multiple);
    assert_eq!(multiple.entrypoints.len(), 2);
    assert!(multiple.targets.is_empty());
}

#[test]
fn refuses_wrapper_when_target_source_already_contains_main() {
    let project = tempdir().expect("project");
    fs::write(
        project.path().join("main.circom"),
        r#"pragma circom 2.1.6;
template Root() { component child = Child(); }
template Child() {}
component main = Root();
"#,
    )
    .expect("source");
    let output = tempdir().expect("output");
    let report =
        discover_project_targets(project.path(), output.path(), None).expect("target discovery");

    assert_eq!(report.targets.len(), 1);
    assert_eq!(report.targets[0].template_name, "Child");
    assert_eq!(report.targets[0].wrapper_status, WrapperStatus::Unsupported);
    assert!(report.targets[0].generated_wrapper_path.is_none());
    assert!(report.targets[0]
        .failure_reason
        .as_deref()
        .is_some_and(|reason| reason.contains("component main")));
}

fn write(path: &Path, source: &str) {
    fs::create_dir_all(path.parent().expect("parent")).expect("source dir");
    fs::write(path, source).expect("source");
}

#[test]
fn selected_entrypoint_uses_only_its_include_closure() {
    let project = tempdir().expect("project");
    let circuits = project.path().join("circuits");
    write(
        &circuits.join("a_main.circom"),
        "pragma circom 2.1.6;\ninclude \"lib.circom\";\ncomponent main = A();\n",
    );
    write(
        &circuits.join("lib.circom"),
        "pragma circom 2.1.6;\ntemplate A() { component leaf = Leaf(); }\ntemplate Leaf() {}\n",
    );
    write(
        &circuits.join("b_main.circom"),
        "pragma circom 2.1.6;\ntemplate B() { component other = Other(); }\ntemplate Other() {}\ncomponent main = B();\n",
    );
    write(&circuits.join("broken.circom"), "template ( {");

    let output = tempdir().expect("output");
    let whole = discover_project_targets(project.path(), output.path(), None).expect("scan");
    assert_eq!(whole.entrypoint_status, EntrypointStatus::Multiple);

    let options = DiscoveryOptions {
        entrypoint: Some(circuits.join("a_main.circom")),
        ..DiscoveryOptions::default()
    };
    let report =
        discover_project_targets_with(project.path(), output.path(), &options).expect("selected");
    assert_eq!(report.entrypoint_status, EntrypointStatus::Found);
    assert_eq!(report.entrypoints.len(), 1);
    assert_eq!(report.entrypoints[0].template_name.as_deref(), Some("A"));
    assert_eq!(
        report
            .targets
            .iter()
            .map(|target| target.template_name.as_str())
            .collect::<Vec<_>>(),
        ["Leaf"]
    );
    assert!(report.unsupported.is_empty(), "{:?}", report.unsupported);
    assert_eq!(
        report.selected_entrypoint.as_deref(),
        Some(
            fs::canonicalize(circuits.join("a_main.circom"))
                .unwrap()
                .as_path()
        )
    );
    assert_eq!(report.compile_timeout_seconds, None);
}

#[test]
fn library_paths_resolve_package_includes_in_order() {
    let project = tempdir().expect("project");
    let library = tempdir().expect("library");
    write(
        &project.path().join("main.circom"),
        "pragma circom 2.1.6;\ninclude \"pkg/circuits/gadget.circom\";\ntemplate Root() { component gadget = Gadget(); }\ncomponent main = Root();\n",
    );
    write(
        &library.path().join("pkg/circuits/gadget.circom"),
        "pragma circom 2.1.6;\ntemplate Gadget() { component bit = Bit(); }\ntemplate Bit() {}\n",
    );
    let output = tempdir().expect("output");
    let mut options = DiscoveryOptions {
        entrypoint: Some(project.path().join("main.circom")),
        ..DiscoveryOptions::default()
    };
    let unresolved =
        discover_project_targets_with(project.path(), output.path(), &options).expect("no library");
    assert!(unresolved.targets.is_empty());
    assert!(unresolved
        .unsupported
        .iter()
        .any(|case| case.construct.contains("pkg/circuits/gadget.circom")));

    options.library_paths = vec![library.path().to_path_buf()];
    let report =
        discover_project_targets_with(project.path(), output.path(), &options).expect("library");
    let mut names = report
        .targets
        .iter()
        .map(|target| target.template_name.as_str())
        .collect::<Vec<_>>();
    names.sort();
    assert_eq!(names, ["Bit", "Gadget"]);
    assert_eq!(
        report.library_paths,
        [fs::canonicalize(library.path()).unwrap()]
    );
}

#[test]
fn invalid_discovery_options_are_rejected() {
    let project = tempdir().expect("project");
    let outside = tempdir().expect("outside");
    write(
        &project.path().join("main.circom"),
        "pragma circom 2.1.6; template M() {} component main = M();",
    );
    write(
        &outside.path().join("main.circom"),
        "pragma circom 2.1.6; template M() {} component main = M();",
    );
    let output = tempdir().expect("output");
    let cases = [
        DiscoveryOptions {
            library_paths: vec![outside.path().to_path_buf()],
            ..DiscoveryOptions::default()
        },
        DiscoveryOptions {
            entrypoint: Some(outside.path().join("main.circom")),
            ..DiscoveryOptions::default()
        },
        DiscoveryOptions {
            compile_timeout_seconds: 0,
            ..DiscoveryOptions::default()
        },
    ];
    for options in cases {
        assert!(discover_project_targets_with(project.path(), output.path(), &options).is_err());
    }
}

#[cfg(unix)]
fn fake_compiler(directory: &Path, body: &str) -> PathBuf {
    use std::os::unix::fs::PermissionsExt;
    let path = directory.join("fake-circom.sh");
    fs::write(
        &path,
        format!("#!/bin/sh\n[ \"$1\" = --warmup ] && exit 0\n{body}\n"),
    )
    .expect("fake compiler");
    fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).expect("executable");
    // macOS can delay the first exec of a newly written executable by hundreds of milliseconds
    // under parallel tests; absorb it here so timing assertions measure only the compiler call.
    assert!(Command::new(&path)
        .arg("--warmup")
        .status()
        .expect("warm up fake compiler")
        .success());
    path
}

#[cfg(unix)]
fn gadget_project() -> (tempfile::TempDir, tempfile::TempDir) {
    let project = tempdir().expect("project");
    let library = tempdir().expect("library");
    write(
        &project.path().join("main.circom"),
        "pragma circom 2.1.6;\ninclude \"pkg/gadget.circom\";\ntemplate Root() { component gadget = Gadget(); }\ncomponent main = Root();\n",
    );
    write(
        &library.path().join("pkg/gadget.circom"),
        "pragma circom 2.1.6;\ntemplate Gadget() {}\n",
    );
    (project, library)
}

#[cfg(unix)]
#[test]
fn wrapper_compilation_passes_project_and_library_paths_and_records_the_command() {
    let (project, library) = gadget_project();
    let tools = tempdir().expect("tools");
    let args_path = tools.path().join("args.txt");
    let compiler = fake_compiler(
        tools.path(),
        &format!("printf '%s\\n' \"$@\" > '{}'", args_path.display()),
    );
    let output = tempdir().expect("output");
    let options = DiscoveryOptions {
        entrypoint: Some(project.path().join("main.circom")),
        library_paths: vec![library.path().to_path_buf()],
        circom_bin: Some(compiler),
        compile_timeout_seconds: 30,
    };
    let report =
        discover_project_targets_with(project.path(), output.path(), &options).expect("discovery");
    assert_eq!(report.targets.len(), 1);
    let target = &report.targets[0];
    assert_eq!(target.wrapper_status, WrapperStatus::CompileSucceeded);
    let compile = target.compile.as_ref().expect("recorded compile");
    assert!(!compile.timed_out);
    assert_eq!(compile.timeout_seconds, 30);
    assert_eq!(report.compile_timeout_seconds, Some(30));
    let recorded = fs::read_to_string(&args_path).expect("recorded args");
    let recorded = recorded.lines().collect::<Vec<_>>();
    assert_eq!(
        recorded,
        compile.args.iter().map(String::as_str).collect::<Vec<_>>()
    );
    let project_root = fs::canonicalize(project.path()).unwrap();
    let library_root = fs::canonicalize(library.path()).unwrap();
    let tail = &recorded[recorded.len() - 4..];
    assert_eq!(
        tail,
        [
            "-l",
            project_root.to_str().unwrap(),
            "-l",
            library_root.to_str().unwrap()
        ]
    );
}

#[cfg(unix)]
#[test]
fn wrapper_compilation_timeout_kills_the_compiler_process_group() {
    let (project, library) = gadget_project();
    let tools = tempdir().expect("tools");
    let pid_path = tools.path().join("grandchild.pid");
    let compiler = fake_compiler(
        tools.path(),
        &format!("sleep 60 &\necho $! > '{}'\nwait", pid_path.display()),
    );
    let output = tempdir().expect("output");
    let options = DiscoveryOptions {
        entrypoint: Some(project.path().join("main.circom")),
        library_paths: vec![library.path().to_path_buf()],
        circom_bin: Some(compiler),
        compile_timeout_seconds: 1,
    };
    let started = Instant::now();
    let report =
        discover_project_targets_with(project.path(), output.path(), &options).expect("discovery");
    assert!(started.elapsed() < Duration::from_secs(20));
    let target = &report.targets[0];
    assert_eq!(target.wrapper_status, WrapperStatus::CompileTimedOut);
    assert!(target
        .compile
        .as_ref()
        .is_some_and(|compile| compile.timed_out));
    assert!(target
        .failure_reason
        .as_deref()
        .is_some_and(|reason| reason.contains("1 seconds")));

    let grandchild = fs::read_to_string(&pid_path).expect("grandchild pid");
    let grandchild = grandchild.trim();
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        let alive = Command::new("kill")
            .args(["-0", grandchild])
            .status()
            .expect("kill -0")
            .success();
        if !alive {
            break;
        }
        assert!(
            Instant::now() < deadline,
            "grandchild {grandchild} survived"
        );
        std::thread::sleep(Duration::from_millis(50));
    }
}

#[test]
fn lexing_large_symbol_dense_files_is_linear() {
    let project = tempdir().expect("project");
    write(
        &project.path().join("main.circom"),
        "pragma circom 2.1.6; template M() {} component main = M();",
    );
    let mut table =
        String::from("pragma circom 2.1.6;\nfunction table() {\n    var a = 0;\n    a = 0");
    for _ in 0..200_000 {
        table.push_str(" + 1");
    }
    table.push_str(";\n    return a;\n}\n");
    write(&project.path().join("table.circom"), &table);
    let output = tempdir().expect("output");
    let started = Instant::now();
    discover_project_targets(project.path(), output.path(), None).expect("discovery");
    assert!(
        started.elapsed() < Duration::from_secs(10),
        "took {:?}",
        started.elapsed()
    );
}

#[cfg(unix)]
fn shared_leaf_project() -> tempfile::TempDir {
    let project = tempdir().expect("project");
    write(
        &project.path().join("main.circom"),
        "pragma circom 2.1.6;\ninclude \"lib.circom\";\ncomponent main = Root();\n",
    );
    write(
        &project.path().join("lib.circom"),
        "pragma circom 2.1.6;\n\
         include \"leaf.circom\";\n\
         include \"missing.circom\";\n\
         template Mid() { component x = Leaf(2); }\n\
         template Root() {\n\
           component a = Leaf(2);\n\
           component b = Leaf(2);\n\
           component c = Leaf(3);\n\
           component m = Mid();\n\
         }\n",
    );
    write(
        &project.path().join("leaf.circom"),
        "pragma circom 2.1.6;\ntemplate Leaf(n) {}\n",
    );
    project
}

#[cfg(unix)]
fn discover_with_compiler(project: &Path, body: &str) -> zkfdo::targets::TargetDiscoveryReport {
    let tools = tempdir().expect("tools");
    let compiler = fake_compiler(tools.path(), body);
    let output = tempdir().expect("output");
    let options = DiscoveryOptions {
        entrypoint: Some(project.join("main.circom")),
        circom_bin: Some(compiler),
        compile_timeout_seconds: 30,
        ..DiscoveryOptions::default()
    };
    discover_project_targets_with(project, output.path(), &options).expect("discovery")
}

#[cfg(unix)]
#[test]
fn repeated_call_sites_share_one_compile_unit_but_keep_their_origins() {
    let project = shared_leaf_project();
    let log = tempdir().expect("log");
    let log_path = log.path().join("invocations.log");
    let report = discover_with_compiler(
        project.path(),
        &format!("echo \"$1\" >> '{}'", log_path.display()),
    );

    // Five call sites: Root.a, Root.b, Root.c, Root.m and Mid.x.
    assert_eq!(report.targets.len(), 5);
    // Three distinct wrappers: Leaf(2), Leaf(3) and Mid().
    assert_eq!(report.compile_units.len(), 3);
    assert_eq!(report.compile_invocation_count, 3);
    let invocations = fs::read_to_string(&log_path).expect("invocation log");
    assert_eq!(invocations.lines().count(), 3);

    let leaf_two = report
        .targets
        .iter()
        .filter(|target| target.template_name == "Leaf" && target.concrete_parameters == ["2"])
        .collect::<Vec<_>>();
    assert_eq!(leaf_two.len(), 3);
    let unit_key = leaf_two[0].compile_unit.clone().expect("compile unit");
    assert!(leaf_two
        .iter()
        .all(|target| target.compile_unit.as_ref() == Some(&unit_key)
            && target.wrapper_status == WrapperStatus::CompileSucceeded
            && target.generated_wrapper_path == leaf_two[0].generated_wrapper_path));
    assert_eq!(
        leaf_two
            .iter()
            .filter(|target| !target.compile_reused)
            .count(),
        1
    );

    // Caller context is preserved per call site, not merged.
    let mut origins = leaf_two
        .iter()
        .map(|target| {
            (
                target.origin.parent_template.as_str(),
                target.origin.component_name.as_str(),
            )
        })
        .collect::<Vec<_>>();
    origins.sort();
    assert_eq!(origins, [("Mid", "x"), ("Root", "a"), ("Root", "b")]);
    let unit = report
        .compile_units
        .iter()
        .find(|unit| unit.key == unit_key)
        .expect("unit record");
    let mut members = unit.call_site_identities.clone();
    members.sort();
    let mut expected = leaf_two
        .iter()
        .map(|target| target.identity.clone())
        .collect::<Vec<_>>();
    expected.sort();
    assert_eq!(members, expected);

    // Every parent is either the root or another call site's instance, so ancestor paths can be
    // reconstructed from the call graph.
    let root = report.root_instance_key.as_deref().expect("root instance");
    assert!(root.ends_with("::Root()"));
    for target in &report.targets {
        assert!(
            target.parent_instance_key == root
                || report
                    .targets
                    .iter()
                    .any(|parent| parent.instance_key == target.parent_instance_key),
            "{}",
            target.parent_instance_key
        );
    }
}

#[cfg(unix)]
#[test]
fn compile_units_record_dependencies_settings_and_shared_failures() {
    let project = shared_leaf_project();
    let report = discover_with_compiler(project.path(), "echo boom >&2\nexit 1");
    assert_eq!(report.compile_invocation_count, 3);
    assert!(report.targets.iter().all(|target| target.wrapper_status
        == WrapperStatus::CompileFailed
        && target.failure_reason.as_deref() == Some("boom")));

    let leaf_unit = report
        .compile_units
        .iter()
        .find(|unit| unit.instance_key.ends_with("::Leaf(2)"))
        .expect("Leaf(2) unit");
    let leaf_path = fs::canonicalize(project.path().join("leaf.circom")).unwrap();
    let leaf_sha = format!(
        "{:x}",
        <sha2::Sha256 as sha2::Digest>::digest(fs::read(&leaf_path).unwrap())
    );
    assert!(leaf_unit
        .dependencies
        .iter()
        .any(|dependency| dependency.path == leaf_path && dependency.sha256 == leaf_sha));
    assert!(leaf_unit.unresolved_includes.is_empty());
    assert!(leaf_unit.compiler_sha256.is_some());
    let project_root = fs::canonicalize(project.path()).unwrap();
    assert_eq!(
        leaf_unit.settings,
        ["--inspect", "-l", project_root.to_str().unwrap()]
    );

    let mid_unit = report
        .compile_units
        .iter()
        .find(|unit| unit.instance_key.ends_with("::Mid()"))
        .expect("Mid unit");
    assert!(mid_unit
        .unresolved_includes
        .iter()
        .any(|include| include.ends_with("missing.circom")));
}
