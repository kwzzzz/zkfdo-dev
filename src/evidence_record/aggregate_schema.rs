//! Versioned, value-free declarations and results for offline aggregation.
use serde::{Deserialize, Serialize};

use super::schema::{Method, Recorded};
use crate::candidate_review::schema::FileRef;

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "kebab-case")]
pub enum Layer {
    ComponentGeneral,
    ComponentContract,
    LegacyUnspecified,
    EntrypointTcct,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Coverage {
    pub complete: bool,
    pub reason: String,
    pub evidence: Vec<FileRef>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReviewCoverage {
    pub layer: Layer,
    /// Complete inventory of expected review rows, not a declaration of positive outcomes.
    pub expected_observation_ids: Vec<String>,
    pub coverage: Coverage,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "kebab-case")]
pub enum TimeBasis {
    ExactGeneration,
    CompletionUpperBound,
    LogObservation,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CandidateTime {
    pub candidate_sha256: String,
    pub run_id: String,
    pub target_id: String,
    pub campaign_id: String,
    /// Identity of the clock/reference frame, not just a unit such as seconds.
    pub clock_id: String,
    pub origin: String,
    pub basis: TimeBasis,
    pub basis_verified: bool,
    pub seconds: f64,
    pub evidence: Vec<FileRef>,
}

/// Optional only for v1 readers; required by the v2 record writer.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RecordAggregationMetadata {
    pub candidate_inventory: Coverage,
    pub review_inventory: Vec<ReviewCoverage>,
    pub candidate_times: Vec<CandidateTime>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub review_semantics: Vec<ReviewSemantics>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReviewSemantics {
    pub observation_id: String,
    pub violation_kind: Recorded<ViolationKind>,
    pub violation_evidence: Vec<FileRef>,
    pub localization_method: Recorded<String>,
    pub localization_method_validated: Recorded<bool>,
    pub localization_evidence: Vec<FileRef>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum ViolationKind {
    OutputDifference,
    ComputationAbort,
    ToolSpecificCheck,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(deny_unknown_fields)]
pub struct ReviewRef {
    pub record_id: String,
    pub observation_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CauseRegistration {
    pub scope_id: String,
    pub cause_id: String,
    pub execution_unit_ids: Vec<String>,
    pub source_versions: Vec<String>,
    pub members: Vec<ReviewRef>,
    pub evidence: Vec<FileRef>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CampaignCoverage {
    pub execution_unit_id: String,
    pub method: Method,
    pub campaign_id: String,
    pub repetition: String,
    /// All record IDs expected for this campaign and method, not a success subset.
    pub record_ids: Vec<String>,
    pub coverage: Coverage,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AggregateRequest {
    pub schema_version: u32,
    pub records: Vec<FileRef>,
    pub campaigns: Vec<CampaignCoverage>,
    pub cause_registry: Vec<CauseRegistration>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum UnitState {
    ConfirmedAttributed,
    ConfirmedUnattributedOnly,
    NotConfirmedComplete,
    NoCandidate,
    UnknownIncomplete,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Issue {
    pub code: String,
    pub record_ids: Vec<String>,
    pub reason: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Occurrence {
    pub record_id: String,
    pub candidate_sha256: String,
    pub review_refs: Vec<ReviewRef>,
    pub confirmed: bool,
    pub attributed: bool,
    pub unresolved: bool,
    pub reasons: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RegisteredCause {
    pub layer: Layer,
    pub scope_id: String,
    pub cause_id: String,
    pub members: Vec<ReviewRef>,
    pub evidence: Vec<FileRef>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum TimeResultKind {
    ExactFirst,
    CompletionUpperBound,
    ObservedMinimum,
    Unavailable,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TimeSeries {
    pub campaign_id: String,
    pub clock_id: String,
    pub origin: String,
    pub basis: TimeBasis,
    pub kind: TimeResultKind,
    pub seconds: f64,
    pub candidate_refs: Vec<OccurrenceRef>,
    pub blockers: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
pub struct OccurrenceRef {
    pub record_id: String,
    pub candidate_sha256: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TimeSummary {
    pub kind: TimeResultKind,
    pub seconds: Recorded<f64>,
    pub reason: String,
    pub series: Vec<TimeSeries>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AggregateGroup {
    pub group_id: String,
    pub execution_unit_id: String,
    pub method: Method,
    pub campaign_id: Recorded<String>,
    pub repetition: Recorded<String>,
    pub layer: Layer,
    pub record_ids: Vec<String>,
    pub state: UnitState,
    pub confirmation_exists: bool,
    pub attributed_confirmation_exists: bool,
    pub candidate_inventory_complete: bool,
    pub campaign_inventory_complete: bool,
    pub review_inventory_complete: bool,
    pub review_results_complete: bool,
    pub cause_count_complete: bool,
    pub distinct_cause_count: Recorded<usize>,
    pub registered_causes: Vec<RegisteredCause>,
    pub confirmed_unattributed: Vec<OccurrenceRef>,
    pub unresolved_occurrences: Vec<OccurrenceRef>,
    pub occurrences: Vec<Occurrence>,
    pub time: TimeSummary,
    pub reasons: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AggregateReport {
    pub schema_version: u32,
    pub request: FileRef,
    pub inputs: Vec<FileRef>,
    pub groups: Vec<AggregateGroup>,
    pub conflicts: Vec<Issue>,
    /// One row per input record; resource measurements are never silently summed.
    pub record_contexts: Vec<RecordContext>,
    /// Scoped keys only; members remain qualified by record and observation.
    pub registered_causes: Vec<RegisteredCause>,
    pub limitations: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RecordContext {
    pub record_id: String,
    pub input_record: FileRef,
    pub original_request: FileRef,
    pub source: super::schema::MetadataSource,
    pub context: super::schema::Context,
    pub policy_intent: super::schema::PolicyIntent,
    pub execution: super::schema::ExecutionObservation,
    pub actual_wall_scope: Recorded<String>,
    pub review_semantics: Vec<ReviewSemantics>,
}
