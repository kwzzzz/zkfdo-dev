use std::{collections::BTreeMap, path::PathBuf};

use serde::{Deserialize, Deserializer, Serialize};
use serde_json::Value;

use crate::experiment::ConfirmationScope;

fn required_option<'de, D, T>(deserializer: D) -> Result<Option<T>, D::Error>
where
    D: Deserializer<'de>,
    T: Deserialize<'de>,
{
    Option::<T>::deserialize(deserializer)
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct FileRef {
    pub path: PathBuf,
    pub sha256: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct DirectoryManifest {
    pub schema_version: u32,
    pub files: Vec<ManifestFile>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ManifestFile {
    pub path: PathBuf,
    pub size: u64,
    pub sha256: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct SpecRef {
    pub id: String,
    pub path: PathBuf,
    pub sha256: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReviewSpec {
    pub schema_version: u32,
    pub review_spec_id: String,
    pub root_cause_id: String,
    pub subject_kind: SubjectKind,
    pub expected_scope: ConfirmationScope,
    pub target_binding: TargetBinding,
    pub field: FieldSpec,
    pub compiled_subject: CompiledSubject,
    pub compiler: CompilerSpec,
    pub contract: ContractSpec,
    pub attribution: AttributionSpec,
    pub production_reachability: ProductionReachability,
    #[serde(deserialize_with = "required_option")]
    pub injection_ground_truth: Option<InjectionGroundTruth>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum SubjectKind {
    PublishedVulnerableSource,
    InjectedMutant,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TargetBinding {
    pub target_id: String,
    #[serde(deserialize_with = "required_option")]
    pub instance_key: Option<String>,
    pub template: String,
    pub concrete_parameters: Vec<ConcreteParameter>,
    pub source_path: PathBuf,
    pub source_sha256: String,
    pub source_closure_manifest_path: PathBuf,
    pub source_closure_manifest_sha256: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(deny_unknown_fields)]
pub struct ConcreteParameter {
    pub position: usize,
    pub name: String,
    pub kind: ParameterKind,
    pub value_decimal: String,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "kebab-case")]
pub enum ParameterKind {
    Integer,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FieldSpec {
    pub name: String,
    pub modulus_decimal: String,
    pub assignment_encoding: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CompiledSubject {
    pub r1cs_path: PathBuf,
    pub r1cs_sha256: String,
    pub sym_path: PathBuf,
    pub sym_sha256: String,
    pub expected_shape: R1csShape,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct R1csShape {
    pub wires: usize,
    pub labels: u64,
    pub public_outputs: usize,
    pub public_inputs: usize,
    pub private_inputs: usize,
    pub constraints: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CompilerSpec {
    pub version: String,
    pub binary_sha256: String,
    pub arguments: Vec<String>,
    pub library_manifest_path: PathBuf,
    pub library_manifest_sha256: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ContractSpec {
    pub definition_path: PathBuf,
    pub definition_sha256: String,
    pub input_contract_id: String,
    pub property_id: String,
    pub input_contract_statement: String,
    pub property_statement: String,
    pub input_signal_names: Vec<String>,
    pub property_signal_names: Vec<String>,
    pub predicate: PredicateSpec,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PredicateSpec {
    pub api_version: u32,
    pub path: PathBuf,
    pub sha256: String,
    pub entrypoint: String,
    pub config: Value,
    pub allowed_results: Vec<AllowedPredicateResult>,
    pub allowed_violation_classes: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct AllowedPredicateResult {
    pub criterion: PredicateCriterion,
    pub verdict: CriterionVerdict,
    pub reason_code: String,
    pub note: String,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "snake_case")]
pub enum PredicateCriterion {
    InputPreconditions,
    SpecifiedPropertyViolation,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "kebab-case")]
pub enum CriterionVerdict {
    Satisfied,
    NotSatisfied,
    Unknown,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AttributionSpec {
    pub method: AttributionMethod,
    pub evidence_path: PathBuf,
    pub evidence_sha256: String,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum AttributionMethod {
    KnownDefectSingleTarget,
    InjectionSingleDiff,
    Unattributed,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProductionReachability {
    pub verdict: ReachabilityVerdict,
    #[serde(deserialize_with = "required_option")]
    pub entrypoint_target_id: Option<String>,
    #[serde(deserialize_with = "required_option")]
    pub instance_key: Option<String>,
    #[serde(deserialize_with = "required_option")]
    pub evidence_path: Option<PathBuf>,
    #[serde(deserialize_with = "required_option")]
    pub evidence_sha256: Option<String>,
    #[serde(deserialize_with = "required_option")]
    pub verifier_manifest_path: Option<PathBuf>,
    #[serde(deserialize_with = "required_option")]
    pub verifier_manifest_sha256: Option<String>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum ReachabilityVerdict {
    Satisfied,
    NotSatisfied,
    Unknown,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct InjectionGroundTruth {
    pub injection_id: String,
    pub operator_id: String,
    pub source_location: SourceLocation,
    pub clean_revision: String,
    pub single_diff: FileRef,
    pub source_closures: SourceClosures,
    pub compiled_variants: CompiledVariants,
    pub compilation_manifest: FileRef,
    pub projection_manifest: FileRef,
    pub expected_clean_constraint_indices: Vec<usize>,
    pub clean_relation_exclusion: CleanRelationExclusion,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SourceLocation {
    pub path: PathBuf,
    pub source_sha256: String,
    pub start_byte: usize,
    pub end_byte: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SourceClosures {
    pub clean: FileRef,
    pub mutant: FileRef,
    pub disturbance_twin: FileRef,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CompiledVariants {
    pub clean: CompiledVariant,
    pub mutant: CompiledVariant,
    pub disturbance_twin: CompiledVariant,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CompiledVariant {
    pub r1cs_path: PathBuf,
    pub r1cs_sha256: String,
    pub sym_path: PathBuf,
    pub sym_sha256: String,
    pub shape: R1csShape,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CompilationReproductionManifest {
    pub schema_version: u32,
    pub compiler: CompilationCompiler,
    pub variants: CompilationReproductionVariants,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CompilationCompiler {
    pub version: String,
    pub runner_path: PathBuf,
    pub runner_sha256: String,
    pub artifact_manifest_path: PathBuf,
    pub artifact_manifest_sha256: String,
    pub arguments: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CompilationReproductionVariants {
    pub clean: CompilationReproductionVariant,
    pub mutant: CompilationReproductionVariant,
    pub disturbance_twin: CompilationReproductionVariant,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CompilationReproductionVariant {
    pub source_closure_manifest_path: PathBuf,
    pub source_closure_manifest_sha256: String,
    pub entrypoint_path: PathBuf,
    pub r1cs_output_path: PathBuf,
    pub sym_output_path: PathBuf,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CleanRelationExclusion {
    pub method: RelationExclusionMethod,
    pub certificate_path: PathBuf,
    pub certificate_sha256: String,
    pub verifier_manifest_path: PathBuf,
    pub verifier_manifest_sha256: String,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum RelationExclusionMethod {
    FullyFixedConstraint,
    OperatorProof,
    SolverUnsatCertificate,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum ReviewRequest {
    #[serde(rename = "backend-candidates")]
    Backend(BackendRequest),
    #[serde(rename = "injection-ground-truth")]
    Injection(InjectionRequest),
}

impl ReviewRequest {
    pub fn schema_version(&self) -> u32 {
        match self {
            Self::Backend(request) => request.schema_version,
            Self::Injection(request) => request.schema_version,
        }
    }

    pub fn request_id(&self) -> &str {
        match self {
            Self::Backend(request) => &request.request_id,
            Self::Injection(request) => &request.request_id,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BackendRequest {
    pub schema_version: u32,
    pub request_id: String,
    pub review_specs: Vec<FileRef>,
    pub executions: Vec<BackendExecutionRequest>,
    pub candidate_adapter: CandidateAdapterRef,
    pub candidate_policy: String,
    pub unmatched_candidate_policy: String,
    pub qualification_bundles: Vec<QualificationBundleRef>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BackendExecutionRequest {
    pub execution_id: String,
    #[serde(deserialize_with = "required_option")]
    pub campaign_coordinates: Option<CampaignCoordinates>,
    pub plan: FileRef,
    pub outcome: FileRef,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct CampaignCoordinates {
    pub block: usize,
    pub strategy: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CandidateAdapterRef {
    pub id: String,
    pub implementation_sha256: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct QualificationBundleRef {
    pub injection_id: String,
    pub path: PathBuf,
    pub sha256: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct InjectionRequest {
    pub schema_version: u32,
    pub request_id: String,
    pub review_spec: FileRef,
    pub generation_manifest: FileRef,
    pub disturbance_assignment: AssignmentRef,
    pub clean_reference_assignment: AssignmentRef,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AssignmentRef {
    pub origin: AssignmentOrigin,
    pub format: AssignmentFormat,
    pub path: PathBuf,
    pub sha256: String,
    pub adapter_implementation_sha256: String,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum AssignmentOrigin {
    DisturbanceTwin,
    CleanWitnessGenerator,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum AssignmentFormat {
    ZkfuzzAssignmentV1,
    WtnsJsonV1,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GenerationManifest {
    pub schema_version: u32,
    pub common_input: FileRef,
    pub generators: Generators,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Generators {
    pub clean: GeneratorSpec,
    pub disturbance_twin: GeneratorSpec,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GeneratorSpec {
    pub runner_path: PathBuf,
    pub runner_sha256: String,
    pub artifact_manifest_path: PathBuf,
    pub artifact_manifest_sha256: String,
    pub arguments: Vec<String>,
    pub witness_path: PathBuf,
    pub witness_sha256: String,
    pub assignment_path: PathBuf,
    pub assignment_sha256: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProjectionManifest {
    pub schema_version: u32,
    pub operator_id: String,
    pub operator_justification: String,
    pub mappings: Vec<ProjectionMapping>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProjectionMapping {
    pub clean_wire_index: usize,
    pub clean_signal_names: Vec<String>,
    pub source_kind: ProjectionSourceKind,
    #[serde(deserialize_with = "required_option")]
    pub source_signal_name: Option<String>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum ProjectionSourceKind {
    DisturbanceSignal,
    CleanReferenceWire,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RelationVerifierManifest {
    pub schema_version: u32,
    pub api_version: u32,
    pub verifier_id: String,
    pub method: RelationExclusionMethod,
    pub implementation: VerifierImplementation,
    pub certificate_format: String,
    pub allowed_results: Vec<AllowedVerifierResult>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct VerifierImplementation {
    pub kind: VerifierImplementationKind,
    #[serde(deserialize_with = "required_option")]
    pub executable_path: Option<PathBuf>,
    #[serde(deserialize_with = "required_option")]
    pub executable_sha256: Option<String>,
    pub source_manifest_path: PathBuf,
    pub source_manifest_sha256: String,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum VerifierImplementationKind {
    EngineBuiltin,
    External,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct AllowedVerifierResult {
    pub verdict: CriterionVerdict,
    pub reason_code: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FullyFixedConstraintCertificate {
    pub schema_version: u32,
    pub method: RelationExclusionMethod,
    pub clean_constraint_indices: Vec<usize>,
    pub fixed_signal_names: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct VerifierResult {
    pub schema_version: u32,
    pub method: RelationExclusionMethod,
    pub verdict: CriterionVerdict,
    pub reason_code: String,
    pub checked_clean_constraint_indices: Vec<usize>,
    pub fixed_signal_names: Vec<String>,
    pub certificate_sha256: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReachabilityEvidence {
    pub schema_version: u32,
    pub completion: ReachabilityCompletion,
    pub entrypoint_target_id: String,
    pub entrypoint_source_sha256: String,
    pub source_closure_sha256: String,
    pub target_instance_key: String,
    pub instances: Vec<ReachabilityInstance>,
    pub unsupported: Vec<ReachabilityIssue>,
    pub unresolved: Vec<ReachabilityIssue>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum ReachabilityCompletion {
    Complete,
    Incomplete,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReachabilityInstance {
    pub instance_key: String,
    #[serde(deserialize_with = "required_option")]
    pub parent_instance_key: Option<String>,
    pub target_id: String,
    pub template: String,
    pub concrete_parameters: Vec<ConcreteParameter>,
    pub source_path: PathBuf,
    pub source_sha256: String,
    pub start_byte: usize,
    pub end_byte: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReachabilityIssue {
    pub reason_code: String,
    #[serde(deserialize_with = "required_option")]
    pub source_path: Option<PathBuf>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReachabilityVerifierManifest {
    pub schema_version: u32,
    pub verifier_id: String,
    pub source_manifest_path: PathBuf,
    pub source_manifest_sha256: String,
    pub discovery_report_path: PathBuf,
    pub discovery_report_sha256: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Criterion {
    pub verdict: CriterionVerdict,
    pub reason_code: String,
    pub evidence: Vec<FileRef>,
    pub note: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CommonCriteria {
    #[serde(deserialize_with = "required_option")]
    pub assignment_encoding: Option<Criterion>,
    #[serde(deserialize_with = "required_option")]
    pub input_preconditions: Option<Criterion>,
    #[serde(deserialize_with = "required_option")]
    pub fixed_target_constraints: Option<Criterion>,
    #[serde(deserialize_with = "required_option")]
    pub specified_property_violation: Option<Criterion>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct QualificationCriteria {
    #[serde(deserialize_with = "required_option")]
    pub twin_r1cs_identity: Option<Criterion>,
    #[serde(deserialize_with = "required_option")]
    pub twin_sym_identity: Option<Criterion>,
    #[serde(deserialize_with = "required_option")]
    pub generation_reproducibility: Option<Criterion>,
    #[serde(deserialize_with = "required_option")]
    pub clean_reference_assignment_encoding: Option<Criterion>,
    #[serde(deserialize_with = "required_option")]
    pub clean_reference_constraints: Option<Criterion>,
    #[serde(deserialize_with = "required_option")]
    pub clean_input_equivalence: Option<Criterion>,
    #[serde(deserialize_with = "required_option")]
    pub clean_rejection: Option<Criterion>,
    #[serde(deserialize_with = "required_option")]
    pub clean_relation_exclusion: Option<Criterion>,
    #[serde(deserialize_with = "required_option")]
    pub production_reachability: Option<Criterion>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct CauseAttribution {
    pub verdict: AttributionVerdict,
    pub reason_code: String,
    pub evidence: Vec<FileRef>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum AttributionVerdict {
    Matched,
    NotMatched,
    Unknown,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum Disposition {
    Validated,
    Rejected,
    Unresolved,
    ReviewError,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum GroundTruthQualification {
    Qualified,
    Rejected,
    Unresolved,
    ReviewError,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CandidateInventory {
    pub outcome_candidate_count: usize,
    pub matched_candidate_count: usize,
    pub unmatched_candidate_count: usize,
    pub candidate_error_count: usize,
    pub review_pair_count: usize,
    pub terminal_review_pair_count: usize,
    pub complete: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionRecord {
    pub execution_id: String,
    pub plan_index: usize,
    #[serde(deserialize_with = "required_option")]
    pub run_id: Option<String>,
    pub target_id: String,
    pub backend_status: String,
    pub candidate_count: usize,
    pub candidate_status: CandidateStatus,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum CandidateStatus {
    CandidatePresent,
    NoCandidate,
    NotApplicable,
    EvidenceError,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CandidateError {
    pub candidate_record_id: String,
    pub execution_id: String,
    pub target_id: String,
    pub path: PathBuf,
    pub expected_sha256: String,
    #[serde(deserialize_with = "required_option")]
    pub observed_sha256: Option<String>,
    pub reason_code: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct UnreviewedCandidate {
    pub candidate_record_id: String,
    pub candidate: FileRef,
    pub execution_id: String,
    pub run_id: String,
    pub target_id: String,
    pub reason_code: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CandidateBinding {
    pub execution_id: String,
    pub plan_index: usize,
    pub run_id: String,
    pub target_id: String,
    pub candidate_hash_verified: bool,
    pub candidate_metadata_verified: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BackendArtifactVerification {
    pub r1cs_sha256_verified: bool,
    pub sym_sha256_verified: bool,
    pub assignment_complete: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct InjectionArtifactVerification {
    pub mutant_r1cs: bool,
    pub mutant_sym: bool,
    pub clean_r1cs: bool,
    pub clean_sym: bool,
    pub twin_r1cs: bool,
    pub twin_sym: bool,
    pub generation_reproduced: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AssignmentLinks {
    pub disturbance: FileRef,
    pub clean_reference: FileRef,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "review_kind")]
pub enum ReviewRecord {
    #[serde(rename = "backend-candidate")]
    Backend(Box<BackendReview>),
    #[serde(rename = "injection-ground-truth")]
    Injection(Box<InjectionReview>),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BackendReview {
    pub candidate_record_id: String,
    pub candidate: FileRef,
    pub binding: CandidateBinding,
    pub review_spec: SpecRef,
    pub root_cause_id: String,
    pub expected_scope: ConfirmationScope,
    pub artifact_verification: BackendArtifactVerification,
    pub failed_target_constraint_count: usize,
    pub failed_target_constraint_indices: Vec<usize>,
    pub criteria: CommonCriteria,
    pub disposition: Disposition,
    pub cause_attribution: CauseAttribution,
    #[serde(deserialize_with = "required_option")]
    pub ground_truth_qualification: Option<GroundTruthQualification>,
    #[serde(deserialize_with = "required_option")]
    pub violation_class: Option<String>,
    pub confirmation_eligible: bool,
    pub automated_review_seconds: f64,
    pub predicate_stream_nonempty: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct InjectionReview {
    #[serde(deserialize_with = "required_option")]
    pub candidate_record_id: Option<String>,
    #[serde(deserialize_with = "required_option")]
    pub candidate: Option<FileRef>,
    #[serde(deserialize_with = "required_option")]
    pub binding: Option<CandidateBinding>,
    pub assignments: AssignmentLinks,
    pub review_spec: SpecRef,
    pub root_cause_id: String,
    pub injection_id: String,
    pub artifact_verification: InjectionArtifactVerification,
    pub failed_target_constraint_count: usize,
    pub failed_target_constraint_indices: Vec<usize>,
    pub failed_clean_constraint_count: usize,
    pub failed_clean_constraint_indices: Vec<usize>,
    pub criteria: CommonCriteria,
    pub qualification_criteria: QualificationCriteria,
    pub disposition: Disposition,
    pub cause_attribution: CauseAttribution,
    pub ground_truth_qualification: GroundTruthQualification,
    #[serde(deserialize_with = "required_option")]
    pub violation_class: Option<String>,
    pub confirmation_eligible: bool,
    pub automated_review_seconds: f64,
    pub predicate_stream_nonempty: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EngineProvenance {
    pub version: String,
    pub source_revision: String,
    pub source_manifest_path: PathBuf,
    pub source_manifest_sha256: String,
    pub executable_path: PathBuf,
    pub executable_sha256: String,
    pub predicate_runner_path: PathBuf,
    pub predicate_runner_sha256: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct AdapterProvenance {
    pub id: String,
    pub implementation_sha256: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReportFailure {
    pub stage: String,
    pub reason_code: String,
    pub evidence: Vec<FileRef>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BackendSummary {
    pub validated: usize,
    pub rejected: usize,
    pub unresolved: usize,
    pub review_error: usize,
    pub unreviewed_candidates: usize,
    pub attributed_validated: usize,
    pub unique_validated_root_causes: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct InjectionSummary {
    pub validated: usize,
    pub rejected: usize,
    pub unresolved: usize,
    pub review_error: usize,
    pub qualified: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum ReviewSummary {
    Backend(BackendSummary),
    Injection(InjectionSummary),
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum ReportStatus {
    Complete,
    Incomplete,
    Failed,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum ReportKind {
    BackendCandidates,
    InjectionGroundTruth,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReviewReport {
    pub schema_version: u32,
    pub report_id: String,
    pub kind: ReportKind,
    pub status: ReportStatus,
    pub review_request: FileRef,
    pub review_specs: Vec<FileRef>,
    pub engine: EngineProvenance,
    pub adapters: Vec<AdapterProvenance>,
    #[serde(deserialize_with = "required_option")]
    pub failure: Option<ReportFailure>,
    #[serde(deserialize_with = "required_option")]
    pub candidate_inventory: Option<CandidateInventory>,
    pub executions: Vec<ExecutionRecord>,
    pub candidate_errors: Vec<CandidateError>,
    pub unreviewed_candidates: Vec<UnreviewedCandidate>,
    pub reviews: Vec<ReviewRecord>,
    pub summary: ReviewSummary,
    pub semantic_result_sha256: String,
    pub raw_values_persisted: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BackendBundleIndex {
    pub schema_version: u32,
    pub kind: String,
    pub review_specs: Vec<FileRef>,
    pub review_request: FileRef,
    pub review_report: FileRef,
    pub execution_evaluations: Vec<ExecutionEvaluation>,
    pub campaign_summary: CampaignSummary,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionEvaluation {
    pub execution_id: String,
    pub confirmation: FileRef,
    pub evaluator_output: FileRef,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CampaignSummary {
    pub pair_count: usize,
    pub by_execution: Vec<ExecutionCampaignSummary>,
    pub unique_validated_root_cause_ids: Vec<String>,
    pub unique_validated_root_cause_count: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionCampaignSummary {
    pub execution_id: String,
    #[serde(deserialize_with = "required_option")]
    pub campaign_coordinates: Option<CampaignCoordinates>,
    pub validated_attributed_root_cause_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GroundTruthBundleIndex {
    pub schema_version: u32,
    pub kind: String,
    pub injection_id: String,
    pub review_spec: FileRef,
    pub review_request: FileRef,
    pub review_report: FileRef,
    pub qualification: GroundTruthQualification,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PredicateContext {
    pub schema_version: u32,
    pub field_modulus_decimal: String,
    pub wire_signals: BTreeMap<String, String>,
    pub eliminated_signals: BTreeMap<String, String>,
    pub parameters: BTreeMap<String, TypedParameterValue>,
    pub predicate_config: Value,
    pub request_kind: ReportKind,
    #[serde(deserialize_with = "required_option")]
    pub injection_id: Option<String>,
    #[serde(deserialize_with = "required_option")]
    pub clean_reference_signals: Option<BTreeMap<String, String>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TypedParameterValue {
    pub kind: ParameterKind,
    pub value_decimal: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PredicateOutput {
    pub input_preconditions: PredicateResult,
    pub specified_property_violation: PredicateResult,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct PredicateResult {
    pub verdict: CriterionVerdict,
    pub reason_code: String,
    #[serde(default)]
    pub violation_class: Option<String>,
}
