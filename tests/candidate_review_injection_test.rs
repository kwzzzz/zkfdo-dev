use std::{
    fs,
    path::{Path, PathBuf},
};

use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tempfile::{tempdir, TempDir};
use zkfdo::{
    candidate_review::{review, schema::ReportStatus, ReviewOptions, ReviewOutput},
    corpus::{self, CorpusTarget, InputContract},
    targets::{self, DiscoveryOptions},
};

const PRIME: u32 = 65_537;
const INPUT: u32 = 17_293;
const STREAM_MARKER: &str = "synthetic-generator-private-stream";
const ENGINE_SOURCE: &[u8] = include_bytes!("../src/candidate_review/engine.rs");

// This fixture encodes a toy output=input relation directly. It does not compile
// or execute a real circuit, use historical candidates, or invoke zkFuzz.
const PREDICATE: &str = r#"API_VERSION = 1

def evaluate(context):
    signals = context["wire_signals"]
    clean = context["clean_reference_signals"]
    assert 0 <= int(signals["main.in"]) < int(context["field_modulus_decimal"])
    assert signals["main.in"] == clean["main.in"]
    assert signals["main.out"] != signals["main.in"]
    assert clean["main.out"] == clean["main.in"]
    return {
        "input_preconditions": {"verdict": "satisfied", "reason_code": "input-in-field"},
        "specified_property_violation": {
            "verdict": "satisfied", "reason_code": "output-differs", "violation_class": "toy-equality"
        }
    }
"#;

const GENERATOR: &str = r#"import json
import pathlib
import sys

role, common_input, witness_output, assignment_output, behavior = sys.argv[1:]
if behavior == "fail":
    sys.exit(9)
if behavior == "stdout":
    print("synthetic-generator-private-stream")
if behavior == "stderr":
    print("synthetic-generator-private-stream", file=sys.stderr)
value = int(json.loads(pathlib.Path(common_input).read_text())["x"])
input_value = value
if behavior == "noncanonical":
    output = value + 65537
elif behavior == "constraint-failure":
    output = value + 1
elif behavior == "input-mismatch":
    input_value = value + 1
    output = input_value
else:
    output = value if role == "clean" else value + 1
assignment = json.dumps(["1", str(output), str(input_value)], separators=(",", ":")).encode()
pathlib.Path(witness_output).write_bytes(b"synthetic-witness:" + assignment)
pathlib.Path(assignment_output).write_bytes(assignment)
"#;

const COMPILER: &str = r#"import pathlib
import struct
import sys

source_path, r1cs_path, sym_path, *_ = sys.argv[1:]
source_path = pathlib.Path(source_path)
source = source_path.read_text()
if 'include "target.circom"' in source:
    source += source_path.with_name("target.circom").read_text()
clean = "out <== in;" in source

header = b"".join(struct.pack("<I", value) for value in [4, 65537, 3, 1, 0, 1])
header += struct.pack("<Q", 3) + struct.pack("<I", int(clean))
constraints = b""
if clean:
    for wire in [2, 0, 1]:
        constraints += struct.pack("<III", 1, wire, 1)
labels = b"".join(struct.pack("<Q", value) for value in [0, 1, 2])
result = b"r1cs" + struct.pack("<II", 1, 3)
for kind, data in [(1, header), (2, constraints), (3, labels)]:
    result += struct.pack("<IQ", kind, len(data)) + data
pathlib.Path(r1cs_path).write_bytes(result)
symbols = b"1,1,0,main.out\n2,2,0,main.in\n"
if not clean:
    symbols += b"1,1,0,main.mutant_only\n"
pathlib.Path(sym_path).write_bytes(symbols)
"#;

#[derive(Clone, Copy, Debug)]
enum Fault {
    None,
    GeneratorExit,
    GeneratorStdout,
    GeneratorStderr,
    GeneratorUnpinnedLiteral,
    GeneratorUnpinnedDirectory,
    GeneratorMixedUnpinnedLiteral,
    CompilerUnpinnedLiteral,
    CompilerUnpinnedDirectory,
    CompilerExternalInclude,
    CompilerLibraryInclude,
    CompilerWrongEntrypointBinding,
    CompiledArtifactMismatch,
    AssignmentEncoding,
    NoncanonicalDisturbance,
    NoncanonicalCleanReference,
    CleanReferenceConstraintFailure,
    CleanInputMismatch,
    SharedHash,
    SharedParse,
    SharedBinding,
    ReachabilityRange,
    ReachabilityOutsideClosure,
    ReachabilityFabricatedParentEdge,
    BuiltinVerifierUnbound,
    CleanContractSignalMissing,
    ExtraClosureFile,
}

struct Fixture {
    temp: TempDir,
    options: ReviewOptions,
}

