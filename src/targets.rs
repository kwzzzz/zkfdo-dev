use std::{
    collections::{BTreeMap, BTreeSet, HashMap, HashSet},
    fs,
    path::{Path, PathBuf},
};

use anyhow::{ensure, Context, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use uuid::Uuid;

use crate::{
    scanner,
    structure::{capture_tool, ToolCapture},
};

const MAX_INSTANTIATION_DEPTH: usize = 64;
const MAX_COMPILE_TIME_LOOP_ITERATIONS: usize = 100_000;
const MAX_TOTAL_EXPANSION_STEPS: usize = 100_000;

struct ExpansionBudget {
    remaining: usize,
    exhausted: bool,
}

impl ExpansionBudget {
    fn new() -> Self {
        Self {
            remaining: MAX_TOTAL_EXPANSION_STEPS,
            exhausted: false,
        }
    }

    fn consume(&mut self) -> bool {
        if self.exhausted || self.remaining == 0 {
            self.exhausted = true;
            return false;
        }
        self.remaining -= 1;
        true
    }
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum EntrypointStatus {
    Found,
    Missing,
    Multiple,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct EntrypointCandidate {
    pub source_path: PathBuf,
    pub line: usize,
    pub template_name: Option<String>,
    pub parameters: Vec<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct TargetOrigin {
    pub source_path: PathBuf,
    pub parent_template: String,
    pub parent_parameters: Vec<String>,
    pub component_name: String,
    pub line: usize,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum WrapperStatus {
    NotGenerated,
    Generated,
    CompileSucceeded,
    CompileFailed,
    CompileTimedOut,
    CompilerUnavailable,
    Unsupported,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct ConcreteFuzzTarget {
    pub identity: String,
    pub source_path: PathBuf,
    pub template_name: String,
    pub concrete_parameters: Vec<String>,
    pub origin: TargetOrigin,
    pub generated_wrapper_path: Option<PathBuf>,
    pub wrapper_status: WrapperStatus,
    pub compiler_stdout_path: Option<PathBuf>,
    pub compiler_stderr_path: Option<PathBuf>,
    pub failure_reason: Option<String>,
    /// Exact bounded compiler invocation; absent in reports created before it was recorded.
    /// Call sites in one compile unit share the unit's single invocation.
    #[serde(default)]
    pub compile: Option<ToolCapture>,
    /// `source::Template(params)` of this instance. Together with `parent_instance_key` the
    /// call sites form a call graph from which every ancestor path can be reconstructed.
    #[serde(default)]
    pub instance_key: String,
    #[serde(default)]
    pub parent_instance_key: String,
    /// Key of the compile unit whose wrapper and compiler result this call site uses.
    #[serde(default)]
    pub compile_unit: Option<String>,
    /// True when the result was reused from an earlier call site in the same compile unit.
    #[serde(default)]
    pub compile_reused: bool,
    /// Wrapper arguments when they differ from `concrete_parameters`: array arguments are keyed
    /// by a value hash but passed to the wrapper as literals (F-01).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub wrapper_arguments: Option<Vec<String>>,
    /// `compiler` or `interpreter`, when instance capture ran (F-01).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub instance_source: Option<String>,
    /// Whether the other discovery method found the same child instance at this call site.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub methods_agree: Option<bool>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq, PartialOrd, Ord)]
pub struct DependencyFingerprint {
    pub path: PathBuf,
    pub sha256: String,
}

/// Wrapper compilation shared by call sites whose wrapper source, dependency closure, compiler
/// binary and settings are identical. It carries no caller context or project-level verdict.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct CompileUnit {
    pub key: String,
    pub instance_key: String,
    pub wrapper_path: PathBuf,
    pub dependencies: Vec<DependencyFingerprint>,
    pub unresolved_includes: Vec<String>,
    pub compiler_binary: Option<PathBuf>,
    pub compiler_sha256: Option<String>,
    pub settings: Vec<String>,
    pub call_site_identities: Vec<String>,
    pub wrapper_status: WrapperStatus,
    pub failure_reason: Option<String>,
    pub compile: Option<ToolCapture>,
}

impl CompileUnit {
    fn apply_to(&self, target: &mut ConcreteFuzzTarget, reused: bool) {
        target.generated_wrapper_path = Some(self.wrapper_path.clone());
        target.wrapper_status = self.wrapper_status.clone();
        target.failure_reason = self.failure_reason.clone();
        target.compiler_stdout_path = self.compile.as_ref().map(|c| c.stdout_path.clone());
        target.compiler_stderr_path = self.compile.as_ref().map(|c| c.stderr_path.clone());
        target.compile = self.compile.clone();
        target.compile_unit = Some(self.key.clone());
        target.compile_reused = reused;
    }
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct UnsupportedCase {
    pub source_path: PathBuf,
    pub line: Option<usize>,
    pub construct: String,
    pub reason: String,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct TargetDiscoveryReport {
    pub discovery_id: String,
    pub project_root: PathBuf,
    pub work_dir: PathBuf,
    pub entrypoint_status: EntrypointStatus,
    pub entrypoints: Vec<EntrypointCandidate>,
    pub targets: Vec<ConcreteFuzzTarget>,
    pub generated_wrapper_count: usize,
    pub compile_succeeded_count: usize,
    pub unsupported: Vec<UnsupportedCase>,
    /// The single file discovery started from; absent when the whole project was scanned.
    #[serde(default)]
    pub selected_entrypoint: Option<PathBuf>,
    #[serde(default)]
    pub library_paths: Vec<PathBuf>,
    /// Per-wrapper compiler limit; absent when wrappers were not compiled.
    #[serde(default)]
    pub compile_timeout_seconds: Option<u64>,
    /// Instance key of the entrypoint's `component main`.
    #[serde(default)]
    pub root_instance_key: Option<String>,
    /// Distinct wrappers; `targets` keeps one entry per call site.
    #[serde(default)]
    pub compile_units: Vec<CompileUnit>,
    /// Compile units for which compilation was attempted, at most one attempt per unit.
    #[serde(default)]
    pub compile_attempt_count: usize,
    /// Attempts whose compiler process was actually started.
    #[serde(default)]
    pub compile_process_count: usize,
    /// Compiler-based instance discovery and its comparison with the interpreter (F-01).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub instance_discovery: Option<InstanceDiscovery>,
}

/// One call site (parent instance, component name, line) and the child instances each method
/// found there. Anonymous component names are compared without the interpreter's bracketed
/// binding context, which the compiler does not report.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq, PartialOrd, Ord)]
pub struct SlotDifference {
    pub parent_instance_key: String,
    pub component_name: String,
    pub line: usize,
    pub interpreter: Vec<String>,
    pub compiler: Vec<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct InstanceDiscovery {
    /// Which method's targets the report carries: `compiler` when the instrumented copy
    /// compiled and was read, otherwise `interpreter`.
    pub selected: String,
    pub capture_status: String,
    pub capture_failure: Option<String>,
    pub capture_path: PathBuf,
    /// Full argument values per instance key (array keys hash these values).
    pub instance_args_path: Option<PathBuf>,
    pub capture_compile_seconds: f64,
    pub capture_compile_attempts: usize,
    pub capture_scan_seconds: f64,
    pub capture_read_seconds: f64,
    #[serde(default)]
    pub capture_assemble_seconds: f64,
    pub interpreter_complete: bool,
    pub compiler_complete: bool,
    pub interpreter_targets: usize,
    pub compiler_targets: usize,
    pub interpreter_root_instance_key: Option<String>,
    pub compiler_root_instance_key: Option<String>,
    pub slots_compared: usize,
    /// Call sites where the methods found different child instances (an empty side means the
    /// site was found by the other method only).
    pub slot_differences: Vec<SlotDifference>,
    /// Distinct target instance keys (the fragment composition) found by one method only.
    pub instance_keys_only_interpreter: Vec<String>,
    pub instance_keys_only_compiler: Vec<String>,
    /// The interpreter's unsupported cases when the compiler result was selected.
    pub interpreter_unsupported: Vec<UnsupportedCase>,
}

/// Operational cap for one wrapper compilation, not an empirically derived bound.
pub const DEFAULT_WRAPPER_COMPILE_TIMEOUT_SECONDS: u64 = 600;

#[derive(Debug, Clone)]
pub struct DiscoveryOptions {
    /// Discover only from this file's `component main` and its include closure.
    pub entrypoint: Option<PathBuf>,
    /// Circom `-l` directories, searched after the including directory and project root.
    pub library_paths: Vec<PathBuf>,
    /// None generates wrappers without compiling them.
    pub circom_bin: Option<PathBuf>,
    pub compile_timeout_seconds: u64,
    /// With a compiler: also discover instances from an instrumented O0 compile (F-01).
    pub instance_capture: Option<PathBuf>,
    pub capture_timeout_seconds: u64,
}

/// Operational cap for the instrumented O0 compile, not an empirically derived bound.
pub const DEFAULT_CAPTURE_TIMEOUT_SECONDS: u64 = 600;

impl Default for DiscoveryOptions {
    fn default() -> Self {
        Self {
            entrypoint: None,
            library_paths: Vec::new(),
            circom_bin: None,
            compile_timeout_seconds: DEFAULT_WRAPPER_COMPILE_TIMEOUT_SECONDS,
            instance_capture: None,
            capture_timeout_seconds: DEFAULT_CAPTURE_TIMEOUT_SECONDS,
        }
    }
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct TemplateSourceScope {
    pub path: PathBuf,
    pub template_name: String,
    pub start_line: usize,
    pub end_line: usize,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq, Hash)]
pub struct InspectedTemplateInstance {
    pub path: PathBuf,
    pub template_name: String,
    pub concrete_parameters: Vec<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct EntrypointInspection {
    pub entrypoint: PathBuf,
    pub project_root: PathBuf,
    pub root: Option<InspectedTemplateInstance>,
    pub instances: Vec<InspectedTemplateInstance>,
    pub scopes: Vec<TemplateSourceScope>,
    pub dependency_paths: Vec<PathBuf>,
    pub complete: bool,
    pub unsupported: Vec<UnsupportedCase>,
}

#[derive(Debug, Clone)]
struct IncludeDirective {
    path: String,
    line: usize,
}

#[derive(Debug, Clone)]
struct ParsedFile {
    path: PathBuf,
    includes: Vec<IncludeDirective>,
    mains: Vec<ParsedMain>,
    templates: Vec<TemplateDefinition>,
    issues: Vec<UnsupportedCase>,
}

#[derive(Debug, Clone)]
struct ParsedMain {
    line: usize,
    call: Option<TemplateCall>,
    failure_reason: Option<String>,
}

#[derive(Debug, Clone)]
struct TemplateDefinition {
    source_path: PathBuf,
    name: String,
    start_line: usize,
    end_line: usize,
    start_byte: usize,
    end_byte: usize,
    parameters: Vec<String>,
    body: Vec<BodyItem>,
}

#[derive(Debug, Clone)]
enum BodyItem {
    Variable {
        name: String,
        expression: Vec<Token>,
        line: usize,
    },
    Instantiation {
        component_name: String,
        component_index: Option<Vec<Token>>,
        call: TemplateCall,
        line: usize,
        anonymous: bool,
    },
    ComponentArray {
        name: String,
        length: Vec<Token>,
        line: usize,
    },
    ForLoop {
        variable: String,
        initial: Vec<Token>,
        condition: Vec<Token>,
        update: LoopUpdate,
        body: Vec<BodyItem>,
        line: usize,
    },
    Conditional {
        condition: Vec<Token>,
        then_body: Vec<BodyItem>,
        else_body: Vec<BodyItem>,
        line: usize,
    },
    Unsupported {
        line: usize,
        construct: String,
        reason: String,
    },
}

#[derive(Debug, Clone, Copy)]
enum LoopUpdate {
    Increment,
    Decrement,
}

#[derive(Debug, Clone)]
struct TemplateCall {
    template_name: String,
    arguments: Vec<Vec<Token>>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct Token {
    pub(crate) kind: TokenKind,
    pub(crate) line: usize,
    /// Character offset retained for stable anonymous-instance identities.
    pub(crate) offset: usize,
    /// UTF-8 byte offset used only when binding source evidence ranges.
    pub(crate) byte_offset: usize,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum TokenKind {
    Identifier(String),
    Number(String),
    StringLiteral(String),
    Symbol(char),
    Operator(String),
}

/// Inspect one existing entrypoint using the same supported syntax as target discovery.
/// The selected file may be an external wrapper; every included dependency must be in project_root.
pub fn inspect_entrypoint(entrypoint: &Path, project_root: &Path) -> Result<EntrypointInspection> {
    inspect_entrypoint_with_libraries(entrypoint, project_root, &[])
}

/// Inspects like [`inspect_entrypoint`], and also resolves includes through circom `-l`
/// library directories. They are searched in the given order after the including file's
/// directory and the project root, so every include that resolves without them resolves to
/// the same file.
pub fn inspect_entrypoint_with_libraries(
    entrypoint: &Path,
    project_root: &Path,
    library_paths: &[PathBuf],
) -> Result<EntrypointInspection> {
    let entrypoint = fs::canonicalize(entrypoint)
        .with_context(|| format!("resolve selected entrypoint {}", entrypoint.display()))?;
    let project_root = fs::canonicalize(project_root)
        .with_context(|| format!("resolve project root {}", project_root.display()))?;
    anyhow::ensure!(
        project_root.is_dir(),
        "inspection project root must be a directory"
    );
    let library_paths = library_paths
        .iter()
        .map(|path| {
            let library = fs::canonicalize(path)
                .with_context(|| format!("resolve inspection library path {}", path.display()))?;
            anyhow::ensure!(
                library.is_dir(),
                "inspection library path is not a directory: {}",
                library.display()
            );
            Ok(library)
        })
        .collect::<Result<Vec<_>>>()?;
    let mut parsed_files = HashMap::new();
    let mut visited = HashSet::new();
    let mut unsupported = Vec::new();
    load_inspection_files(
        &entrypoint,
        &project_root,
        &library_paths,
        &mut parsed_files,
        &mut visited,
        &mut unsupported,
    );
    let mut root_instance = None;
    let mut instances = Vec::new();
    let mut scopes = Vec::new();
    // Unreferenced unsupported definitions do not affect the resolved call closure.
    let template_index = build_template_index(&visited, &parsed_files, &mut Vec::new());
    if let Some(file) = parsed_files.get(&entrypoint) {
        if file.mains.len() != 1 {
            unsupported.push(UnsupportedCase {
                source_path: entrypoint.clone(),
                line: None,
                construct: "selected entrypoint".into(),
                reason: format!(
                    "selected file must declare exactly one main, found {}",
                    file.mains.len()
                ),
            });
        } else {
            let main = &file.mains[0];
            if let Some(reason) = &main.failure_reason {
                unsupported.push(UnsupportedCase {
                    source_path: entrypoint.clone(),
                    line: Some(main.line),
                    construct: "component main".into(),
                    reason: reason.clone(),
                });
            } else if let Some(call) = &main.call {
                match evaluate_arguments(&call.arguments, &HashMap::new()) {
                    Err(reason) => unsupported.push(UnsupportedCase {
                        source_path: entrypoint.clone(),
                        line: Some(main.line),
                        construct: format_source_call(call),
                        reason: format!("main template parameters are not concrete: {reason}"),
                    }),
                    Ok(parameters) => {
                        if let Some(root) = resolve_template(
                            call,
                            &parameters,
                            &entrypoint,
                            main.line,
                            &template_index,
                            &mut unsupported,
                        ) {
                            let instance = InspectedTemplateInstance {
                                path: root.source_path.clone(),
                                template_name: root.name.clone(),
                                concrete_parameters: parameters
                                    .iter()
                                    .map(ToString::to_string)
                                    .collect(),
                            };
                            root_instance = Some(instance.clone());
                            instances.push(instance);
                            let mut children = Vec::new();
                            let mut stack = vec![(root.name.clone(), parameters.clone())];
                            let mut expansion_budget = ExpansionBudget::new();
                            let mut seen_target_identities = HashSet::new();
                            expand_template(
                                root,
                                &parameters,
                                &template_index,
                                &mut stack,
                                &mut children,
                                &mut unsupported,
                                0,
                                &mut expansion_budget,
                                &mut seen_target_identities,
                            );
                            if expansion_budget.exhausted {
                                children.clear();
                            }
                            for target in children {
                                let instance = InspectedTemplateInstance {
                                    path: target.source_path,
                                    template_name: target.template_name,
                                    concrete_parameters: target.concrete_parameters,
                                };
                                if !instances.contains(&instance) {
                                    instances.push(instance);
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    let mut binding_issues = Vec::new();
    let mut checked_definitions = HashSet::new();
    for instance in &instances {
        if checked_definitions.insert((instance.path.clone(), instance.template_name.clone())) {
            let definition = template_index[&instance.template_name]
                .iter()
                .find(|definition| definition.source_path == instance.path)
                .expect("expanded instance refers to a resolved definition");
            binding_issues.extend(inspect_binding_changes(definition)?);
        }
    }
    if !binding_issues.is_empty() {
        unsupported.extend(binding_issues);
        // Children may have been expanded with stale bindings; do not publish guessed instances.
        instances.retain(|instance| root_instance.as_ref() == Some(instance));
    }
    for instance in &instances {
        let definition = template_index[&instance.template_name]
            .iter()
            .find(|definition| definition.source_path == instance.path)
            .expect("expanded instance refers to a resolved definition");
        let scope = TemplateSourceScope {
            path: definition.source_path.clone(),
            template_name: definition.name.clone(),
            start_line: definition.start_line,
            end_line: definition.end_line,
        };
        if !scopes.contains(&scope) {
            scopes.push(scope);
        }
    }
    scopes.sort_by(|a, b| {
        a.path
            .cmp(&b.path)
            .then_with(|| a.start_line.cmp(&b.start_line))
    });
    for scope in &scopes {
        if let Some(file) = parsed_files.get(&scope.path) {
            for other in &file.templates {
                if other.name != scope.template_name
                    && scope.start_line <= other.end_line
                    && other.start_line <= scope.end_line
                {
                    unsupported.push(UnsupportedCase {
                        source_path: scope.path.clone(), line: Some(scope.start_line),
                        construct: format!("template {}", scope.template_name),
                        reason: "template source lines overlap another definition; line-based warning attribution is ambiguous".into(),
                    });
                }
            }
        }
    }
    instances.sort_by(|a, b| {
        a.path
            .cmp(&b.path)
            .then_with(|| a.template_name.cmp(&b.template_name))
            .then_with(|| a.concrete_parameters.cmp(&b.concrete_parameters))
    });
    let mut dependency_paths = visited.into_iter().collect::<Vec<_>>();
    dependency_paths.sort();
    unsupported.sort_by(|a, b| {
        a.source_path
            .cmp(&b.source_path)
            .then_with(|| a.line.cmp(&b.line))
            .then_with(|| a.reason.cmp(&b.reason))
    });
    unsupported.dedup();
    Ok(EntrypointInspection {
        entrypoint,
        project_root,
        root: root_instance,
        instances,
        scopes,
        dependency_paths,
        complete: unsupported.is_empty(),
        unsupported,
    })
}

/// F-01: an inspection of `entrypoint` built from an instance capture instead of the
/// interpreter. The root is the capture's `main` when `entrypoint` is the captured entrypoint;
/// otherwise `entrypoint` must be a wrapper whose `component main` literal arguments equal a
/// captured instance's, and that instance's subtree is used. Dependency paths and scope checks
/// are the interpreter's; instance arguments come only from the capture.
pub fn inspect_entrypoint_from_capture(
    entrypoint: &Path,
    project_root: &Path,
    library_paths: &[PathBuf],
    capture: &crate::instance_capture::InstanceCapture,
) -> Result<EntrypointInspection> {
    use crate::instance_capture::CapturedValue;
    let entrypoint = fs::canonicalize(entrypoint)
        .with_context(|| format!("resolve selected entrypoint {}", entrypoint.display()))?;
    let project_root = fs::canonicalize(project_root)?;
    let library_paths = library_paths
        .iter()
        .map(fs::canonicalize)
        .collect::<std::io::Result<Vec<_>>>()?;
    let mut parsed_files = HashMap::new();
    let mut visited = HashSet::new();
    let mut walk_issues = Vec::new();
    load_inspection_files(
        &entrypoint,
        &project_root,
        &library_paths,
        &mut parsed_files,
        &mut visited,
        &mut walk_issues,
    );
    // Template-syntax limits of the interpreter do not apply; unreadable or unresolved
    // sources do.
    let mut unsupported = walk_issues
        .into_iter()
        .filter(|issue| issue.construct == "source file" || issue.construct.starts_with("include"))
        .collect::<Vec<_>>();
    let prime = capture.prime()?;
    let root = if entrypoint == capture.entrypoint {
        capture.root().cloned()
    } else {
        let file = parsed_files.get(&entrypoint);
        let call = file
            .and_then(|file| (file.mains.len() == 1).then(|| file.mains[0].call.clone()))
            .flatten();
        match call {
            None => {
                unsupported.push(UnsupportedCase {
                    source_path: entrypoint.clone(),
                    line: None,
                    construct: "component main".into(),
                    reason: "wrapper must declare exactly one parsable component main".into(),
                });
                None
            }
            Some(call) => {
                let tokens = call
                    .arguments
                    .iter()
                    .map(|argument| {
                        literal_value(argument, &prime).and_then(|value| {
                            value.key_token(&prime).map_err(|error| error.to_string())
                        })
                    })
                    .collect::<std::result::Result<Vec<_>, String>>();
                match tokens {
                    Err(reason) => {
                        unsupported.push(UnsupportedCase {
                            source_path: entrypoint.clone(),
                            line: None,
                            construct: format_source_call(&call),
                            reason: format!("wrapper argument is not a literal: {reason}"),
                        });
                        None
                    }
                    Ok(tokens) => {
                        let found = capture.instances.iter().find(|instance| {
                            instance.template_name == call.template_name
                                && instance
                                    .arguments
                                    .as_ref()
                                    .and_then(|arguments| {
                                        arguments
                                            .iter()
                                            .map(|value: &CapturedValue| value.key_token(&prime))
                                            .collect::<Result<Vec<_>>>()
                                            .ok()
                                    })
                                    .is_some_and(|captured| captured == tokens)
                        });
                        if found.is_none() {
                            unsupported.push(UnsupportedCase {
                                source_path: entrypoint.clone(),
                                line: None,
                                construct: format_source_call(&call),
                                reason:
                                    "no captured instance has the wrapper's template and arguments"
                                        .into(),
                            });
                        }
                        found.cloned()
                    }
                }
            }
        }
    };
    let token_list = |instance: &crate::instance_capture::CapturedInstance| {
        instance.arguments.as_ref().map(|arguments| {
            arguments
                .iter()
                .map(|value| value.key_token(&prime))
                .collect::<Result<Vec<_>>>()
        })
    };
    let mut root_instance = None;
    let mut instances = Vec::new();
    let mut seen = HashSet::new();
    if let Some(root) = &root {
        let prefix = format!("{}.", root.path);
        for instance in std::iter::once(root).chain(
            capture
                .instances
                .iter()
                .filter(|instance| instance.path.starts_with(&prefix)),
        ) {
            match token_list(instance).transpose()? {
                Some(tokens) => {
                    let inspected = InspectedTemplateInstance {
                        path: instance.source_path.clone(),
                        template_name: instance.template_name.clone(),
                        concrete_parameters: tokens,
                    };
                    if instance.path == root.path {
                        root_instance = Some(inspected.clone());
                    }
                    if seen.insert(inspected.clone()) {
                        instances.push(inspected);
                    }
                }
                None => unsupported.push(UnsupportedCase {
                    source_path: instance.source_path.clone(),
                    line: instance.line,
                    construct: format!("{} ({})", instance.path, instance.template_name),
                    reason: format!(
                        "instance capture: {}",
                        instance.unsupported.clone().unwrap_or_default()
                    ),
                }),
            }
        }
    }
    let mut scopes = Vec::new();
    for instance in &instances {
        if let Some(template) = capture.templates.iter().find(|template| {
            template.name == instance.template_name && template.source_path == instance.path
        }) {
            let scope = TemplateSourceScope {
                path: template.source_path.clone(),
                template_name: template.name.clone(),
                start_line: template.start_line,
                end_line: template.end_line,
            };
            if !scopes.contains(&scope) {
                scopes.push(scope);
            }
        }
    }
    scopes.sort_by(|a, b| {
        a.path
            .cmp(&b.path)
            .then_with(|| a.start_line.cmp(&b.start_line))
    });
    for scope in &scopes {
        for other in capture
            .templates
            .iter()
            .filter(|other| other.source_path == scope.path)
        {
            if other.name != scope.template_name
                && scope.start_line <= other.end_line
                && other.start_line <= scope.end_line
            {
                unsupported.push(UnsupportedCase {
                    source_path: scope.path.clone(),
                    line: Some(scope.start_line),
                    construct: format!("template {}", scope.template_name),
                    reason: "template source lines overlap another definition; line-based warning attribution is ambiguous".into(),
                });
            }
        }
    }
    instances.sort_by(|a, b| {
        a.path
            .cmp(&b.path)
            .then_with(|| a.template_name.cmp(&b.template_name))
            .then_with(|| a.concrete_parameters.cmp(&b.concrete_parameters))
    });
    let mut dependency_paths = visited.into_iter().collect::<Vec<_>>();
    dependency_paths.sort();
    unsupported.sort_by(|a, b| {
        a.source_path
            .cmp(&b.source_path)
            .then_with(|| a.line.cmp(&b.line))
            .then_with(|| a.reason.cmp(&b.reason))
    });
    unsupported.dedup();
    Ok(EntrypointInspection {
        entrypoint,
        project_root,
        root: root_instance,
        instances,
        scopes,
        dependency_paths,
        complete: unsupported.is_empty(),
        unsupported,
    })
}

/// The template and literal argument values of a source file's single `component main` call;
/// an argument that is not an integer or nested array literal maps to the reason.
pub(crate) fn main_literal_arguments(
    path: &Path,
    source: &str,
    prime: &num_bigint::BigUint,
) -> std::result::Result<
    (
        String,
        Vec<std::result::Result<crate::instance_capture::CapturedValue, String>>,
    ),
    String,
> {
    let file = parse_file(path, source).map_err(|case| case.reason)?;
    let [main] = file.mains.as_slice() else {
        return Err("the entrypoint does not declare exactly one component main".into());
    };
    let call = main
        .call
        .as_ref()
        .ok_or_else(|| "the component main call is not parsable".to_owned())?;
    Ok((
        call.template_name.clone(),
        call.arguments
            .iter()
            .map(|argument| literal_value(argument, prime))
            .collect(),
    ))
}

/// A wrapper argument literal: an integer (optionally negated) or a nested array of them.
fn literal_value(
    tokens: &[Token],
    prime: &num_bigint::BigUint,
) -> std::result::Result<crate::instance_capture::CapturedValue, String> {
    use crate::instance_capture::CapturedValue;
    fn integer(
        tokens: &[Token],
        prime: &num_bigint::BigUint,
    ) -> std::result::Result<String, String> {
        let (negative, rest) = match tokens {
            [first, rest @ ..] if first.kind == TokenKind::Symbol('-') => (true, rest),
            _ => (false, tokens),
        };
        let [token] = rest else {
            return Err(format!(
                "`{}` is not an integer literal",
                tokens_to_text(tokens)
            ));
        };
        let TokenKind::Number(text) = &token.kind else {
            return Err(format!(
                "`{}` is not an integer literal",
                tokens_to_text(tokens)
            ));
        };
        let value = if let Some(hex) = text.strip_prefix("0x") {
            num_bigint::BigUint::parse_bytes(hex.as_bytes(), 16)
        } else {
            text.parse::<num_bigint::BigUint>().ok()
        }
        .ok_or_else(|| format!("`{text}` is not an integer"))?
            % prime;
        Ok(if negative && value != num_bigint::BigUint::default() {
            (prime - value).to_string()
        } else {
            value.to_string()
        })
    }
    fn array(
        tokens: &[Token],
        prime: &num_bigint::BigUint,
        dims: &mut Vec<usize>,
        depth: usize,
        values: &mut Vec<String>,
    ) -> std::result::Result<(), String> {
        let is_array = tokens
            .first()
            .is_some_and(|t| t.kind == TokenKind::Symbol('['));
        if !is_array {
            if depth != dims.len() {
                return Err("ragged array literal".into());
            }
            values.push(integer(tokens, prime)?);
            return Ok(());
        }
        let close = find_matching(tokens, 0, '[', ']').ok_or("unbalanced array literal")?;
        if close + 1 != tokens.len() {
            return Err("trailing tokens after an array literal".into());
        }
        let items = split_top_level(&tokens[1..close], ',')?;
        if depth == dims.len() {
            dims.push(items.len());
        } else if dims.get(depth) != Some(&items.len()) {
            return Err("ragged array literal".into());
        }
        for item in items {
            array(&item, prime, dims, depth + 1, values)?;
        }
        Ok(())
    }
    if tokens
        .first()
        .is_some_and(|t| t.kind == TokenKind::Symbol('['))
    {
        let mut dims = Vec::new();
        let mut values = Vec::new();
        array(tokens, prime, &mut dims, 0, &mut values)?;
        Ok(CapturedValue::Array { dims, values })
    } else {
        Ok(CapturedValue::Scalar {
            value: integer(tokens, prime)?,
        })
    }
}

/// Returns the exact half-open UTF-8 byte range occupied by one template definition.
/// This uses the same lexer/parser as discovery so review evidence cannot widen a
/// target instance to another template in the same source file.
pub fn template_source_byte_range(path: &Path, template_name: &str) -> Result<(usize, usize)> {
    let path = fs::canonicalize(path)
        .with_context(|| format!("resolve template source {}", path.display()))?;
    let source = fs::read_to_string(&path)
        .with_context(|| format!("read template source {}", path.display()))?;
    let parsed = parse_file(&path, &source).map_err(|issue| {
        anyhow::anyhow!(
            "parse template source {} at {:?}: {}",
            issue.source_path.display(),
            issue.line,
            issue.reason
        )
    })?;
    let matches = parsed
        .templates
        .iter()
        .filter(|definition| definition.name == template_name)
        .collect::<Vec<_>>();
    ensure!(
        matches.len() == 1,
        "template {template_name:?} is not uniquely defined in {}",
        path.display()
    );
    Ok((matches[0].start_byte, matches[0].end_byte))
}

/// Resolves the selected entrypoint's full Circom include closure with the same
/// search order as target discovery. Review provenance uses this to ensure no
/// source outside a pinned closure influenced a reproduced discovery.
pub fn discovery_dependency_paths(
    entrypoint: &Path,
    project_root: &Path,
    library_paths: &[PathBuf],
) -> Result<Vec<PathBuf>> {
    let entrypoint = fs::canonicalize(entrypoint)
        .with_context(|| format!("resolve selected entrypoint {}", entrypoint.display()))?;
    let project_root = fs::canonicalize(project_root)
        .with_context(|| format!("resolve project root {}", project_root.display()))?;
    let library_paths = library_paths
        .iter()
        .map(|path| {
            fs::canonicalize(path)
                .with_context(|| format!("resolve library path {}", path.display()))
        })
        .collect::<Result<Vec<_>>>()?;
    ensure!(
        entrypoint.is_file() && entrypoint.starts_with(&project_root),
        "entrypoint must be a file inside the project root"
    );

    let mut parsed_files = HashMap::new();
    let mut unsupported = Vec::new();
    load_discovery_closure(
        &entrypoint,
        &project_root,
        &library_paths,
        &mut parsed_files,
        &mut HashSet::new(),
        &mut unsupported,
    );
    let mut reachable = HashSet::new();
    collect_reachable_files(
        &entrypoint,
        &project_root,
        &library_paths,
        &parsed_files,
        &mut reachable,
        &mut unsupported,
    );
    ensure!(
        unsupported.is_empty(),
        "entrypoint source closure cannot be resolved completely"
    );
    let mut paths = reachable.into_iter().collect::<Vec<_>>();
    paths.sort();
    Ok(paths)
}

/// Returns the literal include paths parsed by the discovery lexer/parser.
/// Review-only closure checks use this without changing discovery identities.
pub fn circom_include_literals(path: &Path) -> Result<Vec<String>> {
    let path = fs::canonicalize(path)
        .with_context(|| format!("resolve Circom source {}", path.display()))?;
    let source = fs::read_to_string(&path)
        .with_context(|| format!("read Circom source {}", path.display()))?;
    let parsed = parse_file(&path, &source).map_err(|issue| {
        anyhow::anyhow!(
            "parse Circom source {} at {:?}: {}",
            issue.source_path.display(),
            issue.line,
            issue.reason
        )
    })?;
    Ok(parsed
        .includes
        .into_iter()
        .map(|include| include.path)
        .collect())
}

fn inspect_binding_changes(definition: &TemplateDefinition) -> Result<Vec<UnsupportedCase>> {
    let mut needed = HashSet::new();
    let mut variables = Vec::new();
    let mut components = HashSet::new();
    let mut parsed_component_assignments = HashSet::new();
    collect_resolution_metadata(
        &definition.body,
        &mut needed,
        &mut variables,
        &mut components,
        &mut parsed_component_assignments,
    );
    close_resolution_bindings(&mut needed, &variables);
    let source = fs::read_to_string(&definition.source_path)?;
    let tokens = lex(&source)
        .expect("inspection source was already lexed")
        .into_iter()
        .filter(|token| token.line >= definition.start_line && token.line <= definition.end_line)
        .collect::<Vec<_>>();
    let allowed_loop_updates = concrete_loop_update_positions(&tokens);
    let allowed_loop_declarations = concrete_loop_declaration_positions(&tokens);
    let mut declared = definition
        .parameters
        .iter()
        .cloned()
        .collect::<HashSet<_>>();
    let mut issues = Vec::new();
    for (index, token) in tokens.iter().enumerate() {
        let Some(name) = token_identifier(token) else {
            continue;
        };
        if !needed.contains(name) && !components.contains(name) {
            continue;
        }
        let next = tokens.get(index + 1);
        let previous = index.checked_sub(1).and_then(|i| tokens.get(i));
        let direct_assignment = next.is_some_and(|t| token_is_symbol(t, '='));
        let increment = next.is_some_and(
            |t| matches!(&t.kind, TokenKind::Operator(op) if op == "++" || op == "--"),
        ) || previous.is_some_and(
            |t| matches!(&t.kind, TokenKind::Operator(op) if op == "++" || op == "--"),
        );
        let compound_assignment = next.is_some_and(|t| {
            matches!(
                t.kind,
                TokenKind::Symbol('+' | '-' | '*' | '/' | '%' | '&' | '|' | '^')
            ) || matches!(&t.kind, TokenKind::Operator(op) if op == "<<" || op == ">>" || op == "**")
        }) && tokens
            .get(index + 2)
            .is_some_and(|t| token_is_symbol(t, '='));
        if !direct_assignment && !increment && !compound_assignment {
            continue;
        }
        if increment && allowed_loop_updates.contains(&index) {
            continue;
        }
        if direct_assignment && components.contains(name) {
            let parsed_assignment =
                parsed_component_assignments.contains(&(name.to_string(), token.line));
            if parsed_assignment {
                continue;
            }
        }
        let declaration = previous.is_some_and(|t| token_is_identifier(t, "var"));
        if direct_assignment
            && declaration
            && (allowed_loop_declarations.contains(&index) || declared.insert(name.to_string()))
        {
            continue;
        }
        // The existing expansion evaluates declarations only, never subsequent mutations.
        issues.push(UnsupportedCase {
            source_path: definition.source_path.clone(), line: Some(token.line),
            construct: name.to_string(),
            reason: "binding/component reassignment affecting target resolution is unsupported by inspection".into(),
        });
    }
    Ok(issues)
}

fn resolution_needed_bindings(items: &[BodyItem]) -> HashSet<String> {
    let mut needed = HashSet::new();
    let mut variables = Vec::new();
    let mut components = HashSet::new();
    let mut parsed_component_assignments = HashSet::new();
    collect_resolution_metadata(
        items,
        &mut needed,
        &mut variables,
        &mut components,
        &mut parsed_component_assignments,
    );
    close_resolution_bindings(&mut needed, &variables);
    needed
}

fn close_resolution_bindings(needed: &mut HashSet<String>, variables: &[(String, &[Token])]) {
    loop {
        let before = needed.len();
        for (name, expression) in variables {
            if needed.contains(name) {
                extend_identifiers(needed, expression);
            }
        }
        if before == needed.len() {
            break;
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn collect_resolution_metadata<'a>(
    items: &'a [BodyItem],
    needed: &mut HashSet<String>,
    variables: &mut Vec<(String, &'a [Token])>,
    components: &mut HashSet<String>,
    parsed_component_assignments: &mut HashSet<(String, usize)>,
) {
    for item in items {
        match item {
            BodyItem::Variable {
                name, expression, ..
            } => variables.push((name.clone(), expression)),
            BodyItem::Instantiation {
                component_name,
                component_index,
                call,
                line,
                ..
            } => {
                components.insert(component_name.clone());
                parsed_component_assignments.insert((component_name.clone(), *line));
                if let Some(index) = component_index {
                    extend_identifiers(needed, index);
                }
                for argument in &call.arguments {
                    extend_identifiers(needed, argument);
                }
            }
            BodyItem::ComponentArray { name, length, .. } => {
                components.insert(name.clone());
                extend_identifiers(needed, length);
            }
            BodyItem::ForLoop {
                variable,
                initial,
                condition,
                body,
                ..
            } => {
                needed.insert(variable.clone());
                extend_identifiers(needed, condition);
                variables.push((variable.clone(), initial));
                collect_resolution_metadata(
                    body,
                    needed,
                    variables,
                    components,
                    parsed_component_assignments,
                );
            }
            BodyItem::Conditional {
                condition,
                then_body,
                else_body,
                ..
            } => {
                extend_identifiers(needed, condition);
                collect_resolution_metadata(
                    then_body,
                    needed,
                    variables,
                    components,
                    parsed_component_assignments,
                );
                collect_resolution_metadata(
                    else_body,
                    needed,
                    variables,
                    components,
                    parsed_component_assignments,
                );
            }
            BodyItem::Unsupported { .. } => {}
        }
    }
}

fn concrete_loop_update_positions(tokens: &[Token]) -> HashSet<usize> {
    let mut positions = HashSet::new();
    for (index, token) in tokens.iter().enumerate() {
        if !token_is_identifier(token, "for") {
            continue;
        }
        let Some(open) = tokens[index + 1..]
            .iter()
            .position(|token| token_is_symbol(token, '('))
            .map(|offset| index + 1 + offset)
        else {
            continue;
        };
        let Some(close) = find_matching(tokens, open, '(', ')') else {
            continue;
        };
        let Ok(groups) = split_top_level(&tokens[open + 1..close], ';') else {
            continue;
        };
        let loop_variable = groups.first().and_then(|initializer| {
            (initializer.len() >= 4
                && token_is_identifier(&initializer[0], "var")
                && initializer
                    .get(2)
                    .is_some_and(|token| token_is_symbol(token, '=')))
            .then(|| initializer.get(1).and_then(token_identifier))
            .flatten()
        });
        let update_is_counter = groups.get(2).is_some_and(|update| {
            matches!(
                update.as_slice(),
                [name, Token {
                    kind: TokenKind::Operator(operator),
                    ..
                }] if token_identifier(name) == loop_variable
                    && (operator == "++" || operator == "--")
            )
        });
        if update_is_counter && close >= open + 3 {
            positions.insert(close - 2);
        }
    }
    positions
}

fn concrete_loop_declaration_positions(tokens: &[Token]) -> HashSet<usize> {
    let mut positions = HashSet::new();
    for (index, token) in tokens.iter().enumerate() {
        if !token_is_identifier(token, "for") {
            continue;
        }
        let Some(open) = tokens[index + 1..]
            .iter()
            .position(|token| token_is_symbol(token, '('))
            .map(|offset| index + 1 + offset)
        else {
            continue;
        };
        let Some(close) = find_matching(tokens, open, '(', ')') else {
            continue;
        };
        if open + 3 < close
            && token_is_identifier(&tokens[open + 1], "var")
            && token_identifier(&tokens[open + 2]).is_some()
            && token_is_symbol(&tokens[open + 3], '=')
        {
            positions.insert(open + 2);
        }
    }
    positions
}

fn extend_identifiers(needed: &mut HashSet<String>, tokens: &[Token]) {
    needed.extend(
        tokens
            .iter()
            .filter_map(token_identifier)
            .map(str::to_string),
    );
}

fn load_inspection_files(
    path: &Path,
    project_root: &Path,
    library_paths: &[PathBuf],
    parsed_files: &mut HashMap<PathBuf, ParsedFile>,
    visited: &mut HashSet<PathBuf>,
    unsupported: &mut Vec<UnsupportedCase>,
) {
    if !visited.insert(path.to_path_buf()) {
        return;
    }
    let source = match fs::read_to_string(path) {
        Ok(source) => source,
        Err(error) => {
            unsupported.push(UnsupportedCase {
                source_path: path.into(),
                line: None,
                construct: "source file".into(),
                reason: format!("source could not be read: {error}"),
            });
            return;
        }
    };
    let file = match parse_file(path, &source) {
        Ok(file) => file,
        Err(issue) => {
            unsupported.push(issue);
            return;
        }
    };
    unsupported.extend(
        file.issues
            .iter()
            .filter(|issue| issue.construct != "template definition")
            .cloned(),
    );
    let includes = file.includes.clone();
    parsed_files.insert(path.into(), file);
    for include in includes {
        let candidates = [
            path.parent().unwrap_or(project_root).join(&include.path),
            project_root.join(&include.path),
        ]
        .into_iter()
        .chain(
            library_paths
                .iter()
                .map(|library| library.join(&include.path)),
        );
        let existing = candidates
            .filter_map(|p| fs::canonicalize(p).ok())
            .collect::<Vec<_>>();
        if let Some(included) = existing.iter().find(|candidate| {
            candidate.starts_with(project_root)
                || library_paths
                    .iter()
                    .any(|library| candidate.starts_with(library))
        }) {
            load_inspection_files(
                included,
                project_root,
                library_paths,
                parsed_files,
                visited,
                unsupported,
            );
        } else {
            unsupported.push(UnsupportedCase {
                source_path: path.into(),
                line: Some(include.line),
                construct: format!("include \"{}\"", include.path),
                reason: if existing.is_empty() {
                    "include could not be resolved inside the inspection project".into()
                } else {
                    "include resolves outside the inspection project root".into()
                },
            });
        }
    }
}

pub fn discover_project_targets(
    project: impl AsRef<Path>,
    output_root: impl AsRef<Path>,
    circom_bin: Option<&Path>,
) -> Result<TargetDiscoveryReport> {
    discover_project_targets_with(
        project,
        output_root,
        &DiscoveryOptions {
            circom_bin: circom_bin.map(Path::to_path_buf),
            ..DiscoveryOptions::default()
        },
    )
}

pub fn discover_project_targets_with(
    project: impl AsRef<Path>,
    output_root: impl AsRef<Path>,
    options: &DiscoveryOptions,
) -> Result<TargetDiscoveryReport> {
    let project_root = fs::canonicalize(project.as_ref()).with_context(|| {
        format!(
            "failed to resolve project root: {}",
            project.as_ref().display()
        )
    })?;
    anyhow::ensure!(
        options.compile_timeout_seconds > 0,
        "wrapper compile timeout must be positive"
    );
    let library_paths = options
        .library_paths
        .iter()
        .map(|path| {
            let library = fs::canonicalize(path)
                .with_context(|| format!("failed to resolve library path: {}", path.display()))?;
            anyhow::ensure!(
                library.is_dir(),
                "library path is not a directory: {}",
                library.display()
            );
            Ok(library)
        })
        .collect::<Result<Vec<_>>>()?;
    let selected_entrypoint = options
        .entrypoint
        .as_ref()
        .map(|path| {
            let entrypoint = fs::canonicalize(path)
                .with_context(|| format!("failed to resolve entrypoint: {}", path.display()))?;
            anyhow::ensure!(
                entrypoint.is_file() && entrypoint.starts_with(&project_root),
                "entrypoint must be a file inside the project root: {}",
                entrypoint.display()
            );
            Ok(entrypoint)
        })
        .transpose()?;
    anyhow::ensure!(
        library_paths.is_empty() || selected_entrypoint.is_some(),
        "library paths require a selected entrypoint"
    );
    let discovery_id = Uuid::new_v4().to_string();
    let work_dir = output_root.as_ref().join(&discovery_id);
    fs::create_dir_all(&work_dir).with_context(|| {
        format!(
            "failed to create discovery work dir: {}",
            work_dir.display()
        )
    })?;

    let mut parsed_files = HashMap::new();
    let mut unsupported = Vec::new();

    if let Some(entrypoint) = &selected_entrypoint {
        // Only the selected file's include closure is parsed; other mains are not candidates.
        load_discovery_closure(
            entrypoint,
            &project_root,
            &library_paths,
            &mut parsed_files,
            &mut HashSet::new(),
            &mut unsupported,
        );
    } else {
        for target in scanner::scan_project(&project_root)? {
            let path = fs::canonicalize(&target.path).with_context(|| {
                format!("failed to resolve Circom file: {}", target.path.display())
            })?;
            let source = fs::read_to_string(&path)
                .with_context(|| format!("failed to read Circom file: {}", path.display()))?;

            match parse_file(&path, &source) {
                Ok(parsed) => {
                    parsed_files.insert(path, parsed);
                }
                Err(issue) => unsupported.push(issue),
            }
        }
    }

    let entrypoints = parsed_files
        .values()
        .filter(|file| {
            selected_entrypoint
                .as_ref()
                .is_none_or(|entrypoint| &file.path == entrypoint)
        })
        .flat_map(|file| {
            file.mains.iter().map(|main| EntrypointCandidate {
                source_path: file.path.clone(),
                line: main.line,
                template_name: main.call.as_ref().map(|call| call.template_name.clone()),
                parameters: main
                    .call
                    .as_ref()
                    .map(|call| {
                        call.arguments
                            .iter()
                            .map(|argument| tokens_to_text(argument))
                            .collect()
                    })
                    .unwrap_or_default(),
            })
        })
        .collect::<Vec<_>>();

    let entrypoint_status = match entrypoints.len() {
        0 => EntrypointStatus::Missing,
        1 => EntrypointStatus::Found,
        _ => EntrypointStatus::Multiple,
    };
    let mut targets = Vec::new();
    let mut root_instance_key = None;

    if entrypoint_status == EntrypointStatus::Found {
        let entrypoint = &entrypoints[0];
        let parsed_entrypoint = &parsed_files[&entrypoint.source_path];
        let parsed_main = parsed_entrypoint
            .mains
            .iter()
            .find(|main| main.line == entrypoint.line)
            .expect("entrypoint should refer to a parsed main");

        if let Some(reason) = &parsed_main.failure_reason {
            unsupported.push(UnsupportedCase {
                source_path: entrypoint.source_path.clone(),
                line: Some(entrypoint.line),
                construct: "component main".to_string(),
                reason: reason.clone(),
            });
        } else if let Some(main_call) = &parsed_main.call {
            let mut reachable_files = HashSet::new();
            collect_reachable_files(
                &entrypoint.source_path,
                &project_root,
                &library_paths,
                &parsed_files,
                &mut reachable_files,
                &mut unsupported,
            );

            for path in &reachable_files {
                if let Some(file) = parsed_files.get(path) {
                    unsupported.extend(file.issues.clone());
                }
            }

            let template_index =
                build_template_index(&reachable_files, &parsed_files, &mut unsupported);
            let empty_bindings = HashMap::new();

            match evaluate_arguments(&main_call.arguments, &empty_bindings) {
                Ok(main_parameters) => {
                    if let Some(root) = resolve_template(
                        main_call,
                        &main_parameters,
                        &entrypoint.source_path,
                        entrypoint.line,
                        &template_index,
                        &mut unsupported,
                    ) {
                        root_instance_key = Some(instance_key(
                            &root.source_path,
                            &root.name,
                            &main_parameters
                                .iter()
                                .map(ToString::to_string)
                                .collect::<Vec<_>>(),
                        ));
                        let mut stack = vec![(root.name.clone(), main_parameters.clone())];
                        let mut expansion_budget = ExpansionBudget::new();
                        let mut seen_target_identities = HashSet::new();
                        expand_template(
                            root,
                            &main_parameters,
                            &template_index,
                            &mut stack,
                            &mut targets,
                            &mut unsupported,
                            0,
                            &mut expansion_budget,
                            &mut seen_target_identities,
                        );
                        if expansion_budget.exhausted {
                            targets.clear();
                        }
                        let mut binding_issues = Vec::new();
                        let mut checked_definitions = HashSet::new();
                        if checked_definitions.insert((root.source_path.clone(), root.name.clone()))
                        {
                            binding_issues.extend(inspect_binding_changes(root)?);
                        }
                        for target in &targets {
                            if checked_definitions
                                .insert((target.source_path.clone(), target.template_name.clone()))
                            {
                                let definition = template_index[&target.template_name]
                                    .iter()
                                    .find(|definition| definition.source_path == target.source_path)
                                    .expect("expanded target refers to a resolved definition");
                                binding_issues.extend(inspect_binding_changes(definition)?);
                            }
                        }
                        if !binding_issues.is_empty() {
                            unsupported.extend(binding_issues);
                            // Expansion may have used a stale value after a mutation.
                            targets.clear();
                        }
                    }
                }
                Err(reason) => unsupported.push(UnsupportedCase {
                    source_path: entrypoint.source_path.clone(),
                    line: Some(entrypoint.line),
                    construct: format_source_call(main_call),
                    reason: format!("main template parameters are not concrete: {reason}"),
                }),
            }
        }
    } else {
        let reason = if entrypoint_status == EntrypointStatus::Missing {
            "no top-level component main declaration was found"
        } else {
            "multiple top-level component main declarations were found"
        };
        unsupported.push(UnsupportedCase {
            source_path: project_root.clone(),
            line: None,
            construct: "project entrypoint".to_string(),
            reason: reason.to_string(),
        });
    }

    let instance_discovery = match (&options.instance_capture, &selected_entrypoint) {
        (Some(circom), Some(entrypoint)) if entrypoint_status == EntrypointStatus::Found => {
            Some(apply_instance_capture(
                circom,
                options.capture_timeout_seconds,
                entrypoint,
                &project_root,
                &library_paths,
                &work_dir,
                &mut targets,
                &mut unsupported,
                &mut root_instance_key,
            )?)
        }
        _ => None,
    };

    let compile_units = generate_and_validate_wrappers(
        &mut targets,
        &work_dir,
        &project_root,
        &library_paths,
        &parsed_files,
        options.circom_bin.as_deref(),
        options.compile_timeout_seconds,
    )?;
    let compile_attempt_count = compile_units
        .iter()
        .filter(|unit| unit.compile.is_some())
        .count();
    let compile_process_count = compile_units
        .iter()
        .filter(|unit| {
            unit.compile
                .as_ref()
                .is_some_and(|compile| compile.process_started == Some(true))
        })
        .count();

    let generated_wrapper_count = targets
        .iter()
        .filter(|target| target.generated_wrapper_path.is_some())
        .count();
    let compile_succeeded_count = targets
        .iter()
        .filter(|target| target.wrapper_status == WrapperStatus::CompileSucceeded)
        .count();

    let report = TargetDiscoveryReport {
        discovery_id,
        project_root,
        work_dir: work_dir.clone(),
        entrypoint_status,
        entrypoints,
        targets,
        generated_wrapper_count,
        compile_succeeded_count,
        unsupported,
        compile_timeout_seconds: options
            .circom_bin
            .is_some()
            .then_some(options.compile_timeout_seconds),
        selected_entrypoint,
        library_paths,
        root_instance_key,
        compile_units,
        compile_attempt_count,
        compile_process_count,
        instance_discovery,
    };
    write_report(&work_dir, &report)?;
    Ok(report)
}

type SlotKey = (String, String, usize);

fn slot_key(target: &ConcreteFuzzTarget) -> SlotKey {
    let name = &target.origin.component_name;
    let name = if name.starts_with("@anonymous:") {
        name.split('[').next().unwrap_or(name)
    } else {
        name
    };
    (
        target.parent_instance_key.clone(),
        name.to_owned(),
        target.origin.line,
    )
}

fn slots(targets: &[ConcreteFuzzTarget]) -> BTreeMap<SlotKey, BTreeSet<String>> {
    let mut slots: BTreeMap<SlotKey, BTreeSet<String>> = BTreeMap::new();
    for target in targets {
        slots
            .entry(slot_key(target))
            .or_default()
            .insert(target.instance_key.clone());
    }
    slots
}

fn format_call_tokens(template_name: &str, tokens: &[String]) -> String {
    format!("{template_name}({})", tokens.join(", "))
}

/// F-01: runs instance capture, builds compiler targets with the interpreter's identity format,
/// compares the two, and keeps the compiler result when the instrumented copy compiled and was
/// read. Otherwise the interpreter result stays, labeled as such.
#[allow(clippy::too_many_arguments)]
fn apply_instance_capture(
    circom: &Path,
    timeout_seconds: u64,
    entrypoint: &Path,
    project_root: &Path,
    library_paths: &[PathBuf],
    work_dir: &Path,
    targets: &mut Vec<ConcreteFuzzTarget>,
    unsupported: &mut Vec<UnsupportedCase>,
    root_instance_key: &mut Option<String>,
) -> Result<InstanceDiscovery> {
    use crate::instance_capture::{capture_instances, CaptureRequest};
    let capture = capture_instances(&CaptureRequest {
        entrypoint,
        project_root,
        library_paths,
        circom_bin: circom,
        work_dir: &work_dir.join("instance-capture"),
        timeout_seconds,
    })?;
    let capture_path = work_dir.join("instance-capture.json");
    fs::write(&capture_path, serde_json::to_vec(&capture.interned())?)?;
    let interpreter_complete = unsupported.is_empty();
    let mut discovery = InstanceDiscovery {
        selected: "interpreter".to_owned(),
        capture_status: capture.status.clone(),
        capture_failure: capture.failure.clone(),
        capture_path,
        instance_args_path: None,
        capture_compile_seconds: capture.compile_seconds,
        capture_compile_attempts: capture.compile_attempts,
        capture_scan_seconds: capture.scan_seconds,
        capture_read_seconds: capture.read_seconds,
        capture_assemble_seconds: capture.assemble_seconds,
        interpreter_complete,
        compiler_complete: capture.complete(),
        interpreter_targets: targets.len(),
        compiler_targets: 0,
        interpreter_root_instance_key: root_instance_key.clone(),
        compiler_root_instance_key: None,
        slots_compared: 0,
        slot_differences: Vec::new(),
        instance_keys_only_interpreter: Vec::new(),
        instance_keys_only_compiler: Vec::new(),
        interpreter_unsupported: Vec::new(),
    };
    if capture.status != "captured" {
        for target in targets.iter_mut() {
            target.instance_source = Some("interpreter".to_owned());
        }
        return Ok(discovery);
    }
    let prime = capture.prime()?;
    let by_path = capture
        .instances
        .iter()
        .map(|instance| (instance.path.as_str(), instance))
        .collect::<HashMap<_, _>>();
    let tokens_of =
        |instance: &crate::instance_capture::CapturedInstance| -> Result<Option<Vec<String>>> {
            instance
                .arguments
                .as_ref()
                .map(|arguments| {
                    arguments
                        .iter()
                        .map(|value| value.key_token(&prime))
                        .collect()
                })
                .transpose()
        };
    let interned = capture.interned();
    let mut arguments_by_key = BTreeMap::new();
    for instance in &interned.instances {
        if let Some(key) = interned.instance_key(instance)? {
            arguments_by_key.insert(
                key,
                serde_json::json!({
                    "template": instance.template_name,
                    "source_path": instance.source_path,
                    "arguments": instance.arguments,
                }),
            );
        }
    }
    let args_path = work_dir.join("instance-args.json");
    fs::write(
        &args_path,
        serde_json::to_vec_pretty(&serde_json::json!({
            "schema": "zkfdo-instance-args-v1",
            "prime": capture.prime,
            "array_key_encoding": "[sha256:<hex>] of compact JSON {\"dims\":[...],\"values\":[...]}, values row-major as decimals in [0, p)",
            "instances": arguments_by_key,
            "arrays": interned.arrays,
        }))?,
    )?;
    discovery.instance_args_path = Some(args_path);
    let mut compiler_targets = Vec::new();
    let mut compiler_unsupported = capture.unsupported.clone();
    let mut seen = HashSet::new();
    // Depth-first in path order, like the interpreter's expansion.
    let mut ordered = capture.instances.iter().collect::<Vec<_>>();
    ordered.sort_by_cached_key(|instance| natural_path_key(&instance.path));
    for instance in ordered {
        if instance.path == "main" {
            if let Some(tokens) = tokens_of(instance)? {
                discovery.compiler_root_instance_key = Some(instance_key(
                    &instance.source_path,
                    &instance.template_name,
                    &tokens,
                ));
            }
            continue;
        }
        let (Some(parent_path), Some(component_name), Some(line)) =
            (&instance.parent, &instance.component_name, instance.line)
        else {
            continue;
        };
        let Some(parent) = by_path.get(parent_path.as_str()) else {
            continue;
        };
        let (Some(tokens), Some(parent_tokens)) = (tokens_of(instance)?, tokens_of(parent)?) else {
            if instance.arguments.is_some() {
                compiler_unsupported.push(UnsupportedCase {
                    source_path: parent.source_path.clone(),
                    line: Some(line),
                    construct: format!("{} ({})", instance.path, instance.template_name),
                    reason: "instance capture: the parent instance's arguments were not captured"
                        .to_owned(),
                });
            }
            continue;
        };
        let identity = format!(
            "{}:{}:{}:{}->{}",
            parent.source_path.display(),
            line,
            format_call_tokens(&parent.template_name, &parent_tokens),
            component_name,
            format_call_tokens(&instance.template_name, &tokens)
        );
        if !seen.insert(identity.clone()) {
            continue;
        }
        let arguments = instance.arguments.as_ref().expect("tokens imply arguments");
        let wrapper_arguments = if arguments
            .iter()
            .any(|value| !matches!(value, crate::instance_capture::CapturedValue::Scalar { .. }))
        {
            Some(
                arguments
                    .iter()
                    .map(|value| capture.literal(value, &prime))
                    .collect::<Result<Vec<_>>>()?,
            )
        } else {
            None
        };
        compiler_targets.push(ConcreteFuzzTarget {
            identity,
            source_path: instance.source_path.clone(),
            template_name: instance.template_name.clone(),
            concrete_parameters: tokens.clone(),
            origin: TargetOrigin {
                source_path: parent.source_path.clone(),
                parent_template: parent.template_name.clone(),
                parent_parameters: parent_tokens.clone(),
                component_name: component_name.clone(),
                line,
            },
            generated_wrapper_path: None,
            wrapper_status: WrapperStatus::NotGenerated,
            compiler_stdout_path: None,
            compiler_stderr_path: None,
            failure_reason: None,
            compile: None,
            instance_key: instance_key(&instance.source_path, &instance.template_name, &tokens),
            parent_instance_key: instance_key(
                &parent.source_path,
                &parent.template_name,
                &parent_tokens,
            ),
            compile_unit: None,
            compile_reused: false,
            wrapper_arguments,
            instance_source: Some("compiler".to_owned()),
            methods_agree: None,
        });
    }
    // Comparison by call site: (parent instance, component, line) -> child instances.
    let interpreter_slots = slots(targets);
    let compiler_slots = slots(&compiler_targets);
    let keys = interpreter_slots
        .keys()
        .chain(compiler_slots.keys())
        .cloned()
        .collect::<BTreeSet<_>>();
    discovery.slots_compared = keys.len();
    for key in keys {
        let empty = BTreeSet::new();
        let (interpreter, compiler) = (
            interpreter_slots.get(&key).unwrap_or(&empty),
            compiler_slots.get(&key).unwrap_or(&empty),
        );
        if interpreter != compiler {
            discovery.slot_differences.push(SlotDifference {
                parent_instance_key: key.0,
                component_name: key.1,
                line: key.2,
                interpreter: interpreter.iter().cloned().collect(),
                compiler: compiler.iter().cloned().collect(),
            });
        }
    }
    let interpreter_keys = targets
        .iter()
        .map(|target| target.instance_key.clone())
        .collect::<BTreeSet<_>>();
    let compiler_keys = compiler_targets
        .iter()
        .map(|target| target.instance_key.clone())
        .collect::<BTreeSet<_>>();
    discovery.instance_keys_only_interpreter = interpreter_keys
        .difference(&compiler_keys)
        .cloned()
        .collect();
    discovery.instance_keys_only_compiler = compiler_keys
        .difference(&interpreter_keys)
        .cloned()
        .collect();
    for target in &mut compiler_targets {
        target.methods_agree = Some(
            interpreter_slots
                .get(&slot_key(target))
                .is_some_and(|keys| keys.contains(&target.instance_key)),
        );
    }
    discovery.compiler_targets = compiler_targets.len();
    discovery.selected = "compiler".to_owned();
    discovery.interpreter_unsupported = std::mem::take(unsupported);
    *unsupported = compiler_unsupported;
    *targets = compiler_targets;
    *root_instance_key = discovery.compiler_root_instance_key.clone();
    Ok(discovery)
}

/// Orders instance paths depth-first with numeric indices compared as numbers.
fn natural_path_key(path: &str) -> Vec<(String, u64)> {
    let mut key = Vec::new();
    let mut text = String::new();
    let mut digits = String::new();
    for character in path.chars() {
        if character.is_ascii_digit() {
            digits.push(character);
        } else {
            if !digits.is_empty() {
                key.push((
                    std::mem::take(&mut text),
                    digits.parse().unwrap_or(u64::MAX),
                ));
                digits.clear();
            }
            text.push(character);
        }
    }
    key.push((text, digits.parse().unwrap_or(0)));
    key
}

fn build_template_index<'a>(
    reachable_files: &HashSet<PathBuf>,
    parsed_files: &'a HashMap<PathBuf, ParsedFile>,
    unsupported: &mut Vec<UnsupportedCase>,
) -> HashMap<String, Vec<&'a TemplateDefinition>> {
    let mut index: HashMap<String, Vec<&TemplateDefinition>> = HashMap::new();
    for path in reachable_files {
        if let Some(file) = parsed_files.get(path) {
            for template in &file.templates {
                index
                    .entry(template.name.clone())
                    .or_default()
                    .push(template);
            }
        }
    }

    for (name, definitions) in &index {
        if definitions.len() > 1 {
            unsupported.push(UnsupportedCase {
                source_path: definitions[0].source_path.clone(),
                line: None,
                construct: format!("template {name}"),
                reason: "multiple reachable definitions use the same template name".to_string(),
            });
        }
    }
    index
}

fn resolve_template<'a>(
    call: &TemplateCall,
    parameters: &[i128],
    source_path: &Path,
    line: usize,
    template_index: &'a HashMap<String, Vec<&TemplateDefinition>>,
    unsupported: &mut Vec<UnsupportedCase>,
) -> Option<&'a TemplateDefinition> {
    let definitions = match template_index.get(&call.template_name) {
        Some(definitions) if definitions.len() == 1 => definitions,
        Some(_) => {
            unsupported.push(UnsupportedCase {
                source_path: source_path.to_path_buf(),
                line: Some(line),
                construct: format_call(&call.template_name, parameters),
                reason: "template name is ambiguous".to_string(),
            });
            return None;
        }
        None => {
            unsupported.push(UnsupportedCase {
                source_path: source_path.to_path_buf(),
                line: Some(line),
                construct: format_call(&call.template_name, parameters),
                reason: "template definition is not reachable from the project entrypoint"
                    .to_string(),
            });
            return None;
        }
    };
    let definition = definitions[0];
    if definition.parameters.len() != parameters.len() {
        unsupported.push(UnsupportedCase {
            source_path: source_path.to_path_buf(),
            line: Some(line),
            construct: format_call(&call.template_name, parameters),
            reason: format!(
                "template expects {} parameters but {} were supplied",
                definition.parameters.len(),
                parameters.len()
            ),
        });
        return None;
    }
    Some(definition)
}

fn consume_expansion_step(
    budget: &mut ExpansionBudget,
    unsupported: &mut Vec<UnsupportedCase>,
    source_path: &Path,
    line: Option<usize>,
    construct: String,
) -> bool {
    let already_exhausted = budget.exhausted;
    if budget.consume() {
        return true;
    }
    if !already_exhausted {
        unsupported.push(UnsupportedCase {
            source_path: source_path.to_path_buf(),
            line,
            construct,
            reason: format!(
                "total target expansion exceeded the inspection limit of {MAX_TOTAL_EXPANSION_STEPS} steps"
            ),
        });
    }
    false
}

#[allow(clippy::too_many_arguments)]
fn expand_template(
    definition: &TemplateDefinition,
    concrete_parameters: &[i128],
    template_index: &HashMap<String, Vec<&TemplateDefinition>>,
    stack: &mut Vec<(String, Vec<i128>)>,
    targets: &mut Vec<ConcreteFuzzTarget>,
    unsupported: &mut Vec<UnsupportedCase>,
    depth: usize,
    expansion_budget: &mut ExpansionBudget,
    seen_target_identities: &mut HashSet<String>,
) {
    if depth >= MAX_INSTANTIATION_DEPTH {
        unsupported.push(UnsupportedCase {
            source_path: definition.source_path.clone(),
            line: None,
            construct: format_call(&definition.name, concrete_parameters),
            reason: format!(
                "instantiation depth exceeded the MVP limit of {MAX_INSTANTIATION_DEPTH}"
            ),
        });
        return;
    }

    let mut bindings = definition
        .parameters
        .iter()
        .cloned()
        .zip(concrete_parameters.iter().copied())
        .collect::<HashMap<_, _>>();
    let mut component_arrays = HashMap::new();
    let mut initialized_components = HashSet::new();
    let needed_bindings = resolution_needed_bindings(&definition.body);
    expand_body(
        &definition.body,
        definition,
        concrete_parameters,
        template_index,
        stack,
        targets,
        unsupported,
        depth,
        &mut bindings,
        &mut component_arrays,
        &mut initialized_components,
        &needed_bindings,
        expansion_budget,
        seen_target_identities,
    );
}

#[allow(clippy::too_many_arguments)]
fn expand_body(
    items: &[BodyItem],
    definition: &TemplateDefinition,
    concrete_parameters: &[i128],
    template_index: &HashMap<String, Vec<&TemplateDefinition>>,
    stack: &mut Vec<(String, Vec<i128>)>,
    targets: &mut Vec<ConcreteFuzzTarget>,
    unsupported: &mut Vec<UnsupportedCase>,
    depth: usize,
    bindings: &mut HashMap<String, i128>,
    component_arrays: &mut HashMap<String, usize>,
    initialized_components: &mut HashSet<String>,
    needed_bindings: &HashSet<String>,
    expansion_budget: &mut ExpansionBudget,
    seen_target_identities: &mut HashSet<String>,
) {
    for item in items {
        if expansion_budget.exhausted {
            return;
        }
        match item {
            BodyItem::Variable { name, .. } if !needed_bindings.contains(name) => {}
            BodyItem::Variable {
                name,
                expression,
                line,
            } => match evaluate_expression(expression, bindings) {
                Ok(value) => {
                    bindings.insert(name.clone(), value);
                }
                Err(reason) => unsupported.push(UnsupportedCase {
                    source_path: definition.source_path.clone(),
                    line: Some(*line),
                    construct: format!("var {name} = {}", tokens_to_text(expression)),
                    reason: format!("compile-time variable is not supported: {reason}"),
                }),
            },
            BodyItem::ComponentArray { name, length, line } => {
                let length = match evaluate_expression(length, bindings) {
                    Ok(length) => length,
                    Err(reason) => {
                        unsupported.push(UnsupportedCase {
                            source_path: definition.source_path.clone(),
                            line: Some(*line),
                            construct: format!("component {name}[...]"),
                            reason: format!("component array length is not concrete: {reason}"),
                        });
                        continue;
                    }
                };
                let Ok(length) = usize::try_from(length) else {
                    unsupported.push(UnsupportedCase {
                        source_path: definition.source_path.clone(),
                        line: Some(*line),
                        construct: format!("component {name}[{length}]"),
                        reason:
                            "component array length must be a non-negative platform-sized integer"
                                .to_string(),
                    });
                    continue;
                };
                if component_arrays.insert(name.clone(), length).is_some() {
                    unsupported.push(UnsupportedCase {
                        source_path: definition.source_path.clone(),
                        line: Some(*line),
                        construct: format!("component {name}[{length}]"),
                        reason: "duplicate component array declarations are unsupported"
                            .to_string(),
                    });
                }
            }
            BodyItem::Instantiation {
                component_name,
                component_index,
                call,
                line,
                anonymous,
            } => {
                let concrete_component_name = if *anonymous {
                    let mut context = bindings.iter().collect::<Vec<_>>();
                    context.sort_by(|a, b| a.0.cmp(b.0));
                    format!(
                        "{component_name}[{}]",
                        context
                            .iter()
                            .map(|(name, value)| format!("{name}={value}"))
                            .collect::<Vec<_>>()
                            .join(",")
                    )
                } else if let Some(index) = component_index {
                    let index = match evaluate_expression(index, bindings) {
                        Ok(index) => index,
                        Err(reason) => {
                            unsupported.push(UnsupportedCase {
                                source_path: definition.source_path.clone(),
                                line: Some(*line),
                                construct: format!("{component_name}[...]"),
                                reason: format!("component array index is not concrete: {reason}"),
                            });
                            continue;
                        }
                    };
                    let Some(length) = component_arrays.get(component_name).copied() else {
                        unsupported.push(UnsupportedCase {
                            source_path: definition.source_path.clone(),
                            line: Some(*line),
                            construct: format!("{component_name}[{index}]"),
                            reason: "component array assignment has no concrete declaration"
                                .to_string(),
                        });
                        continue;
                    };
                    let Ok(index) = usize::try_from(index) else {
                        unsupported.push(UnsupportedCase {
                            source_path: definition.source_path.clone(),
                            line: Some(*line),
                            construct: format!("{component_name}[{index}]"),
                            reason: "component array index must be non-negative".to_string(),
                        });
                        continue;
                    };
                    if index >= length {
                        unsupported.push(UnsupportedCase {
                            source_path: definition.source_path.clone(),
                            line: Some(*line),
                            construct: format!("{component_name}[{index}]"),
                            reason: format!(
                                "component array index is outside the concrete length {length}"
                            ),
                        });
                        continue;
                    }
                    format!("{component_name}[{index}]")
                } else {
                    component_name.clone()
                };
                if !*anonymous && !initialized_components.insert(concrete_component_name.clone()) {
                    unsupported.push(UnsupportedCase {
                        source_path: definition.source_path.clone(),
                        line: Some(*line),
                        construct: concrete_component_name,
                        reason: "component is assigned more than once in the concrete expansion"
                            .to_string(),
                    });
                    continue;
                }
                let parameters = match evaluate_arguments(&call.arguments, bindings) {
                    Ok(parameters) => parameters,
                    Err(reason) => {
                        unsupported.push(UnsupportedCase {
                            source_path: definition.source_path.clone(),
                            line: Some(*line),
                            construct: format!(
                                "component {component_name} = {}",
                                format_source_call(call)
                            ),
                            reason: format!("template parameters are not concrete: {reason}"),
                        });
                        continue;
                    }
                };
                let child = match resolve_template(
                    call,
                    &parameters,
                    &definition.source_path,
                    *line,
                    template_index,
                    unsupported,
                ) {
                    Some(child) => child,
                    None => continue,
                };
                let parameter_strings = parameters
                    .iter()
                    .map(ToString::to_string)
                    .collect::<Vec<_>>();
                let parent_parameter_strings = concrete_parameters
                    .iter()
                    .map(ToString::to_string)
                    .collect::<Vec<_>>();
                let identity = format!(
                    "{}:{}:{}:{}->{}",
                    definition.source_path.display(),
                    line,
                    format_call(&definition.name, concrete_parameters),
                    concrete_component_name,
                    format_call(&call.template_name, &parameters)
                );

                if !seen_target_identities.insert(identity.clone()) {
                    continue;
                }
                if !consume_expansion_step(
                    expansion_budget,
                    unsupported,
                    &definition.source_path,
                    Some(*line),
                    identity.clone(),
                ) {
                    return;
                }

                let child_instance_key =
                    instance_key(&child.source_path, &call.template_name, &parameter_strings);
                let parent_instance_key = instance_key(
                    &definition.source_path,
                    &definition.name,
                    &parent_parameter_strings,
                );
                targets.push(ConcreteFuzzTarget {
                    identity,
                    source_path: child.source_path.clone(),
                    template_name: call.template_name.clone(),
                    concrete_parameters: parameter_strings,
                    origin: TargetOrigin {
                        source_path: definition.source_path.clone(),
                        parent_template: definition.name.clone(),
                        parent_parameters: parent_parameter_strings,
                        component_name: concrete_component_name,
                        line: *line,
                    },
                    generated_wrapper_path: None,
                    wrapper_status: WrapperStatus::NotGenerated,
                    compiler_stdout_path: None,
                    compiler_stderr_path: None,
                    failure_reason: None,
                    compile: None,
                    instance_key: child_instance_key,
                    parent_instance_key,
                    compile_unit: None,
                    compile_reused: false,
                    wrapper_arguments: None,
                    instance_source: None,
                    methods_agree: None,
                });

                let key = (child.name.clone(), parameters.clone());
                if stack.contains(&key) {
                    unsupported.push(UnsupportedCase {
                        source_path: definition.source_path.clone(),
                        line: Some(*line),
                        construct: format_call(&child.name, &parameters),
                        reason: "recursive concrete template instantiation is unsupported"
                            .to_string(),
                    });
                    continue;
                }

                stack.push(key);
                expand_template(
                    child,
                    &parameters,
                    template_index,
                    stack,
                    targets,
                    unsupported,
                    depth + 1,
                    expansion_budget,
                    seen_target_identities,
                );
                stack.pop();
            }
            BodyItem::ForLoop {
                variable,
                initial,
                condition,
                update,
                body,
                line,
            } => {
                let initial_value = match evaluate_expression(initial, bindings) {
                    Ok(value) => value,
                    Err(reason) => {
                        unsupported.push(UnsupportedCase {
                            source_path: definition.source_path.clone(),
                            line: Some(*line),
                            construct: format!("for ({variable} = ... )"),
                            reason: format!("loop initial value is not concrete: {reason}"),
                        });
                        continue;
                    }
                };
                let previous = bindings.insert(variable.clone(), initial_value);
                let mut iteration_count = 0_usize;
                let mut current = initial_value;
                let mut loop_failure = None;
                loop {
                    bindings.insert(variable.clone(), current);
                    let condition_value = match evaluate_expression(condition, bindings) {
                        Ok(value) => value,
                        Err(reason) => {
                            loop_failure =
                                Some(format!("loop condition is not concrete: {reason}"));
                            break;
                        }
                    };
                    if condition_value == 0 {
                        break;
                    }
                    if iteration_count >= MAX_COMPILE_TIME_LOOP_ITERATIONS {
                        loop_failure = Some(format!(
                            "loop exceeded the inspection limit of {MAX_COMPILE_TIME_LOOP_ITERATIONS} iterations"
                        ));
                        break;
                    }
                    iteration_count += 1;
                    current = match update {
                        LoopUpdate::Increment => current.checked_add(1),
                        LoopUpdate::Decrement => current.checked_sub(1),
                    }
                    .unwrap_or_else(|| {
                        loop_failure = Some("loop counter overflowed i128".to_string());
                        current
                    });
                    if loop_failure.is_some() {
                        break;
                    }
                }
                match previous {
                    Some(value) => {
                        bindings.insert(variable.clone(), value);
                    }
                    None => {
                        bindings.remove(variable);
                    }
                }
                if let Some(reason) = loop_failure {
                    unsupported.push(UnsupportedCase {
                        source_path: definition.source_path.clone(),
                        line: Some(*line),
                        construct: format!("for ({variable}; ... )"),
                        reason,
                    });
                    continue;
                }
                let mut value = initial_value;
                for _ in 0..iteration_count {
                    if !consume_expansion_step(
                        expansion_budget,
                        unsupported,
                        &definition.source_path,
                        Some(*line),
                        format!("for ({variable}; ... )"),
                    ) {
                        break;
                    }
                    let previous = bindings.insert(variable.clone(), value);
                    expand_body(
                        body,
                        definition,
                        concrete_parameters,
                        template_index,
                        stack,
                        targets,
                        unsupported,
                        depth,
                        bindings,
                        component_arrays,
                        initialized_components,
                        needed_bindings,
                        expansion_budget,
                        seen_target_identities,
                    );
                    match previous {
                        Some(value) => {
                            bindings.insert(variable.clone(), value);
                        }
                        None => {
                            bindings.remove(variable);
                        }
                    }
                    if expansion_budget.exhausted {
                        break;
                    }
                    value = match update {
                        LoopUpdate::Increment => value.checked_add(1),
                        LoopUpdate::Decrement => value.checked_sub(1),
                    }
                    .expect("loop counter was validated before concrete expansion");
                }
            }
            BodyItem::Conditional {
                condition,
                then_body,
                else_body,
                line,
            } => match evaluate_expression(condition, bindings) {
                Ok(value) => expand_body(
                    if value != 0 { then_body } else { else_body },
                    definition,
                    concrete_parameters,
                    template_index,
                    stack,
                    targets,
                    unsupported,
                    depth,
                    bindings,
                    component_arrays,
                    initialized_components,
                    needed_bindings,
                    expansion_budget,
                    seen_target_identities,
                ),
                Err(reason) => unsupported.push(UnsupportedCase {
                    source_path: definition.source_path.clone(),
                    line: Some(*line),
                    construct: format!("if ({})", tokens_to_text(condition)),
                    reason: format!("compile-time condition is not concrete: {reason}"),
                }),
            },
            BodyItem::Unsupported {
                line,
                construct,
                reason,
            } => unsupported.push(UnsupportedCase {
                source_path: definition.source_path.clone(),
                line: Some(*line),
                construct: construct.clone(),
                reason: reason.clone(),
            }),
        }
    }
}

/// One wrapper and at most one compiler run per compile unit. Call-site entries stay separate:
/// each keeps its identity, origin and instance keys, so caller context is never merged.
fn generate_and_validate_wrappers(
    targets: &mut [ConcreteFuzzTarget],
    work_dir: &Path,
    project_root: &Path,
    library_paths: &[PathBuf],
    parsed_files: &HashMap<PathBuf, ParsedFile>,
    circom_bin: Option<&Path>,
    compile_timeout_seconds: u64,
) -> Result<Vec<CompileUnit>> {
    let mut identities = HashSet::new();
    for target in targets.iter() {
        anyhow::ensure!(
            identities.insert(target.identity.as_str()),
            "duplicate concrete target identity before wrapper generation: {}",
            target.identity
        );
    }
    let wrappers_dir = work_dir.join("wrappers");
    fs::create_dir_all(&wrappers_dir)
        .with_context(|| format!("failed to create wrapper dir: {}", wrappers_dir.display()))?;

    // The wrapper includes the target by absolute path, so the compiler needs the same
    // project-root and library fallbacks that discovery used to resolve nested includes.
    let mut settings = vec!["--inspect".to_owned()];
    for library in std::iter::once(project_root).chain(library_paths.iter().map(PathBuf::as_path)) {
        settings.push("-l".to_owned());
        settings.push(library.to_string_lossy().into_owned());
    }
    let compiler = circom_bin.map(|binary| {
        let resolved = crate::experiment::resolve_executable(binary).ok();
        let sha256 = resolved
            .as_ref()
            .and_then(|path| fs::read(path).ok())
            .map(|bytes| sha256_hex(&bytes));
        (resolved, sha256)
    });
    let mut file_hashes = HashMap::new();
    let mut units: Vec<CompileUnit> = Vec::new();
    let mut unit_by_key = HashMap::new();

    for target in targets.iter_mut() {
        if include_closure_contains_main(
            &target.source_path,
            project_root,
            library_paths,
            parsed_files,
            &mut HashSet::new(),
        ) {
            target.wrapper_status = WrapperStatus::Unsupported;
            target.failure_reason = Some(
                "the target source include closure already declares component main".to_string(),
            );
            continue;
        }

        let include_path = target
            .source_path
            .to_string_lossy()
            .replace('\\', "/")
            .replace('"', "\\\"");
        let parameters = target
            .wrapper_arguments
            .as_ref()
            .unwrap_or(&target.concrete_parameters)
            .join(", ");
        let wrapper = format!(
            "pragma circom 2.1.6;\n\ninclude \"{include_path}\";\n\ncomponent main = {}({parameters});\n",
            target.template_name
        );
        let mut dependencies = Vec::new();
        let mut unresolved_includes = Vec::new();
        collect_dependency_fingerprints(
            &target.source_path,
            project_root,
            library_paths,
            parsed_files,
            &mut HashSet::new(),
            &mut file_hashes,
            &mut dependencies,
            &mut unresolved_includes,
        )?;
        dependencies.sort();
        unresolved_includes.sort();
        unresolved_includes.dedup();
        let key = sha256_hex(
            serde_json::to_string(&serde_json::json!({
                "wrapper": wrapper,
                "dependencies": dependencies,
                "unresolved_includes": unresolved_includes,
                "compiler": compiler,
                "settings": settings,
                "compile_timeout_seconds": circom_bin.map(|_| compile_timeout_seconds),
            }))?
            .as_bytes(),
        );

        if let Some(&unit_index) = unit_by_key.get(&key) {
            let unit: &mut CompileUnit = &mut units[unit_index];
            unit.call_site_identities.push(target.identity.clone());
            unit.apply_to(target, true);
            continue;
        }

        let unit_index = units.len();
        let unit_dir = wrappers_dir.join(format!(
            "{unit_index:04}-{}",
            sanitize_file_component(&target.template_name)
        ));
        fs::create_dir_all(&unit_dir)
            .with_context(|| format!("failed to create target work dir: {}", unit_dir.display()))?;
        let wrapper_path = unit_dir.join("target.circom");
        fs::write(&wrapper_path, &wrapper)
            .with_context(|| format!("failed to write wrapper: {}", wrapper_path.display()))?;
        let mut unit = CompileUnit {
            key: key.clone(),
            instance_key: target.instance_key.clone(),
            wrapper_path: wrapper_path.clone(),
            dependencies: dependencies
                .into_iter()
                .map(|(path, sha256)| DependencyFingerprint { path, sha256 })
                .collect(),
            unresolved_includes,
            compiler_binary: compiler.as_ref().and_then(|(path, _)| path.clone()),
            compiler_sha256: compiler.as_ref().and_then(|(_, sha256)| sha256.clone()),
            settings: settings.clone(),
            call_site_identities: vec![target.identity.clone()],
            wrapper_status: WrapperStatus::Generated,
            failure_reason: None,
            compile: None,
        };

        if let Some(circom_bin) = circom_bin {
            let compiler_output_dir = unit_dir.join("circom-output");
            fs::create_dir_all(&compiler_output_dir).with_context(|| {
                format!(
                    "failed to create compiler output dir: {}",
                    compiler_output_dir.display()
                )
            })?;
            let mut args = vec![wrapper_path.to_string_lossy().into_owned()];
            args.extend(settings.iter().take(1).cloned());
            args.push("--output".to_owned());
            args.push(compiler_output_dir.to_string_lossy().into_owned());
            args.extend(settings.iter().skip(1).cloned());
            // Bounded: the compiler runs in its own process group, which is killed at the limit.
            let capture = capture_tool(
                circom_bin,
                args,
                "circom",
                &unit_dir,
                compile_timeout_seconds,
            )?;
            if capture.timed_out {
                unit.wrapper_status = WrapperStatus::CompileTimedOut;
                unit.failure_reason = Some(format!(
                    "wrapper compilation exceeded {compile_timeout_seconds} seconds and was terminated"
                ));
            } else if capture.success {
                unit.wrapper_status = WrapperStatus::CompileSucceeded;
            } else if capture.process_started == Some(false) {
                unit.wrapper_status = WrapperStatus::CompilerUnavailable;
                unit.failure_reason = Some(format!(
                    "failed to start Circom compiler {}: {}",
                    circom_bin.display(),
                    capture.error.as_deref().unwrap_or_default()
                ));
            } else {
                unit.wrapper_status = WrapperStatus::CompileFailed;
                unit.failure_reason = Some(
                    fs::read_to_string(&capture.stderr_path)
                        .unwrap_or_default()
                        .trim()
                        .to_string(),
                );
            }
            unit.compile = Some(capture);
        }
        unit.apply_to(target, false);
        unit_by_key.insert(key, unit_index);
        units.push(unit);
    }
    Ok(units)
}

/// Hashes every file in the include closure of `path`, resolved exactly as discovery resolves it.
#[allow(clippy::too_many_arguments)]
fn collect_dependency_fingerprints(
    path: &Path,
    project_root: &Path,
    library_paths: &[PathBuf],
    parsed_files: &HashMap<PathBuf, ParsedFile>,
    visited: &mut HashSet<PathBuf>,
    file_hashes: &mut HashMap<PathBuf, String>,
    dependencies: &mut Vec<(PathBuf, String)>,
    unresolved_includes: &mut Vec<String>,
) -> Result<()> {
    if !visited.insert(path.to_path_buf()) {
        return Ok(());
    }
    let sha256 = match file_hashes.get(path) {
        Some(sha256) => sha256.clone(),
        None => {
            let bytes = fs::read(path)
                .with_context(|| format!("failed to hash dependency: {}", path.display()))?;
            let sha256 = sha256_hex(&bytes);
            file_hashes.insert(path.to_path_buf(), sha256.clone());
            sha256
        }
    };
    dependencies.push((path.to_path_buf(), sha256));
    let Some(file) = parsed_files.get(path) else {
        return Ok(());
    };
    for include in &file.includes {
        match resolve_include(
            path,
            &include.path,
            project_root,
            library_paths,
            parsed_files,
        ) {
            Some(included) => collect_dependency_fingerprints(
                &included,
                project_root,
                library_paths,
                parsed_files,
                visited,
                file_hashes,
                dependencies,
                unresolved_includes,
            )?,
            None => unresolved_includes.push(format!("{}: {}", path.display(), include.path)),
        }
    }
    Ok(())
}

fn sha256_hex(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

pub(crate) fn instance_key(
    source_path: &Path,
    template_name: &str,
    parameters: &[String],
) -> String {
    format!(
        "{}::{template_name}({})",
        source_path.display(),
        parameters.join(", ")
    )
}

/// Returns the canonical discovery identity for one concrete template instance.
/// Review code uses this to bind a compiled direct wrapper's `component main`
/// to the same source/template/parameter tuple recorded by target discovery.
pub fn concrete_instance_key(
    source_path: &Path,
    template_name: &str,
    parameters: &[String],
) -> Result<String> {
    anyhow::ensure!(!template_name.trim().is_empty(), "template name is empty");
    let source_path = fs::canonicalize(source_path)
        .with_context(|| format!("resolve concrete instance source {}", source_path.display()))?;
    Ok(instance_key(&source_path, template_name, parameters))
}

/// Parses the selected entrypoint and every file its includes resolve to. Unresolved includes
/// are reported later by `collect_reachable_files`, so they are not duplicated here.
fn load_discovery_closure(
    path: &Path,
    project_root: &Path,
    library_paths: &[PathBuf],
    parsed_files: &mut HashMap<PathBuf, ParsedFile>,
    visited: &mut HashSet<PathBuf>,
    unsupported: &mut Vec<UnsupportedCase>,
) {
    if !visited.insert(path.to_path_buf()) {
        return;
    }
    let source = match fs::read_to_string(path) {
        Ok(source) => source,
        Err(error) => {
            unsupported.push(UnsupportedCase {
                source_path: path.into(),
                line: None,
                construct: "source file".into(),
                reason: format!("source could not be read: {error}"),
            });
            return;
        }
    };
    let file = match parse_file(path, &source) {
        Ok(file) => file,
        Err(issue) => {
            unsupported.push(issue);
            return;
        }
    };
    let includes = file.includes.clone();
    parsed_files.insert(path.into(), file);
    for include in includes {
        if let Some(included) = include_candidates(path, &include.path, project_root, library_paths)
            .into_iter()
            .find_map(|candidate| fs::canonicalize(candidate).ok())
        {
            load_discovery_closure(
                &included,
                project_root,
                library_paths,
                parsed_files,
                visited,
                unsupported,
            );
        }
    }
}

fn collect_reachable_files(
    path: &Path,
    project_root: &Path,
    library_paths: &[PathBuf],
    parsed_files: &HashMap<PathBuf, ParsedFile>,
    reachable: &mut HashSet<PathBuf>,
    unsupported: &mut Vec<UnsupportedCase>,
) {
    if !reachable.insert(path.to_path_buf()) {
        return;
    }
    let Some(file) = parsed_files.get(path) else {
        return;
    };
    for include in &file.includes {
        match resolve_include(
            path,
            &include.path,
            project_root,
            library_paths,
            parsed_files,
        ) {
            Some(included_path) => collect_reachable_files(
                &included_path,
                project_root,
                library_paths,
                parsed_files,
                reachable,
                unsupported,
            ),
            None => unsupported.push(UnsupportedCase {
                source_path: path.to_path_buf(),
                line: Some(include.line),
                construct: format!("include \"{}\"", include.path),
                reason: "include could not be resolved inside the scanned project".to_string(),
            }),
        }
    }
}

fn include_closure_contains_main(
    path: &Path,
    project_root: &Path,
    library_paths: &[PathBuf],
    parsed_files: &HashMap<PathBuf, ParsedFile>,
    visited: &mut HashSet<PathBuf>,
) -> bool {
    if !visited.insert(path.to_path_buf()) {
        return false;
    }
    let Some(file) = parsed_files.get(path) else {
        return false;
    };
    if !file.mains.is_empty() {
        return true;
    }
    file.includes.iter().any(|include| {
        resolve_include(
            path,
            &include.path,
            project_root,
            library_paths,
            parsed_files,
        )
        .is_some_and(|included_path| {
            include_closure_contains_main(
                &included_path,
                project_root,
                library_paths,
                parsed_files,
                visited,
            )
        })
    })
}

/// Circom order: the including file's directory, then the project root, then each
/// `-l` library path in the order given.
fn include_candidates(
    source_path: &Path,
    include: &str,
    project_root: &Path,
    library_paths: &[PathBuf],
) -> Vec<PathBuf> {
    source_path
        .parent()
        .map(|parent| parent.join(include))
        .into_iter()
        .chain(std::iter::once(project_root.join(include)))
        .chain(library_paths.iter().map(|library| library.join(include)))
        .collect()
}

fn resolve_include(
    source_path: &Path,
    include: &str,
    project_root: &Path,
    library_paths: &[PathBuf],
    parsed_files: &HashMap<PathBuf, ParsedFile>,
) -> Option<PathBuf> {
    include_candidates(source_path, include, project_root, library_paths)
        .into_iter()
        .filter_map(|candidate| fs::canonicalize(candidate).ok())
        .find(|candidate| parsed_files.contains_key(candidate))
}

fn parse_file(path: &Path, source: &str) -> std::result::Result<ParsedFile, UnsupportedCase> {
    let tokens = lex(source).map_err(|(line, reason)| UnsupportedCase {
        source_path: path.to_path_buf(),
        line: Some(line),
        construct: "source file".to_string(),
        reason,
    })?;
    let mut file = ParsedFile {
        path: path.to_path_buf(),
        includes: Vec::new(),
        mains: Vec::new(),
        templates: Vec::new(),
        issues: Vec::new(),
    };
    let mut cursor = 0;

    while cursor < tokens.len() {
        if token_is_identifier(&tokens[cursor], "include") {
            let line = tokens[cursor].line;
            match tokens.get(cursor + 1).map(|token| &token.kind) {
                Some(TokenKind::StringLiteral(include)) => {
                    file.includes.push(IncludeDirective {
                        path: include.clone(),
                        line,
                    });
                }
                _ => file.issues.push(UnsupportedCase {
                    source_path: path.to_path_buf(),
                    line: Some(line),
                    construct: "include".to_string(),
                    reason: "include path must be a string literal".to_string(),
                }),
            }
            cursor = find_statement_end(&tokens, cursor)
                .map(|end| end + 1)
                .unwrap_or(tokens.len());
            continue;
        }

        if token_is_identifier(&tokens[cursor], "template") {
            match parse_template_definition(path, &tokens, cursor) {
                Ok((template, next)) => {
                    file.templates.push(template);
                    cursor = next;
                }
                Err((line, reason)) => {
                    file.issues.push(UnsupportedCase {
                        source_path: path.to_path_buf(),
                        line: Some(line),
                        construct: "template definition".to_string(),
                        reason,
                    });
                    cursor += 1;
                }
            }
            continue;
        }

        if token_is_identifier(&tokens[cursor], "component")
            && tokens
                .get(cursor + 1)
                .is_some_and(|token| token_is_identifier(token, "main"))
        {
            let line = tokens[cursor].line;
            let end = find_statement_end(&tokens, cursor).unwrap_or(tokens.len() - 1);
            file.mains
                .push(parse_main_declaration(&tokens[cursor..end], line));
            cursor = end + 1;
            continue;
        }
        cursor += 1;
    }
    Ok(file)
}

fn parse_template_definition(
    path: &Path,
    tokens: &[Token],
    start: usize,
) -> std::result::Result<(TemplateDefinition, usize), (usize, String)> {
    let line = tokens[start].line;
    let name = match tokens.get(start + 1).map(|token| &token.kind) {
        Some(TokenKind::Identifier(name)) => name.clone(),
        _ => return Err((line, "template name is missing or unsupported".to_string())),
    };
    let open_parameters = start + 2;
    if !tokens
        .get(open_parameters)
        .is_some_and(|token| token_is_symbol(token, '('))
    {
        return Err((line, "template parameter list is missing".to_string()));
    }
    let close_parameters = find_matching(tokens, open_parameters, '(', ')')
        .ok_or_else(|| (line, "template parameter list is unbalanced".to_string()))?;
    let parameter_groups = split_top_level(&tokens[open_parameters + 1..close_parameters], ',')
        .map_err(|reason| (line, reason))?;
    let mut parameters = Vec::new();
    for group in parameter_groups {
        if group.is_empty() {
            continue;
        }
        if group.len() != 1 {
            return Err((
                group[0].line,
                "only scalar identifier template parameters are supported".to_string(),
            ));
        }
        match &group[0].kind {
            TokenKind::Identifier(parameter) => parameters.push(parameter.clone()),
            _ => {
                return Err((
                    group[0].line,
                    "only scalar identifier template parameters are supported".to_string(),
                ));
            }
        }
    }

    let open_body = close_parameters + 1;
    if !tokens
        .get(open_body)
        .is_some_and(|token| token_is_symbol(token, '{'))
    {
        return Err((
            line,
            "template modifiers or body syntax are unsupported by the MVP parser".to_string(),
        ));
    }
    let close_body = find_matching(tokens, open_body, '{', '}')
        .ok_or_else(|| (line, "template body is unbalanced".to_string()))?;
    let body = parse_template_body(&tokens[open_body + 1..close_body]);
    Ok((
        TemplateDefinition {
            source_path: path.to_path_buf(),
            name,
            start_line: line,
            end_line: tokens[close_body].line,
            start_byte: tokens[start].byte_offset,
            // A closing brace is one UTF-8 byte.
            end_byte: tokens[close_body].byte_offset + 1,
            parameters,
            body,
        },
        close_body + 1,
    ))
}

fn parse_main_declaration(tokens: &[Token], line: usize) -> ParsedMain {
    let Some(equal) = find_top_level_symbol(tokens, '=') else {
        return ParsedMain {
            line,
            call: None,
            failure_reason: Some("main declaration has no assignment".to_string()),
        };
    };
    match parse_call(&tokens[equal + 1..]) {
        Ok(call) => ParsedMain {
            line,
            call: Some(call),
            failure_reason: None,
        },
        Err(reason) => ParsedMain {
            line,
            call: None,
            failure_reason: Some(reason),
        },
    }
}

fn parse_template_body(tokens: &[Token]) -> Vec<BodyItem> {
    let mut items = Vec::new();
    let mut declared_components = HashMap::new();
    parse_body_block(tokens, &mut declared_components, &mut items);
    items
}

fn parse_body_block(
    tokens: &[Token],
    declared_components: &mut HashMap<String, bool>,
    items: &mut Vec<BodyItem>,
) {
    let mut cursor = 0;
    while cursor < tokens.len() {
        if token_is_identifier(&tokens[cursor], "if") {
            let line = tokens[cursor].line;
            let end = control_flow_end(tokens, cursor).unwrap_or(tokens.len());
            if contains_possible_instantiation(&tokens[cursor..end]) {
                match parse_conditional(&tokens[cursor..end], declared_components) {
                    Ok(item) => items.push(item),
                    Err(reason) => items.push(BodyItem::Unsupported {
                        line,
                        construct: "if".to_string(),
                        reason,
                    }),
                }
            }
            cursor = end;
            continue;
        }
        if token_is_identifier(&tokens[cursor], "for") {
            let line = tokens[cursor].line;
            let end = control_flow_end(tokens, cursor).unwrap_or(tokens.len());
            if contains_possible_instantiation(&tokens[cursor..end]) {
                match parse_for_loop(&tokens[cursor..end], declared_components) {
                    Ok(item) => items.push(item),
                    Err(reason) => items.push(BodyItem::Unsupported {
                        line,
                        construct: "for".to_string(),
                        reason,
                    }),
                }
            }
            cursor = end;
            continue;
        }
        if token_is_identifier(&tokens[cursor], "while") {
            let line = tokens[cursor].line;
            let end = control_flow_end(tokens, cursor).unwrap_or(tokens.len());
            if contains_possible_instantiation(&tokens[cursor..end]) {
                items.push(BodyItem::Unsupported {
                    line,
                    construct: "while".to_string(),
                    reason: "component instantiation inside while loops is unsupported".to_string(),
                });
            }
            cursor = end;
            continue;
        }

        if token_is_symbol(&tokens[cursor], '{') {
            if let Some(close) = find_matching(tokens, cursor, '{', '}') {
                parse_body_block(&tokens[cursor + 1..close], declared_components, items);
                cursor = close + 1;
                continue;
            }
        }

        let end = find_statement_end(tokens, cursor).unwrap_or(tokens.len());
        let statement = &tokens[cursor..end];
        let before = items.len();
        if token_is_identifier(&tokens[cursor], "component") {
            parse_component_statement(statement, declared_components, items);
        } else if token_is_identifier(&tokens[cursor], "var") {
            parse_variable_statement(statement, items);
        } else if let Some(component_name) = statement
            .first()
            .and_then(token_identifier)
            .filter(|name| declared_components.contains_key(*name))
        {
            parse_separate_component_assignment(
                component_name,
                declared_components[component_name],
                statement,
                items,
            );
        }
        if contains_anonymous_component_call(statement)
            && !items[before..]
                .iter()
                .any(|item| matches!(item, BodyItem::Unsupported { .. }))
        {
            match parse_anonymous_component_calls(statement) {
                Ok(calls) => items.extend(calls),
                Err(reason) => items.push(BodyItem::Unsupported {
                    line: tokens[cursor].line,
                    construct: tokens_to_text(statement),
                    reason,
                }),
            }
        }
        cursor = if end < tokens.len() { end + 1 } else { end };
    }
}

fn parse_conditional(
    tokens: &[Token],
    declared_components: &mut HashMap<String, bool>,
) -> std::result::Result<BodyItem, String> {
    let line = tokens.first().map_or(1, |token| token.line);
    let open = tokens
        .iter()
        .position(|token| token_is_symbol(token, '('))
        .ok_or_else(|| "compile-time if condition is missing".to_string())?;
    let close = find_matching(tokens, open, '(', ')')
        .ok_or_else(|| "compile-time if condition is unbalanced".to_string())?;
    if close == open + 1 {
        return Err("compile-time if condition is empty".to_string());
    }
    let (then_tokens, mut next) = control_body_tokens(tokens, close + 1)?;
    let mut then_body = Vec::new();
    let mut then_components = declared_components.clone();
    parse_body_block(then_tokens, &mut then_components, &mut then_body);
    let mut else_body = Vec::new();
    if tokens
        .get(next)
        .is_some_and(|token| token_is_identifier(token, "else"))
    {
        let (else_tokens, after_else) = control_body_tokens(tokens, next + 1)?;
        let mut else_components = declared_components.clone();
        parse_body_block(else_tokens, &mut else_components, &mut else_body);
        next = after_else;
    }
    if next != tokens.len() {
        return Err("trailing compile-time if syntax is unsupported".to_string());
    }
    Ok(BodyItem::Conditional {
        condition: tokens[open + 1..close].to_vec(),
        then_body,
        else_body,
        line,
    })
}

fn parse_for_loop(
    tokens: &[Token],
    declared_components: &mut HashMap<String, bool>,
) -> std::result::Result<BodyItem, String> {
    let line = tokens.first().map_or(1, |token| token.line);
    let open = tokens
        .iter()
        .position(|token| token_is_symbol(token, '('))
        .ok_or_else(|| "compile-time for header is missing".to_string())?;
    let close = find_matching(tokens, open, '(', ')')
        .ok_or_else(|| "compile-time for header is unbalanced".to_string())?;
    let groups = split_top_level(&tokens[open + 1..close], ';')?;
    if groups.len() != 3 {
        return Err("compile-time for header must contain three clauses".to_string());
    }
    let initializer = &groups[0];
    if initializer.len() < 4
        || !token_is_identifier(&initializer[0], "var")
        || !initializer
            .get(2)
            .is_some_and(|token| token_is_symbol(token, '='))
    {
        return Err("compile-time for initializer must be `var name = expression`".to_string());
    }
    let variable = initializer[1].kind.clone();
    let TokenKind::Identifier(variable) = variable else {
        return Err("compile-time for variable must be an identifier".to_string());
    };
    if groups[1].is_empty() {
        return Err("compile-time for condition is empty".to_string());
    }
    let update = match groups[2].as_slice() {
        [name, Token {
            kind: TokenKind::Operator(operator),
            ..
        }] if token_identifier(name) == Some(variable.as_str()) && operator == "++" => {
            LoopUpdate::Increment
        }
        [name, Token {
            kind: TokenKind::Operator(operator),
            ..
        }] if token_identifier(name) == Some(variable.as_str()) && operator == "--" => {
            LoopUpdate::Decrement
        }
        _ => {
            return Err("compile-time for update must be `variable++` or `variable--`".to_string())
        }
    };
    let (body_tokens, next) = control_body_tokens(tokens, close + 1)?;
    if next != tokens.len() {
        return Err("trailing compile-time for syntax is unsupported".to_string());
    }
    let mut body = Vec::new();
    let mut body_components = declared_components.clone();
    parse_body_block(body_tokens, &mut body_components, &mut body);
    Ok(BodyItem::ForLoop {
        variable,
        initial: initializer[3..].to_vec(),
        condition: groups[1].clone(),
        update,
        body,
        line,
    })
}

fn control_body_tokens(
    tokens: &[Token],
    start: usize,
) -> std::result::Result<(&[Token], usize), String> {
    if tokens.get(start).is_some_and(|token| {
        ["if", "for", "while"]
            .iter()
            .any(|keyword| token_is_identifier(token, keyword))
    }) {
        let end = control_flow_end(tokens, start)
            .ok_or_else(|| "nested compile-time control-flow body is unbalanced".to_string())?;
        return Ok((&tokens[start..end], end));
    }
    if tokens
        .get(start)
        .is_some_and(|token| token_is_symbol(token, '{'))
    {
        let close = find_matching(tokens, start, '{', '}')
            .ok_or_else(|| "compile-time control-flow body is unbalanced".to_string())?;
        return Ok((&tokens[start + 1..close], close + 1));
    }
    let end = find_statement_end(tokens, start)
        .ok_or_else(|| "compile-time control-flow body has no statement terminator".to_string())?;
    Ok((&tokens[start..=end], end + 1))
}

fn parse_component_statement(
    statement: &[Token],
    declared_components: &mut HashMap<String, bool>,
    items: &mut Vec<BodyItem>,
) {
    let line = statement.first().map_or(1, |token| token.line);
    let Some(component_name) = statement.get(1).and_then(token_identifier) else {
        items.push(BodyItem::Unsupported {
            line,
            construct: tokens_to_text(statement),
            reason: "component name is missing".to_string(),
        });
        return;
    };
    if statement
        .get(2)
        .is_some_and(|token| token_is_symbol(token, '['))
    {
        let Some(close) = find_matching(statement, 2, '[', ']') else {
            items.push(BodyItem::Unsupported {
                line,
                construct: tokens_to_text(statement),
                reason: "component array declaration is unbalanced".to_string(),
            });
            return;
        };
        if close == 3 {
            items.push(BodyItem::Unsupported {
                line,
                construct: tokens_to_text(statement),
                reason: "component array length is empty".to_string(),
            });
            return;
        }
        if close + 1 != statement.len() {
            items.push(BodyItem::Unsupported {
                line,
                construct: tokens_to_text(statement),
                reason: "direct component array initialization is unsupported".to_string(),
            });
            return;
        }
        declared_components.insert(component_name.to_string(), true);
        items.push(BodyItem::ComponentArray {
            name: component_name.to_string(),
            length: statement[3..close].to_vec(),
            line,
        });
        return;
    }
    let Some(equal) = find_top_level_symbol(statement, '=') else {
        declared_components.insert(component_name.to_string(), false);
        return;
    };
    declared_components.insert(component_name.to_string(), false);
    push_instantiation(component_name, None, &statement[equal + 1..], line, items);
}

fn parse_separate_component_assignment(
    component_name: &str,
    is_array: bool,
    statement: &[Token],
    items: &mut Vec<BodyItem>,
) {
    let line = statement.first().map_or(1, |token| token.line);
    if is_array {
        if !statement
            .get(1)
            .is_some_and(|token| token_is_symbol(token, '['))
        {
            return;
        }
        let Some(close) = find_matching(statement, 1, '[', ']') else {
            items.push(BodyItem::Unsupported {
                line,
                construct: tokens_to_text(statement),
                reason: "component array index is unbalanced".to_string(),
            });
            return;
        };
        if close == 2
            || !statement
                .get(close + 1)
                .is_some_and(|token| token_is_symbol(token, '='))
        {
            return;
        }
        push_instantiation(
            component_name,
            Some(statement[2..close].to_vec()),
            &statement[close + 2..],
            line,
            items,
        );
        return;
    }
    if statement
        .get(1)
        .is_some_and(|token| token_is_symbol(token, '['))
    {
        items.push(BodyItem::Unsupported {
            line,
            construct: tokens_to_text(statement),
            reason: "scalar component cannot be assigned through an array index".to_string(),
        });
        return;
    }
    if !statement
        .get(1)
        .is_some_and(|token| token_is_symbol(token, '='))
    {
        return;
    }
    push_instantiation(component_name, None, &statement[2..], line, items);
}

fn push_instantiation(
    component_name: &str,
    component_index: Option<Vec<Token>>,
    right_hand_side: &[Token],
    line: usize,
    items: &mut Vec<BodyItem>,
) {
    match parse_call(right_hand_side) {
        Ok(call) => items.push(BodyItem::Instantiation {
            component_name: component_name.to_string(),
            component_index,
            call,
            line,
            anonymous: false,
        }),
        Err(reason) => items.push(BodyItem::Unsupported {
            line,
            construct: format!(
                "component {component_name} = {}",
                tokens_to_text(right_hand_side)
            ),
            reason,
        }),
    }
}

fn parse_variable_statement(statement: &[Token], items: &mut Vec<BodyItem>) {
    let line = statement.first().map_or(1, |token| token.line);
    let Some(name) = statement.get(1).and_then(token_identifier) else {
        return;
    };
    if statement
        .get(2)
        .is_some_and(|token| token_is_symbol(token, '['))
    {
        items.push(BodyItem::Unsupported {
            line,
            construct: tokens_to_text(statement),
            reason: "compile-time variable arrays are unsupported by this MVP".to_string(),
        });
        return;
    }
    if statement
        .get(2)
        .is_some_and(|token| token_is_symbol(token, '='))
        && statement.len() > 3
    {
        items.push(BodyItem::Variable {
            name: name.to_string(),
            expression: statement[3..].to_vec(),
            line,
        });
    }
}

fn parse_call(tokens: &[Token]) -> std::result::Result<TemplateCall, String> {
    let mut cursor = 0;
    if tokens
        .get(cursor)
        .is_some_and(|token| token_is_identifier(token, "parallel"))
    {
        cursor += 1;
    }
    let template_name = tokens
        .get(cursor)
        .and_then(token_identifier)
        .ok_or_else(|| "template call name is missing".to_string())?
        .to_string();
    cursor += 1;
    if !tokens
        .get(cursor)
        .is_some_and(|token| token_is_symbol(token, '('))
    {
        return Err("template call parameter list is missing".to_string());
    }
    let close = find_matching(tokens, cursor, '(', ')')
        .ok_or_else(|| "template call parameter list is unbalanced".to_string())?;
    let arguments = split_top_level(&tokens[cursor + 1..close], ',')?;
    if tokens[close + 1..]
        .iter()
        .any(|token| !token_is_symbol(token, ';'))
    {
        return Err(
            "chained calls, anonymous components, or trailing call syntax are unsupported"
                .to_string(),
        );
    }
    Ok(TemplateCall {
        template_name,
        arguments,
    })
}

fn evaluate_arguments(
    arguments: &[Vec<Token>],
    bindings: &HashMap<String, i128>,
) -> std::result::Result<Vec<i128>, String> {
    if arguments.iter().any(Vec::is_empty) {
        return Err("empty template argument".to_string());
    }
    arguments
        .iter()
        .map(|argument| evaluate_expression(argument, bindings))
        .collect()
}

fn evaluate_expression(
    tokens: &[Token],
    bindings: &HashMap<String, i128>,
) -> std::result::Result<i128, String> {
    let mut parser = ExpressionParser {
        tokens,
        cursor: 0,
        bindings,
    };
    let value = parser.parse_binary(0)?;
    if parser.cursor != tokens.len() {
        return Err(format!(
            "unsupported expression {}",
            tokens_to_text(&tokens[parser.cursor..])
        ));
    }
    Ok(value)
}

struct ExpressionParser<'a> {
    tokens: &'a [Token],
    cursor: usize,
    bindings: &'a HashMap<String, i128>,
}

impl ExpressionParser<'_> {
    fn parse_binary(&mut self, minimum_precedence: u8) -> std::result::Result<i128, String> {
        let mut left = self.parse_unary()?;
        while let Some((operator, precedence, right_associative)) = self.current_binary_operator() {
            if precedence < minimum_precedence {
                break;
            }
            self.cursor += 1;
            let next_precedence = if right_associative {
                precedence
            } else {
                precedence + 1
            };
            let right = self.parse_binary(next_precedence)?;
            left = apply_binary(operator, left, right)?;
        }
        Ok(left)
    }

    fn parse_unary(&mut self) -> std::result::Result<i128, String> {
        if self
            .tokens
            .get(self.cursor)
            .is_some_and(|token| token_is_symbol(token, '+'))
        {
            self.cursor += 1;
            return self.parse_unary();
        }
        if self
            .tokens
            .get(self.cursor)
            .is_some_and(|token| token_is_symbol(token, '-'))
        {
            self.cursor += 1;
            return self
                .parse_unary()?
                .checked_neg()
                .ok_or_else(|| "integer overflow".to_string());
        }
        if self
            .tokens
            .get(self.cursor)
            .is_some_and(|token| token_is_symbol(token, '!'))
        {
            self.cursor += 1;
            return Ok(i128::from(self.parse_unary()? == 0));
        }
        self.parse_primary()
    }

    fn parse_primary(&mut self) -> std::result::Result<i128, String> {
        let token = self
            .tokens
            .get(self.cursor)
            .ok_or_else(|| "expression is incomplete".to_string())?;
        self.cursor += 1;
        match &token.kind {
            TokenKind::Number(number) => parse_integer(number),
            TokenKind::Identifier(identifier) => self
                .bindings
                .get(identifier)
                .copied()
                .ok_or_else(|| format!("unknown compile-time value {identifier}")),
            TokenKind::Symbol('(') => {
                let value = self.parse_binary(0)?;
                if !self
                    .tokens
                    .get(self.cursor)
                    .is_some_and(|token| token_is_symbol(token, ')'))
                {
                    return Err("parenthesized expression is unbalanced".to_string());
                }
                self.cursor += 1;
                Ok(value)
            }
            _ => Err(format!(
                "unsupported expression token {}",
                token_to_text(token)
            )),
        }
    }

    fn current_binary_operator(&self) -> Option<(&'static str, u8, bool)> {
        let operator = match &self.tokens.get(self.cursor)?.kind {
            TokenKind::Operator(operator) => operator.as_str(),
            TokenKind::Symbol('<') => "<",
            TokenKind::Symbol('>') => ">",
            TokenKind::Symbol('+') => "+",
            TokenKind::Symbol('-') => "-",
            TokenKind::Symbol('*') => "*",
            TokenKind::Symbol('/') => "/",
            TokenKind::Symbol('%') => "%",
            TokenKind::Symbol('&') => "&",
            TokenKind::Symbol('|') => "|",
            TokenKind::Symbol('^') => "^",
            _ => return None,
        };
        binary_operator(operator)
    }
}

fn binary_operator(operator: &str) -> Option<(&'static str, u8, bool)> {
    match operator {
        "||" => Some(("||", 1, false)),
        "&&" => Some(("&&", 2, false)),
        "|" => Some(("|", 3, false)),
        "^" => Some(("^", 4, false)),
        "&" => Some(("&", 5, false)),
        "==" => Some(("==", 6, false)),
        "!=" => Some(("!=", 6, false)),
        "<" => Some(("<", 7, false)),
        "<=" => Some(("<=", 7, false)),
        ">" => Some((">", 7, false)),
        ">=" => Some((">=", 7, false)),
        "<<" => Some(("<<", 8, false)),
        ">>" => Some((">>", 8, false)),
        "+" => Some(("+", 9, false)),
        "-" => Some(("-", 9, false)),
        "*" => Some(("*", 10, false)),
        "/" => Some(("/", 10, false)),
        "%" => Some(("%", 10, false)),
        "**" => Some(("**", 11, true)),
        _ => None,
    }
}

fn apply_binary(operator: &str, left: i128, right: i128) -> std::result::Result<i128, String> {
    let overflow = || format!("integer overflow while evaluating {left} {operator} {right}");
    match operator {
        "||" => Ok(i128::from(left != 0 || right != 0)),
        "&&" => Ok(i128::from(left != 0 && right != 0)),
        "==" => Ok(i128::from(left == right)),
        "!=" => Ok(i128::from(left != right)),
        "<" => Ok(i128::from(left < right)),
        "<=" => Ok(i128::from(left <= right)),
        ">" => Ok(i128::from(left > right)),
        ">=" => Ok(i128::from(left >= right)),
        "+" => left.checked_add(right).ok_or_else(overflow),
        "-" => left.checked_sub(right).ok_or_else(overflow),
        "*" => left.checked_mul(right).ok_or_else(overflow),
        "/" => left
            .checked_div(right)
            .ok_or_else(|| "division by zero or integer overflow".to_string()),
        "%" => left
            .checked_rem(right)
            .ok_or_else(|| "modulo by zero or integer overflow".to_string()),
        "<<" => u32::try_from(right)
            .ok()
            .and_then(|shift| left.checked_shl(shift))
            .ok_or_else(overflow),
        ">>" => u32::try_from(right)
            .ok()
            .and_then(|shift| left.checked_shr(shift))
            .ok_or_else(overflow),
        "&" => Ok(left & right),
        "|" => Ok(left | right),
        "^" => Ok(left ^ right),
        "**" => u32::try_from(right)
            .ok()
            .and_then(|power| left.checked_pow(power))
            .ok_or_else(overflow),
        _ => Err(format!("unsupported binary operator {operator}")),
    }
}

fn parse_integer(value: &str) -> std::result::Result<i128, String> {
    let value = value.replace('_', "");
    if let Some(hex) = value
        .strip_prefix("0x")
        .or_else(|| value.strip_prefix("0X"))
    {
        i128::from_str_radix(hex, 16).map_err(|_| format!("integer {value} exceeds i128"))
    } else {
        value
            .parse()
            .map_err(|_| format!("integer {value} exceeds i128"))
    }
}

fn control_flow_end(tokens: &[Token], start: usize) -> Option<usize> {
    let keyword = tokens.get(start)?;
    let open_condition = tokens
        .get(start + 1..)?
        .iter()
        .position(|token| token_is_symbol(token, '('))?
        + start
        + 1;
    let close_condition = find_matching(tokens, open_condition, '(', ')')?;
    let body_end = control_body_end(tokens, close_condition + 1)?;

    if token_is_identifier(keyword, "if")
        && tokens
            .get(body_end)
            .is_some_and(|token| token_is_identifier(token, "else"))
    {
        return control_body_end(tokens, body_end + 1);
    }
    Some(body_end)
}

fn control_body_end(tokens: &[Token], start: usize) -> Option<usize> {
    let first = tokens.get(start)?;
    if token_is_symbol(first, '{') {
        return find_matching(tokens, start, '{', '}').map(|end| end + 1);
    }
    if ["if", "for", "while"]
        .iter()
        .any(|keyword| token_is_identifier(first, keyword))
    {
        return control_flow_end(tokens, start);
    }
    find_statement_end(tokens, start).map(|end| end + 1)
}

fn contains_possible_instantiation(tokens: &[Token]) -> bool {
    tokens
        .iter()
        .any(|token| token_is_identifier(token, "component"))
        || contains_anonymous_component_call(tokens)
        || contains_assigned_template_call(tokens)
}

fn contains_assigned_template_call(tokens: &[Token]) -> bool {
    tokens.iter().enumerate().any(|(index, token)| {
        if !token_is_symbol(token, '=') {
            return false;
        }
        let end = find_statement_end(tokens, index + 1).unwrap_or(tokens.len());
        parse_call(&tokens[index + 1..end]).is_ok()
    })
}

fn contains_anonymous_component_call(tokens: &[Token]) -> bool {
    for (index, token) in tokens.iter().enumerate() {
        if token_identifier(token).is_none()
            || !tokens
                .get(index + 1)
                .is_some_and(|next| token_is_symbol(next, '('))
        {
            continue;
        }
        let Some(close) = find_matching(tokens, index + 1, '(', ')') else {
            continue;
        };
        if tokens
            .get(close + 1)
            .is_some_and(|next| token_is_symbol(next, '('))
        {
            return true;
        }
    }
    false
}

/// Discover anonymous template instances without interpreting their signal expressions.
/// Template parameters still have to be concrete during expansion. Scanning every call site
/// also records nested anonymous components used as inputs to another anonymous component.
fn parse_anonymous_component_calls(
    statement: &[Token],
) -> std::result::Result<Vec<BodyItem>, String> {
    let mut calls = Vec::new();
    for (index, token) in statement.iter().enumerate() {
        let Some(template_name) = token_identifier(token) else {
            continue;
        };
        if !statement
            .get(index + 1)
            .is_some_and(|next| token_is_symbol(next, '('))
        {
            continue;
        }
        let Some(parameters_end) = find_matching(statement, index + 1, '(', ')') else {
            continue;
        };
        if !statement
            .get(parameters_end + 1)
            .is_some_and(|next| token_is_symbol(next, '('))
        {
            continue;
        }
        find_matching(statement, parameters_end + 1, '(', ')')
            .ok_or_else(|| format!("anonymous {template_name} signal arguments are unbalanced"))?;
        let arguments = split_top_level(&statement[index + 2..parameters_end], ',')?;
        if arguments.iter().any(Vec::is_empty) {
            return Err(format!(
                "anonymous {template_name} has an empty template parameter"
            ));
        }
        calls.push(BodyItem::Instantiation {
            // The byte-independent character offset is unique within a source file. Line and
            // statement-local indexes alone can collide for two compact control-flow bodies.
            component_name: format!("@anonymous:{}:{}", token.line, token.offset),
            component_index: None,
            call: TemplateCall {
                template_name: template_name.to_string(),
                arguments,
            },
            line: token.line,
            anonymous: true,
        });
    }
    Ok(calls)
}

pub(crate) fn find_statement_end(tokens: &[Token], start: usize) -> Option<usize> {
    let mut round = 0_usize;
    let mut square = 0_usize;
    let mut curly = 0_usize;
    for (index, token) in tokens.iter().enumerate().skip(start) {
        match token.kind {
            TokenKind::Symbol('(') => round += 1,
            TokenKind::Symbol(')') => round = round.saturating_sub(1),
            TokenKind::Symbol('[') => square += 1,
            TokenKind::Symbol(']') => square = square.saturating_sub(1),
            TokenKind::Symbol('{') => curly += 1,
            TokenKind::Symbol('}') => curly = curly.saturating_sub(1),
            TokenKind::Symbol(';') if round == 0 && square == 0 && curly == 0 => {
                return Some(index);
            }
            _ => {}
        }
    }
    None
}

pub(crate) fn find_matching(
    tokens: &[Token],
    start: usize,
    open: char,
    close: char,
) -> Option<usize> {
    let mut depth = 0_usize;
    for (index, token) in tokens.iter().enumerate().skip(start) {
        if token_is_symbol(token, open) {
            depth += 1;
        } else if token_is_symbol(token, close) {
            depth = depth.checked_sub(1)?;
            if depth == 0 {
                return Some(index);
            }
        }
    }
    None
}

fn find_top_level_symbol(tokens: &[Token], symbol: char) -> Option<usize> {
    let mut round = 0_usize;
    let mut square = 0_usize;
    let mut curly = 0_usize;
    for (index, token) in tokens.iter().enumerate() {
        if token_is_symbol(token, symbol) && round == 0 && square == 0 && curly == 0 {
            return Some(index);
        }
        match token.kind {
            TokenKind::Symbol('(') => round += 1,
            TokenKind::Symbol(')') => round = round.saturating_sub(1),
            TokenKind::Symbol('[') => square += 1,
            TokenKind::Symbol(']') => square = square.saturating_sub(1),
            TokenKind::Symbol('{') => curly += 1,
            TokenKind::Symbol('}') => curly = curly.saturating_sub(1),
            _ => {}
        }
    }
    None
}

pub(crate) fn split_top_level(
    tokens: &[Token],
    separator: char,
) -> std::result::Result<Vec<Vec<Token>>, String> {
    if tokens.is_empty() {
        return Ok(Vec::new());
    }
    let mut groups = Vec::new();
    let mut start = 0;
    let mut round = 0_usize;
    let mut square = 0_usize;
    let mut curly = 0_usize;
    for (index, token) in tokens.iter().enumerate() {
        if token_is_symbol(token, separator) && round == 0 && square == 0 && curly == 0 {
            groups.push(tokens[start..index].to_vec());
            start = index + 1;
            continue;
        }
        match token.kind {
            TokenKind::Symbol('(') => round += 1,
            TokenKind::Symbol(')') => {
                round = round
                    .checked_sub(1)
                    .ok_or_else(|| "unbalanced parentheses".to_string())?;
            }
            TokenKind::Symbol('[') => square += 1,
            TokenKind::Symbol(']') => {
                square = square
                    .checked_sub(1)
                    .ok_or_else(|| "unbalanced brackets".to_string())?;
            }
            TokenKind::Symbol('{') => curly += 1,
            TokenKind::Symbol('}') => {
                curly = curly
                    .checked_sub(1)
                    .ok_or_else(|| "unbalanced braces".to_string())?;
            }
            _ => {}
        }
    }
    if round != 0 || square != 0 || curly != 0 {
        return Err("unbalanced template arguments".to_string());
    }
    groups.push(tokens[start..].to_vec());
    Ok(groups)
}

pub(crate) fn lex(source: &str) -> std::result::Result<Vec<Token>, (usize, String)> {
    let chars = source.chars().collect::<Vec<_>>();
    let mut byte_offsets = source
        .char_indices()
        .map(|(offset, _)| offset)
        .collect::<Vec<_>>();
    byte_offsets.push(source.len());
    let mut tokens = Vec::new();
    let mut cursor = 0;
    let mut line = 1;
    while cursor < chars.len() {
        let ch = chars[cursor];
        if ch.is_whitespace() {
            if ch == '\n' {
                line += 1;
            }
            cursor += 1;
            continue;
        }
        if ch == '/' && chars.get(cursor + 1) == Some(&'/') {
            cursor += 2;
            while cursor < chars.len() && chars[cursor] != '\n' {
                cursor += 1;
            }
            continue;
        }
        if ch == '/' && chars.get(cursor + 1) == Some(&'*') {
            let start_line = line;
            cursor += 2;
            let mut terminated = false;
            while cursor < chars.len() {
                if chars[cursor] == '\n' {
                    line += 1;
                }
                if chars[cursor] == '*' && chars.get(cursor + 1) == Some(&'/') {
                    cursor += 2;
                    terminated = true;
                    break;
                }
                cursor += 1;
            }
            if !terminated {
                return Err((start_line, "unterminated block comment".to_string()));
            }
            continue;
        }
        if ch == '"' {
            let start_line = line;
            let start = cursor;
            cursor += 1;
            let mut value = String::new();
            let mut escaped = false;
            let mut terminated = false;
            while cursor < chars.len() {
                let current = chars[cursor];
                cursor += 1;
                if current == '\n' {
                    line += 1;
                }
                if escaped {
                    value.push(current);
                    escaped = false;
                } else if current == '\\' {
                    escaped = true;
                } else if current == '"' {
                    terminated = true;
                    break;
                } else {
                    value.push(current);
                }
            }
            if !terminated {
                return Err((start_line, "unterminated string literal".to_string()));
            }
            tokens.push(Token {
                kind: TokenKind::StringLiteral(value),
                line: start_line,
                offset: start,
                byte_offset: byte_offsets[start],
            });
            continue;
        }
        if ch.is_ascii_alphabetic() || ch == '_' {
            let start = cursor;
            cursor += 1;
            while cursor < chars.len()
                && (chars[cursor].is_ascii_alphanumeric() || chars[cursor] == '_')
            {
                cursor += 1;
            }
            tokens.push(Token {
                kind: TokenKind::Identifier(chars[start..cursor].iter().collect()),
                line,
                offset: start,
                byte_offset: byte_offsets[start],
            });
            continue;
        }
        if ch.is_ascii_digit() {
            let start = cursor;
            cursor += 1;
            while cursor < chars.len()
                && (chars[cursor].is_ascii_alphanumeric() || chars[cursor] == '_')
            {
                cursor += 1;
            }
            tokens.push(Token {
                kind: TokenKind::Number(chars[start..cursor].iter().collect()),
                line,
                offset: start,
                byte_offset: byte_offsets[start],
            });
            continue;
        }

        // Operators are at most three characters; copying the whole remaining input here
        // made lexing quadratic on multi-megabyte constant tables.
        let remaining = chars[cursor..chars.len().min(cursor + 3)]
            .iter()
            .collect::<String>();
        let operator = [
            "<==", "==>", "===", "<--", "-->", "**", "<<", ">>", "==", "!=", "<=", ">=", "&&",
            "||", "++", "--",
        ]
        .into_iter()
        .find(|operator| remaining.starts_with(operator));
        if let Some(operator) = operator {
            tokens.push(Token {
                kind: TokenKind::Operator(operator.to_string()),
                line,
                offset: cursor,
                byte_offset: byte_offsets[cursor],
            });
            cursor += operator.len();
        } else {
            tokens.push(Token {
                kind: TokenKind::Symbol(ch),
                line,
                offset: cursor,
                byte_offset: byte_offsets[cursor],
            });
            cursor += 1;
        }
    }
    Ok(tokens)
}

pub(crate) fn token_identifier(token: &Token) -> Option<&str> {
    if let TokenKind::Identifier(identifier) = &token.kind {
        Some(identifier)
    } else {
        None
    }
}

pub(crate) fn token_is_identifier(token: &Token, expected: &str) -> bool {
    token_identifier(token) == Some(expected)
}

pub(crate) fn token_is_symbol(token: &Token, expected: char) -> bool {
    token.kind == TokenKind::Symbol(expected)
}

fn tokens_to_text(tokens: &[Token]) -> String {
    tokens
        .iter()
        .map(token_to_text)
        .collect::<Vec<_>>()
        .join(" ")
}

pub(crate) fn token_to_text(token: &Token) -> String {
    match &token.kind {
        TokenKind::Identifier(value) | TokenKind::Number(value) | TokenKind::Operator(value) => {
            value.clone()
        }
        TokenKind::StringLiteral(value) => format!("\"{value}\""),
        TokenKind::Symbol(value) => value.to_string(),
    }
}

fn format_source_call(call: &TemplateCall) -> String {
    format!(
        "{}({})",
        call.template_name,
        call.arguments
            .iter()
            .map(|argument| tokens_to_text(argument))
            .collect::<Vec<_>>()
            .join(", ")
    )
}

fn format_call(template_name: &str, parameters: &[i128]) -> String {
    format!(
        "{}({})",
        template_name,
        parameters
            .iter()
            .map(ToString::to_string)
            .collect::<Vec<_>>()
            .join(", ")
    )
}

fn sanitize_file_component(value: &str) -> String {
    value
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || ch == '-' || ch == '_' {
                ch
            } else {
                '-'
            }
        })
        .collect()
}

fn write_report(work_dir: &Path, report: &TargetDiscoveryReport) -> Result<()> {
    let report_path = work_dir.join("discovery.json");
    let temporary_path = work_dir.join("discovery.json.tmp");
    let mut json = serde_json::to_vec_pretty(report)?;
    json.push(b'\n');
    fs::write(&temporary_path, json).with_context(|| {
        format!(
            "failed to write discovery report: {}",
            temporary_path.display()
        )
    })?;
    fs::rename(&temporary_path, &report_path).with_context(|| {
        format!(
            "failed to finalize discovery report: {}",
            report_path.display()
        )
    })?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn evaluates_parameter_expressions() {
        let tokens = lex("(n * 32) / limb").expect("tokens");
        let bindings = HashMap::from([("n".to_string(), 64), ("limb".to_string(), 64)]);
        assert_eq!(evaluate_expression(&tokens, &bindings), Ok(32));
    }

    #[test]
    fn rejects_unknown_compile_time_values() {
        let tokens = lex("dynamic + 1").expect("tokens");
        assert!(evaluate_expression(&tokens, &HashMap::new())
            .expect_err("unknown value")
            .contains("unknown compile-time value"));
    }

    #[test]
    fn template_ranges_are_utf8_byte_offsets_without_changing_token_offsets() {
        let temporary = tempfile::tempdir().expect("temporary directory");
        let source =
            "// 한글 프리픽스\ntemplate UnicodeRange() {\n  signal output out;\n  out <== 1;\n}\n";
        let path = temporary.path().join("unicode.circom");
        fs::write(&path, source).expect("write circuit");

        let expected_start = source
            .find("template UnicodeRange")
            .expect("template start");
        let expected_end = source.find("\n}\n").expect("template end") + 2;
        assert_eq!(
            template_source_byte_range(&path, "UnicodeRange").expect("template range"),
            (expected_start, expected_end)
        );

        let tokens = lex(source).expect("tokens");
        let template = tokens
            .iter()
            .find(|token| token_is_identifier(token, "template"))
            .expect("template token");
        assert_ne!(template.offset, template.byte_offset);
        assert_eq!(template.byte_offset, expected_start);
    }

    #[test]
    fn discovery_dependency_paths_follow_library_resolution() {
        let temporary = tempfile::tempdir().expect("temporary directory");
        let project = temporary.path().join("project");
        let library = temporary.path().join("library");
        fs::create_dir_all(&project).expect("project directory");
        fs::create_dir_all(&library).expect("library directory");
        let entrypoint = project.join("main.circom");
        let dependency = library.join("dependency.circom");
        fs::write(
            &entrypoint,
            "pragma circom 2.1.6;\ninclude \"dependency.circom\";\ncomponent main = Dependency();\n",
        )
        .expect("entrypoint");
        fs::write(
            &dependency,
            "pragma circom 2.1.6;\ntemplate Dependency() { signal output out; out <== 1; }\n",
        )
        .expect("dependency");

        let mut expected = vec![
            fs::canonicalize(&entrypoint).expect("canonical entrypoint"),
            fs::canonicalize(&dependency).expect("canonical dependency"),
        ];
        expected.sort();
        assert_eq!(
            discovery_dependency_paths(&entrypoint, &project, &[library])
                .expect("dependency closure"),
            expected
        );
    }

    #[test]
    fn circom_include_literals_use_the_discovery_parser() {
        let temporary = tempfile::tempdir().expect("temporary directory");
        let path = temporary.path().join("includes.circom");
        fs::write(
            &path,
            "pragma circom 2.1.6;\ninclude \"a.circom\";\ninclude \"../b.circom\";\n",
        )
        .expect("source");
        assert_eq!(
            circom_include_literals(&path).expect("includes"),
            vec!["a.circom".to_owned(), "../b.circom".to_owned()]
        );
    }
}
