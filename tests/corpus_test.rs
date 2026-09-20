use std::{
    fs,
    path::{Path, PathBuf},
};

use tempfile::{tempdir, TempDir};
use zkfdo::{
    corpus::{
        fingerprint_sources, prepare_manifest, stable_target_id, verify_fingerprints,
        verify_input_contract_evidence, verify_snapshot_provenance, BoundedEnforcement,
        ContractEvidence, CorpusManifest, CorpusTarget, Exclusion, InputContract, PrepareOptions,
        PreparedCorpus,
    },
    experiment::create_plan,
    static_rank::RankingStrategy,
    targets::inspect_entrypoint,
};

fn definition(project: &Path, entrypoint: &Path, argument: &str) -> CorpusTarget {
    CorpusTarget {
        label: "local unit fixture".to_owned(),
        project: "test-fixture".to_owned(),
        revision: "fixture-v1".to_owned(),
        project_root: project.to_owned(),
        entrypoint: entrypoint.to_owned(),
        template_name: "Root".to_owned(),
        concrete_parameters: vec![argument.to_owned()],
        prime: "bn128".to_owned(),
        compile_args: vec![],
        mode: "original".to_owned(),
        input_assumptions: "Synthetic test only; no public defect claim.".to_owned(),
        input_contract: None,
        known_defects: vec![],
    }
}

fn source_fixture() -> (TempDir, CorpusTarget) {
    let directory = tempdir().unwrap();
    let project = directory.path().join("project");
    fs::create_dir(&project).unwrap();
    fs::write(project.join("library.circom"),
        "pragma circom 2.1.8;\ntemplate Root(n) {\n signal input a;\n signal output b;\n b <== a + n;\n}\ntemplate Unreachable() {\n signal input a;\n signal output b;\n b <-- a * a;\n}\n").unwrap();
    let entrypoint = project.join("main.circom");
    fs::write(
        &entrypoint,
        "pragma circom 2.1.8;\ninclude \"library.circom\";\ncomponent main = Root(4);\n",
    )
    .unwrap();
    let target = definition(&project, &entrypoint, "4");
    (directory, target)
}

fn identity(target: &CorpusTarget) -> String {
    let inspection = inspect_entrypoint(&target.entrypoint, &target.project_root).unwrap();
    assert!(inspection.complete, "{:?}", inspection.unsupported);
    let hashes = fingerprint_sources(&inspection.dependency_paths).unwrap();
    stable_target_id(target, &inspection, &hashes).unwrap()
}

fn manifest(directory: &Path, targets: Vec<CorpusTarget>) -> PathBuf {
    let path = directory.join("manifest.json");
    fs::write(
        &path,
        serde_json::to_vec_pretty(&CorpusManifest {
            schema_version: 1,
            name: "local-fixtures".to_owned(),
            description: "Unit fixtures only".to_owned(),
            targets,
            exclusions: vec![Exclusion {
                label: "external-data".to_owned(),
                reason: "not collected".to_owned(),
            }],
        })
        .unwrap(),
    )
    .unwrap();
    path
}

fn manifest_v2(directory: &Path, targets: Vec<CorpusTarget>) -> PathBuf {
    let path = manifest(directory, targets);
    let mut value: serde_json::Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    value["schema_version"] = serde_json::json!(2);
    fs::write(&path, serde_json::to_vec_pretty(&value).unwrap()).unwrap();
    path
}

#[cfg(unix)]
fn fake_compiler(directory: &Path) -> PathBuf {
    use std::os::unix::fs::PermissionsExt;
    let path = directory.join("unit-fake-circom");
    fs::write(
        &path,
        r#"#!/bin/sh
if [ "$1" = "--version" ]; then
  echo 'unit-test fake circom'
  exit 0
fi
entry="$1"
shift
out=''
while [ "$#" -gt 0 ]; do
  if [ "$1" = '--output' ]; then
    shift
    out="$1"
  fi
  shift
done
stem=$(basename "$entry" .circom)
mkdir -p "$out"
echo 'unit fixture, not real R1CS' > "$out/$stem.r1cs"
echo 'non-linear constraints: 1'
echo 'linear constraints: 2'
"#,
    )
    .unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
    path
}