impl Fixture {
    fn new(fault: Fault) -> Self {
        let temp = tempdir().unwrap();
        let root = temp.path();
        let python = python_bin();
        let python_sha256 = hash(&fs::read(&python).unwrap());

        write(root, "engine/engine.rs", ENGINE_SOURCE);
        write(root, "engine/Cargo.lock", include_bytes!("../Cargo.lock"));
        write(root, "engine/Cargo.toml", include_bytes!("../Cargo.toml"));
        write(
            root,
            "engine/experiment.rs",
            include_bytes!("../src/experiment.rs"),
        );
        write(
            root,
            "engine/mod.rs",
            include_bytes!("../src/candidate_review/mod.rs"),
        );
        write(
            root,
            "engine/predicate.rs",
            include_bytes!("../src/candidate_review/predicate.rs"),
        );
        write(
            root,
            "engine/r1cs.rs",
            include_bytes!("../src/candidate_review/r1cs.rs"),
        );
        write(
            root,
            "engine/schema.rs",
            include_bytes!("../src/candidate_review/schema.rs"),
        );
        write(
            root,
            "engine/subprocess.rs",
            include_bytes!("../src/candidate_review/subprocess.rs"),
        );
        write(
            root,
            "engine/structure.rs",
            include_bytes!("../src/structure.rs"),
        );
        write(
            root,
            "engine/targets.rs",
            include_bytes!("../src/targets.rs"),
        );
        write_manifest(
            root,
            "engine/source-manifest.json",
            &[
                "Cargo.lock",
                "Cargo.toml",
                "engine.rs",
                "experiment.rs",
                "mod.rs",
                "predicate.rs",
                "r1cs.rs",
                "schema.rs",
                "structure.rs",
                "subprocess.rs",
                "targets.rs",
            ],
        );
        write(root, "predicate.py", PREDICATE.as_bytes());
        write(root, "generator.py", GENERATOR.as_bytes());
        write_manifest(root, "generator-artifacts.json", &["generator.py"]);
        write(root, "compiler.py", COMPILER.as_bytes());
        write_manifest(root, "compiler-artifacts.json", &["compiler.py"]);
        write(root, "unpinned-helper.py", b"raise SystemExit(99)\n");
        fs::create_dir(root.join("unpinned-directory")).unwrap();
        write(
            root,
            "unpinned-include.circom",
            b"pragma circom 2.1.6;\ntemplate Unpinned() { signal output out; out <== 0; }\n",
        );
        write(root, "unbound-source.txt", b"unrelated verifier source\n");
        write_manifest(
            root,
            "unbound-source-manifest.json",
            &["unbound-source.txt"],
        );
        write(
            root,
            "library.txt",
            b"Synthetic test uses no circuit dependencies.\n",
        );
        write_manifest(root, "library-manifest.json", &["library.txt"]);
        write_json(root, "common-input.json", &json!({"x": INPUT.to_string()}));
        write_json(
            root,
            "contract.json",
            &json!({"property": "output equals input"}),
        );

        for (variant, source) in [
            (
                "clean",
                "pragma circom 2.1.6;\ntemplate FabricatedParent() {\n  signal output out;\n  out <== 0;\n}\ntemplate Synthetic() {\n  signal input in;\n  signal output out;\n  out <== in;\n}\ncomponent main = Synthetic();\n",
            ),
            (
                "mutant",
                "pragma circom 2.1.6;\ntemplate FabricatedParent() {\n  signal output out;\n  out <== 0;\n}\ntemplate Synthetic() {\n  signal input in;\n  signal output out;\n  out <-- in;\n}\ncomponent main = Synthetic();\n",
            ),
            (
                "twin",
                "pragma circom 2.1.6;\ntemplate FabricatedParent() {\n  signal output out;\n  out <== 0;\n}\ntemplate Synthetic() {\n  signal input in;\n  signal output out;\n  out <-- in + 1;\n}\ncomponent main = Synthetic();\n",
            ),
        ] {
            let source = if matches!(fault, Fault::CompilerExternalInclude) {
                format!(
                    "include \"{}\";\n{source}",
                    root.join("unpinned-include.circom").display()
                )
            } else if matches!(fault, Fault::CompilerLibraryInclude) {
                format!("include \"dependency.circom\";\n{source}")
            } else {
                source.to_owned()
            };
            write(root, &format!("{variant}/target.circom"), source.as_bytes());
            if matches!(fault, Fault::CompilerWrongEntrypointBinding) {
                write(
                    root,
                    &format!("{variant}/wrapper.circom"),
                    b"pragma circom 2.1.6;\ninclude \"target.circom\";\ncomponent main = FabricatedParent();\n",
                );
                write_manifest(
                    root,
                    &format!("{variant}/closure.json"),
                    &["target.circom", "wrapper.circom"],
                );
            } else if matches!(fault, Fault::CompilerLibraryInclude) {
                write(
                    root,
                    &format!("{variant}/lib/dependency.circom"),
                    b"pragma circom 2.1.6;\ntemplate IncludedDependency() { signal output out; out <== 0; }\n",
                );
                write_manifest(
                    root,
                    &format!("{variant}/closure.json"),
                    &["lib/dependency.circom", "target.circom"],
                );
            } else if matches!(fault, Fault::ExtraClosureFile) {
                // Reachability needs files beyond the wrapper in real projects; this one is
                // pinned in every closure but not compiled by the direct wrapper.
                write(
                    root,
                    &format!("{variant}/unused.circom"),
                    b"pragma circom 2.1.6;\ntemplate Unused() { signal output out; out <== 0; }\n",
                );
                write_manifest(
                    root,
                    &format!("{variant}/closure.json"),
                    &["target.circom", "unused.circom"],
                );
            } else {
                write_manifest(
                    root,
                    &format!("{variant}/closure.json"),
                    &["target.circom"],
                );
            }
            write(
                root,
                &format!("{variant}/circuit.r1cs"),
                &r1cs(variant == "clean"),
            );
            let mut symbols = b"1,1,0,main.out\n2,2,0,main.in\n".to_vec();
            if variant != "clean" {
                symbols.extend(b"1,1,0,main.mutant_only\n");
            }
            if matches!(fault, Fault::CompiledArtifactMismatch) && variant == "clean" {
                symbols.extend(b"1,1,0,main.unreproduced_alias\n");
            }
            write(root, &format!("{variant}/circuit.sym"), &symbols);
        }
        let definition = synthetic_definition(root);
        let plan_inspection =
            targets::inspect_entrypoint(&definition.entrypoint, &definition.project_root).unwrap();
        let plan_fingerprints =
            corpus::fingerprint_sources(&plan_inspection.dependency_paths).unwrap();
        let target_id =
            corpus::stable_target_id(&definition, &plan_inspection, &plan_fingerprints).unwrap();
        write(
            root,
            "single.diff",
            b"--- a/target.circom\n+++ b/target.circom\n@@ -5 +5 @@\n-  out <== in;\n+  out <-- in;\n",
        );

        let clean_behavior = match fault {
            Fault::NoncanonicalCleanReference => "noncanonical",
            Fault::CleanReferenceConstraintFailure => "constraint-failure",
            Fault::CleanInputMismatch => "input-mismatch",
            _ => "ok",
        };
        let twin_behavior = match fault {
            Fault::GeneratorExit => "fail",
            Fault::GeneratorStdout => "stdout",
            Fault::GeneratorStderr => "stderr",
            Fault::NoncanonicalDisturbance => "noncanonical",
            _ => "ok",
        };
        for (role, behavior) in [("clean", clean_behavior), ("twin", twin_behavior)] {
            let (output, input) = synthetic_assignment(role, behavior);
            let assignment =
                serde_json::to_vec(&json!(["1", output.to_string(), input.to_string()])).unwrap();
            write(root, &format!("{role}.assignment.json"), &assignment);
            let mut witness = b"synthetic-witness:".to_vec();
            witness.extend(&assignment);
            write(root, &format!("{role}.witness"), &witness);
        }
        if matches!(fault, Fault::AssignmentEncoding) {
            // Hash-valid malformed assignment must fail inside the review pair,
            // after the shared artifacts have passed preflight.
            write_json(
                root,
                "twin.assignment.json",
                &json!(["1", (INPUT + 1).to_string()]),
            );
        }

        let generator = |role: &str, behavior: &str| {
            let mut arguments = vec![
                "-I".to_owned(),
                "-S".to_owned(),
                root.join("generator.py").to_string_lossy().into_owned(),
                role.to_owned(),
                "{common_input}".to_owned(),
                "{witness_output}".to_owned(),
                "{assignment_output}".to_owned(),
                behavior.to_owned(),
            ];
            if matches!(fault, Fault::GeneratorUnpinnedLiteral) {
                arguments.push(
                    root.join("unpinned-helper.py")
                        .to_string_lossy()
                        .into_owned(),
                );
            }
            if matches!(fault, Fault::GeneratorUnpinnedDirectory) {
                arguments.push(
                    root.join("unpinned-directory")
                        .to_string_lossy()
                        .into_owned(),
                );
            }
            if matches!(fault, Fault::GeneratorMixedUnpinnedLiteral) {
                arguments.push(format!(
                    "--cfg={{common_input}},{}",
                    root.join("unpinned-helper.py").display()
                ));
            }
            json!({
                "runner_path": python,
                "runner_sha256": python_sha256,
                "artifact_manifest_path": "generator-artifacts.json",
                "artifact_manifest_sha256": file_hash(root, "generator-artifacts.json"),
                "arguments": arguments,
                "witness_path": format!("{role}.witness"),
                "witness_sha256": file_hash(root, &format!("{role}.witness")),
                "assignment_path": format!("{role}.assignment.json"),
                "assignment_sha256": file_hash(root, &format!("{role}.assignment.json"))
            })
        };
        write_json(
            root,
            "generation.json",
            &json!({
                "schema_version": 1,
                "common_input": file_ref(root, "common-input.json"),
                "generators": {"clean": generator("clean", clean_behavior),
                    "disturbance_twin": generator("twin", twin_behavior)}
            }),
        );

        write_json(
            root,
            "projection.json",
            &json!({
                "schema_version": 1,
                "operator_id": "toy-drop-equality",
                "operator_justification": "Synthetic equality relation test.",
                "mappings": [
                    {"clean_wire_index": 1, "clean_signal_names": ["main.out"],
                        "source_kind": "disturbance-signal", "source_signal_name": "main.out"},
                    {"clean_wire_index": 2, "clean_signal_names": ["main.in"],
                        "source_kind": "disturbance-signal", "source_signal_name": "main.in"}
                ]
            }),
        );
        if matches!(fault, Fault::SharedParse) {
            // Refresh its enclosing references below: this isolates parse failure
            // from the separate stale-hash test.
            write(root, "projection.json", b"{malformed-projection");
        }
        write_json(
            root,
            "certificate.json",
            &json!({
                "schema_version": 1, "method": "fully-fixed-constraint",
                "clean_constraint_indices": [0], "fixed_signal_names": ["main.in", "main.out"]
            }),
        );
        let relation_source_manifest = if matches!(fault, Fault::BuiltinVerifierUnbound) {
            "unbound-source-manifest.json"
        } else {
            "engine/source-manifest.json"
        };
        write_json(
            root,
            "relation-verifier.json",
            &json!({
                "schema_version": 1, "api_version": 1,
                "verifier_id": "synthetic-builtin-relation-verifier", "method": "fully-fixed-constraint",
                "implementation": {"kind": "engine-builtin", "executable_path": null,
                    "executable_sha256": null, "source_manifest_path": relation_source_manifest,
                    "source_manifest_sha256": file_hash(root, relation_source_manifest)},
                "certificate_format": "fully-fixed-constraint-v1",
                "allowed_results": [{"verdict": "satisfied", "reason_code": "clean-relation-excluded"}]
            }),
        );
        let discovery = targets::discover_project_targets_with(
            root.join("mutant"),
            root.join("reachability-discovery"),
            &DiscoveryOptions {
                entrypoint: Some(root.join("mutant/target.circom")),
                library_paths: matches!(fault, Fault::CompilerLibraryInclude)
                    .then(|| vec![root.join("mutant/lib")])
                    .unwrap_or_default(),
                circom_bin: None,
                ..DiscoveryOptions::default()
            },
        )
        .unwrap();
        let discovery_path = discovery.work_dir.join("discovery.json");
        let instance_key = discovery.root_instance_key.clone().unwrap();
        let (template_start, template_end) =
            targets::template_source_byte_range(&root.join("mutant/target.circom"), "Synthetic")
                .unwrap();
        let (fabricated_start, fabricated_end) = targets::template_source_byte_range(
            &root.join("mutant/target.circom"),
            "FabricatedParent",
        )
        .unwrap();
        write_json(
            root,
            "reachability-verifier.json",
            &json!({
                "schema_version": 1, "verifier_id": "synthetic-reachability-verifier",
                "source_manifest_path": "engine/source-manifest.json",
                "source_manifest_sha256": file_hash(root, "engine/source-manifest.json"),
                "discovery_report_path": discovery_path,
                "discovery_report_sha256": hash(&fs::read(&discovery_path).unwrap())
            }),
        );
        let source_hash = file_hash(root, "mutant/target.circom");
        let outside_entrypoint_id = "e".repeat(64);
        let outside_instance_key = "f".repeat(64);
        let outside_source = "synthetic production entrypoint\n";
        write(root, "outside/entrypoint.circom", outside_source.as_bytes());
        let outside_source_hash = file_hash(root, "outside/entrypoint.circom");
        let target_parent = matches!(fault, Fault::ReachabilityOutsideClosure)
            .then_some(outside_instance_key.clone());
        let entrypoint_target_id = if matches!(fault, Fault::ReachabilityOutsideClosure) {
            outside_entrypoint_id.clone()
        } else {
            target_id.clone()
        };
        let entrypoint_source_hash = if matches!(fault, Fault::ReachabilityOutsideClosure) {
            outside_source_hash.clone()
        } else {
            source_hash.clone()
        };
        let target_end_byte = if matches!(fault, Fault::ReachabilityRange) {
            template_end - 1
        } else {
            template_end
        };
        let mut reachability_instances = vec![json!({
            "instance_key": instance_key, "parent_instance_key": target_parent,
            "target_id": target_id, "template": "Synthetic", "concrete_parameters": [],
            "source_path": "mutant/target.circom", "source_sha256": source_hash,
            "start_byte": template_start, "end_byte": target_end_byte
        })];
        if matches!(fault, Fault::ReachabilityOutsideClosure) {
            reachability_instances.push(json!({
                "instance_key": outside_instance_key, "parent_instance_key": null,
                "target_id": outside_entrypoint_id, "template": "ProductionEntrypoint",
                "concrete_parameters": [], "source_path": "outside/entrypoint.circom",
                "source_sha256": outside_source_hash, "start_byte": 0,
                "end_byte": outside_source.len()
            }));
        }
        if matches!(fault, Fault::ReachabilityFabricatedParentEdge) {
            let canonical_source = fs::canonicalize(root.join("mutant/target.circom")).unwrap();
            reachability_instances.push(json!({
                "instance_key": format!("{}::FabricatedParent()", canonical_source.display()),
                "parent_instance_key": instance_key,
                "target_id": "b".repeat(64), "template": "FabricatedParent",
                "concrete_parameters": [], "source_path": "mutant/target.circom",
                "source_sha256": source_hash, "start_byte": fabricated_start,
                "end_byte": fabricated_end
            }));
        }
        write_json(
            root,
            "reachability.json",
            &json!({
                "schema_version": 1, "completion": "complete",
                "entrypoint_target_id": entrypoint_target_id,
                "entrypoint_source_sha256": entrypoint_source_hash,
                "source_closure_sha256": file_hash(root, "mutant/closure.json"),
                "target_instance_key": instance_key,
                "instances": reachability_instances,
                "unsupported": [], "unresolved": []
            }),
        );

        let compiled_variant = |variant: &str| {
            json!({
                "r1cs_path": format!("{variant}/circuit.r1cs"),
                "r1cs_sha256": file_hash(root, &format!("{variant}/circuit.r1cs")),
                "sym_path": format!("{variant}/circuit.sym"),
                "sym_sha256": file_hash(root, &format!("{variant}/circuit.sym")),
                "shape": shape(variant == "clean")
            })
        };
        let mut compiler_arguments = vec![
            "-I".to_owned(),
            "-S".to_owned(),
            "{artifact_root}/compiler.py".to_owned(),
            "{entrypoint}".to_owned(),
            "{r1cs_output}".to_owned(),
            "{sym_output}".to_owned(),
            "-l".to_owned(),
            "{source_root}".to_owned(),
        ];
        if matches!(fault, Fault::CompilerUnpinnedLiteral) {
            compiler_arguments.push(
                root.join("unpinned-helper.py")
                    .to_string_lossy()
                    .into_owned(),
            );
        }
        if matches!(fault, Fault::CompilerUnpinnedDirectory) {
            compiler_arguments.push(
                root.join("unpinned-directory")
                    .to_string_lossy()
                    .into_owned(),
            );
        }
        if matches!(fault, Fault::CompilerLibraryInclude) {
            compiler_arguments.extend(["-l".to_owned(), "{source_root}/lib".to_owned()]);
        }
        let compilation_variant = |variant: &str| {
            json!({
                "source_closure_manifest_path": format!("{variant}/closure.json"),
                "source_closure_manifest_sha256": file_hash(root, &format!("{variant}/closure.json")),
                "entrypoint_path": if matches!(fault, Fault::CompilerWrongEntrypointBinding) {
                    "wrapper.circom"
                } else {
                    "target.circom"
                },
                "r1cs_output_path": "circuit.r1cs",
                "sym_output_path": "circuit.sym"
            })
        };
        write_json(
            root,
            "compilation.json",
            &json!({
                "schema_version": 1,
                "compiler": {
                    "version": "synthetic-r1cs-test-encoder",
                    "runner_path": python,
                    "runner_sha256": python_sha256,
                    "artifact_manifest_path": "compiler-artifacts.json",
                    "artifact_manifest_sha256": file_hash(root, "compiler-artifacts.json"),
                    "arguments": compiler_arguments
                },
                "variants": {
                    "clean": compilation_variant("clean"),
                    "mutant": compilation_variant("mutant"),
                    "disturbance_twin": compilation_variant("twin")
                }
            }),
        );
        let prepared_compiler_arguments = if matches!(fault, Fault::CompilerLibraryInclude) {
            vec![
                "-l".to_owned(),
                root.join("mutant/lib").to_string_lossy().into_owned(),
            ]
        } else {
            Vec::new()
        };
        let mut spec = json!({
            "schema_version": 1, "review_spec_id": "synthetic-injection-spec",
            "root_cause_id": "synthetic-equality", "subject_kind": "injected-mutant",
            "expected_scope": "original-component",
            "target_binding": {"target_id": target_id, "instance_key": instance_key,
                "template": "Synthetic", "concrete_parameters": [],
                "source_path": "mutant/target.circom", "source_sha256": source_hash,
                "source_closure_manifest_path": "mutant/closure.json",
                "source_closure_manifest_sha256": file_hash(root, "mutant/closure.json")},
            "field": {"name": "synthetic-prime", "modulus_decimal": PRIME.to_string(),
                "assignment_encoding": "canonical-field-elements"},
            "compiled_subject": {"r1cs_path": "mutant/circuit.r1cs",
                "r1cs_sha256": file_hash(root, "mutant/circuit.r1cs"),
                "sym_path": "mutant/circuit.sym", "sym_sha256": file_hash(root, "mutant/circuit.sym"),
                "expected_shape": shape(false)},
            "compiler": {"version": "synthetic-r1cs-test-encoder", "binary_sha256": python_sha256,
                "arguments": prepared_compiler_arguments, "library_manifest_path": "library-manifest.json",
                "library_manifest_sha256": file_hash(root, "library-manifest.json")},
            "contract": {"definition_path": "contract.json", "definition_sha256": file_hash(root, "contract.json"),
                "input_contract_id": "canonical-input", "property_id": "output-equals-input",
                "input_contract_statement": "The toy input is a canonical field element.",
                "property_statement": "The toy output equals its input.",
                "input_signal_names": ["main.in"], "property_signal_names": ["main.out"],
                "predicate": {"api_version": 1, "path": "predicate.py", "sha256": file_hash(root, "predicate.py"),
                    "entrypoint": "evaluate", "config": {},
                    "allowed_results": [
                        {"criterion": "input_preconditions", "verdict": "satisfied", "reason_code": "input-in-field",
                            "note": "Input is a canonical field element."},
                        {"criterion": "specified_property_violation", "verdict": "satisfied", "reason_code": "output-differs",
                            "note": "Output violates the predeclared equality property."}],
                    "allowed_violation_classes": ["toy-equality"]}},
            "attribution": {"method": "injection-single-diff", "evidence_path": "single.diff",
                "evidence_sha256": file_hash(root, "single.diff")},
            "production_reachability": {"verdict": "satisfied", "entrypoint_target_id": target_id,
                "instance_key": instance_key, "evidence_path": "reachability.json",
                "evidence_sha256": file_hash(root, "reachability.json"),
                "verifier_manifest_path": "reachability-verifier.json",
                "verifier_manifest_sha256": file_hash(root, "reachability-verifier.json")},
            "injection_ground_truth": {"injection_id": "synthetic-injection", "operator_id": "toy-drop-equality",
                "source_location": {"path": "mutant/target.circom", "source_sha256": source_hash,
                    "start_byte": template_start, "end_byte": template_end}, "clean_revision": "c".repeat(40),
                "single_diff": file_ref(root, "single.diff"),
                "source_closures": {"clean": file_ref(root, "clean/closure.json"),
                    "mutant": file_ref(root, "mutant/closure.json"), "disturbance_twin": file_ref(root, "twin/closure.json")},
                "compiled_variants": {"clean": compiled_variant("clean"),
                    "mutant": compiled_variant("mutant"), "disturbance_twin": compiled_variant("twin")},
                "compilation_manifest": file_ref(root, "compilation.json"),
                "projection_manifest": file_ref(root, "projection.json"),
                "expected_clean_constraint_indices": [0],
                "clean_relation_exclusion": {"method": "fully-fixed-constraint",
                    "certificate_path": "certificate.json", "certificate_sha256": file_hash(root, "certificate.json"),
                    "verifier_manifest_path": "relation-verifier.json",
                    "verifier_manifest_sha256": file_hash(root, "relation-verifier.json")}}
        });
        if matches!(fault, Fault::ReachabilityOutsideClosure) {
            spec["production_reachability"]["entrypoint_target_id"] =
                Value::String(entrypoint_target_id);
        }
        if matches!(fault, Fault::SharedBinding) {
            spec["target_binding"]["target_id"] = Value::String("d".repeat(64));
        }
        if matches!(fault, Fault::CleanContractSignalMissing) {
            spec["contract"]["property_signal_names"] = json!(["main.mutant_only"]);
        }
        write_json(root, "spec.json", &spec);
        let assignment_ref = |role: &str, origin: &str| {
            json!({
                "origin": origin, "format": "wtns-json-v1", "path": format!("{role}.assignment.json"),
                "sha256": file_hash(root, &format!("{role}.assignment.json")),
                "adapter_implementation_sha256": assignment_adapter_hash()
            })
        };
        write_json(
            root,
            "request.json",
            &json!({
                "schema_version": 1, "kind": "injection-ground-truth", "request_id": "synthetic-injection-request",
                "review_spec": file_ref(root, "spec.json"), "generation_manifest": file_ref(root, "generation.json"),
                "disturbance_assignment": assignment_ref("twin", "disturbance-twin"),
                "clean_reference_assignment": assignment_ref("clean", "clean-witness-generator")
            }),
        );
        if matches!(fault, Fault::SharedHash) {
            write(
                root,
                "mutant/target.circom",
                b"changed-after-hash-pinning\n",
            );
        }
        let options = ReviewOptions {
            request: root.join("request.json"),
            output: root.join("review-output"),
            python_bin: python,
            source_revision: "synthetic-integration-test".to_owned(),
            engine_source_manifest: root.join("engine/source-manifest.json"),
            executable: std::env::current_exe().unwrap(),
        };
        Self { temp, options }
    }

