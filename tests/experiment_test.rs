#![cfg(unix)]

use std::{
    collections::BTreeSet,
    fs,
    os::unix::fs::PermissionsExt,
    path::{Path, PathBuf},
};

use tempfile::{tempdir, TempDir};
use zkfdo::{
    corpus::{
        fingerprint_sources, prepare_manifest, CorpusManifest, CorpusTarget, KnownDefect,
        PrepareOptions, PreparedCorpus,
    },
    experiment::{
        create_plan, evaluate, execute_plan, ConfirmationScope, ConfirmationSet,
        DefectConfirmation, EvidenceOrigin, ExecuteOptions, ExperimentOutcome, ExperimentPlan,
        OriginalComponentReview, ReviewCriterion, ReviewVerdict,
    },
    static_rank::{ComplexityGroups, RankingStrategy, StaticRankingConfig},
    structure::STRUCTURAL_METRIC,
};

struct Fixture {
    directory: TempDir,
    prepared: PreparedCorpus,
    config_path: PathBuf,
}

fn script(directory: &Path, name: &str, body: &str) -> PathBuf {
    let path = directory.join(name);
    fs::write(&path, format!("#!/bin/sh\n{body}\n")).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
    path
}

fn fixture() -> Fixture {
    let directory = tempdir().unwrap();
    let project_root = directory.path().join("sources");
    fs::create_dir(&project_root).unwrap();
    let targets = ["B", "A"].into_iter().map(|label| {
        let entrypoint = project_root.join(format!("{label}.circom"));
        fs::write(&entrypoint, format!("template Root{label}() {{\n signal input x;\n signal output y;\n y <== x;\n}}\ncomponent main = Root{label}();\n")).unwrap();
        CorpusTarget {
            label: label.to_owned(), project: "unit-test-only".to_owned(), revision: "fixture-v1".to_owned(),
            project_root: project_root.clone(), entrypoint, template_name: format!("Root{label}"), concrete_parameters: vec![],
            prime: "bn128".to_owned(), compile_args: vec![], mode: "original".to_owned(),
            input_assumptions: "Synthetic test fixture; no actual vulnerability claim.".to_owned(),
            input_contract: None,
            known_defects: vec![KnownDefect {
                root_cause_id: "synthetic-shared-root-cause".to_owned(), location: format!("{label}.circom:1"),
                source_url: "unit-test:fixture".to_owned(), reported: true,
                local_reproduction: "synthetic-test-only".to_owned(), tcct_status: "not-evaluated".to_owned(),
                reachability: "synthetic-test-only".to_owned(), evidence: vec![],
            }],
            instance_capture: None,
        }
    }).collect();
    let manifest_path = directory.path().join("manifest.json");
    write_json(
        &manifest_path,
        &CorpusManifest {
            schema_version: 1,
            name: "unit-fixtures".to_owned(),
            description: "Synthetic tests".to_owned(),
            targets,
            exclusions: vec![],
        },
    );
    let compiler = script(
        directory.path(),
        "fake-circom",
        r#"
if [ "$1" = '--version' ]; then echo 'unit fake compiler'; exit 0; fi
input="$1"
shift
while [ "$#" -gt 0 ]; do
  if [ "$1" = '--output' ]; then shift; out="$1"; fi
  shift
done
name=${input##*/}
stem=${name%.circom}
echo 'unit fixture artifact' > "$out/$stem.r1cs"
echo 'non-linear constraints: 1'
echo 'linear constraints: 0'
"#,
    );
    let options = PrepareOptions {
        circom_bin: compiler,
        strategy: Some(RankingStrategy::PathOrder),
        ..PrepareOptions::default()
    };
    let prepared =
        prepare_manifest(&manifest_path, &options, &directory.path().join("prepared")).unwrap();
    assert!(
        prepared.targets.iter().all(|target| target.eligible),
        "{:?}",
        prepared
            .targets
            .iter()
            .map(|target| &target.exclusion_reasons)
            .collect::<Vec<_>>()
    );
    let config_path = directory.path().join("config.json");
    write_json(&config_path, &StaticRankingConfig::default());
    Fixture {
        directory,
        prepared,
        config_path,
    }
}

fn plan(fixture: &Fixture) -> ExperimentPlan {
    create_plan(
        &fixture.prepared.report_path,
        RankingStrategy::PathOrder,
        &fixture.config_path,
        None,
        &fixture.directory.path().join("plan.json"),
    )
    .unwrap()
}

fn execute(fixture: &Fixture, plan: &ExperimentPlan, bug_candidate: bool) -> ExperimentOutcome {
    let body = if bug_candidate {
        r#"
printf '{"synthetic":"test candidate"}\n' > "${1}_123_counterexample.json"
printf 'Random Seed: 123\nGeneration: 1/500\nVerification: NOT SAFE\n'
"#
    } else {
        "printf 'Verification: No Counter Example Found\\n'"
    };
    let options = ExecuteOptions {
        zkfuzz_bin: script(fixture.directory.path(), "fake-zkfuzz", body),
        budget_seconds: 10,
        total_budget_seconds: 30,
        zkfuzz_seed: Some(123),
        mutation_settings: None,
        output: fixture.directory.path().join("executions"),
    };
    execute_plan(&plan.plan_path, &options).unwrap()
}

fn write_json(path: &Path, value: &impl serde::Serialize) {
    fs::write(path, serde_json::to_vec_pretty(value).unwrap()).unwrap();
}

fn original_component_review(
    evidence: &Path,
    input_preconditions: ReviewVerdict,
    fixed_original_constraints: ReviewVerdict,
    specified_property_violation: ReviewVerdict,
) -> OriginalComponentReview {
    let criterion = |verdict, note: &str| ReviewCriterion {
        verdict,
        evidence: vec![evidence.to_path_buf()],
        note: note.to_owned(),
    };
    OriginalComponentReview {
        input_preconditions: criterion(input_preconditions, "Synthetic input review"),
        fixed_original_constraints: criterion(
            fixed_original_constraints,
            "Synthetic constraint review",
        ),
        specified_property_violation: criterion(
            specified_property_violation,
            "Synthetic property review",
        ),
    }
}

#[test]
fn reviewed_project_root_causes_are_deduplicated_across_targets_and_runs() {
    let fixture = fixture();
    let plan = plan(&fixture);
    let outcome = execute(&fixture, &plan, true);
    assert_eq!(outcome.scheduler.runs.len(), 2);
    let evidence = fixture.directory.path().join("synthetic-review.txt");
    fs::write(
        &evidence,
        "Unit-test review placeholder, not a real defect confirmation.",
    )
    .unwrap();
    let mut confirmations = outcome
        .scheduler
        .runs
        .iter()
        .map(|run| DefectConfirmation {
            run_id: run.result.run_id.clone(),
            target_id: run.target_id.clone(),
            root_cause_id: "synthetic-shared-root-cause".to_owned(),
            scope: ConfirmationScope::Project,
            evidence_origin: EvidenceOrigin::BackendExecution,
            original_component_review: None,
            evidence: vec![evidence.clone()],
            note: "Synthetic reviewed fixture".to_owned(),
        })
        .collect::<Vec<_>>();
    for (scope, root_cause_id) in [
        (ConfirmationScope::WrapperOnly, "wrapper-fixture"),
        (ConfirmationScope::ReachabilityUnknown, "unknown-fixture"),
    ] {
        confirmations.push(DefectConfirmation {
            run_id: outcome.scheduler.runs[0].result.run_id.clone(),
            target_id: outcome.scheduler.runs[0].target_id.clone(),
            root_cause_id: root_cause_id.to_owned(),
            scope,
            evidence_origin: EvidenceOrigin::BackendExecution,
            original_component_review: None,
            evidence: vec![evidence.clone()],
            note: "Synthetic reviewed fixture".to_owned(),
        });
    }
    let confirmation_path = fixture.directory.path().join("confirmations.json");
    write_json(
        &confirmation_path,
        &ConfirmationSet {
            schema_version: 1,
            confirmations,
        },
    );
    let report = evaluate(
        &plan.plan_path,
        &outcome.report_path,
        Some(&confirmation_path),
        &fixture.directory.path().join("evaluation.json"),
    )
    .unwrap();
    assert_eq!(report.backend_bug_candidate_count, 2);
    assert_eq!(report.preserved_counterexample_count, 2);
    assert_eq!(report.reviewed_confirmation_count, 4);
    assert_eq!(report.confirmed_project_defect_count, 1);
    assert_eq!(report.confirmed_original_component_defect_count, 0);
    assert_eq!(report.wrapper_only_confirmation_count, 1);
    assert_eq!(report.reachability_unknown_confirmation_count, 1);
    assert_eq!(
        report.confirmed_project_root_causes,
        ["synthetic-shared-root-cause"]
    );
    assert_eq!(report.known_defect_target_count, 2);
    assert_eq!(report.known_defect_root_cause_count, 1);
    assert_eq!(report.recall_at_k[0].recall, Some(0.5));
    assert_eq!(report.detection_curve.len(), 1);
    assert_eq!(
        report.detection_curve[0].cumulative_confirmed_project_defects,
        1
    );
    assert_eq!(
        report.first_confirmed_defect_observed_by_seconds,
        Some(outcome.scheduler.runs[0].completion_offset_seconds)
    );
}

#[test]
fn backend_candidates_without_review_leave_detection_time_null() {
    let fixture = fixture();
    let plan = plan(&fixture);
    let outcome = execute(&fixture, &plan, true);
    let report = evaluate(
        &plan.plan_path,
        &outcome.report_path,
        None,
        &fixture.directory.path().join("evaluation.json"),
    )
    .unwrap();
    assert_eq!(report.backend_bug_candidate_count, 2);
    assert_eq!(report.confirmed_project_defect_count, 0);
    assert_eq!(report.confirmed_original_component_defect_count, 0);
    assert!(report.detection_curve.is_empty());
    assert!(report.original_component_detection_curve.is_empty());
    assert_eq!(report.first_confirmed_defect_observed_by_seconds, None);
    assert_eq!(
        report.first_confirmed_original_component_defect_observed_by_seconds,
        None
    );
    let json: serde_json::Value =
        serde_json::from_slice(&fs::read(report.report_path).unwrap()).unwrap();
    assert!(json["first_confirmed_defect_observed_by_seconds"].is_null());
}

#[test]
fn original_component_execution_confirmations_are_deduplicated_by_root_cause() {
    let fixture = fixture();
    let plan = plan(&fixture);
    let outcome = execute(&fixture, &plan, true);
    let evidence = fixture.directory.path().join("component-review.txt");
    fs::write(&evidence, "Synthetic structured component review").unwrap();
    let confirmations = outcome
        .scheduler
        .runs
        .iter()
        .map(|run| DefectConfirmation {
            run_id: run.result.run_id.clone(),
            target_id: run.target_id.clone(),
            root_cause_id: "synthetic-component-root".to_owned(),
            scope: ConfirmationScope::OriginalComponent,
            evidence_origin: EvidenceOrigin::BackendExecution,
            original_component_review: Some(original_component_review(
                &evidence,
                ReviewVerdict::Satisfied,
                ReviewVerdict::Satisfied,
                ReviewVerdict::Satisfied,
            )),
            evidence: vec![evidence.clone()],
            note: "Synthetic record; no real defect claim".to_owned(),
        })
        .collect();
    let confirmation_path = fixture.directory.path().join("confirmations-v2.json");
    write_json(
        &confirmation_path,
        &ConfirmationSet {
            schema_version: 2,
            confirmations,
        },
    );

    let report = evaluate(
        &plan.plan_path,
        &outcome.report_path,
        Some(&confirmation_path),
        &fixture.directory.path().join("evaluation.json"),
    )
    .unwrap();

    assert_eq!(report.schema_version, 2);
    assert_eq!(report.reviewed_confirmation_count, 2);
    assert_eq!(report.confirmed_project_defect_count, 0);
    assert_eq!(report.confirmed_original_component_defect_count, 1);
    assert_eq!(
        report.confirmed_original_component_root_causes,
        ["synthetic-component-root"]
    );
    assert_eq!(report.original_component_detection_curve.len(), 1);
    assert_eq!(
        report.original_component_detection_curve[0]
            .cumulative_confirmed_original_component_defects,
        1
    );
    let earliest_completion = outcome
        .scheduler
        .runs
        .iter()
        .map(|run| run.completion_offset_seconds)
        .min_by(f64::total_cmp);
    assert_eq!(
        report.first_confirmed_original_component_defect_observed_by_seconds,
        earliest_completion
    );
}

#[test]
fn unmet_or_unknown_component_criteria_do_not_count_as_valid_defects() {
    let fixture = fixture();
    let plan = plan(&fixture);
    let outcome = execute(&fixture, &plan, true);
    let run = &outcome.scheduler.runs[0];
    let evidence = fixture.directory.path().join("incomplete-review.txt");
    fs::write(&evidence, "Synthetic incomplete review").unwrap();
    let confirmations = vec![
        DefectConfirmation {
            run_id: run.result.run_id.clone(),
            target_id: run.target_id.clone(),
            root_cause_id: "synthetic-precondition-failure".to_owned(),
            scope: ConfirmationScope::OriginalComponent,
            evidence_origin: EvidenceOrigin::BackendExecution,
            original_component_review: Some(original_component_review(
                &evidence,
                ReviewVerdict::NotSatisfied,
                ReviewVerdict::Satisfied,
                ReviewVerdict::Satisfied,
            )),
            evidence: vec![evidence.clone()],
            note: "Synthetic rejected review".to_owned(),
        },
        DefectConfirmation {
            run_id: run.result.run_id.clone(),
            target_id: run.target_id.clone(),
            root_cause_id: "synthetic-property-unknown".to_owned(),
            scope: ConfirmationScope::OriginalComponent,
            evidence_origin: EvidenceOrigin::BackendExecution,
            original_component_review: Some(original_component_review(
                &evidence,
                ReviewVerdict::Satisfied,
                ReviewVerdict::Satisfied,
                ReviewVerdict::Unknown,
            )),
            evidence: vec![evidence.clone()],
            note: "Synthetic unresolved review".to_owned(),
        },
        DefectConfirmation {
            run_id: run.result.run_id.clone(),
            target_id: run.target_id.clone(),
            root_cause_id: "synthetic-wrapper-only".to_owned(),
            scope: ConfirmationScope::WrapperOnly,
            evidence_origin: EvidenceOrigin::BackendExecution,
            original_component_review: Some(original_component_review(
                &evidence,
                ReviewVerdict::Satisfied,
                ReviewVerdict::Satisfied,
                ReviewVerdict::Satisfied,
            )),
            evidence: vec![evidence.clone()],
            note: "Synthetic wrapper-only classification".to_owned(),
        },
        DefectConfirmation {
            run_id: run.result.run_id.clone(),
            target_id: run.target_id.clone(),
            root_cause_id: "synthetic-reachability-unknown".to_owned(),
            scope: ConfirmationScope::ReachabilityUnknown,
            evidence_origin: EvidenceOrigin::BackendExecution,
            original_component_review: Some(original_component_review(
                &evidence,
                ReviewVerdict::Satisfied,
                ReviewVerdict::Satisfied,
                ReviewVerdict::Satisfied,
            )),
            evidence: vec![evidence.clone()],
            note: "Synthetic unknown-reachability classification".to_owned(),
        },
    ];
    let confirmation_path = fixture.directory.path().join("confirmations-v2.json");
    write_json(
        &confirmation_path,
        &ConfirmationSet {
            schema_version: 2,
            confirmations,
        },
    );

    let report = evaluate(
        &plan.plan_path,
        &outcome.report_path,
        Some(&confirmation_path),
        &fixture.directory.path().join("evaluation.json"),
    )
    .unwrap();

    assert_eq!(report.reviewed_confirmation_count, 4);
    assert_eq!(report.wrapper_only_confirmation_count, 1);
    assert_eq!(report.reachability_unknown_confirmation_count, 1);
    assert_eq!(report.confirmed_original_component_defect_count, 0);
    assert!(report.original_component_detection_curve.is_empty());
    assert_eq!(
        report.first_confirmed_original_component_defect_observed_by_seconds,
        None
    );
}

#[test]
fn original_component_scope_requires_a_structured_review() {
    let fixture = fixture();
    let plan = plan(&fixture);
    let outcome = execute(&fixture, &plan, true);
    let run = &outcome.scheduler.runs[0];
    let evidence = fixture.directory.path().join("missing-review.txt");
    fs::write(&evidence, "Synthetic missing structured review").unwrap();
    let confirmation_path = fixture.directory.path().join("confirmations-v2.json");
    write_json(
        &confirmation_path,
        &ConfirmationSet {
            schema_version: 2,
            confirmations: vec![DefectConfirmation {
                run_id: run.result.run_id.clone(),
                target_id: run.target_id.clone(),
                root_cause_id: "synthetic-missing-review".to_owned(),
                scope: ConfirmationScope::OriginalComponent,
                evidence_origin: EvidenceOrigin::BackendExecution,
                original_component_review: None,
                evidence: vec![evidence],
                note: "Synthetic invalid component record".to_owned(),
            }],
        },
    );

    let error = evaluate(
        &plan.plan_path,
        &outcome.report_path,
        Some(&confirmation_path),
        &fixture.directory.path().join("evaluation.json"),
    )
    .unwrap_err();
    assert!(error
        .to_string()
        .contains("original-component scope requires a structured original-component review"));
}

#[test]
fn static_review_evidence_is_preserved_but_not_counted_as_execution_discovery() {
    let fixture = fixture();
    let plan = plan(&fixture);
    let outcome = execute(&fixture, &plan, false);
    let run = &outcome.scheduler.runs[0];
    let evidence = fixture.directory.path().join("static-review.txt");
    fs::write(&evidence, "Synthetic static review").unwrap();
    let confirmation_path = fixture.directory.path().join("confirmations-v2.json");
    write_json(
        &confirmation_path,
        &ConfirmationSet {
            schema_version: 2,
            confirmations: vec![DefectConfirmation {
                run_id: run.result.run_id.clone(),
                target_id: run.target_id.clone(),
                root_cause_id: "synthetic-static-root".to_owned(),
                scope: ConfirmationScope::OriginalComponent,
                evidence_origin: EvidenceOrigin::StaticWarning,
                original_component_review: Some(original_component_review(
                    &evidence,
                    ReviewVerdict::Satisfied,
                    ReviewVerdict::Satisfied,
                    ReviewVerdict::Satisfied,
                )),
                evidence: vec![evidence],
                note: "Synthetic static evidence only".to_owned(),
            }],
        },
    );

    let report = evaluate(
        &plan.plan_path,
        &outcome.report_path,
        Some(&confirmation_path),
        &fixture.directory.path().join("evaluation.json"),
    )
    .unwrap();

    assert_eq!(report.reviewed_confirmation_count, 1);
    assert_eq!(report.evidence_origin_counts["static-warning"], 1);
    assert_eq!(report.confirmed_original_component_defect_count, 0);
    assert_eq!(report.confirmed_project_defect_count, 0);
}

#[test]
fn legacy_project_confirmation_keeps_project_metric_without_component_promotion() {
    let fixture = fixture();
    let plan = plan(&fixture);
    let outcome = execute(&fixture, &plan, true);
    let run = &outcome.scheduler.runs[0];
    let evidence = fixture.directory.path().join("legacy-review.txt");
    fs::write(&evidence, "Synthetic legacy project review").unwrap();
    let confirmation_path = fixture.directory.path().join("confirmations-v1.json");
    write_json(
        &confirmation_path,
        &serde_json::json!({
            "schema_version": 1,
            "confirmations": [{
                "run_id": run.result.run_id,
                "target_id": run.target_id,
                "root_cause_id": "synthetic-legacy-project-root",
                "scope": "project",
                "evidence": [evidence],
                "note": "Synthetic schema-1 compatibility record"
            }]
        }),
    );

    let report = evaluate(
        &plan.plan_path,
        &outcome.report_path,
        Some(&confirmation_path),
        &fixture.directory.path().join("evaluation.json"),
    )
    .unwrap();

    assert_eq!(report.confirmed_project_defect_count, 1);
    assert_eq!(report.confirmed_original_component_defect_count, 0);
    assert_eq!(report.evidence_origin_counts["backend-execution"], 1);
}

#[test]
fn project_confirmation_with_component_review_contributes_to_both_scopes() {
    let fixture = fixture();
    let plan = plan(&fixture);
    let outcome = execute(&fixture, &plan, true);
    let run = &outcome.scheduler.runs[0];
    let evidence = fixture
        .directory
        .path()
        .join("project-component-review.txt");
    fs::write(&evidence, "Synthetic project and component review").unwrap();
    let confirmation_path = fixture.directory.path().join("confirmations-v2.json");
    write_json(
        &confirmation_path,
        &ConfirmationSet {
            schema_version: 2,
            confirmations: vec![DefectConfirmation {
                run_id: run.result.run_id.clone(),
                target_id: run.target_id.clone(),
                root_cause_id: "synthetic-reviewed-project-root".to_owned(),
                scope: ConfirmationScope::Project,
                evidence_origin: EvidenceOrigin::BackendExecution,
                original_component_review: Some(original_component_review(
                    &evidence,
                    ReviewVerdict::Satisfied,
                    ReviewVerdict::Satisfied,
                    ReviewVerdict::Satisfied,
                )),
                evidence: vec![evidence],
                note: "Synthetic dual-scope qualification".to_owned(),
            }],
        },
    );

    let report = evaluate(
        &plan.plan_path,
        &outcome.report_path,
        Some(&confirmation_path),
        &fixture.directory.path().join("evaluation.json"),
    )
    .unwrap();

    assert_eq!(report.confirmed_project_defect_count, 1);
    assert_eq!(report.confirmed_original_component_defect_count, 1);
}

#[test]
fn mismatched_confirmation_run_and_target_is_rejected() {
    let fixture = fixture();
    let plan = plan(&fixture);
    let outcome = execute(&fixture, &plan, true);
    let evidence = fixture.directory.path().join("mismatch-review.txt");
    fs::write(&evidence, "Synthetic mismatched review").unwrap();
    let confirmation_path = fixture.directory.path().join("confirmations-v2.json");
    write_json(
        &confirmation_path,
        &ConfirmationSet {
            schema_version: 2,
            confirmations: vec![DefectConfirmation {
                run_id: outcome.scheduler.runs[0].result.run_id.clone(),
                target_id: outcome.scheduler.runs[1].target_id.clone(),
                root_cause_id: "synthetic-mismatch-root".to_owned(),
                scope: ConfirmationScope::OriginalComponent,
                evidence_origin: EvidenceOrigin::BackendExecution,
                original_component_review: Some(original_component_review(
                    &evidence,
                    ReviewVerdict::Satisfied,
                    ReviewVerdict::Satisfied,
                    ReviewVerdict::Satisfied,
                )),
                evidence: vec![evidence],
                note: "Synthetic invalid linkage".to_owned(),
            }],
        },
    );

    let error = evaluate(
        &plan.plan_path,
        &outcome.report_path,
        Some(&confirmation_path),
        &fixture.directory.path().join("evaluation.json"),
    )
    .unwrap_err();
    assert!(error
        .to_string()
        .contains("confirmation run/target mismatch"));
}

#[test]
fn source_changes_after_preparation_are_rejected_before_planning() {
    let fixture = fixture();
    let source = &fixture.prepared.targets[0].definition.entrypoint;
    fs::write(
        source,
        "template Changed() {}\ncomponent main = Changed();\n",
    )
    .unwrap();
    let error = create_plan(
        &fixture.prepared.report_path,
        RankingStrategy::PathOrder,
        &fixture.config_path,
        None,
        &fixture.directory.path().join("plan.json"),
    )
    .unwrap_err();
    assert!(error.to_string().contains("source changed"));
}

#[test]
fn snapshot_changes_after_planning_are_rejected_before_execution() {
    let fixture = fixture();
    let plan = plan(&fixture);
    fs::write(
        &plan.targets[0].run_entrypoint,
        "template Changed() {}\ncomponent main = Changed();\n",
    )
    .unwrap();
    let options = ExecuteOptions {
        zkfuzz_bin: fixture.directory.path().join("must-not-start"),
        budget_seconds: 2,
        total_budget_seconds: 5,
        zkfuzz_seed: None,
        mutation_settings: None,
        output: fixture.directory.path().join("executions"),
    };
    let error = execute_plan(&plan.plan_path, &options).unwrap_err();
    assert!(error.to_string().contains("source changed"));
    assert!(!options.output.exists());
}

#[test]
fn refreshing_snapshot_hashes_does_not_change_the_original_target_identity() {
    let mut fixture = fixture();
    let target = &mut fixture.prepared.targets[0];
    fs::write(
        target.run_entrypoint.as_ref().unwrap(),
        "template Foreign() {}\ncomponent main = Foreign();\n",
    )
    .unwrap();
    target.snapshot_fingerprints = fingerprint_sources(
        &target
            .snapshot_fingerprints
            .iter()
            .map(|value| value.path.clone())
            .collect::<Vec<_>>(),
    )
    .unwrap();
    write_json(&fixture.prepared.report_path, &fixture.prepared);
    let error = create_plan(
        &fixture.prepared.report_path,
        RankingStrategy::PathOrder,
        &fixture.config_path,
        None,
        &fixture.directory.path().join("plan.json"),
    )
    .unwrap_err();
    assert!(error.to_string().contains("snapshot"), "{error:#}");
}

#[test]
fn saved_plan_cannot_drop_eligible_targets() {
    let fixture = fixture();
    let mut plan = plan(&fixture);
    plan.targets.pop();
    write_json(&plan.plan_path, &plan);
    let options = ExecuteOptions {
        zkfuzz_bin: fixture.directory.path().join("must-not-start"),
        budget_seconds: 2,
        total_budget_seconds: 5,
        zkfuzz_seed: None,
        mutation_settings: None,
        output: fixture.directory.path().join("executions"),
    };
    let error = execute_plan(&plan.plan_path, &options).unwrap_err();
    assert!(error.to_string().contains("target set"), "{error:#}");
    assert!(!options.output.exists());
}

#[test]
fn saved_plan_scores_remain_bound_to_the_prepared_report() {
    let fixture = fixture();
    let mut plan = plan(&fixture);
    plan.targets[0].ranking.size = Some(9999);
    write_json(&plan.plan_path, &plan);
    let options = ExecuteOptions {
        zkfuzz_bin: fixture.directory.path().join("must-not-start"),
        budget_seconds: 2,
        total_budget_seconds: 5,
        zkfuzz_seed: None,
        mutation_settings: None,
        output: fixture.directory.path().join("executions"),
    };
    let error = execute_plan(&plan.plan_path, &options).unwrap_err();
    assert!(
        error.to_string().contains("frozen prepared corpus"),
        "{error:#}"
    );
    assert!(!options.output.exists());
}

#[test]
fn schema_two_plans_reject_a_changed_tie_summary() {
    let fixture = fixture();
    let mut plan = plan(&fixture);
    assert_eq!(plan.schema_version, 2);
    let mut ties = plan.ties.clone().expect("non-random plan records ties");
    ties.tie_group_count += 1;
    plan.ties = Some(ties);
    write_json(&plan.plan_path, &plan);
    let options = ExecuteOptions {
        zkfuzz_bin: fixture.directory.path().join("must-not-start"),
        budget_seconds: 2,
        total_budget_seconds: 5,
        zkfuzz_seed: None,
        mutation_settings: None,
        output: fixture.directory.path().join("executions"),
    };
    let error = execute_plan(&plan.plan_path, &options).unwrap_err();
    assert!(error.to_string().contains("tie summary"), "{error:#}");
    plan.ties = None;
    write_json(&plan.plan_path, &plan);
    let error = execute_plan(&plan.plan_path, &options).unwrap_err();
    assert!(error.to_string().contains("tie summary"), "{error:#}");
    assert!(!options.output.exists());
}

#[test]
fn schema_one_plans_without_ties_remain_valid_but_cannot_add_them() {
    let fixture = fixture();
    let mut plan = plan(&fixture);
    let ties = plan.ties.take();
    plan.schema_version = 1;
    let mut value = serde_json::to_value(&plan).unwrap();
    value.as_object_mut().unwrap().remove("ties");
    write_json(&plan.plan_path, &value);
    let options = ExecuteOptions {
        zkfuzz_bin: fixture.directory.path().join("must-not-start"),
        budget_seconds: 2,
        total_budget_seconds: 5,
        zkfuzz_seed: None,
        mutation_settings: None,
        output: fixture.directory.path().join("executions"),
    };
    // A legacy plan passes validation and fails only when the missing backend is started.
    let error = execute_plan(&plan.plan_path, &options).unwrap_err();
    assert!(
        error.to_string().contains("zkFuzz binary unavailable"),
        "{error:#}"
    );
    for stored in [
        serde_json::to_value(&ties).unwrap(),
        serde_json::Value::Null,
    ] {
        value
            .as_object_mut()
            .unwrap()
            .insert("ties".to_owned(), stored);
        write_json(&plan.plan_path, &value);
        let error = execute_plan(&plan.plan_path, &options).unwrap_err();
        assert!(
            error
                .to_string()
                .contains("schema 1 plan must not carry tie reporting"),
            "{error:#}"
        );
    }
}

#[test]
fn schema_two_random_plans_require_an_explicit_null_tie_summary() {
    let fixture = fixture();
    let plan = create_plan(
        &fixture.prepared.report_path,
        RankingStrategy::Random,
        &fixture.config_path,
        Some(77),
        &fixture.directory.path().join("random-plan.json"),
    )
    .unwrap();
    assert_eq!(plan.ties, None);
    let mut value: serde_json::Value =
        serde_json::from_slice(&fs::read(&plan.plan_path).unwrap()).unwrap();
    assert!(value.get("ties").is_some_and(serde_json::Value::is_null));
    value.as_object_mut().unwrap().remove("ties");
    write_json(&plan.plan_path, &value);
    let options = ExecuteOptions {
        zkfuzz_bin: fixture.directory.path().join("must-not-start"),
        budget_seconds: 2,
        total_budget_seconds: 5,
        zkfuzz_seed: None,
        mutation_settings: None,
        output: fixture.directory.path().join("executions"),
    };
    let error = execute_plan(&plan.plan_path, &options).unwrap_err();
    assert!(
        error.to_string().contains("missing its tie summary"),
        "{error:#}"
    );
}

#[test]
fn a_run_without_a_backend_candidate_cannot_be_confirmed() {
    let fixture = fixture();
    let plan = plan(&fixture);
    let outcome = execute(&fixture, &plan, false);
    let evidence = fixture.directory.path().join("review.txt");
    fs::write(&evidence, "Synthetic test evidence").unwrap();
    let run = &outcome.scheduler.runs[0];
    let confirmation_path = fixture.directory.path().join("confirmations.json");
    write_json(
        &confirmation_path,
        &ConfirmationSet {
            schema_version: 1,
            confirmations: vec![DefectConfirmation {
                run_id: run.result.run_id.clone(),
                target_id: run.target_id.clone(),
                root_cause_id: "synthetic-root".to_owned(),
                scope: ConfirmationScope::Project,
                evidence_origin: EvidenceOrigin::BackendExecution,
                original_component_review: None,
                evidence: vec![evidence],
                note: "Synthetic test only".to_owned(),
            }],
        },
    );
    let error = evaluate(
        &plan.plan_path,
        &outcome.report_path,
        Some(&confirmation_path),
        &fixture.directory.path().join("evaluation.json"),
    )
    .unwrap_err();
    assert!(error.to_string().contains("only backend BugFound runs"));
}

#[test]
fn stored_outcome_cannot_duplicate_a_run_to_inflate_evaluation_counts() {
    let fixture = fixture();
    let plan = plan(&fixture);
    let mut outcome = execute(&fixture, &plan, false);
    outcome
        .scheduler
        .runs
        .push(outcome.scheduler.runs[0].clone());
    write_json(&outcome.report_path, &outcome);
    let error = evaluate(
        &plan.plan_path,
        &outcome.report_path,
        None,
        &fixture.directory.path().join("evaluation.json"),
    )
    .unwrap_err();
    assert!(
        error.to_string().contains("duplicate target result"),
        "{error:#}"
    );
}

#[test]
#[ignore = "requires actual locally installed Circom, zkFuzz AST, and pinned Circomspect; no fuzz search"]
fn all_strategies_preserve_one_common_complete_target_set() {
    let fixture = fixture();
    let manifest_path = fixture.directory.path().join("manifest.json");
    let mut manifest: CorpusManifest =
        serde_json::from_slice(&fs::read(&manifest_path).unwrap()).unwrap();
    let mut unsupported = manifest.targets[0].clone();
    unsupported.label = "C-unsupported".to_owned();
    unsupported.template_name = "RootC".to_owned();
    unsupported.entrypoint = unsupported.project_root.join("C.circom");
    unsupported.known_defects.clear();
    fs::write(&unsupported.entrypoint, "template RootC() {\n component children[2];\n for (var i=0; i<2; i++) { children[i] = Leaf(); }\n}\ntemplate Leaf() {}\ncomponent main = RootC();\n").unwrap();
    manifest.targets.push(unsupported);
    write_json(&manifest_path, &manifest);
    let prepared = prepare_manifest(
        &manifest_path,
        &PrepareOptions::default(),
        &fixture.directory.path().join("real-common"),
    )
    .unwrap();
    let eligible = prepared
        .targets
        .iter()
        .filter(|target| target.eligible)
        .map(|target| target.target_id.clone())
        .collect::<BTreeSet<_>>();
    assert_eq!(
        eligible.len(),
        2,
        "{:?}",
        prepared
            .targets
            .iter()
            .map(|target| (&target.definition.label, &target.exclusion_reasons))
            .collect::<Vec<_>>()
    );
    assert!(!prepared.targets[2].eligible);
    write_json(
        &fixture.config_path,
        &StaticRankingConfig {
            schema_version: 1,
            complexity_groups: Some(ComplexityGroups {
                metric: STRUCTURAL_METRIC.to_owned(),
                upper_bounds: vec![0],
                group_order: vec![0, 1],
                provenance:
                    "Synthetic test boundary only; not a selected empirical research configuration."
                        .to_owned(),
            }),
        },
    );
    for strategy in [
        RankingStrategy::PathOrder,
        RankingStrategy::Random,
        RankingStrategy::SmallFirst,
        RankingStrategy::Legacy,
        RankingStrategy::WarningFirst,
        RankingStrategy::RiskOnly,
        RankingStrategy::RiskGrouped,
        RankingStrategy::CostAware,
    ] {
        let seed = (strategy == RankingStrategy::Random).then_some(77);
        let plan = create_plan(
            &prepared.report_path,
            strategy,
            &fixture.config_path,
            seed,
            &fixture
                .directory
                .path()
                .join(format!("{strategy}-plan.json")),
        )
        .unwrap();
        assert_eq!(plan.comparison_target_set, "common-complete-feature-set");
        assert_eq!(
            plan.targets
                .iter()
                .map(|target| target.target_id.clone())
                .collect::<BTreeSet<_>>(),
            eligible
        );
        assert_eq!(plan.exclusions.len(), 1);
        assert_eq!(plan.exclusions[0].label, "C-unsupported");
        assert_eq!(plan.ties.is_none(), strategy == RankingStrategy::Random);
    }
}