#[cfg(unix)]
fn baseline_options(directory: &Path) -> PrepareOptions {
    PrepareOptions {
        circom_bin: fake_compiler(directory),
        zkfuzz_bin: directory.join("deliberately-missing-zkfuzz"),
        analyzer_bin: directory.join("deliberately-missing-analyzer"),
        strategy: Some(RankingStrategy::PathOrder),
        ..PrepareOptions::default()
    }
}

#[test]
fn identity_tracks_parameters_content_field_revision_and_compile_settings() {
    let (_directory, target) = source_fixture();
    let original = identity(&target);
    let mut changed = target.clone();
    changed.prime = "goldilocks".to_owned();
    assert_ne!(original, identity(&changed));
    changed = target.clone();
    changed.compile_args.push("--O0".to_owned());
    assert_ne!(original, identity(&changed));
    changed = target.clone();
    changed.revision = "fixture-v2".to_owned();
    assert_ne!(original, identity(&changed));
    fs::write(
        &target.entrypoint,
        "include \"library.circom\";\ncomponent main = Root(9);\n",
    )
    .unwrap();
    changed = target.clone();
    changed.concrete_parameters = vec!["9".to_owned()];
    assert_ne!(original, identity(&changed));
    let with_argument = identity(&changed);
    let library = target.project_root.join("library.circom");
    fs::write(
        &library,
        fs::read_to_string(&library)
            .unwrap()
            .replace("a + n", "a * n"),
    )
    .unwrap();
    assert_ne!(with_argument, identity(&changed));
}

#[test]
fn identity_does_not_depend_on_wrapper_filename_or_manifest_label() {
    let (_directory, target) = source_fixture();
    let original = identity(&target);
    let mut renamed = target.clone();
    renamed.entrypoint = target.project_root.join("generated-uuid.circom");
    renamed.label = "renamed fixture".to_owned();
    fs::copy(&target.entrypoint, &renamed.entrypoint).unwrap();
    assert_eq!(original, identity(&renamed));
}

#[test]
fn identity_rejects_incomplete_or_foreign_fingerprint_sets() {
    let (directory, target) = source_fixture();
    let inspection = inspect_entrypoint(&target.entrypoint, &target.project_root).unwrap();
    let mut hashes = fingerprint_sources(&inspection.dependency_paths).unwrap();
    hashes.pop();
    assert!(stable_target_id(&target, &inspection, &hashes).is_err());
    fs::write(
        directory.path().join("foreign.circom"),
        "template Foreign() {}\n",
    )
    .unwrap();
    let mut hashes = fingerprint_sources(&inspection.dependency_paths).unwrap();
    hashes.extend(fingerprint_sources(&[directory.path().join("foreign.circom")]).unwrap());
    assert!(stable_target_id(&target, &inspection, &hashes).is_err());
}

#[test]
fn manifest_cannot_supply_unverified_or_unreachable_semantic_scopes() {
    let (_directory, target) = source_fixture();
    let mut value = serde_json::to_value(target).unwrap();
    value["scopes"] = serde_json::json!([{"path":"foreign.circom","template_name":"Unreachable","start_line":1,"end_line":200}]);
    assert!(serde_json::from_value::<CorpusTarget>(value).is_err());
}

#[test]
fn empty_manifest_preserves_explicit_exclusions_without_running_tools() {
    let directory = tempdir().unwrap();
    let path = manifest(directory.path(), vec![]);
    let report = prepare_manifest(
        &path,
        &PrepareOptions::default(),
        &directory.path().join("out"),
    )
    .unwrap();
    assert!(report.targets.is_empty());
    assert_eq!(report.exclusions[0].label, "external-data");
    assert!(report.report_path.is_file());
    let restored: PreparedCorpus =
        serde_json::from_slice(&fs::read(report.report_path).unwrap()).unwrap();
    assert_eq!(restored.exclusions[0].reason, "not collected");
}