    fn run(&self) -> (ReviewOutput, Value) {
        let output = review(&self.options).unwrap();
        let bytes = fs::read(&output.report_path).unwrap();
        assert_eq!(output.report_sha256, hash(&bytes));
        let report: Value = serde_json::from_slice(&bytes).unwrap();
        assert_value_free(&report);
        assert!(self.temp.path().is_dir());
        (output, report)
    }

    fn backend_options(&self, qualification: &ReviewOutput) -> ReviewOptions {
        let root = self.temp.path();
        let definition = synthetic_definition(root);
        let inspection =
            targets::inspect_entrypoint(&definition.entrypoint, &definition.project_root).unwrap();
        let source_fingerprints =
            corpus::fingerprint_sources(&inspection.dependency_paths).unwrap();
        let target_id =
            corpus::stable_target_id(&definition, &inspection, &source_fingerprints).unwrap();

        let snapshot_root = root.join("backend-snapshot");
        for source in &inspection.dependency_paths {
            let relative = source.strip_prefix(&inspection.project_root).unwrap();
            write(
                root,
                &format!("backend-snapshot/{}", relative.display()),
                &fs::read(source).unwrap(),
            );
        }
        let run_entrypoint = snapshot_root.join("target.circom");
        let snapshot_paths = inspection
            .dependency_paths
            .iter()
            .map(|source| {
                snapshot_root.join(source.strip_prefix(&inspection.project_root).unwrap())
            })
            .collect::<Vec<_>>();
        let snapshot_fingerprints = corpus::fingerprint_sources(&snapshot_paths).unwrap();

        let timestamp = "2026-09-27T00:00:00Z";
        let python = python_bin();
        let compiler_sha256 = hash(&fs::read(&python).unwrap());
        let capture = |purpose: &str, success: bool| {
            json!({
                "requested": true,
                "purpose": purpose,
                "binary": python,
                "args": [],
                "started_at": timestamp,
                "finished_at": timestamp,
                "elapsed_seconds": 0.0,
                "timeout_seconds": 1,
                "exit_code": if success { Some(0) } else { None },
                "success": success,
                "timed_out": false,
                "stdout_path": root.join(format!("{purpose}.stdout")),
                "stderr_path": root.join(format!("{purpose}.stderr")),
                "error": null,
                "process_started": true
            })
        };
        let ranking = json!({
            "target_id": target_id,
            "path": definition.entrypoint,
            "risk_score": null,
            "warning_count": null,
            "complexity": null,
            "size": 1,
            "legacy_score": null
        });
        let structure = json!({
            "profile_kind": "synthetic-integration-test",
            "complete": true,
            "entrypoint": run_entrypoint,
            "root_template": "Synthetic",
            "prime": "bn128",
            "compile_args": [],
            "size": 1,
            "size_source": "synthetic-r1cs",
            "r1cs_path": root.join("mutant/circuit.r1cs"),
            "r1cs_sha256": file_hash(root, "mutant/circuit.r1cs"),
            "complexity": null,
            "metric": "root_ast_if_plus_while",
            "parameter_reflected": true,
            "compile_success": true,
            "ast_success": false,
            "ast_requested": false,
            "ast_stats": null,
            "compile": capture("compile", true),
            "ast": capture("ast", false),
            "circom_version": capture("circom-version", true),
            "zkfuzz_version": capture("zkfuzz-version", true),
            "limitations": [],
            "errors": [],
            "profile_path": root.join("synthetic-structure.json")
        });
        let plan_target = json!({
            "rank": 1,
            "target_id": target_id,
            "definition": definition,
            "inspection": inspection,
            "run_entrypoint": run_entrypoint,
            "ranking": ranking,
            "source_fingerprints": source_fingerprints,
            "snapshot_fingerprints": snapshot_fingerprints
        });
        let prepared_target = json!({
            "target_id": target_id,
            "definition": plan_target["definition"],
            "inspection": plan_target["inspection"],
            "run_entrypoint": plan_target["run_entrypoint"],
            "structure": structure,
            "semantic": null,
            "ranking": plan_target["ranking"],
            "eligible": true,
            "exclusion_reasons": [],
            "source_fingerprints": plan_target["source_fingerprints"],
            "snapshot_fingerprints": plan_target["snapshot_fingerprints"],
            "timings": {"inspection_seconds": 0.0, "snapshot_seconds": 0.0,
                "structure_seconds": 0.0, "semantic_seconds": 0.0, "legacy_seconds": 0.0},
            "elapsed_seconds": 0.0,
            "limitations": []
        });
        write_json(
            root,
            "backend-prepared.json",
            &json!({
                "schema_version": 1,
                "name": "synthetic-injected-backend",
                "description": "qualification-to-backend integration fixture",
                "manifest_path": root.join("synthetic-manifest.json"),
                "manifest_sha256": "0".repeat(64),
                "output_dir": root,
                "report_path": root.join("backend-prepared.json"),
                "profile_strategy": "path-order",
                "options": {"circom_bin": python, "zkfuzz_bin": python,
                    "analyzer_bin": python, "analyzer_version": "synthetic",
                    "analyzer_revision": "synthetic", "timeout_seconds": 1,
                    "strategy": "path-order"},
                "environment": {"circom_binary": python,
                    "circom_binary_sha256": compiler_sha256},
                "started_at": timestamp,
                "finished_at": timestamp,
                "elapsed_seconds": 0.0,
                "targets": [prepared_target],
                "exclusions": [],
                "limitations": []
            }),
        );
        write_json(
            root,
            "backend-config.json",
            &json!({"schema_version": 1, "complexity_groups": null}),
        );
        let prepared_path = root.join("backend-prepared.json");
        let config_path = root.join("backend-config.json");
        let plan_path = root.join("backend-plan.json");
        let plan = json!({
            "schema_version": 1,
            "plan_id": "synthetic-injected-backend-plan",
            "created_at": timestamp,
            "plan_path": plan_path,
            "prepared_path": prepared_path,
            "prepared_sha256": file_hash(root, "backend-prepared.json"),
            "preparation_profile_strategy": "path-order",
            "strategy": "path-order",
            "ranking_seed": null,
            "random_algorithm": null,
            "config_path": config_path,
            "config_sha256": file_hash(root, "backend-config.json"),
            "config": {"schema_version": 1, "complexity_groups": null},
            "comparison_target_set": "synthetic-single-target",
            "preparation_elapsed_seconds": 0.0,
            "preparation_accounting": {"inspection_seconds": 0.0, "snapshot_seconds": 0.0,
                "structure_seconds": 0.0, "semantic_seconds": 0.0, "legacy_seconds": 0.0,
                "excluded_target_elapsed_seconds": 0.0, "orchestration_overhead_seconds": 0.0},
            "planning_elapsed_seconds": 0.0,
            "targets": [plan_target],
            "exclusions": [],
            "manifest_exclusions": [],
            "limitations": []
        });
        write_json(root, "backend-plan.json", &plan);
        write_json(
            root,
            "backend-outcome.json",
            &json!({
                "schema_version": 1,
                "outcome_id": "synthetic-injected-backend-outcome",
                "report_path": root.join("backend-outcome.json"),
                "plan_path": plan_path,
                "plan_sha256": file_hash(root, "backend-plan.json"),
                "plan_id": "synthetic-injected-backend-plan",
                "strategy": "path-order",
                "execution_mode": "ranking-separated",
                "ranking_preparation_excluded_from_fuzzing_budget": true,
                "started_at": timestamp,
                "finished_at": timestamp,
                "elapsed_seconds": 0.0,
                "budget_seconds_per_target": 1,
                "total_budget_seconds": 1,
                "zkfuzz_binary": python,
                "zkfuzz_binary_sha256": compiler_sha256,
                "mutation_settings": {"source_path": null, "source_sha256": null,
                    "frozen_path": null, "frozen_sha256": null, "requested_seed": null,
                    "effective_seed": null, "seed_controlled": false},
                "scheduler": {"experiment_id": "synthetic-injected-backend-experiment",
                    "scheduler": "uniform-ordered", "budget_seconds_per_target": 1,
                    "total_budget_seconds": 1, "planned_target_ids": [target_id],
                    "started_at": timestamp, "finished_at": timestamp, "elapsed_seconds": 0.0,
                    "runs": [], "failures": [],
                    "skipped": [{"target_id": target_id, "index": 0,
                        "reason": "synthetic no-candidate integration fixture"}],
                    "summary_path": root.join("synthetic-summary.json")},
                "counterexample_candidates": [],
                "limitations": []
            }),
        );
        let qualification_index = qualification.bundle_index_path.as_ref().unwrap();
        write_json(
            root,
            "backend-request.json",
            &json!({
                "schema_version": 1,
                "request_id": "synthetic-injected-backend-request",
                "kind": "backend-candidates",
                "review_specs": [file_ref(root, "spec.json")],
                "executions": [{"execution_id": "synthetic-injected-backend-execution",
                    "campaign_coordinates": null,
                    "plan": file_ref(root, "backend-plan.json"),
                    "outcome": file_ref(root, "backend-outcome.json")}],
                "candidate_adapter": {"id": "zkfuzz-counterexample-v1",
                    "implementation_sha256": candidate_adapter_hash()},
                "candidate_policy": "all-outcome-candidates",
                "unmatched_candidate_policy": "record-unreviewed",
                "qualification_bundles": [{"injection_id": "synthetic-injection",
                    "path": qualification_index,
                    "sha256": qualification.bundle_index_sha256.as_ref().unwrap()}]
            }),
        );
        ReviewOptions {
            request: root.join("backend-request.json"),
            output: root.join("backend-review-output"),
            python_bin: self.options.python_bin.clone(),
            source_revision: self.options.source_revision.clone(),
            engine_source_manifest: self.options.engine_source_manifest.clone(),
            executable: self.options.executable.clone(),
        }
    }
}

