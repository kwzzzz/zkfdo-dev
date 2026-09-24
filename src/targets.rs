use std::{
    collections::{HashMap, HashSet},
    fs,
    path::{Path, PathBuf},
    process::Command,
};

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::scanner;

const MAX_INSTANTIATION_DEPTH: usize = 64;

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
    CompilerUnavailable,
    Unsupported,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
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
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct UnsupportedCase {
    pub source_path: PathBuf,
    pub line: Option<usize>,
    pub construct: String,
    pub reason: String,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
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
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct TemplateSourceScope {
    pub path: PathBuf,
    pub template_name: String,
    pub start_line: usize,
    pub end_line: usize,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
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
        call: TemplateCall,
        line: usize,
    },
    Unsupported {
        line: usize,
        construct: String,
        reason: String,
    },
}

#[derive(Debug, Clone)]
struct TemplateCall {
    template_name: String,
    arguments: Vec<Vec<Token>>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct Token {
    kind: TokenKind,
    line: usize,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum TokenKind {
    Identifier(String),
    Number(String),
    StringLiteral(String),
    Symbol(char),
    Operator(String),
}

/// Inspect one existing entrypoint using the same supported syntax as target discovery.
/// The selected file may be an external wrapper; every included dependency must be in project_root.
pub fn inspect_entrypoint(entrypoint: &Path, project_root: &Path) -> Result<EntrypointInspection> {
    let entrypoint = fs::canonicalize(entrypoint)
        .with_context(|| format!("resolve selected entrypoint {}", entrypoint.display()))?;
    let project_root = fs::canonicalize(project_root)
        .with_context(|| format!("resolve project root {}", project_root.display()))?;
    anyhow::ensure!(
        project_root.is_dir(),
        "inspection project root must be a directory"
    );
    let mut parsed_files = HashMap::new();
    let mut visited = HashSet::new();
    let mut unsupported = Vec::new();
    load_inspection_files(
        &entrypoint,
        &project_root,
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
                            expand_template(
                                root,
                                &parameters,
                                &template_index,
                                &mut stack,
                                &mut children,
                                &mut unsupported,
                                0,
                            );
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

fn inspect_binding_changes(definition: &TemplateDefinition) -> Result<Vec<UnsupportedCase>> {
    let mut needed = definition
        .body
        .iter()
        .filter_map(|item| match item {
            BodyItem::Instantiation { call, .. } => Some(&call.arguments),
            _ => None,
        })
        .flatten()
        .flatten()
        .filter_map(token_identifier)
        .map(str::to_string)
        .collect::<HashSet<_>>();
    loop {
        let before = needed.len();
        for item in &definition.body {
            if let BodyItem::Variable {
                name, expression, ..
            } = item
            {
                if needed.contains(name) {
                    needed.extend(
                        expression
                            .iter()
                            .filter_map(token_identifier)
                            .map(str::to_string),
                    );
                }
            }
        }
        if before == needed.len() {
            break;
        }
    }
    let components = definition
        .body
        .iter()
        .filter_map(|item| match item {
            BodyItem::Instantiation { component_name, .. } => Some(component_name.clone()),
            _ => None,
        })
        .collect::<HashSet<_>>();
    let source = fs::read_to_string(&definition.source_path)?;
    let tokens = lex(&source)
        .expect("inspection source was already lexed")
        .into_iter()
        .filter(|token| token.line >= definition.start_line && token.line <= definition.end_line)
        .collect::<Vec<_>>();
    let mut declared = definition
        .parameters
        .iter()
        .cloned()
        .collect::<HashSet<_>>();
    let mut initialized_components = HashSet::new();
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
        if direct_assignment && components.contains(name) {
            let parsed_assignment = definition.body.iter().any(|item| {
                matches!(item, BodyItem::Instantiation { component_name, line, .. }
                    if component_name == name && *line == token.line)
            });
            if parsed_assignment && initialized_components.insert(name.to_string()) {
                continue;
            }
        }
        let declaration = previous.is_some_and(|t| token_is_identifier(t, "var"));
        if direct_assignment && declaration && declared.insert(name.to_string()) {
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

fn load_inspection_files(
    path: &Path,
    project_root: &Path,
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
        ];
        let existing = candidates
            .into_iter()
            .filter_map(|p| fs::canonicalize(p).ok())
            .collect::<Vec<_>>();
        if let Some(included) = existing
            .iter()
            .find(|candidate| candidate.starts_with(project_root))
        {
            load_inspection_files(included, project_root, parsed_files, visited, unsupported);
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
    let project_root = fs::canonicalize(project.as_ref()).with_context(|| {
        format!(
            "failed to resolve project root: {}",
            project.as_ref().display()
        )
    })?;
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

    for target in scanner::scan_project(&project_root)? {
        let path = fs::canonicalize(&target.path)
            .with_context(|| format!("failed to resolve Circom file: {}", target.path.display()))?;
        let source = fs::read_to_string(&path)
            .with_context(|| format!("failed to read Circom file: {}", path.display()))?;

        match parse_file(&path, &source) {
            Ok(parsed) => {
                parsed_files.insert(path, parsed);
            }
            Err(issue) => unsupported.push(issue),
        }
    }

    let entrypoints = parsed_files
        .values()
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
                        let mut stack = vec![(root.name.clone(), main_parameters.clone())];
                        expand_template(
                            root,
                            &main_parameters,
                            &template_index,
                            &mut stack,
                            &mut targets,
                            &mut unsupported,
                            0,
                        );
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

    generate_and_validate_wrappers(
        &mut targets,
        &work_dir,
        &project_root,
        &parsed_files,
        circom_bin,
    )?;

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
    };
    write_report(&work_dir, &report)?;
    Ok(report)
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

#[allow(clippy::too_many_arguments)]
fn expand_template(
    definition: &TemplateDefinition,
    concrete_parameters: &[i128],
    template_index: &HashMap<String, Vec<&TemplateDefinition>>,
    stack: &mut Vec<(String, Vec<i128>)>,
    targets: &mut Vec<ConcreteFuzzTarget>,
    unsupported: &mut Vec<UnsupportedCase>,
    depth: usize,
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

    for item in &definition.body {
        match item {
            BodyItem::Variable {
                name,
                expression,
                line,
            } => match evaluate_expression(expression, &bindings) {
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
            BodyItem::Instantiation {
                component_name,
                call,
                line,
            } => {
                let parameters = match evaluate_arguments(&call.arguments, &bindings) {
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
                    "{}:{}:{}->{}",
                    definition.source_path.display(),
                    line,
                    component_name,
                    format_call(&call.template_name, &parameters)
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
                        component_name: component_name.clone(),
                        line: *line,
                    },
                    generated_wrapper_path: None,
                    wrapper_status: WrapperStatus::NotGenerated,
                    compiler_stdout_path: None,
                    compiler_stderr_path: None,
                    failure_reason: None,
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
                );
                stack.pop();
            }
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

fn generate_and_validate_wrappers(
    targets: &mut [ConcreteFuzzTarget],
    work_dir: &Path,
    project_root: &Path,
    parsed_files: &HashMap<PathBuf, ParsedFile>,
    circom_bin: Option<&Path>,
) -> Result<()> {
    let wrappers_dir = work_dir.join("wrappers");
    fs::create_dir_all(&wrappers_dir)
        .with_context(|| format!("failed to create wrapper dir: {}", wrappers_dir.display()))?;

    for (index, target) in targets.iter_mut().enumerate() {
        if include_closure_contains_main(
            &target.source_path,
            project_root,
            parsed_files,
            &mut HashSet::new(),
        ) {
            target.wrapper_status = WrapperStatus::Unsupported;
            target.failure_reason = Some(
                "the target source include closure already declares component main".to_string(),
            );
            continue;
        }

        let target_dir = wrappers_dir.join(format!(
            "{index:04}-{}",
            sanitize_file_component(&target.template_name)
        ));
        fs::create_dir_all(&target_dir).with_context(|| {
            format!("failed to create target work dir: {}", target_dir.display())
        })?;
        let wrapper_path = target_dir.join("target.circom");
        let include_path = target
            .source_path
            .to_string_lossy()
            .replace('\\', "/")
            .replace('"', "\\\"");
        let parameters = target.concrete_parameters.join(", ");
        let wrapper = format!(
            "pragma circom 2.1.6;\n\ninclude \"{include_path}\";\n\ncomponent main = {}({parameters});\n",
            target.template_name
        );
        fs::write(&wrapper_path, wrapper)
            .with_context(|| format!("failed to write wrapper: {}", wrapper_path.display()))?;
        target.generated_wrapper_path = Some(wrapper_path.clone());
        target.wrapper_status = WrapperStatus::Generated;

        let Some(circom_bin) = circom_bin else {
            continue;
        };
        let compiler_output_dir = target_dir.join("circom-output");
        fs::create_dir_all(&compiler_output_dir).with_context(|| {
            format!(
                "failed to create compiler output dir: {}",
                compiler_output_dir.display()
            )
        })?;
        let compiler_stdout_path = target_dir.join("circom.stdout.log");
        let compiler_stderr_path = target_dir.join("circom.stderr.log");
        target.compiler_stdout_path = Some(compiler_stdout_path.clone());
        target.compiler_stderr_path = Some(compiler_stderr_path.clone());

        match Command::new(circom_bin)
            .arg(&wrapper_path)
            .arg("--inspect")
            .arg("--output")
            .arg(&compiler_output_dir)
            .output()
        {
            Ok(output) => {
                fs::write(&compiler_stdout_path, &output.stdout)?;
                fs::write(&compiler_stderr_path, &output.stderr)?;
                if output.status.success() {
                    target.wrapper_status = WrapperStatus::CompileSucceeded;
                } else {
                    target.wrapper_status = WrapperStatus::CompileFailed;
                    target.failure_reason =
                        Some(String::from_utf8_lossy(&output.stderr).trim().to_string());
                }
            }
            Err(error) => {
                target.wrapper_status = WrapperStatus::CompilerUnavailable;
                target.failure_reason = Some(format!(
                    "failed to start Circom compiler {}: {error}",
                    circom_bin.display()
                ));
            }
        }
    }
    Ok(())
}

fn collect_reachable_files(
    path: &Path,
    project_root: &Path,
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
        match resolve_include(path, &include.path, project_root, parsed_files) {
            Some(included_path) => collect_reachable_files(
                &included_path,
                project_root,
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
        resolve_include(path, &include.path, project_root, parsed_files).is_some_and(
            |included_path| {
                include_closure_contains_main(&included_path, project_root, parsed_files, visited)
            },
        )
    })
}

fn resolve_include(
    source_path: &Path,
    include: &str,
    project_root: &Path,
    parsed_files: &HashMap<PathBuf, ParsedFile>,
) -> Option<PathBuf> {
    let relative_candidate = source_path.parent()?.join(include);
    let project_candidate = project_root.join(include);
    [relative_candidate, project_candidate]
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
    let mut declared_components = HashSet::new();
    parse_body_block(tokens, &mut declared_components, &mut items);
    items
}

fn parse_body_block(
    tokens: &[Token],
    declared_components: &mut HashSet<String>,
    items: &mut Vec<BodyItem>,
) {
    let mut cursor = 0;
    while cursor < tokens.len() {
        if token_is_identifier(&tokens[cursor], "if")
            || token_is_identifier(&tokens[cursor], "for")
            || token_is_identifier(&tokens[cursor], "while")
        {
            let line = tokens[cursor].line;
            let construct = token_identifier(&tokens[cursor]).unwrap_or("control flow");
            let end = control_flow_end(tokens, cursor).unwrap_or(tokens.len());
            if contains_possible_instantiation(&tokens[cursor..end]) {
                items.push(BodyItem::Unsupported {
                    line,
                    construct: construct.to_string(),
                    reason:
                        "component instantiation inside control flow is unsupported by this MVP"
                            .to_string(),
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
        if token_is_identifier(&tokens[cursor], "component") {
            parse_component_statement(statement, declared_components, items);
        } else if token_is_identifier(&tokens[cursor], "var") {
            parse_variable_statement(statement, items);
        } else if let Some(component_name) = statement
            .first()
            .and_then(token_identifier)
            .filter(|name| declared_components.contains(*name))
        {
            parse_separate_component_assignment(component_name, statement, items);
        } else if contains_anonymous_component_call(statement) {
            items.push(BodyItem::Unsupported {
                line: tokens[cursor].line,
                construct: tokens_to_text(statement),
                reason: "anonymous component calls are unsupported by this MVP".to_string(),
            });
        }
        cursor = if end < tokens.len() { end + 1 } else { end };
    }
}

fn parse_component_statement(
    statement: &[Token],
    declared_components: &mut HashSet<String>,
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
        items.push(BodyItem::Unsupported {
            line,
            construct: tokens_to_text(statement),
            reason: "component arrays are unsupported by this MVP".to_string(),
        });
        return;
    }
    let Some(equal) = find_top_level_symbol(statement, '=') else {
        declared_components.insert(component_name.to_string());
        return;
    };
    push_instantiation(component_name, &statement[equal + 1..], line, items);
}

fn parse_separate_component_assignment(
    component_name: &str,
    statement: &[Token],
    items: &mut Vec<BodyItem>,
) {
    let line = statement.first().map_or(1, |token| token.line);
    if statement
        .get(1)
        .is_some_and(|token| token_is_symbol(token, '['))
    {
        items.push(BodyItem::Unsupported {
            line,
            construct: tokens_to_text(statement),
            reason: "component array assignments are unsupported by this MVP".to_string(),
        });
        return;
    }
    if !statement
        .get(1)
        .is_some_and(|token| token_is_symbol(token, '='))
    {
        return;
    }
    push_instantiation(component_name, &statement[2..], line, items);
}

fn push_instantiation(
    component_name: &str,
    right_hand_side: &[Token],
    line: usize,
    items: &mut Vec<BodyItem>,
) {
    match parse_call(right_hand_side) {
        Ok(call) => items.push(BodyItem::Instantiation {
            component_name: component_name.to_string(),
            call,
            line,
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
        "|" => Some(("|", 1, false)),
        "^" => Some(("^", 2, false)),
        "&" => Some(("&", 3, false)),
        "<<" => Some(("<<", 4, false)),
        ">>" => Some((">>", 4, false)),
        "+" => Some(("+", 5, false)),
        "-" => Some(("-", 5, false)),
        "*" => Some(("*", 6, false)),
        "/" => Some(("/", 6, false)),
        "%" => Some(("%", 6, false)),
        "**" => Some(("**", 7, true)),
        _ => None,
    }
}

fn apply_binary(operator: &str, left: i128, right: i128) -> std::result::Result<i128, String> {
    let overflow = || format!("integer overflow while evaluating {left} {operator} {right}");
    match operator {
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
    let open_condition = tokens[start + 1..]
        .iter()
        .position(|token| token_is_symbol(token, '('))?
        + start
        + 1;
    let close_condition = find_matching(tokens, open_condition, '(', ')')?;
    let body_start = close_condition + 1;
    let body_end = if tokens
        .get(body_start)
        .is_some_and(|token| token_is_symbol(token, '{'))
    {
        find_matching(tokens, body_start, '{', '}')? + 1
    } else {
        find_statement_end(tokens, body_start)? + 1
    };

    if token_is_identifier(&tokens[start], "if")
        && tokens
            .get(body_end)
            .is_some_and(|token| token_is_identifier(token, "else"))
    {
        let else_start = body_end + 1;
        if tokens
            .get(else_start)
            .is_some_and(|token| token_is_symbol(token, '{'))
        {
            return find_matching(tokens, else_start, '{', '}').map(|end| end + 1);
        }
        return find_statement_end(tokens, else_start).map(|end| end + 1);
    }
    Some(body_end)
}

fn contains_possible_instantiation(tokens: &[Token]) -> bool {
    tokens
        .iter()
        .any(|token| token_is_identifier(token, "component"))
        || contains_anonymous_component_call(tokens)
        || tokens.windows(3).any(|window| {
            token_is_symbol(&window[0], '=')
                && token_identifier(&window[1]).is_some()
                && token_is_symbol(&window[2], '(')
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

fn find_statement_end(tokens: &[Token], start: usize) -> Option<usize> {
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

fn find_matching(tokens: &[Token], start: usize, open: char, close: char) -> Option<usize> {
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

fn split_top_level(
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

fn lex(source: &str) -> std::result::Result<Vec<Token>, (usize, String)> {
    let chars = source.chars().collect::<Vec<_>>();
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
            });
            continue;
        }

        let remaining = chars[cursor..].iter().collect::<String>();
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
            });
            cursor += operator.len();
        } else {
            tokens.push(Token {
                kind: TokenKind::Symbol(ch),
                line,
            });
            cursor += 1;
        }
    }
    Ok(tokens)
}

fn token_identifier(token: &Token) -> Option<&str> {
    if let TokenKind::Identifier(identifier) = &token.kind {
        Some(identifier)
    } else {
        None
    }
}

fn token_is_identifier(token: &Token, expected: &str) -> bool {
    token_identifier(token) == Some(expected)
}

fn token_is_symbol(token: &Token, expected: char) -> bool {
    token.kind == TokenKind::Symbol(expected)
}

fn tokens_to_text(tokens: &[Token]) -> String {
    tokens
        .iter()
        .map(token_to_text)
        .collect::<Vec<_>>()
        .join(" ")
}

fn token_to_text(token: &Token) -> String {
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
}