#[test]
fn missing_target_is_retained_with_explicit_failure() {
    let directory = tempdir().unwrap();
    let target = definition(
        directory.path(),
        &directory.path().join("missing.circom"),
        "4",
    );
    let path = manifest(directory.path(), vec![target]);
    let report = prepare_manifest(
        &path,
        &PrepareOptions::default(),
        &directory.path().join("out"),
    )
    .unwrap();
    assert_eq!(report.targets.len(), 1);
    assert!(!report.targets[0].eligible);
    assert!(!report.targets[0].exclusion_reasons.is_empty());
    assert!(report.targets[0].ranking.risk_score.is_none());
    assert!(report.report_path.is_file());
}

#[cfg(unix)]
#[test]
fn baseline_compiles_snapshot_without_requesting_ast_or_semantic() {
    let (directory, target) = source_fixture();
    let original = fs::read(&target.entrypoint).unwrap();
    let path = manifest(directory.path(), vec![target.clone()]);
    let report = prepare_manifest(
        &path,
        &baseline_options(directory.path()),
        &directory.path().join("out"),
    )
    .unwrap();
    let prepared = &report.targets[0];
    assert!(prepared.eligible, "{:?}", prepared.exclusion_reasons);
    assert_eq!(prepared.ranking.size, Some(3));
    assert!(prepared.ranking.risk_score.is_none());
    assert!(prepared.semantic.is_none());
    assert!(!prepared.structure.as_ref().unwrap().ast_requested);
    assert!(
        !prepared
            .structure
            .as_ref()
            .unwrap()
            .zkfuzz_version
            .requested
    );
    let entrypoint = prepared.run_entrypoint.as_ref().unwrap();
    assert_ne!(entrypoint, &target.entrypoint);
    assert!(entrypoint
        .parent()
        .unwrap()
        .join("library.circom")
        .is_file());
    assert_eq!(fs::read(&target.entrypoint).unwrap(), original);
    assert_eq!(prepared.inspection.as_ref().unwrap().scopes.len(), 1);
    assert_eq!(
        prepared.inspection.as_ref().unwrap().scopes[0].template_name,
        "Root"
    );
    verify_fingerprints(&prepared.source_fingerprints).unwrap();
    verify_fingerprints(&prepared.snapshot_fingerprints).unwrap();
    verify_snapshot_provenance(
        prepared.inspection.as_ref().unwrap(),
        entrypoint,
        &prepared.source_fingerprints,
        &prepared.snapshot_fingerprints,
    )
    .unwrap();
    fs::write(&target.entrypoint, "changed after prepare").unwrap();
    assert!(verify_fingerprints(&prepared.source_fingerprints).is_err());
    verify_fingerprints(&prepared.snapshot_fingerprints).unwrap();
}

#[cfg(unix)]
#[test]
fn schema_two_excludes_unverified_bounded_inputs_but_retains_compile_evidence() {
    let (directory, mut target) = source_fixture();
    target.input_contract = Some(InputContract::Bounded {
        enforcement: BoundedEnforcement::Unverified,
        evidence: None,
    });
    let path = manifest_v2(directory.path(), vec![target]);
    let report = prepare_manifest(
        &path,
        &baseline_options(directory.path()),
        &directory.path().join("out"),
    )
    .unwrap();
    let prepared = &report.targets[0];
    assert!(!prepared.eligible);
    assert!(prepared.structure.as_ref().unwrap().compile_success);
    assert!(prepared
        .exclusion_reasons
        .iter()
        .any(|reason| reason.contains("bounded input contract is not reviewed")));
    let config = Path::new(env!("CARGO_MANIFEST_DIR")).join("configs/static-ranking.json");
    let error = create_plan(
        &report.report_path,
        RankingStrategy::PathOrder,
        &config,
        None,
        &directory.path().join("plan.json"),
    )
    .unwrap_err();
    assert!(format!("{error:#}").contains("no targets eligible"));
}