#[test]
fn synthetic_injection_is_qualified_and_complete() {
    for fault in [Fault::None, Fault::CompilerLibraryInclude] {
        let fixture = Fixture::new(fault);
        let (output, report) = fixture.run();
        assert_eq!(
            output.status,
            ReportStatus::Complete,
            "{fault:?}: {report:#}"
        );
        assert!(report["failure"].is_null());
        assert_eq!(report["reviews"].as_array().unwrap().len(), 1);
        let review = &report["reviews"][0];
        assert_eq!(review["disposition"], "validated");
        assert_eq!(review["ground_truth_qualification"], "qualified");
        assert_eq!(review["failed_target_constraint_indices"], json!([]));
        assert_eq!(review["failed_clean_constraint_indices"], json!([0]));
        assert_eq!(review["confirmation_eligible"], false);
        assert_eq!(report["summary"]["qualified"], 1);
        assert_eq!(report["summary"]["review_error"], 0);
        for criterion in review["qualification_criteria"]
            .as_object()
            .unwrap()
            .values()
        {
            assert_eq!(criterion["verdict"], "satisfied");
        }
        let index_path = output.bundle_index_path.unwrap();
        let index_bytes = fs::read(index_path).unwrap();
        assert_eq!(output.bundle_index_sha256.unwrap(), hash(&index_bytes));
        let index: Value = serde_json::from_slice(&index_bytes).unwrap();
        assert_eq!(index["qualification"], "qualified");
        assert_value_free(&index);
    }
}

