use std::{
    collections::{BTreeSet, HashSet},
    fs::{self, File},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    thread,
    time::{Duration, Instant},
};

use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const ANALYZER_VERSION: &str = "0.9.0";
pub const ANALYZER_REVISION: &str = "ece9efe0a21e6c422a43ab6f2e1c0ce99678013b";
pub const REQUIRED_RULE_IDS: [&str; 5] = ["CS0013", "CS0014", "CS0015", "CS0017", "CS0018"];
const HEALTH_LOG_FILTER: &str = "warn,circomspect_program_analysis::analysis_runner=trace,circomspect_program_structure::control_flow_graph=debug";

/// Inclusive source range. The caller verifies membership in the target's reachable closure.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SourceScope {
    pub path: PathBuf,
    pub template_name: String,
    pub start_line: usize,
    pub end_line: usize,
}

#[derive(Debug, Clone)]
pub struct AnalysisOptions {
    pub binary: PathBuf,
    pub curve: String,
    pub timeout_seconds: u64,
    pub tool_version: String,
    pub tool_revision: String,
}

impl Default for AnalysisOptions {
    fn default() -> Self {
        Self {
            binary: PathBuf::from(".external/circomspect/target/release/circomspect"),
            curve: "BN254".to_string(),
            timeout_seconds: 60,
            tool_version: ANALYZER_VERSION.to_string(),
            tool_revision: ANALYZER_REVISION.to_string(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AnalysisCapture {
    pub tool_path: PathBuf,
    pub tool_version: String,
    pub tool_revision: String,
    pub curve: String,
    pub command: Vec<String>,
    pub sarif_path: PathBuf,
    pub stdout_path: PathBuf,
    pub stderr_path: PathBuf,
    pub exit_code: Option<i32>,
    pub timed_out: bool,
    pub elapsed_seconds: f64,
    pub execution_error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum FeatureStatus {
    Complete,
    Unknown,
    Unsupported,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct EvidenceLocation {
    pub path: PathBuf,
    pub start_line: usize,
    pub end_line: usize,
    pub start_column: usize,
    pub end_column: usize,
    pub label: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SemanticWarning {
    pub rule_id: String,
    pub message: String,
    pub locations: Vec<EvidenceLocation>,
    pub related_locations: Vec<EvidenceLocation>,
    pub attributed_scopes: Vec<SourceScope>,
    pub attribution_basis: String,
    pub raw_result_index: usize,
    pub raw_result_path: PathBuf,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SemanticFeature {
    pub rule_id: String,
    pub rule_name: String,
    pub meaning: String,
    pub status: FeatureStatus,
    pub value: Option<u8>,
    pub observed_warning_count: usize,
    pub reasons: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UnsupportedFeature {
    pub name: String,
    pub status: FeatureStatus,
    pub reason: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SemanticAnalysis {
    pub schema_version: u32,
    pub scopes: Vec<SourceScope>,
    pub capture: AnalysisCapture,
    pub complete: bool,
    pub features: Vec<SemanticFeature>,
    pub risk_score: Option<usize>,
    pub warning_count: usize,
    pub warnings: Vec<SemanticWarning>,
    pub ignored_out_of_scope_count: usize,
    pub ignored_other_rule_count: usize,
    pub duplicate_warning_count: usize,
    pub reasons: Vec<String>,
    pub unsupported_features: Vec<UnsupportedFeature>,
    pub limitations: Vec<String>,
}

pub fn analyze_target(
    scopes: &[SourceScope],
    options: &AnalysisOptions,
    output_dir: &Path,
) -> Result<SemanticAnalysis> {
    let scopes = validate_scopes(scopes)?;
    if options.timeout_seconds == 0 {
        bail!("semantic analysis timeout must be positive");
    }
    if !matches!(options.curve.as_str(), "BN254" | "BLS12_381" | "GOLDILOCKS") {
        bail!("unsupported Circomspect curve: {}", options.curve);
    }
    fs::create_dir_all(output_dir)?;
    let output_dir = fs::canonicalize(output_dir)?;
    let sarif_path = output_dir.join("analysis.sarif");
    if sarif_path.exists() {
        bail!("semantic output already exists: {}", sarif_path.display());
    }
    let stdout_path = output_dir.join("stdout.log");
    let stderr_path = output_dir.join("stderr.log");
    let sources = scopes
        .iter()
        .map(|s| s.path.clone())
        .collect::<BTreeSet<_>>();
    let mut args = vec![
        "--level".to_string(),
        "INFO".to_string(),
        "--verbose".to_string(),
        "--curve".to_string(),
        options.curve.clone(),
        "--sarif-file".to_string(),
        sarif_path.to_string_lossy().into_owned(),
    ];
    args.extend(sources.iter().map(|p| p.to_string_lossy().into_owned()));
    let mut capture = AnalysisCapture {
        tool_path: options.binary.clone(),
        tool_version: options.tool_version.clone(),
        tool_revision: options.tool_revision.clone(),
        curve: options.curve.clone(),
        command: std::iter::once(options.binary.to_string_lossy().into_owned())
            .chain(args.iter().cloned())
            .collect(),
        sarif_path,
        stdout_path: stdout_path.clone(),
        stderr_path: stderr_path.clone(),
        exit_code: None,
        timed_out: false,
        elapsed_seconds: 0.0,
        execution_error: None,
    };
    let start = Instant::now();
    let child = Command::new(&options.binary)
        .args(&args)
        .env("RUST_LOG", HEALTH_LOG_FILTER)
        .env("NO_COLOR", "1")
        .stdin(Stdio::null())
        .stdout(File::create(&stdout_path)?)
        .stderr(File::create(&stderr_path)?)
        .spawn();
    match child {
        Ok(mut child) => loop {
            if let Some(status) = child.try_wait()? {
                capture.exit_code = status.code();
                break;
            }
            if start.elapsed() >= Duration::from_secs(options.timeout_seconds) {
                capture.timed_out = true;
                child
                    .kill()
                    .context("stop Circomspect after analysis timeout")?;
                capture.exit_code = child.wait()?.code();
                break;
            }
            thread::sleep(Duration::from_millis(10));
        },
        Err(error) => capture.execution_error = Some(error.to_string()),
    }
    capture.elapsed_seconds = start.elapsed().as_secs_f64();
    fs::write(
        output_dir.join("capture.json"),
        serde_json::to_vec_pretty(&capture)?,
    )?;
    let report = import_sarif(&scopes, capture)?;
    fs::write(
        output_dir.join("semantic.json"),
        serde_json::to_vec_pretty(&report)?,
    )?;
    Ok(report)
}

/// SARIF alone does not prove completion: the capture and pinned health logs are required.
pub fn import_sarif(scopes: &[SourceScope], capture: AnalysisCapture) -> Result<SemanticAnalysis> {
    let scopes = validate_scopes(scopes)?;
    let mut reasons = Vec::new();
    if capture.tool_version != ANALYZER_VERSION || capture.tool_revision != ANALYZER_REVISION {
        reasons.push(
            "unverified analyzer version/revision; completion contract is unsupported".into(),
        );
    }
    if capture.timed_out {
        reasons.push("analyzer exceeded its time limit".into());
    }
    if let Some(error) = &capture.execution_error {
        reasons.push(format!("analyzer could not execute: {error}"));
    }
    if !matches!(capture.exit_code, Some(0 | 1)) {
        reasons.push("analyzer did not exit normally with its documented status 0 or 1".into());
    }
    let stdout = fs::read_to_string(&capture.stdout_path).unwrap_or_default();
    let stderr = fs::read_to_string(&capture.stderr_path).unwrap_or_default();
    let completed = stdout.lines().any(|line| {
        line == "circomspect: No issues found."
            || line.strip_prefix("circomspect: ").is_some_and(|line| {
                line.strip_suffix(" issue found.")
                    .or_else(|| line.strip_suffix(" issues found."))
                    .is_some_and(|count| count.parse::<usize>().is_ok())
            })
    });
    if !completed {
        reasons.push("analyzer completion summary is missing".into());
    }
    for scope in &scopes {
        if !stdout.contains(&format!("analyzing template '{}'", scope.template_name))
            || !stderr.contains(&format!(
                "successfully lifted template `{}`",
                scope.template_name
            ))
        {
            reasons.push(format!(
                "template analysis/CFG completion is unverified: {}",
                scope.template_name
            ));
        }
    }
    for marker in [
        "failed to lift",
        "failed to propagate",
        "failed to convert",
        "failed to write reports",
    ] {
        if stderr.contains(marker) {
            reasons.push(format!("analyzer reported incomplete work: {marker}"));
        }
    }
    let parsed: std::result::Result<Value, _> = fs::read(&capture.sarif_path)
        .map_err(|e| e.to_string())
        .and_then(|bytes| serde_json::from_slice(&bytes).map_err(|e| e.to_string()));
    let mut warnings = Vec::new();
    let mut ignored_out_of_scope_count = 0;
    let mut ignored_other_rule_count = 0;
    let mut duplicate_warning_count = 0;
    let mut seen = HashSet::new();
    match parsed {
        Err(error) => reasons.push(format!("SARIF is unavailable or invalid: {error}")),
        Ok(sarif) => {
            let run = sarif
                .get("runs")
                .and_then(Value::as_array)
                .filter(|runs| runs.len() == 1)
                .and_then(|runs| runs.first());
            if sarif.get("version").and_then(Value::as_str) != Some("2.1.0")
                || run
                    .and_then(|r| r.pointer("/tool/driver/name"))
                    .and_then(Value::as_str)
                    != Some("Circomspect")
            {
                reasons.push(
                    "SARIF does not match the verified single-run Circomspect 2.1.0 format".into(),
                );
            }
            if let Some(results) = run.and_then(|r| r.get("results")).and_then(Value::as_array) {
                for (index, result) in results.iter().enumerate() {
                    let id = result.get("ruleId").and_then(Value::as_str).unwrap_or("");
                    if result.get("level").and_then(Value::as_str) == Some("error") {
                        reasons.push(format!("analyzer emitted error {id} at result {index}"));
                    }
                    if !REQUIRED_RULE_IDS.contains(&id) {
                        ignored_other_rule_count += 1;
                        continue;
                    }
                    let locations = parse_locations(result.get("locations"));
                    let related = parse_locations(result.get("relatedLocations"));
                    let (Ok(locations), Ok(related_locations)) = (locations, related) else {
                        reasons.push(format!(
                            "unreadable source location for rule {id}, result {index}"
                        ));
                        continue;
                    };
                    if locations.is_empty() {
                        reasons.push(format!(
                            "primary source location missing for rule {id}, result {index}"
                        ));
                        continue;
                    }
                    let attributed_scopes = scopes
                        .iter()
                        .filter(|scope| {
                            locations.iter().any(|location| {
                                location.path == scope.path
                                    && location.start_line >= scope.start_line
                                    && location.end_line <= scope.end_line
                            })
                        })
                        .cloned()
                        .collect::<Vec<_>>();
                    if attributed_scopes.is_empty() {
                        ignored_out_of_scope_count += 1;
                        continue;
                    }
                    let message = result
                        .pointer("/message/text")
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .to_string();
                    let key = serde_json::to_string(&(id, &message, &locations))?;
                    if !seen.insert(key) {
                        duplicate_warning_count += 1;
                        continue;
                    }
                    warnings.push(SemanticWarning {
                        rule_id: id.into(),
                        message,
                        locations,
                        related_locations,
                        attributed_scopes,
                        attribution_basis:
                            "primary source region inside caller-validated reachable template scope"
                                .into(),
                        raw_result_index: index,
                        raw_result_path: capture.sarif_path.clone(),
                    });
                }
            } else {
                reasons.push("SARIF results array is missing".into());
            }
        }
    }
    warnings.sort_by(|a, b| {
        a.rule_id
            .cmp(&b.rule_id)
            .then_with(|| a.locations[0].path.cmp(&b.locations[0].path))
            .then_with(|| a.locations[0].start_line.cmp(&b.locations[0].start_line))
            .then_with(|| a.message.cmp(&b.message))
    });
    reasons.sort();
    reasons.dedup();
    let complete = reasons.is_empty();
    let features = rule_definitions()
        .into_iter()
        .map(|(id, name, meaning)| {
            let count = warnings.iter().filter(|w| w.rule_id == id).count();
            SemanticFeature {
                rule_id: id.into(),
                rule_name: name.into(),
                meaning: meaning.into(),
                status: if complete {
                    FeatureStatus::Complete
                } else {
                    FeatureStatus::Unknown
                },
                value: complete.then_some(u8::from(count > 0)),
                observed_warning_count: count,
                reasons: reasons.clone(),
            }
        })
        .collect::<Vec<_>>();
    let risk_score = complete.then(|| features.iter().map(|f| usize::from(f.value.unwrap())).sum());
    Ok(SemanticAnalysis {
        schema_version: 1, scopes, capture, complete, features, risk_score,
        warning_count: warnings.len(), warnings, ignored_out_of_scope_count,
        ignored_other_rule_count, duplicate_warning_count, reasons,
        unsupported_features: vec![UnsupportedFeature {
            name: "compile-time parameter assertion versus signal-dependent assertion".into(),
            status: FeatureStatus::Unsupported,
            reason: "the verified Circomspect release has no dedicated rule that establishes this distinction; assertions are not counted".into(),
        }],
        limitations: vec![
            "Warnings describe template definitions; Circomspect does not specialize templates with this target's concrete parameters.".into(),
            "The caller must validate reachable template scopes and their full dependency closure; file co-location is not reachability.".into(),
            "Complete means these analyzer passes ran with no observed analysis failure, not that the circuit is safe or all bugs are detectable.".into(),
            "Any detected partial analysis conservatively makes every required feature unknown; observed warnings remain available.".into(),
            "Only the five selected rule IDs count in warning-first; unrelated lint reports remain in raw SARIF.".into(),
        ],
    })
}

fn validate_scopes(scopes: &[SourceScope]) -> Result<Vec<SourceScope>> {
    if scopes.is_empty() {
        bail!("reachable template scopes are required for semantic attribution");
    }
    let mut normalized = Vec::new();
    for scope in scopes {
        let path = fs::canonicalize(&scope.path)
            .with_context(|| format!("read semantic source {}", scope.path.display()))?;
        let line_count = fs::read_to_string(&path)?.lines().count();
        if scope.template_name.is_empty()
            || scope.start_line == 0
            || scope.start_line > scope.end_line
            || scope.end_line > line_count
        {
            bail!("invalid reachable source scope for {}", scope.template_name);
        }
        let item = SourceScope {
            path,
            ..scope.clone()
        };
        if !normalized.contains(&item) {
            normalized.push(item);
        }
    }
    normalized.sort_by(|a, b| {
        a.path
            .cmp(&b.path)
            .then_with(|| a.start_line.cmp(&b.start_line))
    });
    for pair in normalized.windows(2) {
        if pair[0].path == pair[1].path && pair[0].end_line >= pair[1].start_line {
            bail!("overlapping template scopes cannot be attributed precisely");
        }
    }
    Ok(normalized)
}

fn parse_locations(value: Option<&Value>) -> Result<Vec<EvidenceLocation>> {
    let Some(value) = value else {
        return Ok(Vec::new());
    };
    let Some(locations) = value.as_array() else {
        bail!("locations must be an array")
    };
    locations
        .iter()
        .map(|location| {
            let uri = location
                .pointer("/physicalLocation/artifactLocation/uri")
                .and_then(Value::as_str)
                .context("source URI missing")?;
            let path = uri
                .strip_prefix("file://")
                .context("unsupported source URI")?;
            // This pinned writer emits literal file paths, not percent-encoded URIs.
            let path = fs::canonicalize(path).context("SARIF source file is unavailable")?;
            let region = location
                .pointer("/physicalLocation/region")
                .context("source region missing")?;
            let field = |key: &str| -> Result<usize> {
                region
                    .get(key)
                    .and_then(Value::as_u64)
                    .and_then(|v| usize::try_from(v).ok())
                    .filter(|v| *v > 0)
                    .with_context(|| format!("invalid source region {key}"))
            };
            let start_line = field("startLine")?;
            let end_line = field("endLine")?;
            if end_line < start_line {
                bail!("reversed source region")
            }
            Ok(EvidenceLocation {
                path,
                start_line,
                end_line,
                start_column: field("startColumn")?,
                end_column: field("endColumn")?,
                label: location
                    .pointer("/message/text")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .into(),
            })
        })
        .collect()
}

fn rule_definitions() -> [(&'static str, &'static str, &'static str); 5] {
    [
        ("CS0013", "unnecessary-signal-assignment", "single-arrow assignment has a quadratic RHS that could instead use a constraint assignment; separate constraints can still make it correct"),
        ("CS0014", "unconstrained-less-than", "analyzer could not establish the required input range for a Circomlib LessThan use"),
        ("CS0015", "unconstrained-division", "analyzer did not find its supported IsZero-based nonzero check for the divisor"),
        ("CS0017", "under-constrained-signal", "intermediate signal appears in fewer than two separate constraints under this analyzer's analysis"),
        ("CS0018", "unused-output-signal", "instantiated component output is not used as expected, subject to the analyzer's allowlist and access approximation"),
    ]
}