#[cfg(unix)]
#[test]
fn schema_two_requires_a_contract_and_accepts_field_only() {
    let (directory, target) = source_fixture();
    let path = manifest_v2(directory.path(), vec![target.clone()]);
    let missing = prepare_manifest(
        &path,
        &baseline_options(directory.path()),
        &directory.path().join("missing-out"),
    )
    .unwrap();
    assert!(!missing.targets[0].eligible);
    assert!(missing.targets[0]
        .exclusion_reasons
        .iter()
        .any(|reason| reason.contains("missing input_contract")));

    let mut field_only = target;
    field_only.input_contract = Some(InputContract::FieldOnly);
    let path = manifest_v2(directory.path(), vec![field_only]);
    let accepted = prepare_manifest(
        &path,
        &baseline_options(directory.path()),
        &directory.path().join("accepted-out"),
    )
    .unwrap();
    assert!(accepted.targets[0].eligible);
    assert_ne!(missing.targets[0].target_id, accepted.targets[0].target_id);
}

#[cfg(unix)]
#[test]
fn reviewed_bounded_contract_must_match_fingerprinted_entrypoint_and_evidence() {
    let (directory, mut target) = source_fixture();
    let evidence_path = directory.path().join("range-review.txt");
    fs::write(&evidence_path, "unit-test review record").unwrap();
    let evidence_sha256 = sha256_hex(&fs::read(&evidence_path).unwrap());
    let entrypoint_sha256 = sha256_hex(&fs::read(&target.entrypoint).unwrap());
    let inspection = inspect_entrypoint(&target.entrypoint, &target.project_root).unwrap();
    let source_fingerprints = fingerprint_sources(&inspection.dependency_paths).unwrap();
    let source_closure_sha256 = sha256_hex(&serde_json::to_vec(&source_fingerprints).unwrap());
    target.input_contract = Some(InputContract::Bounded {
        enforcement: BoundedEnforcement::ReviewedInExecutable,
        evidence: Some(ContractEvidence {
            path: evidence_path.clone(),
            sha256: evidence_sha256,
            entrypoint_sha256,
            source_closure_sha256,
        }),
    });
    let path = manifest_v2(directory.path(), vec![target.clone()]);
    let accepted = prepare_manifest(
        &path,
        &baseline_options(directory.path()),
        &directory.path().join("accepted-out"),
    )
    .unwrap();
    assert!(accepted.targets[0].eligible);

    fs::write(&evidence_path, "changed review record").unwrap();
    assert!(verify_input_contract_evidence(&accepted.targets[0]).is_err());
    let rejected = prepare_manifest(
        &path,
        &baseline_options(directory.path()),
        &directory.path().join("rejected-out"),
    )
    .unwrap();
    assert!(!rejected.targets[0].eligible);
    assert!(rejected.targets[0]
        .exclusion_reasons
        .iter()
        .any(|reason| reason.contains("evidence hash mismatch")));
}

fn sha256_hex(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    format!("{:x}", Sha256::digest(bytes))
}

#[cfg(unix)]
#[test]
fn incorrect_manifest_root_is_excluded_but_compile_evidence_is_retained() {
    let (directory, mut target) = source_fixture();
    target.template_name = "Unreachable".to_owned();
    target.concrete_parameters = vec!["999".to_owned()];
    let path = manifest(directory.path(), vec![target]);
    let report = prepare_manifest(
        &path,
        &baseline_options(directory.path()),
        &directory.path().join("out"),
    )
    .unwrap();
    let prepared = &report.targets[0];
    assert!(!prepared.eligible);
    assert!(prepared
        .exclusion_reasons
        .iter()
        .any(|reason| reason.contains("differs from parsed root")));
    assert!(prepared
        .exclusion_reasons
        .iter()
        .any(|reason| reason.contains("parameters")));
    assert_eq!(prepared.structure.as_ref().unwrap().root_template, "Root");
    assert!(prepared.structure.as_ref().unwrap().compile_success);
    assert_eq!(prepared.inspection.as_ref().unwrap().scopes.len(), 1);
}