#[test]
fn qualified_injection_is_replayed_and_consumed_by_backend_review() {
    let fixture = Fixture::new(Fault::None);
    let (qualification, qualification_report) = fixture.run();
    assert_eq!(qualification.status, ReportStatus::Complete);
    assert_eq!(
        qualification_report["reviews"][0]["ground_truth_qualification"],
        "qualified"
    );

    let backend = review(&fixture.backend_options(&qualification)).unwrap();
    assert_eq!(backend.status, ReportStatus::Complete);
    let report: Value = serde_json::from_slice(&fs::read(&backend.report_path).unwrap()).unwrap();
    assert!(report["failure"].is_null(), "{report:#}");
    assert_eq!(report["candidate_inventory"]["outcome_candidate_count"], 0);
    assert_eq!(report["reviews"], json!([]));
    assert!(backend.bundle_index_path.is_some());
    assert!(backend.bundle_index_sha256.is_some());
    assert_value_free(&report);
}

#[test]
fn backend_binds_an_injected_spec_whose_closure_extends_beyond_the_wrapper() {
    let fixture = Fixture::new(Fault::ExtraClosureFile);
    let (qualification, qualification_report) = fixture.run();
    assert_eq!(
        qualification.status,
        ReportStatus::Complete,
        "{qualification_report:#}"
    );
    assert_eq!(
        qualification_report["reviews"][0]["ground_truth_qualification"],
        "qualified"
    );
    let backend = review(&fixture.backend_options(&qualification)).unwrap();
    let report: Value = serde_json::from_slice(&fs::read(&backend.report_path).unwrap()).unwrap();
    assert!(report["failure"].is_null(), "{report:#}");
    assert_eq!(backend.status, ReportStatus::Complete);
}

