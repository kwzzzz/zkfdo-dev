//! Development-injection builder.
//!
//! Turns one value-free injection plan into everything the common review engine needs to
//! qualify an injected fault as ground truth: clean, mutant and disturbance-twin source trees,
//! their compiled R1CS/SYM, pinned witness generators, the same-input assignments, the
//! signal-name projection, the injection-related clean constraints, a relation-exclusion
//! certificate, reachability evidence from a complete discovery, the review spec and the
//! qualification request.
//!
//! Raw inputs, witnesses, assignments and compiled artifacts stay in the plan's ignored
//! workspace. The tracked output directory receives only paths, hashes and value-free files.
//! The builder never decides qualification itself; the engine re-derives every criterion.

use std::{
    collections::{BTreeMap, BTreeSet, VecDeque},
    fs,
    ops::Range,
    path::{Component, Path, PathBuf},
    process::{Command, Stdio},
};

use anyhow::{bail, ensure, Context, Result};
use num_bigint::BigUint;
use num_traits::{One, Zero};
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::{
    candidate_review::{
        r1cs::{Constraint, LinearCombination, R1cs, SymbolTable},
        schema::{
            AllowedPredicateResult, AllowedVerifierResult, AssignmentFormat, AssignmentOrigin,
            AssignmentRef, AttributionMethod, AttributionSpec, CleanRelationExclusion,
            CompilationCompiler, CompilationReproductionManifest, CompilationReproductionVariant,
            CompilationReproductionVariants, CompiledSubject, CompiledVariant, CompiledVariants,
            CompilerSpec, ConcreteParameter, ContractSpec, CriterionVerdict, DirectoryManifest,
            FieldSpec, FileRef, FullyFixedConstraintCertificate, GenerationManifest, GeneratorSpec,
            Generators, InjectionGroundTruth, InjectionRequest, ManifestFile, PredicateSpec,
            ProductionReachability, ProjectionManifest, ProjectionMapping, ProjectionSourceKind,
            ReachabilityCompletion, ReachabilityEvidence, ReachabilityInstance,
            ReachabilityVerdict, ReachabilityVerifierManifest, RelationExclusionMethod,
            RelationVerifierManifest, ReviewRequest, ReviewSpec, SourceClosures, SourceLocation,
            SubjectKind, TargetBinding, VerifierImplementation, VerifierImplementationKind,
        },
        subprocess::{run_bounded, COMPILER_TIMEOUT, GENERATOR_TIMEOUT},
    },
    corpus::{self, CorpusTarget, InputContract},
    experiment::ConfirmationScope,
    targets::{self, DiscoveryOptions},
};

const ENGINE_SOURCE: &str = include_str!("candidate_review/engine.rs");
const WTNS_ADAPTER_DESCRIPTOR: &str = "zkfDO assignment adapter wtns-json-v1 schema 1\n";
const BN128_MODULUS: &str =
    "21888242871839275222246405745257275088548364400416034343698204186575808495617";
const WRAPPER_FILE: &str = "zkfdo_injection_target.circom";
const WRAPPER_STEM: &str = "zkfdo_injection_target";
const CLOSURE_FILE: &str = "closure.json";

/// Loads the circom-generated witness calculator next to it and writes both the binary
/// witness and the wtns-json-v1 assignment. It must stay silent: the engine rejects any
/// stream output from a generator.
const WITNESS_RUNNER: &str = r#""use strict";
const fs = require("fs");
const path = require("path");
const builder = require(path.join(__dirname, "witness_calculator.js"));

async function main() {
  const [wasmPath, inputPath, witnessPath, assignmentPath] = process.argv.slice(2);
  const input = JSON.parse(fs.readFileSync(inputPath, "utf8"));
  const calculator = await builder(fs.readFileSync(wasmPath));
  const witness = await calculator.calculateWitness(input, 0);
  const binary = await calculator.calculateWTNSBin(input, 0);
  fs.writeFileSync(witnessPath, binary);
  fs.writeFileSync(assignmentPath, JSON.stringify(witness.map((value) => value.toString())));
}

main().then(
  () => process.exit(0),
  () => process.exit(1),
);
"#;