#[cfg(unix)]
#[test]
fn duplicate_identities_are_explicitly_excluded() {
    let (directory, target) = source_fixture();
    let mut duplicate = target.clone();
    duplicate.label = "duplicate".to_owned();
    duplicate.entrypoint = target.project_root.join("other-wrapper.circom");
    fs::copy(&target.entrypoint, &duplicate.entrypoint).unwrap();
    let path = manifest(directory.path(), vec![target, duplicate]);
    let report = prepare_manifest(
        &path,
        &baseline_options(directory.path()),
        &directory.path().join("out"),
    )
    .unwrap();
    assert_eq!(report.targets[0].target_id, report.targets[1].target_id);
    assert!(report.targets.iter().all(|target| !target.eligible
        && target
            .exclusion_reasons
            .iter()
            .any(|reason| reason.contains("duplicate executable"))));
}

#[cfg(unix)]
#[test]
fn missing_required_semantic_data_remains_unknown() {
    let (directory, target) = source_fixture();
    let path = manifest(directory.path(), vec![target]);
    let mut options = baseline_options(directory.path());
    options.strategy = Some(RankingStrategy::RiskOnly);
    let report = prepare_manifest(&path, &options, &directory.path().join("out")).unwrap();
    let prepared = &report.targets[0];
    assert!(!prepared.eligible);
    assert!(prepared.ranking.risk_score.is_none());
    assert!(prepared.ranking.warning_count.is_none());
    assert!(prepared
        .semantic
        .as_ref()
        .is_some_and(|analysis| !analysis.complete));
    assert!(prepared
        .exclusion_reasons
        .iter()
        .any(|reason| reason.contains("semantic")));
    assert!(!prepared.structure.as_ref().unwrap().ast_requested);
}

#[cfg(unix)]
#[test]
fn relative_manifest_paths_resolve_from_manifest_directory() {
    let (directory, mut target) = source_fixture();
    target.project_root = PathBuf::from("project");
    target.entrypoint = PathBuf::from("project/main.circom");
    let path = manifest(directory.path(), vec![target]);
    let report = prepare_manifest(
        &path,
        &baseline_options(directory.path()),
        &directory.path().join("out"),
    )
    .unwrap();
    assert!(
        report.targets[0].eligible,
        "{:?}",
        report.targets[0].exclusion_reasons
    );
    assert!(report.targets[0].definition.entrypoint.is_absolute());
    assert!(report.targets[0].definition.project_root.is_absolute());
}

#[test]
#[ignore = "requires locally installed Circom, zkFuzz, and the pinned Circomspect build; no fuzz search"]
fn real_local_tools_prepare_a_complete_fixture() {
    let (directory, mut target) = source_fixture();
    let wrapper_dir = directory.path().join("wrappers");
    fs::create_dir(&wrapper_dir).unwrap();
    target.entrypoint = wrapper_dir.join("generated.circom");
    target.mode = "direct".to_owned();
    fs::write(
        &target.entrypoint,
        "pragma circom 2.1.8;\ninclude \"../project/library.circom\";\ncomponent main = Root(4);\n",
    )
    .unwrap();
    let path = manifest(directory.path(), vec![target]);
    let report = prepare_manifest(
        &path,
        &PrepareOptions::default(),
        &directory.path().join("out"),
    )
    .unwrap();
    let prepared = &report.targets[0];
    assert!(prepared.eligible, "{:?}", prepared.exclusion_reasons);
    assert!(prepared.structure.as_ref().unwrap().complete);
    assert!(prepared.semantic.as_ref().unwrap().complete);
    assert_eq!(prepared.ranking.complexity, Some(0));
    assert_eq!(prepared.ranking.risk_score, Some(0));
    assert!(
        prepared
            .semantic
            .as_ref()
            .unwrap()
            .ignored_out_of_scope_count
            > 0
    );
    assert!(prepared.ranking.legacy_score.is_some());
    verify_fingerprints(&prepared.source_fingerprints).unwrap();
    verify_fingerprints(&prepared.snapshot_fingerprints).unwrap();
    verify_snapshot_provenance(
        prepared.inspection.as_ref().unwrap(),
        prepared.run_entrypoint.as_ref().unwrap(),
        &prepared.source_fingerprints,
        &prepared.snapshot_fingerprints,
    )
    .unwrap();
}