#[test]
fn injected_backend_requires_prepared_corpus_to_freeze_the_r1cs_hash() {
    let fixture = Fixture::new(Fault::None);
    let (qualification, _) = fixture.run();
    let options = fixture.backend_options(&qualification);
    let root = fixture.temp.path();

    let mut prepared: Value =
        serde_json::from_slice(&fs::read(root.join("backend-prepared.json")).unwrap()).unwrap();
    prepared["targets"][0]["structure"]
        .as_object_mut()
        .unwrap()
        .remove("r1cs_sha256");
    write_json(root, "backend-prepared.json", &prepared);

    let mut plan: Value =
        serde_json::from_slice(&fs::read(root.join("backend-plan.json")).unwrap()).unwrap();
    plan["prepared_sha256"] = Value::String(file_hash(root, "backend-prepared.json"));
    write_json(root, "backend-plan.json", &plan);

    let mut outcome: Value =
        serde_json::from_slice(&fs::read(root.join("backend-outcome.json")).unwrap()).unwrap();
    outcome["plan_sha256"] = Value::String(file_hash(root, "backend-plan.json"));
    write_json(root, "backend-outcome.json", &outcome);

    let mut request: Value =
        serde_json::from_slice(&fs::read(root.join("backend-request.json")).unwrap()).unwrap();
    request["executions"][0]["plan"]["sha256"] =
        Value::String(file_hash(root, "backend-plan.json"));
    request["executions"][0]["outcome"]["sha256"] =
        Value::String(file_hash(root, "backend-outcome.json"));
    write_json(root, "backend-request.json", &request);

    let output = review(&options).unwrap();
    assert_eq!(output.status, ReportStatus::Failed);
    assert!(output.bundle_index_path.is_none());
    let report: Value = serde_json::from_slice(&fs::read(output.report_path).unwrap()).unwrap();
    assert_eq!(report["failure"]["stage"], "shared-input-validation");
    assert_eq!(report["reviews"], json!([]));
}

