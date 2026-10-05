//! Value-free metadata only. Review states are imported claims, never new verdicts.
use std::{collections::BTreeMap, path::PathBuf};

use serde::{Deserialize, Serialize};

use crate::candidate_review::schema::{BackendReview, FileRef, ReviewReport};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(tag = "state", rename_all = "kebab-case", deny_unknown_fields)]
pub enum Recorded<T> {
    Known { value: T },
    Unknown { reason: String },
}

impl<T> Recorded<T> {
    pub fn known(value: T) -> Self {
        Self::Known { value }
    }

    pub fn unknown(reason: impl Into<String>) -> Self {
        Self::Unknown {
            reason: reason.into(),
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum Method {
    Whole,
    Split,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Context {
    pub execution_unit_id: String,
    pub method: Method,
    pub repetition: Recorded<String>,
    pub project: Recorded<String>,
    pub source_version: Recorded<String>,
    pub entrypoint: Recorded<PathBuf>,
    pub settings_sha256: Recorded<String>,
    pub tool_versions: BTreeMap<String, Recorded<String>>,
}

/// Research policy intent, deliberately separate from the historical observation.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PolicyIntent {
    pub design: PolicyDesign,
    pub unit_wall_budget_seconds: Recorded<f64>,
    pub attempt_wall_limit_seconds: Recorded<f64>,
    pub cpu_limit: Recorded<String>,
    pub memory_limit_bytes: Recorded<u64>,
    pub seed_order_ref: Recorded<String>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum PolicyDesign {
    A,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "format", rename_all = "kebab-case", deny_unknown_fields)]
pub enum MetadataSource {
    RunnerResult {
        file: FileRef,
        target_id: String,
    },
    ExperimentOutcome {
        file: FileRef,
        run_id: String,
    },
    P2Ledger {
        file: FileRef,
        execution_index: usize,
    },
}

impl MetadataSource {
    pub fn file(&self) -> &FileRef {
        match self {
            Self::RunnerResult { file, .. }
            | Self::ExperimentOutcome { file, .. }
            | Self::P2Ledger { file, .. } => file,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ImportRequest {
    pub schema_version: u32,
    pub record_id: String,
    pub context: Context,
    pub policy_intent: PolicyIntent,
    pub source: MetadataSource,
    /// Hash-pinned, value-free existing review reports; no engine is invoked.
    pub review_reports: Vec<FileRef>,
    /// Explicit value-free claims for review dimensions absent from legacy reports.
    pub review_observations: Vec<ReviewObservation>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub aggregation_metadata: Option<super::aggregate_schema::RecordAggregationMetadata>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum ReviewState {
    ReportedConfirmed,
    Rejected,
    Unresolved,
    NotAttempted,
    Interrupted,
    Error,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Assessment {
    pub state: ReviewState,
    pub reason: String,
    pub evidence: Vec<FileRef>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum AttributionState {
    Matched,
    NotMatched,
    Unknown,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Attribution {
    pub state: AttributionState,
    pub method: Recorded<String>,
    /// A proposed ID is retained even when attribution failed; it is not a count.
    pub proposed_cause_id: Recorded<String>,
    pub reason: String,
    pub evidence: Vec<FileRef>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum Completion {
    NotStarted,
    InProgress,
    Complete,
    Incomplete,
    Interrupted,
    Failed,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum ComponentLayer {
    General,
    Contract,
    LegacyUnspecified,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "state", rename_all = "kebab-case", deny_unknown_fields)]
pub enum Localization {
    Localized {
        instance_key: String,
        evidence: Vec<FileRef>,
    },
    Root {
        evidence: Vec<FileRef>,
    },
    Multi {
        instance_keys: Vec<String>,
        reason: String,
    },
    Failed {
        reason: String,
    },
    NotAttempted {
        reason: String,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "state", rename_all = "kebab-case", deny_unknown_fields)]
pub enum CauseDeduplication {
    Canonical,
    DuplicateOf { cause_id: String },
    Unresolved { reason: String },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReviewObservation {
    pub observation_id: String,
    pub run_id: String,
    pub target_id: String,
    pub candidate: FileRef,
    pub candidate_record_id: Recorded<String>,
    pub component_layer: ComponentLayer,
    pub localization: Localization,
    pub cause_deduplication: CauseDeduplication,
    pub component: Assessment,
    pub entrypoint_tcct: Assessment,
    pub projection: Assessment,
    pub attribution: Attribution,
    pub completion: Completion,
    pub completion_reason: String,
    pub automated_review_seconds: Recorded<f64>,
    pub human_review_seconds: Recorded<f64>,
    /// Metadata link only; duplicates remain present rather than being discarded.
    pub duplicate_of: Recorded<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TimingObservation {
    pub seconds: Recorded<f64>,
    pub meaning: String,
    pub origin: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionObservation {
    pub campaign_id: Recorded<String>,
    pub attempt_index: Recorded<u64>,
    pub source_plan_index: Recorded<u64>,
    pub round_index: Recorded<u64>,
    pub seed: Recorded<u64>,
    pub ranking_seed: Recorded<u64>,
    pub instance_key: Recorded<String>,
    pub source_versions: BTreeMap<String, Recorded<String>>,
    pub run_id: Recorded<String>,
    pub target_id: Recorded<String>,
    pub source_repetition: Recorded<String>,
    pub source_method: Recorded<String>,
    pub started_at: Recorded<String>,
    pub finished_at: Recorded<String>,
    pub allocated_attempt_seconds: Recorded<f64>,
    pub allocated_campaign_seconds: Recorded<f64>,
    pub execution_limit_seconds: Recorded<f64>,
    pub actual_wall_seconds: Recorded<f64>,
    pub actual_cpu_seconds: Recorded<f64>,
    pub peak_memory_bytes: Recorded<u64>,
    pub idle_seconds: Recorded<f64>,
    pub remaining_budget_seconds: Recorded<f64>,
    pub remaining_at_attempt_start_seconds: Recorded<f64>,
    pub backend_status: Recorded<String>,
    pub termination_reason: Recorded<String>,
    pub campaign_termination_reason: Recorded<String>,
    pub exit_code: Recorded<i64>,
    pub candidate_times: Vec<TimingObservation>,
    pub process_start_offset: TimingObservation,
    pub exact_candidate_time: Recorded<f64>,
    pub candidates: Vec<FileRef>,
    pub candidate_inventory: Recorded<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ImportedReview {
    pub source_report: Recorded<FileRef>,
    pub metadata_binding: Recorded<bool>,
    pub observation: ReviewObservation,
    /// Preserves original scope, criterion details, and engine claims unchanged.
    pub legacy_review: Option<BackendReview>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PreservedReport {
    pub file: FileRef,
    /// Includes inventory, errors, unreviewed candidates and report interruption.
    pub report: ReviewReport,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EvidenceRecord {
    pub schema_version: u32,
    pub record_id: String,
    pub request: FileRef,
    pub source: MetadataSource,
    pub context: Context,
    pub policy_intent: PolicyIntent,
    pub policy_rules: Vec<String>,
    pub policy_execution_verified: Recorded<bool>,
    pub execution: ExecutionObservation,
    pub reviews: Vec<ImportedReview>,
    pub preserved_review_reports: Vec<PreservedReport>,
    /// Reported cause -> all matching observation IDs; no global performance count.
    pub component_cause_links: BTreeMap<String, Vec<String>>,
    pub aggregation_issues: BTreeMap<String, String>,
    pub limitations: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub aggregation_metadata: Option<super::aggregate_schema::RecordAggregationMetadata>,
}