/// Repository files that fix the engine and builder implementation used for a review.
const ENGINE_SOURCES: &[&str] = &[
    "Cargo.lock",
    "Cargo.toml",
    "src/candidate_review/engine.rs",
    "src/candidate_review/mod.rs",
    "src/candidate_review/predicate.rs",
    "src/candidate_review/r1cs.rs",
    "src/candidate_review/schema.rs",
    "src/candidate_review/subprocess.rs",
    "src/bin/relation_verifier.rs",
    "src/cli.rs",
    "src/corpus.rs",
    "src/experiment.rs",
    "src/injection.rs",
    "src/structure.rs",
    "src/targets.rs",
];

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct InjectionPlan {
    pub schema_version: u32,
    pub injection_id: String,
    pub root_cause_id: String,
    pub operator: OperatorPlan,
    pub project: ProjectPlan,
    pub target: TargetPlan,
    /// Applied to the clean target source to create the mutant.
    pub mutant_edit: SourceEdit,
    /// Applied to the mutant target source to create the disturbance twin. It may only change
    /// witness computation; the engine requires identical R1CS and SYM.
    pub twin_edit: SourceEdit,
    pub contract: ContractPlan,
    /// Raw common input under the ignored workspace tree; never tracked.
    pub common_input: PathBuf,
    pub relation_exclusion: RelationExclusionMethod,
    pub workspace: PathBuf,
    pub output: PathBuf,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OperatorPlan {
    pub id: String,
    pub justification: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProjectPlan {
    pub name: String,
    pub revision: String,
    pub checkout: PathBuf,
    /// Relative to the checkout.
    pub entrypoint: PathBuf,
    /// Relative to the checkout, in circom `-l` order.
    pub library_paths: Vec<PathBuf>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TargetPlan {
    /// Relative to the checkout; must be a project source, not a library file.
    pub source_path: PathBuf,
    pub template: String,
    pub concrete_parameters: Vec<ConcreteParameter>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SourceEdit {
    pub find: String,
    pub replace: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ContractPlan {
    pub input_contract_id: String,
    pub property_id: String,
    pub input_contract_statement: String,
    pub property_statement: String,
    pub input_contract: InputContract,
    pub input_signal_names: Vec<String>,
    pub property_signal_names: Vec<String>,
    pub predicate: PredicatePlan,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PredicatePlan {
    /// Relative to the plan file.
    pub path: PathBuf,
    pub config: Value,
    pub allowed_results: Vec<AllowedPredicateResult>,
    pub allowed_violation_classes: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct InjectOptions {
    pub plan: PathBuf,
    pub circom_bin: PathBuf,
    pub node_bin: PathBuf,
    /// Pinned external verifier used for `operator-proof` relation exclusion.
    pub relation_verifier_bin: PathBuf,
}

/// Certificate checked by the pinned `zkfdo-relation-verifier` executable.
///
/// Unique propagation fixes the contract input and property signals, then repeatedly
/// solves any clean constraint with exactly one undetermined wire that appears linearly
/// with a nonzero coefficient. Every value it derives is forced in every clean assignment
/// that agrees on the fixed signals, so a listed constraint whose wires are all derived and
/// that is violated proves that no such clean assignment exists.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PropagationCertificate {
    pub schema_version: u32,
    pub method: RelationExclusionMethod,
    pub format: String,
    pub contradiction_constraint_indices: Vec<usize>,
    pub fixed_signal_names: Vec<String>,
}

pub const PROPAGATION_FORMAT: &str = "unique-propagation-v1";

#[derive(Debug, Clone, Serialize)]
pub struct InjectOutput {
    pub injection_id: String,
    pub request: PathBuf,
    pub review_spec: PathBuf,
    pub engine_source_manifest: PathBuf,
    pub source_revision: String,
    pub expected_clean_constraint_count: usize,
    pub certificate_constraint_count: usize,
}

struct Variant {
    label: &'static str,
    tree: PathBuf,
    closure: PathBuf,
    r1cs: PathBuf,
    sym: PathBuf,
}

pub fn build(options: &InjectOptions) -> Result<InjectOutput> {
    let plan_path = fs::canonicalize(&options.plan)
        .with_context(|| format!("resolve injection plan {}", options.plan.display()))?;
    let plan_dir = plan_path
        .parent()
        .context("plan has no parent")?
        .to_path_buf();
    let plan: InjectionPlan = serde_json::from_slice(&fs::read(&plan_path)?)
        .context("parse strict injection plan schema 1")?;
    validate_plan(&plan)?;

    let checkout = fs::canonicalize(plan_dir.join(&plan.project.checkout))
        .context("resolve project checkout")?;
    let entrypoint_rel = safe_relative(&plan.project.entrypoint, "entrypoint")?;
    let library_rels = plan
        .project
        .library_paths
        .iter()
        .map(|path| safe_relative(path, "library path"))
        .collect::<Result<Vec<_>>>()?;
    let target_rel = safe_relative(&plan.target.source_path, "target source")?;
    ensure!(
        !library_rels
            .iter()
            .any(|library| target_rel.starts_with(library)),
        "the target source is inside a library path; dependencies are never mutated"
    );
    let parameter_values = plan
        .target
        .concrete_parameters
        .iter()
        .map(|parameter| parameter.value_decimal.clone())
        .collect::<Vec<_>>();

    let workspace = normalize_lexical(&plan_dir.join(&plan.workspace));
    ensure!(
        !workspace.exists(),
        "refusing to reuse existing workspace {}",
        workspace.display()
    );
    fs::create_dir_all(&workspace)?;
    let workspace = fs::canonicalize(&workspace)?;
    let output = normalize_lexical(&plan_dir.join(&plan.output));
    fs::create_dir_all(&output)?;
    let output = fs::canonicalize(&output)?;

    // 1. The clean project must reach the target from the selected entrypoint with a
    //    complete discovery; its include closure becomes the tree layout.
    let clean_entrypoint = checkout.join(&entrypoint_rel);
    let clean_libraries = library_rels
        .iter()
        .map(|library| checkout.join(library))
        .collect::<Vec<_>>();
    let checkout_discovery = targets::discover_project_targets_with(
        &checkout,
        workspace.join("discovery-checkout"),
        &discovery_options(&clean_entrypoint, &clean_libraries),
    )?;
    ensure!(
        checkout_discovery.entrypoint_status == targets::EntrypointStatus::Found
            && checkout_discovery.unsupported.is_empty(),
        "checkout discovery from the entrypoint is not complete"
    );
    let checkout_target_key = targets::concrete_instance_key(
        &checkout.join(&target_rel),
        &plan.target.template,
        &parameter_values,
    )?;
    ensure!(
        checkout_discovery.root_instance_key.as_deref() == Some(checkout_target_key.as_str())
            || checkout_discovery
                .targets
                .iter()
                .any(|target| target.instance_key == checkout_target_key),
        "the target instance is not reachable from the selected entrypoint"
    );
    let closure_files =
        targets::discovery_dependency_paths(&clean_entrypoint, &checkout, &clean_libraries)?
            .into_iter()
            .map(|path| {
                path.strip_prefix(&checkout)
                    .map(Path::to_path_buf)
                    .context("closure file is outside the checkout")
            })
            .collect::<Result<Vec<_>>>()?;
    ensure!(
        closure_files.contains(&target_rel),
        "the target source is outside the entrypoint closure"
    );
    ensure!(
        !closure_files.contains(&PathBuf::from(WRAPPER_FILE))
            && !closure_files.contains(&PathBuf::from(CLOSURE_FILE)),
        "the project already uses a reserved builder file name"
    );

    // 2. Clean, mutant and twin trees differ only at the target source.
    let variants = ["clean", "mutant", "twin"].map(|label| {
        let tree = workspace.join(label);
        Variant {
            label,
            closure: tree.join(CLOSURE_FILE),
            r1cs: workspace
                .join("compiled")
                .join(label)
                .join(format!("{WRAPPER_STEM}.r1cs")),
            sym: workspace
                .join("compiled")
                .join(label)
                .join(format!("{WRAPPER_STEM}.sym")),
            tree,
        }
    });
    for variant in &variants {
        for file in &closure_files {
            let destination = variant.tree.join(file);
            fs::create_dir_all(destination.parent().context("closure file has no parent")?)?;
            fs::copy(checkout.join(file), &destination)
                .with_context(|| format!("copy {}", file.display()))?;
        }
    }
    let clean_target = variants[0].tree.join(&target_rel);
    let mutant_target = variants[1].tree.join(&target_rel);
    let twin_target = variants[2].tree.join(&target_rel);
    let clean_text = fs::read_to_string(&clean_target)?;
    let clean_scope = template_range(&clean_target, &plan.target.template)?;
    let mutant_text = apply_edit(&clean_text, &plan.mutant_edit, clean_scope, "mutant")?;
    fs::write(&mutant_target, &mutant_text)?;
    let mutant_scope = template_range(&mutant_target, &plan.target.template)?;
    let twin_text = apply_edit(&mutant_text, &plan.twin_edit, mutant_scope.clone(), "twin")?;
    fs::write(&twin_target, &twin_text)?;
    let location = injection_location(
        clean_text.as_bytes(),
        mutant_text.as_bytes(),
        twin_text.as_bytes(),
        &mutant_scope,
    )?;

    let wrapper = format!(
        "pragma circom 2.1.6;\n\ninclude \"{}\";\n\ncomponent main = {}({});\n",
        slash_path(&target_rel),
        plan.target.template,
        parameter_values.join(", ")
    );
    let mut manifest_files = closure_files.clone();
    manifest_files.push(PathBuf::from(WRAPPER_FILE));
    manifest_files.sort();
    for variant in &variants {
        fs::write(variant.tree.join(WRAPPER_FILE), &wrapper)?;
        write_json_new(
            &variant.closure,
            &directory_manifest(&variant.tree, &manifest_files)?,
        )?;
    }

    // 3. Compile every variant with a pinned copy of the compiler, then build the two
    //    witness generators from separate wasm compilations of the clean and twin trees.
    let compiler_dir = workspace.join("compiler");
    fs::create_dir_all(&compiler_dir)?;
    let compiler = compiler_dir.join("circom");
    fs::copy(resolve_program(&options.circom_bin)?, &compiler)?;
    let compiler_manifest = compiler_dir.join("artifacts.json");
    write_json_new(
        &compiler_manifest,
        &directory_manifest(&compiler_dir, &[PathBuf::from("circom")])?,
    )?;
    let compiler_version = circom_version(&compiler)?;
    let mut compile_template = vec![
        "{entrypoint}".to_owned(),
        "--r1cs".to_owned(),
        "--sym".to_owned(),
        "-l".to_owned(),
        "{source_root}".to_owned(),
    ];
    for library in &library_rels {
        compile_template.push("-l".to_owned());
        compile_template.push(format!("{{source_root}}/{}", slash_path(library)));
    }
    compile_template.extend(["-o".to_owned(), "{output_dir}".to_owned()]);
    for variant in &variants {
        let output_dir = variant
            .r1cs
            .parent()
            .context("compiled output has no parent")?;
        fs::create_dir_all(output_dir)?;
        run_compiler(
            &compiler,
            &variant.tree,
            &library_rels,
            output_dir,
            &workspace,
            false,
        )
        .with_context(|| format!("compile {} variant", variant.label))?;
        ensure!(
            variant.r1cs.is_file() && variant.sym.is_file(),
            "compiler did not create the {} R1CS/SYM",
            variant.label
        );
    }

    let node = resolve_program(&options.node_bin)?;
    let input = workspace.join("input.json");
    fs::copy(plan_dir.join(&plan.common_input), &input).context("copy common input")?;
    let generator_dir = workspace.join("generators");
    let witness_dir = workspace.join("witness");
    fs::create_dir_all(&witness_dir)?;
    let mut generators = BTreeMap::new();
    for variant in [&variants[0], &variants[2]] {
        let directory = generator_dir.join(variant.label);
        let build_dir = workspace.join("wasm-build").join(variant.label);
        fs::create_dir_all(&directory)?;
        fs::create_dir_all(&build_dir)?;
        run_compiler(
            &compiler,
            &variant.tree,
            &library_rels,
            &build_dir,
            &workspace,
            true,
        )
        .with_context(|| format!("compile {} witness generator", variant.label))?;
        let generated = build_dir.join(format!("{WRAPPER_STEM}_js"));
        fs::copy(
            generated.join(format!("{WRAPPER_STEM}.wasm")),
            directory.join(format!("{WRAPPER_STEM}.wasm")),
        )?;
        fs::copy(
            generated.join("witness_calculator.js"),
            directory.join("witness_calculator.js"),
        )?;
        fs::write(directory.join("runner.js"), WITNESS_RUNNER)?;
        let artifacts = directory.join("artifacts.json");
        write_json_new(
            &artifacts,
            &directory_manifest(
                &directory,
                &[
                    PathBuf::from("runner.js"),
                    PathBuf::from("witness_calculator.js"),
                    PathBuf::from(format!("{WRAPPER_STEM}.wasm")),
                ],
            )?,
        )?;
        let witness = witness_dir.join(format!("{}.wtns", variant.label));
        let assignment = witness_dir.join(format!("{}.assignment.json", variant.label));
        let arguments = vec![
            directory.join("runner.js").to_string_lossy().into_owned(),
            directory
                .join(format!("{WRAPPER_STEM}.wasm"))
                .to_string_lossy()
                .into_owned(),
            "{common_input}".to_owned(),
            "{witness_output}".to_owned(),
            "{assignment_output}".to_owned(),
        ];
        run_generator(&node, &arguments, &input, &witness, &assignment, &workspace)
            .with_context(|| format!("run {} witness generator", variant.label))?;
        generators.insert(
            variant.label,
            (node.clone(), artifacts, arguments, witness, assignment),
        );
    }

    // 4. Structural facts: twin identity, same-input assignments, projection, the
    //    injection-related clean constraints and the relation-exclusion certificate.
    let clean_r1cs = R1cs::parse(&fs::read(&variants[0].r1cs)?)?;
    let clean_symbols = SymbolTable::parse(&fs::read(&variants[0].sym)?, &clean_r1cs)?;
    let mutant_r1cs = R1cs::parse(&fs::read(&variants[1].r1cs)?)?;
    let mutant_symbols = SymbolTable::parse(&fs::read(&variants[1].sym)?, &mutant_r1cs)?;
    ensure!(
        sha256_file(&variants[1].r1cs)? == sha256_file(&variants[2].r1cs)?
            && sha256_file(&variants[1].sym)? == sha256_file(&variants[2].sym)?,
        "the disturbance twin does not compile to the mutant R1CS/SYM"
    );
    let clean_assignment = read_assignment(&generators["clean"].4)?;
    let twin_assignment = read_assignment(&generators["twin"].4)?;
    ensure!(
        clean_r1cs
            .failed_constraint_indices(&clean_assignment)?
            .is_empty(),
        "the clean reference does not satisfy the clean R1CS"
    );
    ensure!(
        mutant_r1cs
            .failed_constraint_indices(&twin_assignment)?
            .is_empty(),
        "the disturbance assignment does not satisfy the mutant R1CS"
    );
    let preferred = plan
        .contract
        .input_signal_names
        .iter()
        .chain(&plan.contract.property_signal_names)
        .cloned()
        .collect::<BTreeSet<_>>();
    let projection = build_projection(&clean_symbols, &mutant_symbols, &preferred)?;
    let expected = injection_related_constraints(&clean_r1cs, &mutant_r1cs, &projection.wires)?;
    ensure!(
        !expected.is_empty(),
        "the mutant removes no clean constraint; the edit is not a constraint injection"
    );
    let projected = project_assignment(
        &projection,
        &clean_assignment,
        &twin_assignment,
        &mutant_symbols,
    )?;
    ensure!(
        clean_r1cs
            .failed_constraint_indices(&projected)?
            .iter()
            .any(|index| expected.contains(index)),
        "the projected disturbance fails no injection-related clean constraint"
    );
    let (certificate, certificate_constraint_count): (Value, usize) = match plan.relation_exclusion
    {
        RelationExclusionMethod::FullyFixedConstraint => {
            let certificate = fully_fixed_certificate(
                &clean_r1cs,
                &projection.mappings,
                &projected,
                &expected,
                &preferred,
            )?;
            let count = certificate.clean_constraint_indices.len();
            (serde_json::to_value(certificate)?, count)
        }
        RelationExclusionMethod::OperatorProof => {
            let fixed = preferred
                .iter()
                .map(|name| {
                    let wire = mutant_symbols
                        .by_name
                        .get(name)
                        .and_then(|symbol| usize::try_from(symbol.wire).ok())
                        .with_context(|| format!("contract signal {name} is not a mutant wire"))?;
                    Ok((name.clone(), twin_assignment[wire].clone()))
                })
                .collect::<Result<BTreeMap<_, _>>>()?;
            let known = unique_propagation(&clean_r1cs, &clean_symbols, &fixed)?;
            let contradictions = propagation_contradictions(&clean_r1cs, &known, &expected);
            ensure!(
                !contradictions.is_empty(),
                "unique propagation does not determine a violated injection-related constraint"
            );
            let certificate = PropagationCertificate {
                schema_version: 1,
                method: RelationExclusionMethod::OperatorProof,
                format: PROPAGATION_FORMAT.to_owned(),
                contradiction_constraint_indices: contradictions.clone(),
                fixed_signal_names: fixed.keys().cloned().collect(),
            };
            (serde_json::to_value(certificate)?, contradictions.len())
        }
        RelationExclusionMethod::SolverUnsatCertificate => {
            bail!("solver certificates are not produced by this builder")
        }
    };

    // 5. Reachability from the entrypoint inside the mutant tree, as the engine reruns it.
    let mutant_root = fs::canonicalize(&variants[1].tree)?;
    let mutant_entrypoint = mutant_root.join(&entrypoint_rel);
    let mutant_libraries = library_rels
        .iter()
        .map(|library| mutant_root.join(library))
        .collect::<Vec<_>>();
    let reachability_discovery = targets::discover_project_targets_with(
        &mutant_root,
        workspace.join("discovery-mutant"),
        &discovery_options(&mutant_entrypoint, &mutant_libraries),
    )?;
    ensure!(
        reachability_discovery.entrypoint_status == targets::EntrypointStatus::Found
            && reachability_discovery.unsupported.is_empty(),
        "mutant discovery from the entrypoint is not complete"
    );
    let discovery_report = reachability_discovery.work_dir.join("discovery.json");
    ensure!(
        discovery_report.is_file(),
        "discovery report was not written"
    );
    let mutant_target_key = targets::concrete_instance_key(
        &mutant_root.join(&target_rel),
        &plan.target.template,
        &parameter_values,
    )?;
    let chain = reachability_chain(&reachability_discovery, &mutant_target_key)?;

    // 6. Identities follow the corpus target identity so that a later backend plan built
    //    from the same definition binds the same target ID.
    let semantic_compile_args = mutant_libraries
        .iter()
        .flat_map(|library| ["-l".to_owned(), library.to_string_lossy().into_owned()])
        .collect::<Vec<_>>();
    let target_definition = CorpusTarget {
        label: plan.injection_id.clone(),
        project: plan.project.name.clone(),
        revision: plan.project.revision.clone(),
        project_root: mutant_root.clone(),
        entrypoint: mutant_root.join(WRAPPER_FILE),
        template_name: plan.target.template.clone(),
        concrete_parameters: parameter_values.clone(),
        prime: "bn128".to_owned(),
        compile_args: semantic_compile_args.clone(),
        mode: "direct".to_owned(),
        input_assumptions: plan.contract.input_contract_statement.clone(),
        input_contract: Some(plan.contract.input_contract.clone()),
        known_defects: Vec::new(),
    };
    let target_id = target_identity(&target_definition)?;
    let identity_dir = workspace.join("identity-wrappers");
    fs::create_dir_all(&identity_dir)?;
    let mut instances = Vec::new();
    for (index, instance) in chain.iter().enumerate() {
        let id = if instance.key == mutant_target_key {
            target_id.clone()
        } else if instance.parent.is_none() {
            target_identity(&CorpusTarget {
                entrypoint: mutant_entrypoint.clone(),
                mode: "original".to_owned(),
                ..chain_definition(&plan, &mutant_root, instance, &semantic_compile_args)
            })?
        } else {
            let wrapper = identity_dir.join(format!("instance-{index:03}.circom"));
            fs::write(
                &wrapper,
                format!(
                    "pragma circom 2.1.6;\n\ninclude \"{}\";\n\ncomponent main = {}({});\n",
                    instance.source.to_string_lossy().replace('"', "\\\""),
                    instance.template,
                    instance.parameters.join(", ")
                ),
            )?;
            target_identity(&CorpusTarget {
                entrypoint: wrapper,
                ..chain_definition(&plan, &mutant_root, instance, &semantic_compile_args)
            })?
        };
        instances.push((instance, id));
    }

    // 7. Tracked, value-free artifacts.
    let engine_manifest = output.join("engine-source-manifest.json");
    write_json_new(&engine_manifest, &engine_source_manifest(&output)?)?;
    let engine_manifest_ref = file_ref(&output, &engine_manifest)?;

    let predicate_source = fs::canonicalize(plan_dir.join(&plan.contract.predicate.path))
        .context("resolve predicate")?;
    let contract_path = output.join("contract.json");
    write_json_new(
        &contract_path,
        &serde_json::json!({
            "schema_version": 1,
            "injection_id": plan.injection_id,
            "operator_id": plan.operator.id,
            "input_contract_id": plan.contract.input_contract_id,
            "property_id": plan.contract.property_id,
            "input_contract_statement": plan.contract.input_contract_statement,
            "property_statement": plan.contract.property_statement,
            "input_contract": plan.contract.input_contract,
            "input_signal_names": plan.contract.input_signal_names,
            "property_signal_names": plan.contract.property_signal_names,
        }),
    )?;

    let diff_path = output.join("single.diff");
    write_new(
        &diff_path,
        unified_diff(&slash_path(&target_rel), &clean_text, &mutant_text).as_bytes(),
    )?;

    let projection_path = output.join("projection.json");
    write_json_new(
        &projection_path,
        &ProjectionManifest {
            schema_version: 1,
            operator_id: plan.operator.id.clone(),
            operator_justification: plan.operator.justification.clone(),
            mappings: projection.mappings.clone(),
        },
    )?;
    let certificate_path = output.join("certificate.json");
    write_json_new(&certificate_path, &certificate)?;
    let relation_verifier_path = output.join("relation-verifier.json");
    let relation_verifier = match plan.relation_exclusion {
        RelationExclusionMethod::FullyFixedConstraint => RelationVerifierManifest {
            schema_version: 1,
            api_version: 1,
            verifier_id: "zkfdo-builtin-fully-fixed-constraint".to_owned(),
            method: RelationExclusionMethod::FullyFixedConstraint,
            implementation: VerifierImplementation {
                kind: VerifierImplementationKind::EngineBuiltin,
                executable_path: None,
                executable_sha256: None,
                source_manifest_path: engine_manifest_ref.path.clone(),
                source_manifest_sha256: engine_manifest_ref.sha256.clone(),
            },
            certificate_format: "fully-fixed-constraint-v1".to_owned(),
            allowed_results: vec![
                AllowedVerifierResult {
                    verdict: CriterionVerdict::Satisfied,
                    reason_code: "clean-relation-excluded".to_owned(),
                },
                AllowedVerifierResult {
                    verdict: CriterionVerdict::NotSatisfied,
                    reason_code: "clean-extension-not-excluded".to_owned(),
                },
            ],
        },
        _ => {
            let verifier_dir = workspace.join("verifier");
            fs::create_dir_all(&verifier_dir)?;
            let executable = verifier_dir.join("zkfdo-relation-verifier");
            fs::copy(
                resolve_program(&options.relation_verifier_bin)?,
                &executable,
            )
            .context("copy the relation verifier")?;
            let executable_ref = file_ref(&output, &executable)?;
            RelationVerifierManifest {
                schema_version: 1,
                api_version: 1,
                verifier_id: "zkfdo-unique-propagation".to_owned(),
                method: RelationExclusionMethod::OperatorProof,
                implementation: VerifierImplementation {
                    kind: VerifierImplementationKind::External,
                    executable_path: Some(executable_ref.path),
                    executable_sha256: Some(executable_ref.sha256),
                    source_manifest_path: engine_manifest_ref.path.clone(),
                    source_manifest_sha256: engine_manifest_ref.sha256.clone(),
                },
                certificate_format: PROPAGATION_FORMAT.to_owned(),
                allowed_results: vec![
                    AllowedVerifierResult {
                        verdict: CriterionVerdict::Satisfied,
                        reason_code: "clean-relation-excluded".to_owned(),
                    },
                    AllowedVerifierResult {
                        verdict: CriterionVerdict::Unknown,
                        reason_code: "exclusion-proof-incomplete".to_owned(),
                    },
                ],
            }
        }
    };
    write_json_new(&relation_verifier_path, &relation_verifier)?;

    let reachability_path = output.join("reachability.json");
    let root = instances.last().context("reachability chain is empty")?;
    let evidence = ReachabilityEvidence {
        schema_version: 1,
        completion: ReachabilityCompletion::Complete,
        entrypoint_target_id: root.1.clone(),
        entrypoint_source_sha256: sha256_file(&root.0.source)?,
        source_closure_sha256: sha256_file(&variants[1].closure)?,
        target_instance_key: mutant_target_key.clone(),
        instances: instances
            .iter()
            .map(|(instance, id)| {
                let (start_byte, end_byte) =
                    targets::template_source_byte_range(&instance.source, &instance.template)?;
                Ok(ReachabilityInstance {
                    instance_key: instance.key.clone(),
                    parent_instance_key: instance.parent.clone(),
                    target_id: id.clone(),
                    template: instance.template.clone(),
                    concrete_parameters: if instance.key == mutant_target_key {
                        plan.target.concrete_parameters.clone()
                    } else {
                        typed_parameters(
                            &instance.source,
                            &instance.template,
                            &instance.parameters,
                        )?
                    },
                    source_path: relative_path(&output, &instance.source)?,
                    source_sha256: sha256_file(&instance.source)?,
                    start_byte,
                    end_byte,
                })
            })
            .collect::<Result<Vec<_>>>()?,
        unsupported: Vec::new(),
        unresolved: Vec::new(),
    };
    write_json_new(&reachability_path, &evidence)?;
    let reachability_verifier_path = output.join("reachability-verifier.json");
    write_json_new(
        &reachability_verifier_path,
        &ReachabilityVerifierManifest {
            schema_version: 1,
            verifier_id: "zkfdo-targets-discovery-rerun".to_owned(),
            source_manifest_path: engine_manifest_ref.path.clone(),
            source_manifest_sha256: engine_manifest_ref.sha256.clone(),
            discovery_report_path: relative_path(&output, &discovery_report)?,
            discovery_report_sha256: sha256_file(&discovery_report)?,
        },
    )?;

    let compiled = |variant: &Variant, r1cs: &R1cs| -> Result<CompiledVariant> {
        Ok(CompiledVariant {
            r1cs_path: relative_path(&output, &variant.r1cs)?,
            r1cs_sha256: sha256_file(&variant.r1cs)?,
            sym_path: relative_path(&output, &variant.sym)?,
            sym_sha256: sha256_file(&variant.sym)?,
            shape: r1cs.shape.clone(),
        })
    };
    let twin_r1cs = R1cs::parse(&fs::read(&variants[2].r1cs)?)?;
    let compiled_variants = CompiledVariants {
        clean: compiled(&variants[0], &clean_r1cs)?,
        mutant: compiled(&variants[1], &mutant_r1cs)?,
        disturbance_twin: compiled(&variants[2], &twin_r1cs)?,
    };
    let closure_ref = |variant: &Variant| file_ref(&output, &variant.closure);
    let compilation_variant = |variant: &Variant| -> Result<CompilationReproductionVariant> {
        let closure = closure_ref(variant)?;
        Ok(CompilationReproductionVariant {
            source_closure_manifest_path: closure.path,
            source_closure_manifest_sha256: closure.sha256,
            entrypoint_path: PathBuf::from(WRAPPER_FILE),
            r1cs_output_path: PathBuf::from(format!("{WRAPPER_STEM}.r1cs")),
            sym_output_path: PathBuf::from(format!("{WRAPPER_STEM}.sym")),
        })
    };
    let compilation_path = output.join("compilation.json");
    let compiler_ref = file_ref(&output, &compiler)?;
    let compiler_manifest_ref = file_ref(&output, &compiler_manifest)?;
    write_json_new(
        &compilation_path,
        &CompilationReproductionManifest {
            schema_version: 1,
            compiler: CompilationCompiler {
                version: compiler_version.clone(),
                runner_path: compiler_ref.path.clone(),
                runner_sha256: compiler_ref.sha256.clone(),
                artifact_manifest_path: compiler_manifest_ref.path,
                artifact_manifest_sha256: compiler_manifest_ref.sha256,
                arguments: compile_template,
            },
            variants: CompilationReproductionVariants {
                clean: compilation_variant(&variants[0])?,
                mutant: compilation_variant(&variants[1])?,
                disturbance_twin: compilation_variant(&variants[2])?,
            },
        },
    )?;

    let generation_path = output.join("generation.json");
    let generator_spec = |label: &str| -> Result<GeneratorSpec> {
        let (runner, artifacts, arguments, witness, assignment) = &generators[label];
        let artifacts = file_ref(&output, artifacts)?;
        let witness = file_ref(&output, witness)?;
        let assignment = file_ref(&output, assignment)?;
        Ok(GeneratorSpec {
            runner_path: runner.clone(),
            runner_sha256: sha256_file(runner)?,
            artifact_manifest_path: artifacts.path,
            artifact_manifest_sha256: artifacts.sha256,
            arguments: arguments.clone(),
            witness_path: witness.path,
            witness_sha256: witness.sha256,
            assignment_path: assignment.path,
            assignment_sha256: assignment.sha256,
        })
    };
    write_json_new(
        &generation_path,
        &GenerationManifest {
            schema_version: 1,
            common_input: file_ref(&output, &input)?,
            generators: Generators {
                clean: generator_spec("clean")?,
                disturbance_twin: generator_spec("twin")?,
            },
        },
    )?;

    // The predicate is reviewed code referenced in place and pinned by hash.
    let predicate_path = predicate_source;
    let spec_path = output.join("spec.json");
    let mutant_closure = closure_ref(&variants[1])?;
    let mutant_target_ref = file_ref(&output, &mutant_root.join(&target_rel))?;
    let spec = ReviewSpec {
        schema_version: 1,
        review_spec_id: format!("{}/spec", plan.injection_id),
        root_cause_id: plan.root_cause_id.clone(),
        subject_kind: SubjectKind::InjectedMutant,
        expected_scope: ConfirmationScope::OriginalComponent,
        target_binding: TargetBinding {
            target_id: target_id.clone(),
            instance_key: Some(mutant_target_key.clone()),
            template: plan.target.template.clone(),
            concrete_parameters: plan.target.concrete_parameters.clone(),
            source_path: mutant_target_ref.path.clone(),
            source_sha256: mutant_target_ref.sha256.clone(),
            source_closure_manifest_path: mutant_closure.path.clone(),
            source_closure_manifest_sha256: mutant_closure.sha256.clone(),
        },
        field: FieldSpec {
            name: "bn128".to_owned(),
            modulus_decimal: BN128_MODULUS.to_owned(),
            assignment_encoding: "canonical-field-elements".to_owned(),
        },
        compiled_subject: CompiledSubject {
            r1cs_path: compiled_variants.mutant.r1cs_path.clone(),
            r1cs_sha256: compiled_variants.mutant.r1cs_sha256.clone(),
            sym_path: compiled_variants.mutant.sym_path.clone(),
            sym_sha256: compiled_variants.mutant.sym_sha256.clone(),
            expected_shape: compiled_variants.mutant.shape.clone(),
        },
        compiler: CompilerSpec {
            version: compiler_version,
            binary_sha256: compiler_ref.sha256.clone(),
            arguments: semantic_compile_args,
            library_manifest_path: mutant_closure.path.clone(),
            library_manifest_sha256: mutant_closure.sha256.clone(),
        },
        contract: ContractSpec {
            definition_path: relative_path(&output, &contract_path)?,
            definition_sha256: sha256_file(&contract_path)?,
            input_contract_id: plan.contract.input_contract_id.clone(),
            property_id: plan.contract.property_id.clone(),
            input_contract_statement: plan.contract.input_contract_statement.clone(),
            property_statement: plan.contract.property_statement.clone(),
            input_signal_names: plan.contract.input_signal_names.clone(),
            property_signal_names: plan.contract.property_signal_names.clone(),
            predicate: PredicateSpec {
                api_version: 1,
                path: relative_path(&output, &predicate_path)?,
                sha256: sha256_file(&predicate_path)?,
                entrypoint: "evaluate".to_owned(),
                config: plan.contract.predicate.config.clone(),
                allowed_results: plan.contract.predicate.allowed_results.clone(),
                allowed_violation_classes: plan
                    .contract
                    .predicate
                    .allowed_violation_classes
                    .clone(),
            },
        },
        attribution: AttributionSpec {
            method: AttributionMethod::InjectionSingleDiff,
            evidence_path: relative_path(&output, &diff_path)?,
            evidence_sha256: sha256_file(&diff_path)?,
        },
        production_reachability: ProductionReachability {
            verdict: ReachabilityVerdict::Satisfied,
            entrypoint_target_id: Some(root.1.clone()),
            instance_key: Some(mutant_target_key.clone()),
            evidence_path: Some(relative_path(&output, &reachability_path)?),
            evidence_sha256: Some(sha256_file(&reachability_path)?),
            verifier_manifest_path: Some(relative_path(&output, &reachability_verifier_path)?),
            verifier_manifest_sha256: Some(sha256_file(&reachability_verifier_path)?),
        },
        injection_ground_truth: Some(InjectionGroundTruth {
            injection_id: plan.injection_id.clone(),
            operator_id: plan.operator.id.clone(),
            source_location: SourceLocation {
                path: mutant_target_ref.path,
                source_sha256: mutant_target_ref.sha256,
                start_byte: location.start,
                end_byte: location.end,
            },
            clean_revision: plan.project.revision.clone(),
            single_diff: file_ref(&output, &diff_path)?,
            source_closures: SourceClosures {
                clean: closure_ref(&variants[0])?,
                mutant: mutant_closure,
                disturbance_twin: closure_ref(&variants[2])?,
            },
            compiled_variants,
            compilation_manifest: file_ref(&output, &compilation_path)?,
            projection_manifest: file_ref(&output, &projection_path)?,
            expected_clean_constraint_indices: expected.iter().copied().collect(),
            clean_relation_exclusion: CleanRelationExclusion {
                method: plan.relation_exclusion,
                certificate_path: relative_path(&output, &certificate_path)?,
                certificate_sha256: sha256_file(&certificate_path)?,
                verifier_manifest_path: relative_path(&output, &relation_verifier_path)?,
                verifier_manifest_sha256: sha256_file(&relation_verifier_path)?,
            },
        }),
    };
    write_json_new(&spec_path, &spec)?;

    let adapter_sha256 = {
        let mut hasher = Sha256::new();
        hasher.update(ENGINE_SOURCE.as_bytes());
        hasher.update(b"\0");
        hasher.update(WTNS_ADAPTER_DESCRIPTOR.as_bytes());
        format!("{:x}", hasher.finalize())
    };
    let assignment_ref = |label: &str, origin| -> Result<AssignmentRef> {
        let reference = file_ref(&output, &generators[label].4)?;
        Ok(AssignmentRef {
            origin,
            format: AssignmentFormat::WtnsJsonV1,
            path: reference.path,
            sha256: reference.sha256,
            adapter_implementation_sha256: adapter_sha256.clone(),
        })
    };
    let request_path = output.join("request.json");
    write_json_new(
        &request_path,
        &ReviewRequest::Injection(InjectionRequest {
            schema_version: 1,
            request_id: format!("{}/qualification", plan.injection_id),
            review_spec: file_ref(&output, &spec_path)?,
            generation_manifest: file_ref(&output, &generation_path)?,
            disturbance_assignment: assignment_ref("twin", AssignmentOrigin::DisturbanceTwin)?,
            clean_reference_assignment: assignment_ref(
                "clean",
                AssignmentOrigin::CleanWitnessGenerator,
            )?,
        }),
    )?;

    Ok(InjectOutput {
        injection_id: plan.injection_id,
        request: request_path,
        review_spec: spec_path,
        engine_source_manifest: engine_manifest.clone(),
        source_revision: format!(
            "worktree-engine-manifest:{}",
            sha256_file(&engine_manifest)?
        ),
        expected_clean_constraint_count: expected.len(),
        certificate_constraint_count,
    })
}

fn validate_plan(plan: &InjectionPlan) -> Result<()> {
    ensure!(
        plan.schema_version == 1,
        "unsupported injection plan schema"
    );
    for (label, value) in [
        ("injection_id", &plan.injection_id),
        ("root_cause_id", &plan.root_cause_id),
        ("operator.id", &plan.operator.id),
        ("operator.justification", &plan.operator.justification),
        ("project.name", &plan.project.name),
        ("target.template", &plan.target.template),
        (
            "contract.input_contract_id",
            &plan.contract.input_contract_id,
        ),
        ("contract.property_id", &plan.contract.property_id),
    ] {
        ensure!(!value.trim().is_empty(), "plan field {label} is empty");
    }
    ensure!(
        matches!(plan.project.revision.len(), 40 | 64)
            && plan
                .project
                .revision
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)),
        "project revision must be a full lowercase Git object ID"
    );
    ensure!(
        !plan.mutant_edit.find.is_empty() && !plan.twin_edit.find.is_empty(),
        "source edits must name the text they replace"
    );
    ensure!(
        !plan.contract.input_signal_names.is_empty()
            && !plan.contract.property_signal_names.is_empty(),
        "the contract must name its input and property signals"
    );
    for (position, parameter) in plan.target.concrete_parameters.iter().enumerate() {
        ensure!(
            parameter.position == position,
            "target parameters must be listed in positional order"
        );
    }
    Ok(())
}

fn template_range(source: &Path, template: &str) -> Result<Range<usize>> {
    let (start, end) = targets::template_source_byte_range(source, template)?;
    Ok(start..end)
}

fn discovery_options(entrypoint: &Path, libraries: &[PathBuf]) -> DiscoveryOptions {
    DiscoveryOptions {
        entrypoint: Some(entrypoint.to_path_buf()),
        library_paths: libraries.to_vec(),
        circom_bin: None,
        compile_timeout_seconds: targets::DEFAULT_WRAPPER_COMPILE_TIMEOUT_SECONDS,
    }
}

/// Replaces the single occurrence of `edit.find`, which must lie inside `scope`.
fn apply_edit(text: &str, edit: &SourceEdit, scope: Range<usize>, label: &str) -> Result<String> {
    let occurrences = text.match_indices(&edit.find).collect::<Vec<_>>();
    ensure!(
        occurrences.len() == 1,
        "{label} edit text occurs {} times in the target source; it must occur exactly once",
        occurrences.len()
    );
    let start = occurrences[0].0;
    let end = start + edit.find.len();
    ensure!(
        scope.start <= start && end <= scope.end,
        "{label} edit is outside the target template definition"
    );
    ensure!(
        edit.find != edit.replace,
        "{label} edit does not change the source"
    );
    Ok(format!(
        "{}{}{}",
        &text[..start],
        edit.replace,
        &text[end..]
    ))
}

fn minimal_changed_ranges(left: &[u8], right: &[u8]) -> (Range<usize>, Range<usize>) {
    let prefix = left
        .iter()
        .zip(right)
        .take_while(|(left, right)| left == right)
        .count();
    let remaining = left.len().min(right.len()).saturating_sub(prefix);
    let suffix = left[prefix..]
        .iter()
        .rev()
        .zip(right[prefix..].iter().rev())
        .take(remaining)
        .take_while(|(left, right)| left == right)
        .count();
    (
        prefix..left.len().saturating_sub(suffix),
        prefix..right.len().saturating_sub(suffix),
    )
}

/// The smallest mutant-side byte range covering both source transitions, widened to whole
/// lines so that a pure deletion still has a nonempty location.
fn injection_location(
    clean: &[u8],
    mutant: &[u8],
    twin: &[u8],
    template: &Range<usize>,
) -> Result<Range<usize>> {
    let (_, clean_to_mutant) = minimal_changed_ranges(clean, mutant);
    let (mutant_to_twin, _) = minimal_changed_ranges(mutant, twin);
    let mut start = clean_to_mutant.start.min(mutant_to_twin.start);
    let mut end = clean_to_mutant.end.max(mutant_to_twin.end);
    while start > template.start && mutant[start - 1] != b'\n' {
        start -= 1;
    }
    while end < template.end && (end == start || mutant[end - 1] != b'\n') {
        end += 1;
    }
    ensure!(
        template.start <= start && start < end && end <= template.end,
        "the injected changes are not inside the target template definition"
    );
    Ok(start..end)
}

fn directory_manifest(root: &Path, files: &[PathBuf]) -> Result<DirectoryManifest> {
    let mut sorted = files.to_vec();
    sorted.sort();
    sorted.dedup();
    ensure!(sorted.len() == files.len(), "duplicate manifest file");
    Ok(DirectoryManifest {
        schema_version: 1,
        files: sorted
            .into_iter()
            .map(|path| {
                let bytes = fs::read(root.join(&path))
                    .with_context(|| format!("read manifest file {}", path.display()))?;
                Ok(ManifestFile {
                    size: bytes.len() as u64,
                    sha256: sha256_bytes(&bytes),
                    path,
                })
            })
            .collect::<Result<Vec<_>>>()?,
    })
}

fn run_compiler(
    compiler: &Path,
    tree: &Path,
    libraries: &[PathBuf],
    output_dir: &Path,
    workspace: &Path,
    wasm: bool,
) -> Result<()> {
    let tmp = workspace.join("tmp");
    fs::create_dir_all(&tmp)?;
    let mut command = Command::new(compiler);
    command.arg(tree.join(WRAPPER_FILE));
    if wasm {
        command.arg("--wasm");
    } else {
        command.args(["--r1cs", "--sym"]);
    }
    command.arg("-l").arg(tree);
    for library in libraries {
        command.arg("-l").arg(tree.join(library));
    }
    command
        .arg("-o")
        .arg(output_dir)
        .current_dir(workspace)
        .env_clear()
        .env("TMPDIR", &tmp)
        .env("LANG", "C")
        .env("LC_ALL", "C")
        .stdin(Stdio::null());
    let output = run_bounded(&mut command, COMPILER_TIMEOUT)?;
    ensure!(!output.timed_out, "compiler exceeded its fixed timeout");
    ensure!(output.status.success(), "compiler exited unsuccessfully");
    Ok(())
}

fn run_generator(
    runner: &Path,
    arguments: &[String],
    input: &Path,
    witness: &Path,
    assignment: &Path,
    workspace: &Path,
) -> Result<()> {
    let tmp = workspace.join("tmp");
    fs::create_dir_all(&tmp)?;
    let arguments = arguments
        .iter()
        .map(|argument| {
            argument
                .replace("{common_input}", &input.to_string_lossy())
                .replace("{witness_output}", &witness.to_string_lossy())
                .replace("{assignment_output}", &assignment.to_string_lossy())
        })
        .collect::<Vec<_>>();
    let mut command = Command::new(runner);
    command
        .args(&arguments)
        .current_dir(&tmp)
        .env_clear()
        .env("TMPDIR", &tmp)
        .env("LANG", "C")
        .env("LC_ALL", "C")
        .stdin(Stdio::null());
    let output = run_bounded(&mut command, GENERATOR_TIMEOUT)?;
    ensure!(!output.timed_out, "generator exceeded its fixed timeout");
    ensure!(
        output.status.success(),
        "generator exited unsuccessfully; the input may violate a template assertion"
    );
    ensure!(
        !output.stdout_nonempty && !output.stderr_nonempty,
        "generator wrote to stdout or stderr"
    );
    Ok(())
}

fn circom_version(compiler: &Path) -> Result<String> {
    let output = Command::new(compiler)
        .arg("--version")
        .env_clear()
        .stdin(Stdio::null())
        .output()
        .context("query compiler version")?;
    ensure!(output.status.success(), "compiler version query failed");
    let text = String::from_utf8(output.stdout).context("compiler version is not UTF-8")?;
    text.split_whitespace()
        .last()
        .map(ToOwned::to_owned)
        .context("compiler printed no version")
}

fn read_assignment(path: &Path) -> Result<Vec<BigUint>> {
    let values: Vec<String> = serde_json::from_slice(&fs::read(path)?)
        .with_context(|| format!("parse assignment {}", path.display()))?;
    values
        .iter()
        .map(|value| {
            BigUint::parse_bytes(value.as_bytes(), 10)
                .with_context(|| "assignment entry is not a decimal integer".to_owned())
        })
        .collect()
}

struct Projection {
    mappings: Vec<ProjectionMapping>,
    /// Mutant wire that each clean wire's shared signal names resolve to (index 0 unused).
    wires: Vec<Option<usize>>,
}

/// Maps every nonconstant clean wire to a mutant signal of the same name when one exists,
/// and to the clean reference wire otherwise. Contract signals are preferred as sources.
fn build_projection(
    clean: &SymbolTable,
    mutant: &SymbolTable,
    preferred: &BTreeSet<String>,
) -> Result<Projection> {
    let mut mappings = Vec::new();
    let mut wires = vec![None; clean.wire_to_names.len()];
    for (wire, names) in clean.wire_to_names.iter().enumerate().skip(1) {
        ensure!(!names.is_empty(), "clean wire {wire} has no SYM name");
        let shared = names
            .iter()
            .filter_map(|name| {
                let symbol = mutant.by_name.get(name)?;
                usize::try_from(symbol.wire)
                    .ok()
                    .map(|mutant_wire| (name, mutant_wire))
            })
            .collect::<Vec<_>>();
        let (source_kind, source_signal_name) = if shared.is_empty() {
            (ProjectionSourceKind::CleanReferenceWire, None)
        } else {
            let targets = shared
                .iter()
                .map(|(_, wire)| *wire)
                .collect::<BTreeSet<_>>();
            ensure!(
                targets.len() == 1,
                "clean wire {wire} has aliases that resolve to different mutant wires"
            );
            wires[wire] = targets.into_iter().next();
            let source = shared
                .iter()
                .find(|(name, _)| preferred.contains(*name))
                .unwrap_or(&shared[0])
                .0
                .clone();
            (ProjectionSourceKind::DisturbanceSignal, Some(source))
        };
        mappings.push(ProjectionMapping {
            clean_wire_index: wire,
            clean_signal_names: names.clone(),
            source_kind,
            source_signal_name,
        });
    }
    Ok(Projection { mappings, wires })
}

fn project_assignment(
    projection: &Projection,
    clean: &[BigUint],
    disturbance: &[BigUint],
    mutant_symbols: &SymbolTable,
) -> Result<Vec<BigUint>> {
    let mut projected = vec![BigUint::one(); clean.len()];
    for mapping in &projection.mappings {
        projected[mapping.clean_wire_index] = match &mapping.source_signal_name {
            Some(name) => {
                let wire = usize::try_from(mutant_symbols.by_name[name].wire)
                    .context("projection source is an eliminated signal")?;
                disturbance[wire].clone()
            }
            None => clean[mapping.clean_wire_index].clone(),
        };
    }
    Ok(projected)
}

type CanonicalConstraint = (
    Vec<(usize, BigUint)>,
    Vec<(usize, BigUint)>,
    Vec<(usize, BigUint)>,
);

/// Clean constraints with no counterpart in the mutant, compared in mutant wire space and up
/// to scaling, so that renumbered or rescaled but otherwise identical constraints match.
/// This is decided from the two constraint systems alone, before any assignment is used.
fn injection_related_constraints(
    clean: &R1cs,
    mutant: &R1cs,
    wire_map: &[Option<usize>],
) -> Result<BTreeSet<usize>> {
    let prime = &mutant.prime;
    let mut remaining = BTreeMap::<CanonicalConstraint, usize>::new();
    for constraint in &mutant.constraints {
        let identity = (0..mutant.shape.wires).map(Some).collect::<Vec<_>>();
        if let Some(canonical) = canonical_constraint(constraint, &identity, prime) {
            *remaining.entry(canonical).or_default() += 1;
        }
    }
    let mut related = BTreeSet::new();
    for (index, constraint) in clean.constraints.iter().enumerate() {
        match canonical_constraint(constraint, wire_map, prime) {
            Some(canonical) => match remaining.get_mut(&canonical) {
                Some(count) if *count > 0 => *count -= 1,
                _ => {
                    related.insert(index);
                }
            },
            None => {
                related.insert(index);
            }
        }
    }
    Ok(related)
}

fn canonical_constraint(
    constraint: &Constraint,
    wire_map: &[Option<usize>],
    prime: &BigUint,
) -> Option<CanonicalConstraint> {
    let a = translate(&constraint.a, wire_map, prime)?;
    let b = translate(&constraint.b, wire_map, prime)?;
    let c = translate(&constraint.c, wire_map, prime)?;
    if a.is_empty() || b.is_empty() {
        let (c, _) = normalize(c, prime);
        return Some((Vec::new(), Vec::new(), c));
    }
    let (a, a_scale) = normalize(a, prime);
    let (b, b_scale) = normalize(b, prime);
    let scale = (a_scale * b_scale) % prime;
    let inverse = scale.modpow(&(prime - 2u32), prime);
    let c = c
        .into_iter()
        .map(|(wire, value)| (wire, (value * &inverse) % prime))
        .collect();
    let (first, second) = if a <= b { (a, b) } else { (b, a) };
    Some((first, second, c))
}

fn translate(
    combination: &LinearCombination,
    wire_map: &[Option<usize>],
    prime: &BigUint,
) -> Option<Vec<(usize, BigUint)>> {
    let mut translated = BTreeMap::<usize, BigUint>::new();
    for (wire, coefficient) in combination {
        let wire = *wire as usize;
        let target = if wire == 0 {
            0
        } else {
            (*wire_map.get(wire)?)?
        };
        let entry = translated.entry(target).or_insert_with(BigUint::zero);
        *entry = (&*entry + coefficient) % prime;
    }
    Some(
        translated
            .into_iter()
            .filter(|(_, value)| !value.is_zero())
            .collect(),
    )
}

/// Scales a combination so that its first coefficient is one; returns the removed scale.
fn normalize(
    combination: Vec<(usize, BigUint)>,
    prime: &BigUint,
) -> (Vec<(usize, BigUint)>, BigUint) {
    let Some((_, first)) = combination.first() else {
        return (combination, BigUint::one());
    };
    let scale = first.clone();
    let inverse = scale.modpow(&(prime - 2u32), prime);
    (
        combination
            .into_iter()
            .map(|(wire, value)| (wire, (value * &inverse) % prime))
            .collect(),
        scale,
    )
}

/// Lists the failing injection-related clean constraints whose every nonconstant wire is a
/// disturbance-projected contract signal. The engine recomputes all of this.
fn fully_fixed_certificate(
    clean: &R1cs,
    mappings: &[ProjectionMapping],
    projected: &[BigUint],
    expected: &BTreeSet<usize>,
    fixable: &BTreeSet<String>,
) -> Result<FullyFixedConstraintCertificate> {
    let failed = clean.failed_constraint_indices(projected)?;
    ensure!(
        failed.iter().any(|index| expected.contains(index)),
        "the projected disturbance fails no injection-related clean constraint"
    );
    let mut indices = Vec::new();
    let mut names = BTreeSet::new();
    for index in failed.into_iter().filter(|index| expected.contains(index)) {
        let constraint = &clean.constraints[index];
        let wires = constraint
            .a
            .keys()
            .chain(constraint.b.keys())
            .chain(constraint.c.keys())
            .copied()
            .filter(|wire| *wire != 0)
            .collect::<BTreeSet<_>>();
        let sources = wires
            .iter()
            .map(|wire| {
                let mapping = &mappings[*wire as usize - 1];
                match (&mapping.source_kind, &mapping.source_signal_name) {
                    (ProjectionSourceKind::DisturbanceSignal, Some(name))
                        if fixable.contains(name) =>
                    {
                        Some(name.clone())
                    }
                    _ => None,
                }
            })
            .collect::<Option<Vec<_>>>();
        if let Some(sources) = sources {
            indices.push(index);
            names.extend(sources);
        }
    }
    ensure!(
        !indices.is_empty(),
        "no failing injection-related clean constraint is fully fixed by contract signals"
    );
    Ok(FullyFixedConstraintCertificate {
        schema_version: 1,
        method: RelationExclusionMethod::FullyFixedConstraint,
        clean_constraint_indices: indices,
        fixed_signal_names: names.into_iter().collect(),
    })
}

/// Values forced by the fixed signals under unique linear propagation (see
/// [`PropagationCertificate`]); `None` for wires the propagation leaves undetermined.
pub(crate) fn unique_propagation(
    r1cs: &R1cs,
    symbols: &SymbolTable,
    fixed: &BTreeMap<String, BigUint>,
) -> Result<Vec<Option<BigUint>>> {
    let prime = &r1cs.prime;
    let mut known = vec![None; r1cs.shape.wires];
    known[0] = Some(BigUint::one());
    for (name, value) in fixed {
        let wire = symbols
            .by_name
            .get(name)
            .and_then(|symbol| usize::try_from(symbol.wire).ok())
            .with_context(|| format!("fixed signal {name} is not a clean wire"))?;
        ensure!(value < prime, "fixed signal {name} is not canonical");
        match &known[wire] {
            Some(existing) => ensure!(existing == value, "fixed aliases of {name} disagree"),
            None => known[wire] = Some(value.clone()),
        }
    }
    loop {
        let mut progress = false;
        for constraint in &r1cs.constraints {
            let unknown = constraint
                .a
                .keys()
                .chain(constraint.b.keys())
                .chain(constraint.c.keys())
                .filter(|wire| known[**wire as usize].is_none())
                .copied()
                .collect::<BTreeSet<_>>();
            let [wire] = unknown.into_iter().collect::<Vec<_>>()[..] else {
                continue;
            };
            let (a0, a1) = split_combination(&constraint.a, wire, &known, prime);
            let (b0, b1) = split_combination(&constraint.b, wire, &known, prime);
            let (c0, c1) = split_combination(&constraint.c, wire, &known, prime);
            // (a0 + a1 x)(b0 + b1 x) = c0 + c1 x is solved only when it is linear in x.
            if !((&a1 * &b1) % prime).is_zero() {
                continue;
            }
            let slope = ((&a0 * &b1) % prime + (&a1 * &b0) % prime + prime - &c1) % prime;
            if slope.is_zero() {
                continue;
            }
            let offset = (&c0 + prime - (&a0 * &b0) % prime) % prime;
            let inverse = slope.modpow(&(prime - 2u32), prime);
            known[wire as usize] = Some((offset * inverse) % prime);
            progress = true;
        }
        if !progress {
            return Ok(known);
        }
    }
}

fn split_combination(
    combination: &LinearCombination,
    unknown: u32,
    known: &[Option<BigUint>],
    prime: &BigUint,
) -> (BigUint, BigUint) {
    let mut constant = BigUint::zero();
    let mut coefficient = BigUint::zero();
    for (wire, value) in combination {
        if *wire == unknown {
            coefficient = (coefficient + value) % prime;
        } else if let Some(assigned) = &known[*wire as usize] {
            constant = (constant + value * assigned) % prime;
        }
    }
    (constant, coefficient)
}

/// Candidate constraints whose wires are all determined and that are violated.
pub(crate) fn propagation_contradictions(
    r1cs: &R1cs,
    known: &[Option<BigUint>],
    candidates: &BTreeSet<usize>,
) -> Vec<usize> {
    let prime = &r1cs.prime;
    let evaluate = |combination: &LinearCombination| {
        combination
            .iter()
            .try_fold(BigUint::zero(), |sum, (wire, value)| {
                known[*wire as usize]
                    .as_ref()
                    .map(|assigned| (sum + value * assigned) % prime)
            })
    };
    candidates
        .iter()
        .copied()
        .filter(|index| {
            let constraint = &r1cs.constraints[*index];
            matches!(
                (evaluate(&constraint.a), evaluate(&constraint.b), evaluate(&constraint.c)),
                (Some(a), Some(b), Some(c)) if (&a * &b) % prime != c
            )
        })
        .collect()
}

/// Entry point of the pinned external verifier: reads the engine's ephemeral context,
/// re-derives the unique propagation and writes a value-free result.
pub fn run_relation_verifier(context_path: &Path, result_path: &Path) -> Result<()> {
    let context: Value = serde_json::from_slice(&fs::read(context_path)?)?;
    let file = |key: &str| -> Result<PathBuf> {
        let path = PathBuf::from(
            context[key]["path"]
                .as_str()
                .with_context(|| format!("context {key} has no path"))?,
        );
        let expected = context[key]["sha256"]
            .as_str()
            .with_context(|| format!("context {key} has no hash"))?;
        ensure!(
            sha256_file(&path)? == expected,
            "context {key} hash mismatch"
        );
        Ok(path)
    };
    ensure!(
        context["schema_version"] == 1 && context["method"] == "operator-proof",
        "unsupported verifier context"
    );
    let certificate_path = file("certificate")?;
    let certificate_sha256 = sha256_file(&certificate_path)?;
    let certificate: PropagationCertificate =
        serde_json::from_slice(&fs::read(&certificate_path)?)?;
    ensure!(
        certificate.schema_version == 1
            && certificate.method == RelationExclusionMethod::OperatorProof
            && certificate.format == PROPAGATION_FORMAT,
        "unsupported propagation certificate"
    );
    for list in [
        certificate
            .contradiction_constraint_indices
            .iter()
            .map(ToString::to_string)
            .collect::<Vec<_>>(),
        certificate.fixed_signal_names.clone(),
    ] {
        ensure!(!list.is_empty(), "certificate lists must not be empty");
    }
    ensure!(
        certificate
            .contradiction_constraint_indices
            .windows(2)
            .all(|pair| pair[0] < pair[1])
            && certificate
                .fixed_signal_names
                .windows(2)
                .all(|pair| pair[0] < pair[1]),
        "certificate lists must be sorted and unique"
    );
    let expected = context["expected_clean_constraint_indices"]
        .as_array()
        .context("context has no expected constraint list")?
        .iter()
        .map(|value| {
            value
                .as_u64()
                .map(|index| index as usize)
                .context("invalid expected index")
        })
        .collect::<Result<BTreeSet<_>>>()?;
    let claimed = certificate
        .contradiction_constraint_indices
        .iter()
        .copied()
        .collect::<BTreeSet<_>>();
    ensure!(
        claimed.is_subset(&expected),
        "certificate names a constraint outside the injection-related set"
    );
    let supplied = context["fixed_signals"]
        .as_object()
        .context("context has no fixed signals")?;
    let fixed = certificate
        .fixed_signal_names
        .iter()
        .map(|name| {
            let text = supplied
                .get(name)
                .and_then(Value::as_str)
                .with_context(|| format!("fixed signal {name} is not supplied"))?;
            let value =
                BigUint::parse_bytes(text.as_bytes(), 10).context("fixed signal is not decimal")?;
            Ok((name.clone(), value))
        })
        .collect::<Result<BTreeMap<_, _>>>()?;
    let r1cs = R1cs::parse(&fs::read(file("clean_r1cs")?)?)?;
    ensure!(
        context["field_modulus_decimal"].as_str() == Some(r1cs.prime.to_str_radix(10).as_str()),
        "clean R1CS uses another field"
    );
    let symbols = SymbolTable::parse(&fs::read(file("clean_sym")?)?, &r1cs)?;
    let known = unique_propagation(&r1cs, &symbols, &fixed)?;
    let proven = propagation_contradictions(&r1cs, &known, &claimed);
    let excluded = proven.len() == claimed.len();
    fs::write(
        result_path,
        serde_json::to_vec(&serde_json::json!({
            "schema_version": 1,
            "method": "operator-proof",
            "verdict": if excluded { "satisfied" } else { "unknown" },
            "reason_code": if excluded {
                "clean-relation-excluded"
            } else {
                "exclusion-proof-incomplete"
            },
            "checked_clean_constraint_indices": certificate.contradiction_constraint_indices,
            "fixed_signal_names": certificate.fixed_signal_names,
            "certificate_sha256": certificate_sha256,
        }))?,
    )?;
    Ok(())
}

#[derive(Debug, Clone)]
struct ChainInstance {
    key: String,
    parent: Option<String>,
    source: PathBuf,
    template: String,
    parameters: Vec<String>,
}

/// One shortest parent chain from the discovery root to the target instance.
fn reachability_chain(
    discovery: &targets::TargetDiscoveryReport,
    target_key: &str,
) -> Result<Vec<ChainInstance>> {
    let root = discovery
        .root_instance_key
        .clone()
        .context("discovery has no root instance")?;
    let mut children = BTreeMap::<String, BTreeSet<String>>::new();
    for target in &discovery.targets {
        if !target.parent_instance_key.is_empty() {
            children
                .entry(target.parent_instance_key.clone())
                .or_default()
                .insert(target.instance_key.clone());
        }
    }
    let mut parent_of = BTreeMap::<String, String>::new();
    let mut queue = VecDeque::from([root.clone()]);
    let mut seen = BTreeSet::from([root.clone()]);
    while let Some(key) = queue.pop_front() {
        if key == target_key {
            break;
        }
        for child in children.get(&key).into_iter().flatten() {
            if seen.insert(child.clone()) {
                parent_of.insert(child.clone(), key.clone());
                queue.push_back(child.clone());
            }
        }
    }
    ensure!(
        seen.contains(target_key),
        "the target instance is not reachable in the mutant discovery"
    );
    let mut chain = Vec::new();
    let mut cursor = target_key.to_owned();
    loop {
        let parent = parent_of.get(&cursor).cloned();
        let (source, template, parameters) = parse_instance_key(&cursor)?;
        chain.push(ChainInstance {
            key: cursor.clone(),
            parent: parent.clone(),
            source,
            template,
            parameters,
        });
        match parent {
            Some(parent) => cursor = parent,
            None => break,
        }
    }
    ensure!(
        chain.last().map(|instance| instance.key.as_str()) == Some(root.as_str()),
        "reachability chain does not end at the discovery root"
    );
    Ok(chain)
}

/// Splits `source::Template(p1, p2)` into its parts.
fn parse_instance_key(key: &str) -> Result<(PathBuf, String, Vec<String>)> {
    let (source, call) = key
        .rsplit_once("::")
        .context("instance key has no source separator")?;
    let (template, arguments) = call
        .strip_suffix(')')
        .and_then(|call| call.split_once('('))
        .context("instance key has no parameter list")?;
    let parameters = if arguments.trim().is_empty() {
        Vec::new()
    } else {
        arguments
            .split(", ")
            .map(ToOwned::to_owned)
            .collect::<Vec<_>>()
    };
    Ok((PathBuf::from(source), template.to_owned(), parameters))
}

fn typed_parameters(
    source: &Path,
    template: &str,
    values: &[String],
) -> Result<Vec<ConcreteParameter>> {
    let text = fs::read_to_string(source)?;
    let pattern = Regex::new(&format!(
        r"template\s+(?:custom\s+)?(?:parallel\s+)?{}\s*\(([^)]*)\)",
        regex::escape(template)
    ))?;
    let captures = pattern
        .captures(&text)
        .with_context(|| format!("template {template} header not found"))?;
    let names = captures[1]
        .split(',')
        .map(str::trim)
        .filter(|name| !name.is_empty())
        .collect::<Vec<_>>();
    ensure!(
        names.len() == values.len(),
        "template {template} parameter count differs from its instance key"
    );
    Ok(names
        .into_iter()
        .zip(values)
        .enumerate()
        .map(|(position, (name, value))| ConcreteParameter {
            position,
            name: name.to_owned(),
            kind: crate::candidate_review::schema::ParameterKind::Integer,
            value_decimal: value.clone(),
        })
        .collect())
}

fn chain_definition(
    plan: &InjectionPlan,
    project_root: &Path,
    instance: &ChainInstance,
    compile_args: &[String],
) -> CorpusTarget {
    CorpusTarget {
        label: format!("{} reachability chain", plan.injection_id),
        project: plan.project.name.clone(),
        revision: plan.project.revision.clone(),
        project_root: project_root.to_path_buf(),
        entrypoint: instance.source.clone(),
        template_name: instance.template.clone(),
        concrete_parameters: instance.parameters.clone(),
        prime: "bn128".to_owned(),
        compile_args: compile_args.to_vec(),
        mode: "direct".to_owned(),
        input_assumptions: "Reachability-chain instance identity; not a planned target.".to_owned(),
        input_contract: None,
        known_defects: Vec::new(),
    }
}

fn target_identity(definition: &CorpusTarget) -> Result<String> {
    let inspection = targets::inspect_entrypoint_with_libraries(
        &definition.entrypoint,
        &definition.project_root,
        &corpus::compile_library_paths(definition),
    )?;
    ensure!(
        inspection.complete,
        "target identity inspection is incomplete for {}",
        definition.entrypoint.display()
    );
    let root = inspection
        .root
        .as_ref()
        .context("identity inspection has no root")?;
    ensure!(
        root.template_name == definition.template_name
            && root.concrete_parameters == definition.concrete_parameters,
        "identity entrypoint does not instantiate the requested template"
    );
    let fingerprints = corpus::fingerprint_sources(&inspection.dependency_paths)?;
    corpus::stable_target_id(definition, &inspection, &fingerprints)
}

fn engine_source_manifest(output: &Path) -> Result<DirectoryManifest> {
    let repository = Path::new(env!("CARGO_MANIFEST_DIR"));
    let mut files = Vec::new();
    for source in ENGINE_SOURCES {
        let path = repository.join(source);
        let bytes = fs::read(&path).with_context(|| format!("read engine source {source}"))?;
        files.push(ManifestFile {
            path: relative_path(output, &path)?,
            size: bytes.len() as u64,
            sha256: sha256_bytes(&bytes),
        });
    }
    files.sort_by(|left, right| left.path.cmp(&right.path));
    Ok(DirectoryManifest {
        schema_version: 1,
        files,
    })
}

/// A single-hunk unified diff with three lines of context; human-readable evidence only.
fn unified_diff(path: &str, before: &str, after: &str) -> String {
    let old = before.split_inclusive('\n').collect::<Vec<_>>();
    let new = after.split_inclusive('\n').collect::<Vec<_>>();
    let prefix = old
        .iter()
        .zip(&new)
        .take_while(|(left, right)| left == right)
        .count();
    let suffix = old[prefix..]
        .iter()
        .rev()
        .zip(new[prefix..].iter().rev())
        .take_while(|(left, right)| left == right)
        .count();
    let context = 3;
    let start = prefix.saturating_sub(context);
    let old_end = (old.len() - suffix + context).min(old.len());
    let new_end = (new.len() - suffix + context).min(new.len());
    let mut text = format!(
        "--- a/{path}\n+++ b/{path}\n@@ -{},{} +{},{} @@\n",
        start + 1,
        old_end - start,
        start + 1,
        new_end - start
    );
    let line = |marker: char, content: &str| {
        let mut line = format!("{marker}{content}");
        if !line.ends_with('\n') {
            line.push_str("\n\\ No newline at end of file\n");
        }
        line
    };
    for content in &old[start..prefix] {
        text.push_str(&line(' ', content));
    }
    for content in &old[prefix..old.len() - suffix] {
        text.push_str(&line('-', content));
    }
    for content in &new[prefix..new.len() - suffix] {
        text.push_str(&line('+', content));
    }
    for content in &old[old.len() - suffix..old_end] {
        text.push_str(&line(' ', content));
    }
    text
}

fn safe_relative(path: &Path, label: &str) -> Result<PathBuf> {
    ensure!(
        !path.as_os_str().is_empty()
            && path
                .components()
                .all(|component| matches!(component, Component::Normal(_))),
        "{label} must be a plain relative path"
    );
    Ok(path.to_path_buf())
}

fn slash_path(path: &Path) -> String {
    path.components()
        .map(|component| component.as_os_str().to_string_lossy().into_owned())
        .collect::<Vec<_>>()
        .join("/")
}

fn resolve_program(program: &Path) -> Result<PathBuf> {
    if program.components().count() > 1 {
        return fs::canonicalize(program)
            .with_context(|| format!("resolve program {}", program.display()));
    }
    let paths = std::env::var_os("PATH").context("PATH is not set")?;
    for directory in std::env::split_paths(&paths) {
        let candidate = directory.join(program);
        if candidate.is_file() {
            return Ok(fs::canonicalize(candidate)?);
        }
    }
    bail!("program {} is not on PATH", program.display())
}

fn normalize_lexical(path: &Path) -> PathBuf {
    let mut result = PathBuf::new();
    for component in path.components() {
        match component {
            Component::ParentDir => {
                result.pop();
            }
            Component::CurDir => {}
            other => result.push(other.as_os_str()),
        }
    }
    result
}

fn relative_path(from_directory: &Path, to: &Path) -> Result<PathBuf> {
    let from = fs::canonicalize(from_directory)?;
    let to = fs::canonicalize(to).with_context(|| format!("resolve {}", to.display()))?;
    let from_components = from.components().collect::<Vec<_>>();
    let to_components = to.components().collect::<Vec<_>>();
    let common = from_components
        .iter()
        .zip(&to_components)
        .take_while(|(left, right)| left == right)
        .count();
    let mut relative = PathBuf::new();
    for _ in common..from_components.len() {
        relative.push("..");
    }
    for component in &to_components[common..] {
        relative.push(component.as_os_str());
    }
    Ok(relative)
}

fn file_ref(from_directory: &Path, path: &Path) -> Result<FileRef> {
    Ok(FileRef {
        path: relative_path(from_directory, path)?,
        sha256: sha256_file(path)?,
    })
}

fn sha256_bytes(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn sha256_file(path: &Path) -> Result<String> {
    Ok(sha256_bytes(
        &fs::read(path).with_context(|| format!("read {}", path.display()))?,
    ))
}

fn pretty_json<T: Serialize>(value: &T) -> Result<Vec<u8>> {
    let mut bytes = serde_json::to_vec_pretty(value)?;
    bytes.push(b'\n');
    Ok(bytes)
}

fn write_new(path: &Path, bytes: &[u8]) -> Result<()> {
    ensure!(!path.exists(), "refusing to overwrite {}", path.display());
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(path, bytes).with_context(|| format!("write {}", path.display()))
}

fn write_json_new<T: Serialize>(path: &Path, value: &T) -> Result<()> {
    write_new(path, &pretty_json(value)?)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::candidate_review::schema::R1csShape;

    #[test]
    fn edit_must_be_unique_and_inside_the_template() {
        let text = "template A() { x <== y; }\ntemplate B() { x <== y; z <== w; }\n";
        let scope = text.find("template B").unwrap()..text.len();
        let duplicate = SourceEdit {
            find: "x <== y;".into(),
            replace: "x <-- y;".into(),
        };
        assert!(apply_edit(text, &duplicate, scope.clone(), "mutant").is_err());
        let outside = SourceEdit {
            find: "template A".into(),
            replace: "template C".into(),
        };
        assert!(apply_edit(text, &outside, scope.clone(), "mutant").is_err());
        let unique = SourceEdit {
            find: "z <== w;".into(),
            replace: "z <-- w;".into(),
        };
        let edited = apply_edit(text, &unique, scope, "mutant").unwrap();
        assert!(edited.contains("z <-- w;") && edited.contains("x <== y; z"));
    }

    #[test]
    fn deletion_location_is_widened_to_whole_lines() {
        let clean = b"template T() {\n  a;\n  b;\n}\n";
        let mutant = b"template T() {\n  a;\n}\n";
        let twin = b"template T() {\n  A;\n}\n";
        let template = 0..mutant.len();
        let range = injection_location(clean, mutant, twin, &template).unwrap();
        // Covers the deletion point after "a;" and the twin change of "a", nothing more.
        assert_eq!(&mutant[range], b"  a;\n");
    }

    #[test]
    fn instance_keys_split_into_source_template_and_parameters() {
        let (source, template, parameters) =
            parse_instance_key("/tmp/a::b/x.circom::Num2Bits(41)").unwrap();
        assert_eq!(source, PathBuf::from("/tmp/a::b/x.circom"));
        assert_eq!(template, "Num2Bits");
        assert_eq!(parameters, vec!["41".to_owned()]);
        let (_, _, none) = parse_instance_key("/x.circom::Where()").unwrap();
        assert!(none.is_empty());
    }

    #[test]
    fn scaled_and_renumbered_constraints_match_but_removed_ones_do_not() {
        let prime = BigUint::from(97u32);
        let lc = |terms: &[(u32, u32)]| {
            terms
                .iter()
                .map(|(wire, value)| (*wire, BigUint::from(*value)))
                .collect::<LinearCombination>()
        };
        let shape = |wires, constraints| R1csShape {
            wires,
            labels: wires as u64,
            public_outputs: 0,
            public_inputs: 0,
            private_inputs: 0,
            constraints,
        };
        // Clean: w1 * w2 = w3 and w1 * w1 = w1 (booleanity). Mutant keeps only the
        // product, renumbered (clean 1,2,3 -> mutant 2,1,3) and scaled by 5.
        let clean = R1cs {
            prime: prime.clone(),
            shape: shape(4, 2),
            constraints: vec![
                Constraint {
                    a: lc(&[(1, 1)]),
                    b: lc(&[(2, 1)]),
                    c: lc(&[(3, 1)]),
                },
                Constraint {
                    a: lc(&[(1, 1)]),
                    b: lc(&[(1, 1)]),
                    c: lc(&[(1, 1)]),
                },
            ],
            wire_labels: vec![0, 1, 2, 3],
        };
        let mutant = R1cs {
            prime,
            shape: shape(4, 1),
            constraints: vec![Constraint {
                a: lc(&[(1, 5)]),
                b: lc(&[(2, 1)]),
                c: lc(&[(3, 5)]),
            }],
            wire_labels: vec![0, 1, 2, 3],
        };
        let related =
            injection_related_constraints(&clean, &mutant, &[None, Some(2), Some(1), Some(3)])
                .unwrap();
        assert_eq!(related, BTreeSet::from([1]));
    }

    fn propagation_fixture(constraints: Vec<Constraint>) -> (R1cs, SymbolTable) {
        let r1cs = R1cs {
            prime: BigUint::from(97u32),
            shape: R1csShape {
                wires: 4,
                labels: 4,
                public_outputs: 1,
                public_inputs: 0,
                private_inputs: 1,
                constraints: constraints.len(),
            },
            constraints,
            wire_labels: vec![0, 1, 2, 3],
        };
        let symbols =
            SymbolTable::parse(b"1,1,0,main.out\n2,2,0,main.in\n3,3,0,main.t\n", &r1cs).unwrap();
        (r1cs, symbols)
    }

    fn term(wire: u32, value: u32) -> LinearCombination {
        LinearCombination::from([(wire, BigUint::from(value))])
    }

    fn fixed(values: &[(&str, u32)]) -> BTreeMap<String, BigUint> {
        values
            .iter()
            .map(|(name, value)| ((*name).to_owned(), BigUint::from(*value)))
            .collect()
    }

    #[test]
    fn propagation_derives_internal_wires_and_finds_the_contradiction() {
        // t = 3 * in, then out = t: fixing in and a wrong out violates the second constraint.
        let (r1cs, symbols) = propagation_fixture(vec![
            Constraint {
                a: term(2, 3),
                b: term(0, 1),
                c: term(3, 1),
            },
            Constraint {
                a: term(3, 1),
                b: term(0, 1),
                c: term(1, 1),
            },
        ]);
        let known =
            unique_propagation(&r1cs, &symbols, &fixed(&[("main.in", 5), ("main.out", 16)]))
                .unwrap();
        assert_eq!(known[3], Some(BigUint::from(15u32)));
        let candidates = BTreeSet::from([0, 1]);
        assert_eq!(
            propagation_contradictions(&r1cs, &known, &candidates),
            vec![1]
        );
        let consistent =
            unique_propagation(&r1cs, &symbols, &fixed(&[("main.in", 5), ("main.out", 15)]))
                .unwrap();
        assert!(propagation_contradictions(&r1cs, &consistent, &candidates).is_empty());
    }

    #[test]
    fn propagation_does_not_solve_a_quadratic_unknown() {
        // t * t = in has two roots, so t stays undetermined and the constraint proves nothing,
        // even for a nonsquare input.
        let (r1cs, symbols) = propagation_fixture(vec![Constraint {
            a: term(3, 1),
            b: term(3, 1),
            c: term(2, 1),
        }]);
        let known = unique_propagation(&r1cs, &symbols, &fixed(&[("main.in", 5)])).unwrap();
        assert_eq!(known[3], None);
        assert!(propagation_contradictions(&r1cs, &known, &BTreeSet::from([0])).is_empty());
    }

    #[test]
    fn unified_diff_shows_the_removed_line_with_context() {
        let diff = unified_diff("a.circom", "1\n2\n3\n4\n5\n6\n7\n", "1\n2\n3\n5\n6\n7\n");
        assert!(diff.starts_with("--- a/a.circom\n+++ b/a.circom\n@@ -1,7 +1,6 @@\n"));
        assert!(diff.contains("\n-4\n"));
    }
}