#[test]
fn qualification_bundle_must_match_current_engine_replay() {
    let fixture = Fixture::new(Fault::None);
    let (qualification, _) = fixture.run();
    let options = fixture.backend_options(&qualification);
    let root = fixture.temp.path();

    let mut qualification_report: Value =
        serde_json::from_slice(&fs::read(&qualification.report_path).unwrap()).unwrap();
    qualification_report["reviews"][0]["criteria"]["assignment_encoding"]["note"] =
        Value::String("Tampered value-free note that replay must reject.".to_owned());
    fs::write(
        &qualification.report_path,
        serde_json::to_vec(&qualification_report).unwrap(),
    )
    .unwrap();

    let index_path = qualification.bundle_index_path.as_ref().unwrap();
    let mut index: Value = serde_json::from_slice(&fs::read(index_path).unwrap()).unwrap();
    index["review_report"]["sha256"] =
        Value::String(hash(&fs::read(&qualification.report_path).unwrap()));
    fs::write(index_path, serde_json::to_vec(&index).unwrap()).unwrap();

    let mut request: Value =
        serde_json::from_slice(&fs::read(root.join("backend-request.json")).unwrap()).unwrap();
    request["qualification_bundles"][0]["sha256"] =
        Value::String(hash(&fs::read(index_path).unwrap()));
    write_json(root, "backend-request.json", &request);

    let output = review(&options).unwrap();
    assert_eq!(output.status, ReportStatus::Failed);
    assert!(output.bundle_index_path.is_none());
    let report: Value = serde_json::from_slice(&fs::read(output.report_path).unwrap()).unwrap();
    assert_eq!(report["failure"]["stage"], "shared-input-validation");
    assert_eq!(report["reviews"], json!([]));
}

#[test]
fn synthetic_injection_execution_and_adapter_errors_are_single_incomplete_reviews() {
    for fault in [
        Fault::GeneratorExit,
        Fault::GeneratorStdout,
        Fault::GeneratorStderr,
        Fault::AssignmentEncoding,
    ] {
        let fixture = Fixture::new(fault);
        let (output, report) = fixture.run();
        assert_eq!(
            output.status,
            ReportStatus::Incomplete,
            "{fault:?}: {report:#}"
        );
        assert!(report["failure"].is_null());
        assert_eq!(report["reviews"].as_array().unwrap().len(), 1);
        assert_eq!(report["reviews"][0]["disposition"], "review-error");
        assert_eq!(
            report["reviews"][0]["ground_truth_qualification"],
            "review-error"
        );
        assert_eq!(report["summary"]["review_error"], 1);
        assert_eq!(report["summary"]["qualified"], 0);
        assert!(output.bundle_index_path.is_none());
        assert!(output.bundle_index_sha256.is_none());
    }
}

#[test]
fn noncanonical_disturbance_is_a_complete_scientific_rejection() {
    let fixture = Fixture::new(Fault::NoncanonicalDisturbance);
    let (output, report) = fixture.run();
    assert_eq!(output.status, ReportStatus::Complete, "{report:#}");
    let review = &report["reviews"][0];
    assert_eq!(review["disposition"], "rejected");
    assert_eq!(review["ground_truth_qualification"], "rejected");
    assert_eq!(
        review["criteria"]["assignment_encoding"]["verdict"],
        "not-satisfied"
    );
    assert_eq!(
        review["criteria"]["fixed_target_constraints"]["verdict"],
        "unknown"
    );
    assert_eq!(
        review["qualification_criteria"]["clean_rejection"]["verdict"],
        "unknown"
    );
    assert_eq!(
        review["qualification_criteria"]["clean_relation_exclusion"]["verdict"],
        "unknown"
    );
    assert_eq!(report["summary"]["review_error"], 0);
    assert!(output.bundle_index_path.is_none());
    assert!(output.bundle_index_sha256.is_none());
}

#[test]
fn noncanonical_clean_reference_is_a_complete_scientific_rejection() {
    assert_clean_scientific_rejection(
        Fault::NoncanonicalCleanReference,
        "clean_reference_assignment_encoding",
    );
}

#[test]
fn clean_reference_constraint_failure_is_a_complete_scientific_rejection() {
    assert_clean_scientific_rejection(
        Fault::CleanReferenceConstraintFailure,
        "clean_reference_constraints",
    );
}

#[test]
fn clean_input_mismatch_is_a_complete_scientific_rejection() {
    assert_clean_scientific_rejection(Fault::CleanInputMismatch, "clean_input_equivalence");
}

#[test]
fn synthetic_injection_shared_hash_parse_and_binding_errors_fail_the_report() {
    for fault in [
        Fault::SharedHash,
        Fault::SharedParse,
        Fault::SharedBinding,
        Fault::GeneratorUnpinnedLiteral,
        Fault::GeneratorUnpinnedDirectory,
        Fault::GeneratorMixedUnpinnedLiteral,
        Fault::CompilerUnpinnedLiteral,
        Fault::CompilerUnpinnedDirectory,
        Fault::CompilerExternalInclude,
        Fault::CompilerWrongEntrypointBinding,
        Fault::CompiledArtifactMismatch,
        Fault::ReachabilityRange,
        Fault::ReachabilityOutsideClosure,
        Fault::ReachabilityFabricatedParentEdge,
        Fault::BuiltinVerifierUnbound,
        Fault::CleanContractSignalMissing,
    ] {
        let fixture = Fixture::new(fault);
        let (output, report) = fixture.run();
        assert_eq!(output.status, ReportStatus::Failed, "{fault:?}: {report:#}");
        assert_eq!(report["failure"]["stage"], "shared-input-validation");
        assert_eq!(report["reviews"], json!([]));
        assert_eq!(report["summary"]["review_error"], 0);
        assert_eq!(report["summary"]["qualified"], 0);
        assert!(output.bundle_index_path.is_none());
    }
}