#[cfg(unix)]
#[test]
fn updating_snapshot_hashes_cannot_rebind_a_target_to_different_source() {
    let (directory, target) = source_fixture();
    let path = manifest(directory.path(), vec![target]);
    let report = prepare_manifest(
        &path,
        &baseline_options(directory.path()),
        &directory.path().join("out"),
    )
    .unwrap();
    let prepared = &report.targets[0];
    let entrypoint = prepared.run_entrypoint.as_ref().unwrap();
    fs::write(
        entrypoint,
        "template Other() {}\ncomponent main = Other();\n",
    )
    .unwrap();
    let snapshot_paths = prepared
        .snapshot_fingerprints
        .iter()
        .map(|value| value.path.clone())
        .collect::<Vec<_>>();
    let updated_hashes = fingerprint_sources(&snapshot_paths).unwrap();
    verify_fingerprints(&updated_hashes).unwrap();
    let error = verify_snapshot_provenance(
        prepared.inspection.as_ref().unwrap(),
        entrypoint,
        &prepared.source_fingerprints,
        &updated_hashes,
    )
    .unwrap_err();
    assert!(error.to_string().contains("do not match"));
}

#[test]
fn original_entrypoint_cannot_be_used_as_its_own_snapshot() {
    let (_directory, target) = source_fixture();
    let inspection = inspect_entrypoint(&target.entrypoint, &target.project_root).unwrap();
    let fingerprints = fingerprint_sources(&inspection.dependency_paths).unwrap();
    let error = verify_snapshot_provenance(
        &inspection,
        &inspection.entrypoint,
        &fingerprints,
        &fingerprints,
    )
    .unwrap_err();
    assert!(error.to_string().contains("independent file"));
}

#[cfg(unix)]
#[test]
fn snapshot_hard_links_cannot_expose_original_sources_to_execution_writes() {
    let (directory, target) = source_fixture();
    let path = manifest(directory.path(), vec![target]);
    let report = prepare_manifest(
        &path,
        &baseline_options(directory.path()),
        &directory.path().join("out"),
    )
    .unwrap();
    let prepared = &report.targets[0];
    let entrypoint = prepared.run_entrypoint.as_ref().unwrap();
    fs::remove_file(entrypoint).unwrap();
    fs::hard_link(&prepared.definition.entrypoint, entrypoint).unwrap();
    let error = verify_snapshot_provenance(
        prepared.inspection.as_ref().unwrap(),
        entrypoint,
        &prepared.source_fingerprints,
        &prepared.snapshot_fingerprints,
    )
    .unwrap_err();
    assert!(error.to_string().contains("hard link"));
}

#[test]
fn checked_in_dev_manifest_is_an_honest_three_target_direct_subset() {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("datasets/manifest.dev10.json");
    let manifest: CorpusManifest = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
    assert_eq!(manifest.targets.len(), 3);
    assert_eq!(manifest.exclusions.len(), 2);
    assert!(manifest.description.contains("not ten targets"));
    assert!(manifest
        .targets
        .iter()
        .all(|target| target.mode == "direct"));
    let roots = manifest
        .targets
        .iter()
        .flat_map(|target| {
            target
                .known_defects
                .iter()
                .map(|defect| defect.root_cause_id.as_str())
        })
        .collect::<std::collections::BTreeSet<_>>();
    assert_eq!(roots.len(), 3);
    assert!(manifest.targets.iter().all(|target| {
        target.known_defects.iter().all(|defect| {
            defect.reported
                && defect.local_reproduction.starts_with("Not reproduced")
                && defect.tcct_status.contains("not been verified")
        })
    }));
}