fn assert_value_free(value: &Value) {
    match value {
        Value::Object(fields) => {
            for forbidden in [
                "wire_signals",
                "eliminated_signals",
                "7_assignment",
                "witness",
                "value_decimal",
            ] {
                assert!(
                    !fields.contains_key(forbidden),
                    "raw assignment field {forbidden}"
                );
            }
            if let Some(persisted) = fields.get("raw_values_persisted") {
                assert_eq!(persisted, false);
            }
            for child in fields.values() {
                assert_value_free(child);
            }
        }
        Value::Array(values) => values.iter().for_each(assert_value_free),
        Value::String(text) => {
            assert!(!text.contains(&INPUT.to_string()));
            assert!(!text.contains(&(INPUT + 1).to_string()));
            assert!(!text.contains(STREAM_MARKER));
        }
        Value::Number(number) => {
            assert_ne!(number.as_u64(), Some(u64::from(INPUT)));
            assert_ne!(number.as_u64(), Some(u64::from(INPUT + 1)));
        }
        Value::Null | Value::Bool(_) => {}
    }
}

fn assert_clean_scientific_rejection(fault: Fault, failed_criterion: &str) {
    let fixture = Fixture::new(fault);
    let (output, report) = fixture.run();
    assert_eq!(
        output.status,
        ReportStatus::Complete,
        "{fault:?}: {report:#}"
    );
    let review = &report["reviews"][0];
    assert_eq!(review["ground_truth_qualification"], "rejected");
    assert_ne!(review["disposition"], "review-error");
    assert_eq!(
        review["qualification_criteria"][failed_criterion]["verdict"],
        "not-satisfied"
    );
    assert_eq!(
        review["qualification_criteria"]["clean_rejection"]["verdict"],
        "unknown"
    );
    assert_eq!(
        review["qualification_criteria"]["clean_relation_exclusion"]["verdict"],
        "unknown"
    );
    assert_eq!(report["summary"]["review_error"], 0);
    assert!(output.bundle_index_path.is_none());
    assert!(output.bundle_index_sha256.is_none());
}

fn write(root: &Path, name: &str, bytes: &[u8]) {
    let path = root.join(name);
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(path, bytes).unwrap();
}

fn write_json(root: &Path, name: &str, value: &Value) {
    write(root, name, &serde_json::to_vec(value).unwrap());
}

fn file_ref(root: &Path, name: &str) -> Value {
    json!({"path": name, "sha256": file_hash(root, name)})
}

fn file_hash(root: &Path, name: &str) -> String {
    hash(&fs::read(root.join(name)).unwrap())
}

fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn python_bin() -> PathBuf {
    // Prefer the configured interpreter. Apple's /usr/bin/python3 may write a
    // launcher warning when the generator runs with an empty environment.
    std::env::var_os("PATH")
        .into_iter()
        .flat_map(|paths| std::env::split_paths(&paths).collect::<Vec<_>>())
        .map(|directory| directory.join("python3"))
        .chain([PathBuf::from("/usr/bin/python3")])
        .find(|path| path.is_file())
        .map(|path| fs::canonicalize(path).unwrap())
        .expect("synthetic review tests require python3")
}

fn synthetic_definition(root: &Path) -> CorpusTarget {
    CorpusTarget {
        label: "Synthetic injected target".to_owned(),
        project: "synthetic-local-project".to_owned(),
        revision: "c".repeat(40),
        project_root: root.join("mutant"),
        entrypoint: root.join("mutant/target.circom"),
        template_name: "Synthetic".to_owned(),
        concrete_parameters: Vec::new(),
        prime: "bn128".to_owned(),
        compile_args: Vec::new(),
        mode: "original".to_owned(),
        input_assumptions: "The toy input is a canonical field element.".to_owned(),
        input_contract: Some(InputContract::FieldOnly),
        known_defects: Vec::new(),
    }
}

fn assignment_adapter_hash() -> String {
    let mut hasher = Sha256::new();
    hasher.update(ENGINE_SOURCE);
    hasher.update(b"\0");
    hasher.update(b"zkfDO assignment adapter wtns-json-v1 schema 1\n");
    format!("{:x}", hasher.finalize())
}

fn candidate_adapter_hash() -> String {
    let mut hasher = Sha256::new();
    hasher.update(ENGINE_SOURCE);
    hasher.update(b"\0");
    hasher.update(b"zkfDO candidate adapter zkfuzz-counterexample-v1 schema 1\n");
    format!("{:x}", hasher.finalize())
}

fn write_manifest(root: &Path, name: &str, files: &[&str]) {
    let path = root.join(name);
    let parent = path.parent().unwrap();
    let entries = files
        .iter()
        .map(|name| {
            let bytes = fs::read(parent.join(name)).unwrap();
            json!({"path": name, "size": bytes.len(), "sha256": hash(&bytes)})
        })
        .collect::<Vec<_>>();
    write_json(root, name, &json!({"schema_version": 1, "files": entries}));
}

fn shape(clean: bool) -> Value {
    json!({"wires": 3, "labels": 3, "public_outputs": 1, "public_inputs": 0,
        "private_inputs": 1, "constraints": usize::from(clean)})
}

fn synthetic_assignment(role: &str, behavior: &str) -> (u32, u32) {
    match behavior {
        "noncanonical" => (INPUT + PRIME, INPUT),
        "constraint-failure" => (INPUT + 1, INPUT),
        "input-mismatch" => (INPUT + 1, INPUT + 1),
        _ if role == "clean" => (INPUT, INPUT),
        _ => (INPUT + 1, INPUT),
    }
}

fn r1cs(clean: bool) -> Vec<u8> {
    let mut header = Vec::new();
    for value in [4_u32, PRIME, 3, 1, 0, 1] {
        header.extend(value.to_le_bytes());
    }
    header.extend(3_u64.to_le_bytes());
    header.extend(u32::from(clean).to_le_bytes());
    let mut constraints = Vec::new();
    if clean {
        // wire 2 (input) * wire 0 (one) = wire 1 (output).
        for wire in [2_u32, 0, 1] {
            constraints.extend(1_u32.to_le_bytes());
            constraints.extend(wire.to_le_bytes());
            constraints.extend(1_u32.to_le_bytes());
        }
    }
    let labels = [0_u64, 1, 2]
        .into_iter()
        .flat_map(u64::to_le_bytes)
        .collect::<Vec<_>>();
    let mut result = b"r1cs".to_vec();
    result.extend(1_u32.to_le_bytes());
    result.extend(3_u32.to_le_bytes());
    for (kind, data) in [(1_u32, header), (2, constraints), (3, labels)] {
        result.extend(kind.to_le_bytes());
        result.extend((data.len() as u64).to_le_bytes());
        result.extend(data);
    }
    result
}
