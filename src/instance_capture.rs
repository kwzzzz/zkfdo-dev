//! F-01: compiler-based instance discovery.
//!
//! circom computes every template argument while it generates constraints, but none of its
//! outputs records argument values: `.sym` names instance paths, and the C++/wasm generators
//! name template instances only by an id per distinct argument tuple. A diagnostic copy of the
//! sources therefore adds capture constraints that circom evaluates for us:
//!
//! - every template declares a marker `__zkfdo_t<k>` (its template id) and, for each scalar
//!   parameter, `__zkfdo_p<i> === <parameter>`, so each instance records its own values;
//! - every instantiation site records each execution (`__zkfdo_s<n>_n`), its component indices,
//!   and each array argument element by element, with the dimensions taken from the array
//!   variable's declaration. An array argument that is the caller's own array parameter is
//!   taken from the caller's instance.
//!
//! `--O0` keeps every `s === v` constraint, in execution order and including duplicates, so the
//! values are read from the R1CS by the capture signal's `.sym` name. Inserted text never adds a
//! line, and anonymous-component byte offsets are mapped back to the original sources. The copy
//! is used only to discover instances: wrappers and compile units are built from the original
//! sources, and [`neutrality`] checks that removing the capture signals and constraints gives
//! back the original O0 R1CS.

use std::{
    collections::{BTreeMap, HashMap, HashSet},
    fs,
    io::{BufRead, BufReader, Read, Seek, SeekFrom},
    path::{Path, PathBuf},
    time::Instant,
};

use anyhow::{ensure, Context, Result};
use num_bigint::BigUint;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::{
    structure::{capture_tool, ToolCapture},
    targets::{
        find_matching, find_statement_end, lex, split_top_level, token_identifier,
        token_is_identifier, token_is_symbol, token_to_text, Token, TokenKind, UnsupportedCase,
    },
};

pub const CAPTURE_SCHEMA: &str = "zkfdo-instance-capture-v1";
pub const CAPTURE_PREFIX: &str = "__zkfdo_";
const MAX_RETRIES: usize = 4;
/// Evaluation point of the array fingerprint (Horner over the field, row-major).
const FINGERPRINT_BASE: u64 = 1_000_003;

/// A captured template argument. Values are canonical decimals in [0, p).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum CapturedValue {
    Scalar {
        value: String,
    },
    /// Row-major values of an array with the given dimensions.
    Array {
        dims: Vec<usize>,
        values: Vec<String>,
    },
    /// An array stored once in [`InstanceCapture::arrays`], by the hash in its key token.
    ArrayRef {
        sha256: String,
    },
}

#[derive(Serialize)]
struct CanonicalArray<'a> {
    dims: &'a [usize],
    values: &'a [String],
}

impl CapturedValue {
    /// The token used in instance keys: a scalar in signed form (values above p/2 as
    /// negatives, a one-to-one map), an array as `[sha256:<hex>]` of [`Self::canonical`].
    pub fn key_token(&self, prime: &BigUint) -> Result<String> {
        match self {
            CapturedValue::Scalar { value } => signed_decimal(value, prime),
            CapturedValue::Array { .. } => Ok(format!("[sha256:{}]", self.array_hash())),
            CapturedValue::ArrayRef { sha256 } => Ok(format!("[sha256:{sha256}]")),
        }
    }

    fn array_hash(&self) -> String {
        format!("{:x}", Sha256::digest(self.canonical().as_bytes()))
    }

    /// Canonical encoding hashed into array key tokens: compact JSON
    /// `{"dims":[d1,...],"values":["v0",...]}`, values row-major as decimals in [0, p).
    pub fn canonical(&self) -> String {
        match self {
            CapturedValue::Scalar { value } => value.clone(),
            CapturedValue::Array { dims, values } => {
                serde_json::to_string(&CanonicalArray { dims, values }).unwrap_or_default()
            }
            CapturedValue::ArrayRef { sha256 } => format!("sha256:{sha256}"),
        }
    }

    /// The circom literal passed in a wrapper's `component main` call.
    pub fn literal(&self, prime: &BigUint) -> Result<String> {
        match self {
            CapturedValue::Scalar { value } => signed_decimal(value, prime),
            CapturedValue::Array { dims, values } => {
                ensure!(
                    !dims.is_empty() && dims.iter().product::<usize>() == values.len(),
                    "array value count does not match its dimensions"
                );
                Ok(nested_literal(dims, values))
            }
            CapturedValue::ArrayRef { .. } => anyhow::bail!("an interned array has no literal"),
        }
    }
}

fn nested_literal(dims: &[usize], values: &[String]) -> String {
    if dims.len() == 1 {
        return format!("[{}]", values.join(", "));
    }
    let stride = dims[1..].iter().product::<usize>();
    let parts = (0..dims[0])
        .map(|row| nested_literal(&dims[1..], &values[row * stride..(row + 1) * stride]))
        .collect::<Vec<_>>();
    format!("[{}]", parts.join(", "))
}

pub fn signed_decimal(value: &str, prime: &BigUint) -> Result<String> {
    let parsed = value
        .parse::<BigUint>()
        .with_context(|| format!("captured value {value} is not a decimal"))?;
    ensure!(&parsed < prime, "captured value is not canonical");
    if parsed > prime >> 1 {
        Ok(format!("-{}", prime - parsed))
    } else {
        Ok(parsed.to_string())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct CapturedInstance {
    /// Instance path in circom's `.sym` naming, anonymous offsets mapped to the original source.
    pub path: String,
    pub template_name: String,
    pub source_path: PathBuf,
    /// One value per template parameter; None when some argument could not be captured.
    pub arguments: Option<Vec<CapturedValue>>,
    pub parent: Option<String>,
    /// The child component name in discovery's naming: `ark[1]`, or `@anonymous:<line>:<char>`.
    pub component_name: Option<String>,
    /// Line of the instantiation in the parent template's source.
    pub line: Option<usize>,
    pub unsupported: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct TemplateRecord {
    pub id: usize,
    pub name: String,
    pub source_path: PathBuf,
    pub start_line: usize,
    pub end_line: usize,
    pub instrumented: bool,
    pub array_parameters: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ArtifactRecord {
    pub path: PathBuf,
    pub sha256: String,
    pub bytes: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct InstanceCapture {
    pub schema: String,
    pub entrypoint: PathBuf,
    pub project_root: PathBuf,
    pub library_paths: Vec<PathBuf>,
    /// `captured`, `scan_failed`, `compile_failed`, `compile_timed_out`, or `read_failed`.
    pub status: String,
    pub failure: Option<String>,
    pub prime: Option<String>,
    pub instances: Vec<CapturedInstance>,
    pub unsupported: Vec<UnsupportedCase>,
    pub templates: Vec<TemplateRecord>,
    pub compile: Option<ToolCapture>,
    /// Compilations of the diagnostic copy, including retries after a capture statement circom
    /// rejected (for example an array parameter taken for a scalar).
    pub compile_attempts: usize,
    pub compile_seconds: f64,
    pub scan_seconds: f64,
    pub read_seconds: f64,
    /// Matching captured values to instances and their creating sites.
    #[serde(default)]
    pub assemble_seconds: f64,
    pub capture_signals: usize,
    pub capture_constraints: usize,
    pub diagnostic_r1cs: Option<ArtifactRecord>,
    pub diagnostic_sym: Option<ArtifactRecord>,
    /// Distinct array arguments by the hash in their key token, when arguments are interned.
    #[serde(default)]
    pub arrays: BTreeMap<String, CapturedValue>,
    /// Array parameters of the main component, whose values no template site passes: taken
    /// from integer literals in the `component main` statement (circom reduces them mod p).
    #[serde(default)]
    pub main_literal_parameters: Vec<String>,
}

impl InstanceCapture {
    /// The capture with every array argument replaced by a reference into `arrays`.
    pub fn interned(&self) -> InstanceCapture {
        let mut capture = self.clone();
        for instance in &mut capture.instances {
            for value in instance.arguments.iter_mut().flatten() {
                if matches!(value, CapturedValue::Array { .. }) {
                    let sha256 = value.array_hash();
                    let array = std::mem::replace(
                        value,
                        CapturedValue::ArrayRef {
                            sha256: sha256.clone(),
                        },
                    );
                    capture.arrays.entry(sha256).or_insert(array);
                }
            }
        }
        capture
    }

    pub fn complete(&self) -> bool {
        self.status == "captured"
            && self.unsupported.is_empty()
            && self.instances.iter().all(|i| i.arguments.is_some())
    }

    pub fn prime(&self) -> Result<BigUint> {
        self.prime
            .as_deref()
            .context("capture has no prime")?
            .parse()
            .context("capture prime")
    }

    /// The circom literal of an argument, resolving interned arrays.
    pub fn literal(&self, value: &CapturedValue, prime: &BigUint) -> Result<String> {
        match value {
            CapturedValue::ArrayRef { sha256 } => self
                .arrays
                .get(sha256)
                .context("interned array is missing")?
                .literal(prime),
            other => other.literal(prime),
        }
    }

    pub fn root(&self) -> Option<&CapturedInstance> {
        self.instances
            .iter()
            .find(|instance| instance.path == "main")
    }

    /// `source::Template(tokens)` of an instance, when its arguments were captured.
    pub fn instance_key(&self, instance: &CapturedInstance) -> Result<Option<String>> {
        let prime = self.prime()?;
        let Some(arguments) = &instance.arguments else {
            return Ok(None);
        };
        let tokens = arguments
            .iter()
            .map(|value| value.key_token(&prime))
            .collect::<Result<Vec<_>>>()?;
        Ok(Some(crate::targets::instance_key(
            &instance.source_path,
            &instance.template_name,
            &tokens,
        )))
    }
}

pub struct CaptureRequest<'a> {
    pub entrypoint: &'a Path,
    pub project_root: &'a Path,
    pub library_paths: &'a [PathBuf],
    pub circom_bin: &'a Path,
    pub work_dir: &'a Path,
    pub timeout_seconds: u64,
}

// ---------------------------------------------------------------------------------------
// Source scan

#[derive(Debug, Clone)]
struct Site {
    id: usize,
    line: usize,
    /// Byte offsets of the statement's first token and just after its `;`.
    statement_start: usize,
    statement_end: usize,
    declaration: bool,
    /// Named: component name and index expressions. Anonymous: None.
    component: Option<(String, Vec<String>)>,
    /// Anonymous: the callee token's byte and character offsets.
    anonymous_offset: Option<(usize, usize)>,
    callee: String,
    arguments: Vec<Vec<Token>>,
}

#[derive(Debug, Clone)]
struct ScannedTemplate {
    id: usize,
    name: String,
    file: PathBuf,
    start_line: usize,
    end_line: usize,
    parameters: Vec<String>,
    custom: bool,
    body_open: usize,
    sites: Vec<Site>,
    /// Array variables: name -> dimension expressions; None when declared more than once.
    array_vars: HashMap<String, Option<Vec<String>>>,
    indexed: HashSet<String>,
    /// (function name, argument position, identifier) for bare identifiers passed to calls.
    function_arguments: Vec<(String, usize, String)>,
}

#[derive(Debug, Clone)]
struct ScannedFunction {
    parameters: Vec<String>,
    indexed: HashSet<String>,
}

struct Scan {
    templates: Vec<ScannedTemplate>,
    functions: HashMap<String, ScannedFunction>,
    sources: HashMap<PathBuf, String>,
    files: Vec<PathBuf>,
    issues: Vec<UnsupportedCase>,
}

fn source_text(source: &str, tokens: &[Token]) -> String {
    let (Some(first), Some(last)) = (tokens.first(), tokens.last()) else {
        return String::new();
    };
    let end = last.byte_offset + token_to_text(last).len();
    source
        .get(first.byte_offset..end.min(source.len()))
        .map(str::to_owned)
        .unwrap_or_else(|| {
            tokens
                .iter()
                .map(token_to_text)
                .collect::<Vec<_>>()
                .join(" ")
        })
}

/// Resolves an include like discovery: the including file's directory, the project root, then
/// the library paths.
fn resolve_include(
    from: &Path,
    include: &str,
    project_root: &Path,
    library_paths: &[PathBuf],
) -> Option<PathBuf> {
    std::iter::once(from.parent().unwrap_or(project_root).join(include))
        .chain(std::iter::once(project_root.join(include)))
        .chain(library_paths.iter().map(|library| library.join(include)))
        .find_map(|candidate| fs::canonicalize(candidate).ok().filter(|p| p.is_file()))
}

fn scan_closure(entrypoint: &Path, project_root: &Path, library_paths: &[PathBuf]) -> Result<Scan> {
    let mut scan = Scan {
        templates: Vec::new(),
        functions: HashMap::new(),
        sources: HashMap::new(),
        files: Vec::new(),
        issues: Vec::new(),
    };
    let mut queue = vec![entrypoint.to_path_buf()];
    let mut seen = HashSet::new();
    let mut tokens_by_file = Vec::new();
    while let Some(path) = queue.pop() {
        if !seen.insert(path.clone()) {
            continue;
        }
        let source =
            fs::read_to_string(&path).with_context(|| format!("read {}", path.display()))?;
        let tokens = match lex(&source) {
            Ok(tokens) => tokens,
            Err((line, reason)) => {
                scan.issues.push(UnsupportedCase {
                    source_path: path.clone(),
                    line: Some(line),
                    construct: "source file".into(),
                    reason: format!("instance capture cannot lex the file: {reason}"),
                });
                continue;
            }
        };
        let mut cursor = 0;
        while cursor < tokens.len() {
            if token_is_identifier(&tokens[cursor], "include") {
                if let Some(TokenKind::StringLiteral(include)) =
                    tokens.get(cursor + 1).map(|token| &token.kind)
                {
                    match resolve_include(&path, include, project_root, library_paths) {
                        Some(included) => queue.push(included),
                        None => scan.issues.push(UnsupportedCase {
                            source_path: path.clone(),
                            line: Some(tokens[cursor].line),
                            construct: format!("include \"{include}\""),
                            reason: "instance capture cannot resolve the include".into(),
                        }),
                    }
                }
            }
            cursor += 1;
        }
        scan.files.push(path.clone());
        tokens_by_file.push((path.clone(), tokens));
        scan.sources.insert(path, source);
    }
    // Definitions first, so call sites can be told from function calls.
    let mut template_names = HashSet::new();
    let mut definitions = Vec::new();
    for (path, tokens) in &tokens_by_file {
        let mut cursor = 0;
        while cursor < tokens.len() {
            let keyword = token_identifier(&tokens[cursor]);
            if !matches!(keyword, Some("template" | "function")) {
                cursor += 1;
                continue;
            }
            let is_template = keyword == Some("template");
            let mut name_index = cursor + 1;
            let mut custom = false;
            while let Some(modifier) = tokens.get(name_index).and_then(token_identifier) {
                match modifier {
                    "custom" => custom = true,
                    "parallel" => {}
                    _ => break,
                }
                name_index += 1;
            }
            let (Some(name), Some(open)) = (
                tokens.get(name_index).and_then(token_identifier),
                tokens.get(name_index + 1),
            ) else {
                cursor += 1;
                continue;
            };
            if !token_is_symbol(open, '(') {
                cursor += 1;
                continue;
            }
            let Some(close) = find_matching(tokens, name_index + 1, '(', ')') else {
                cursor += 1;
                continue;
            };
            let parameters = tokens[name_index + 2..close]
                .iter()
                .filter_map(token_identifier)
                .map(str::to_owned)
                .collect::<Vec<_>>();
            let Some(body_open) =
                (close + 1..tokens.len()).find(|index| token_is_symbol(&tokens[*index], '{'))
            else {
                cursor += 1;
                continue;
            };
            let Some(body_close) = find_matching(tokens, body_open, '{', '}') else {
                cursor += 1;
                continue;
            };
            if is_template {
                template_names.insert(name.to_owned());
            }
            definitions.push((
                path.clone(),
                is_template,
                name.to_owned(),
                parameters,
                custom,
                tokens[cursor].line,
                body_open,
                body_close,
            ));
            cursor = body_close + 1;
        }
    }
    let tokens_of = tokens_by_file
        .iter()
        .map(|(path, tokens)| (path.clone(), tokens))
        .collect::<HashMap<_, _>>();
    for (path, is_template, name, parameters, custom, line, body_open, body_close) in definitions {
        let tokens = tokens_of[&path];
        let body = &tokens[body_open + 1..body_close];
        let indexed = body
            .windows(2)
            .filter(|pair| token_is_symbol(&pair[1], '['))
            .filter_map(|pair| token_identifier(&pair[0]).map(str::to_owned))
            .collect::<HashSet<_>>();
        if !is_template {
            scan.functions.insert(
                name,
                ScannedFunction {
                    parameters,
                    indexed,
                },
            );
            continue;
        }
        let source = &scan.sources[&path];
        let mut template = ScannedTemplate {
            id: scan.templates.len(),
            name,
            file: path.clone(),
            start_line: line,
            end_line: tokens[body_close].line,
            parameters,
            custom,
            body_open: tokens[body_open].byte_offset + 1,
            sites: Vec::new(),
            array_vars: HashMap::new(),
            indexed,
            function_arguments: Vec::new(),
        };
        let mut statements = Vec::new();
        walk_statements(body, &mut statements);
        let declared = statements
            .iter()
            .filter(|(start, _)| token_is_identifier(&body[*start], "component"))
            .filter_map(|(start, _)| body.get(start + 1).and_then(token_identifier))
            .map(str::to_owned)
            .collect::<HashSet<_>>();
        for (start, end) in statements {
            scan_statement(
                &body[start..=end],
                source,
                &template_names,
                &declared,
                &mut template,
            );
        }
        scan.templates.push(template);
    }
    Ok(scan)
}

/// Statements of a block as (first token, `;` token) index pairs, descending into blocks and
/// control-flow bodies.
fn walk_statements(tokens: &[Token], out: &mut Vec<(usize, usize)>) {
    walk_range(tokens, 0, tokens.len(), out);
}

fn walk_range(tokens: &[Token], mut cursor: usize, end: usize, out: &mut Vec<(usize, usize)>) {
    while cursor < end {
        let token = &tokens[cursor];
        if token_is_symbol(token, '{') {
            let close = find_matching(tokens, cursor, '{', '}').unwrap_or(end - 1);
            walk_range(tokens, cursor + 1, close, out);
            cursor = close + 1;
            continue;
        }
        if token_is_symbol(token, '}') || token_is_symbol(token, ';') {
            cursor += 1;
            continue;
        }
        if token_is_identifier(token, "else") {
            cursor += 1;
            continue;
        }
        if ["for", "while", "if"]
            .iter()
            .any(|keyword| token_is_identifier(token, keyword))
            && tokens
                .get(cursor + 1)
                .is_some_and(|next| token_is_symbol(next, '('))
        {
            let Some(header_close) = find_matching(tokens, cursor + 1, '(', ')') else {
                return;
            };
            cursor = header_close + 1;
            continue;
        }
        let Some(statement_end) = find_statement_end(&tokens[..end], cursor) else {
            return;
        };
        out.push((cursor, statement_end));
        cursor = statement_end + 1;
    }
}

fn scan_statement(
    statement: &[Token],
    source: &str,
    templates: &HashSet<String>,
    declared: &HashSet<String>,
    template: &mut ScannedTemplate,
) {
    let line = statement[0].line;
    let statement_start = statement[0].byte_offset;
    let statement_end = statement
        .last()
        .map_or(statement_start, |t| t.byte_offset + 1);
    // `var name[d1][d2] ...`: an array variable and its declared dimensions.
    if token_is_identifier(&statement[0], "var") {
        if let (Some(name), Some(open)) = (
            statement.get(1).and_then(token_identifier),
            statement.get(2),
        ) {
            if token_is_symbol(open, '[') {
                let mut dims = Vec::new();
                let mut cursor = 2;
                while statement
                    .get(cursor)
                    .is_some_and(|token| token_is_symbol(token, '['))
                {
                    let Some(close) = find_matching(statement, cursor, '[', ']') else {
                        break;
                    };
                    dims.push(source_text(source, &statement[cursor + 1..close]));
                    cursor = close + 1;
                }
                template
                    .array_vars
                    .entry(name.to_owned())
                    .and_modify(|existing| *existing = None)
                    .or_insert(Some(dims));
            }
        }
    }
    // Bare identifiers passed to function calls, for array-parameter inference.
    for (index, token) in statement.iter().enumerate() {
        let Some(name) = token_identifier(token) else {
            continue;
        };
        if templates.contains(name)
            || !statement
                .get(index + 1)
                .is_some_and(|next| token_is_symbol(next, '('))
        {
            continue;
        }
        if let Some(close) = find_matching(statement, index + 1, '(', ')') {
            if let Ok(arguments) = split_top_level(&statement[index + 2..close], ',') {
                for (position, argument) in arguments.iter().enumerate() {
                    if let [single] = argument.as_slice() {
                        if let Some(identifier) = token_identifier(single) {
                            template.function_arguments.push((
                                name.to_owned(),
                                position,
                                identifier.to_owned(),
                            ));
                        }
                    }
                }
            }
        }
    }
    let mut push = |component: Option<(String, Vec<String>)>,
                    anonymous_offset: Option<(usize, usize)>,
                    callee: &str,
                    arguments: Vec<Vec<Token>>,
                    declaration: bool,
                    line: usize| {
        let id = template.sites.len();
        template.sites.push(Site {
            id,
            line,
            statement_start,
            statement_end,
            declaration,
            component,
            anonymous_offset,
            callee: callee.to_owned(),
            arguments,
        });
    };
    // Named instantiation: `component c = T(...)` or `c[i][j] = T(...)`.
    let declaration = ["component", "signal", "var"]
        .iter()
        .any(|keyword| token_is_identifier(&statement[0], keyword));
    let name_index = usize::from(token_is_identifier(&statement[0], "component"));
    if let Some(name) = statement.get(name_index).and_then(token_identifier) {
        if name_index == 1 || declared.contains(name) {
            let mut cursor = name_index + 1;
            let mut indices = Vec::new();
            while statement
                .get(cursor)
                .is_some_and(|token| token_is_symbol(token, '['))
            {
                let Some(close) = find_matching(statement, cursor, '[', ']') else {
                    break;
                };
                indices.push(source_text(source, &statement[cursor + 1..close]));
                cursor = close + 1;
            }
            if statement
                .get(cursor)
                .is_some_and(|token| token_is_symbol(token, '='))
            {
                let mut callee_index = cursor + 1;
                if statement
                    .get(callee_index)
                    .is_some_and(|token| token_is_identifier(token, "parallel"))
                {
                    callee_index += 1;
                }
                if let Some(callee) = statement
                    .get(callee_index)
                    .and_then(token_identifier)
                    .filter(|callee| templates.contains(*callee))
                {
                    if let Some(close) = find_matching(statement, callee_index + 1, '(', ')') {
                        if close + 1 == statement.len() - 1
                            && (name_index != 1 || indices.is_empty())
                        {
                            let arguments =
                                split_top_level(&statement[callee_index + 2..close], ',')
                                    .unwrap_or_default()
                                    .into_iter()
                                    .filter(|argument| !argument.is_empty())
                                    .collect();
                            push(
                                Some((name.to_owned(), indices)),
                                None,
                                callee,
                                arguments,
                                name_index == 1,
                                line,
                            );
                            return;
                        }
                    }
                }
            }
        }
    }
    // Anonymous components: `T(args)(signals)` anywhere in the statement.
    for (index, token) in statement.iter().enumerate() {
        let Some(callee) = token_identifier(token).filter(|name| templates.contains(*name)) else {
            continue;
        };
        if !statement
            .get(index + 1)
            .is_some_and(|next| token_is_symbol(next, '('))
        {
            continue;
        }
        let Some(close) = find_matching(statement, index + 1, '(', ')') else {
            continue;
        };
        if !statement
            .get(close + 1)
            .is_some_and(|next| token_is_symbol(next, '('))
        {
            continue;
        }
        let arguments = split_top_level(&statement[index + 2..close], ',')
            .unwrap_or_default()
            .into_iter()
            .filter(|argument| !argument.is_empty())
            .collect();
        // circom names an anonymous component by its callee token's line and offset.
        push(
            None,
            Some((token.byte_offset, token.offset)),
            callee,
            arguments,
            declaration,
            token.line,
        );
    }
}

/// Which template parameters are arrays: indexed in the body, passed to an array parameter of a
/// called template, or passed to a function that indexes that parameter. Iterated to a fixpoint.
fn infer_array_parameters(scan: &Scan, assumed: &HashSet<(usize, String)>) -> Vec<HashSet<String>> {
    let by_name = scan
        .templates
        .iter()
        .map(|template| (template.name.as_str(), template.id))
        .collect::<HashMap<_, _>>();
    let mut arrays = scan
        .templates
        .iter()
        .map(|template| {
            template
                .parameters
                .iter()
                .filter(|parameter| {
                    template.indexed.contains(*parameter)
                        || assumed.contains(&(template.id, (*parameter).clone()))
                        || template.function_arguments.iter().any(
                            |(function, position, identifier)| {
                                identifier == *parameter
                                    && scan.functions.get(function).is_some_and(|f| {
                                        f.parameters
                                            .get(*position)
                                            .is_some_and(|p| f.indexed.contains(p))
                                    })
                            },
                        )
                })
                .cloned()
                .collect::<HashSet<_>>()
        })
        .collect::<Vec<_>>();
    loop {
        let mut changed = false;
        for template in &scan.templates {
            for site in &template.sites {
                let Some(&callee) = by_name.get(site.callee.as_str()) else {
                    continue;
                };
                for (position, argument) in site.arguments.iter().enumerate() {
                    let callee_parameter = scan.templates[callee].parameters.get(position);
                    if let ([single], Some(parameter)) = (argument.as_slice(), callee_parameter) {
                        if let Some(identifier) = token_identifier(single) {
                            if arrays[callee].contains(parameter)
                                && template.parameters.iter().any(|p| p == identifier)
                                && arrays[template.id].insert(identifier.to_owned())
                            {
                                changed = true;
                            }
                        }
                    }
                }
            }
        }
        if !changed {
            return arrays;
        }
    }
}

// ---------------------------------------------------------------------------------------
// Instrumentation

#[derive(Debug, Clone)]
enum ArrayArgument {
    /// Captured at the site with these dimension expressions (and an index prefix for a slice).
    Captured {
        expression: String,
        dims: Vec<String>,
    },
    /// The caller's own array parameter.
    PassThrough(String),
    Uncapturable(String),
}

/// Text inserted at one original byte position; `parts` label sub-ranges of `text`.
#[derive(Debug, Clone)]
struct Insertion {
    position: usize,
    text: String,
    parts: Vec<(std::ops::Range<usize>, CaptureStatement)>,
}

impl Insertion {
    fn plain(position: usize, text: &str) -> Self {
        Self {
            position,
            text: text.to_owned(),
            parts: Vec::new(),
        }
    }

    fn push(&mut self, text: &str, statement: CaptureStatement) {
        let start = self.text.len();
        self.text.push_str(text);
        self.parts.push((start..self.text.len(), statement));
    }
}

struct Plan {
    /// Per file, in insertion order. Inserted text never contains a newline. At one position
    /// earlier insertions end up first.
    insertions: BTreeMap<PathBuf, Vec<Insertion>>,
    arrays: Vec<HashSet<String>>,
    /// (template id, site id, argument position) -> how the array argument is obtained.
    array_arguments: HashMap<(usize, usize, usize), ArrayArgument>,
}

impl Plan {
    fn file_insertions(&self, file: &Path) -> Vec<(usize, usize)> {
        self.insertions
            .get(file)
            .map(|list| list.iter().map(|i| (i.position, i.text.len())).collect())
            .unwrap_or_default()
    }
}

/// The instrumented text of `source` and, for each insertion, its start in that text.
fn apply(source: &str, insertions: &[Insertion]) -> (String, Vec<usize>) {
    let mut order = (0..insertions.len()).collect::<Vec<_>>();
    // Ascending position; at one position, insertion order.
    order.sort_by_key(|index| (insertions[*index].position, *index));
    let mut text = String::with_capacity(source.len());
    let mut starts = vec![0; insertions.len()];
    let mut cursor = 0;
    for index in order {
        let insertion = &insertions[index];
        text.push_str(&source[cursor..insertion.position]);
        cursor = insertion.position;
        starts[index] = text.len();
        text.push_str(&insertion.text);
    }
    text.push_str(&source[cursor..]);
    (text, starts)
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
enum CaptureStatement {
    Parameter(usize, String),
    Site(usize, usize),
    Marker(usize),
}

fn plan_instrumentation(
    scan: &Scan,
    assumed_arrays: &HashSet<(usize, String)>,
    skipped_sites: &HashSet<(usize, usize)>,
) -> Plan {
    let arrays = infer_array_parameters(scan, assumed_arrays);
    let by_name = scan
        .templates
        .iter()
        .map(|template| (template.name.as_str(), template.id))
        .collect::<HashMap<_, _>>();
    let mut plan = Plan {
        insertions: BTreeMap::new(),
        arrays: arrays.clone(),
        array_arguments: HashMap::new(),
    };
    for template in &scan.templates {
        if template.custom {
            continue;
        }
        let source = &scan.sources[&template.file];
        let id = template.id;
        let mut header = Insertion::plain(template.body_open, "");
        header.push(
            &format!(" signal {CAPTURE_PREFIX}t{id} <-- 0; {CAPTURE_PREFIX}t{id} === {id};"),
            CaptureStatement::Marker(id),
        );
        for (index, parameter) in template.parameters.iter().enumerate() {
            if arrays[id].contains(parameter) {
                continue;
            }
            header.push(
                &format!(
                    " signal {CAPTURE_PREFIX}p{index} <-- 0; {CAPTURE_PREFIX}p{index} === {parameter};"
                ),
                CaptureStatement::Parameter(id, parameter.clone()),
            );
        }
        // Site signals are declared at the top (signals cannot be declared inside loops).
        let mut by_statement: BTreeMap<(usize, usize, bool), Vec<(String, CaptureStatement)>> =
            BTreeMap::new();
        for site in &template.sites {
            if skipped_sites.contains(&(id, site.id)) {
                continue;
            }
            let prefix = format!("{CAPTURE_PREFIX}s{}", site.id);
            let mut declarations = format!(" signal {prefix}_n <-- 0;");
            let mut captures = format!(" {prefix}_n === 1;");
            if let Some((_, indices)) = &site.component {
                for (position, index) in indices.iter().enumerate() {
                    declarations.push_str(&format!(" signal {prefix}_i{position} <-- 0;"));
                    captures.push_str(&format!(" {prefix}_i{position} === ({index});"));
                }
            }
            if let Some(&callee) = by_name.get(site.callee.as_str()) {
                for (position, argument) in site.arguments.iter().enumerate() {
                    let Some(parameter) = scan.templates[callee].parameters.get(position) else {
                        continue;
                    };
                    if !arrays[callee].contains(parameter) {
                        continue;
                    }
                    let how = array_argument(template, &arrays[id], argument, source);
                    if let ArrayArgument::Captured { expression, dims } = &how {
                        // Every execution records the dimensions and a field fingerprint; full
                        // values only at the first execution in this instance and whenever the
                        // fingerprint differs from the previous execution's.
                        let counter = format!("{prefix}_k{position}");
                        let hash = format!("{prefix}_h{position}");
                        let last = format!("{prefix}_l{position}");
                        declarations.push_str(&format!(
                            " signal {prefix}_a{position} <-- 0; signal {prefix}_f{position} <-- 0; var {counter} = 0; var {hash} = 0; var {last} = 0;"
                        ));
                        let mut access = expression.clone();
                        let mut loops = String::new();
                        for (level, dim) in dims.iter().enumerate() {
                            declarations
                                .push_str(&format!(" signal {prefix}_d{position}_{level} <-- 0;"));
                            captures
                                .push_str(&format!(" {prefix}_d{position}_{level} === ({dim});"));
                            let variable = format!("{prefix}_v{position}_{level}");
                            loops.push_str(&format!(
                                " for (var {variable} = 0; {variable} < ({dim}); {variable}++) {{"
                            ));
                            access.push_str(&format!("[{variable}]"));
                        }
                        let close = " }".repeat(dims.len());
                        captures.push_str(&format!(
                            " {hash} = 0;{loops} {hash} = {hash} * {FINGERPRINT_BASE} + {access};{close} {prefix}_f{position} === {hash};"
                        ));
                        captures.push_str(&format!(
                            " if ({counter} == 0 || {hash} != {last}) {{{loops} {prefix}_a{position} === {access};{close} }} {last} = {hash}; {counter} = {counter} + 1;"
                        ));
                    }
                    plan.array_arguments.insert((id, site.id, position), how);
                }
            }
            header.push(&declarations, CaptureStatement::Site(id, site.id));
            by_statement
                .entry((site.statement_start, site.statement_end, site.declaration))
                .or_default()
                .push((captures, CaptureStatement::Site(id, site.id)));
        }
        let file = plan.insertions.entry(template.file.clone()).or_default();
        file.push(header);
        for ((start, end, declaration), captures) in by_statement {
            // A braced block keeps the captures and the statement together even when the
            // statement is the unbraced body of a loop or conditional. Declarations cannot be
            // such a body and must stay in their scope, so they are not wrapped.
            let mut insertion = Insertion::plain(start, if declaration { "" } else { "{" });
            for (text, statement) in captures {
                insertion.push(&text, statement);
            }
            insertion.text.push(' ');
            file.push(insertion);
            if !declaration {
                file.push(Insertion::plain(end, " }"));
            }
        }
    }
    plan
}

fn array_argument(
    template: &ScannedTemplate,
    array_parameters: &HashSet<String>,
    argument: &[Token],
    source: &str,
) -> ArrayArgument {
    let Some(name) = argument.first().and_then(token_identifier) else {
        return ArrayArgument::Uncapturable(format!(
            "array argument `{}` is not a variable",
            source_text(source, argument)
        ));
    };
    // Index prefix of a slice such as `M[i]`.
    let mut cursor = 1;
    let mut prefix = 0;
    while argument
        .get(cursor)
        .is_some_and(|token| token_is_symbol(token, '['))
    {
        let Some(close) = find_matching(argument, cursor, '[', ']') else {
            break;
        };
        prefix += 1;
        cursor = close + 1;
    }
    if cursor != argument.len() {
        return ArrayArgument::Uncapturable(format!(
            "array argument `{}` is an expression, not a variable or its slice",
            source_text(source, argument)
        ));
    }
    if prefix == 0 && array_parameters.contains(name) {
        return ArrayArgument::PassThrough(name.to_owned());
    }
    match template.array_vars.get(name) {
        Some(Some(dims)) if dims.len() > prefix => ArrayArgument::Captured {
            expression: source_text(source, argument),
            dims: dims[prefix..].to_vec(),
        },
        Some(Some(_)) => ArrayArgument::Uncapturable(format!(
            "array argument `{}` indexes every declared dimension",
            source_text(source, argument)
        )),
        Some(None) => ArrayArgument::Uncapturable(format!(
            "array variable `{name}` is declared more than once; its dimensions are ambiguous"
        )),
        None => ArrayArgument::Uncapturable(format!(
            "array argument `{}` has no declared dimensions in {}",
            source_text(source, argument),
            template.name
        )),
    }
}

/// Copied entrypoint, copied library paths, and (original, copy) base directories.
type CopiedTree = (PathBuf, Vec<PathBuf>, Vec<(PathBuf, PathBuf)>);

/// Copies the `.circom` files of the project root and of libraries outside it, applies the
/// insertions, and returns the copied entrypoint and library paths.
fn write_copy(request: &CaptureRequest, plan: &Plan, directory: &Path) -> Result<CopiedTree> {
    if directory.exists() {
        fs::remove_dir_all(directory)?;
    }
    let mut bases = vec![(request.project_root.to_path_buf(), directory.join("root"))];
    for (index, library) in request.library_paths.iter().enumerate() {
        if !library.starts_with(request.project_root) {
            bases.push((library.clone(), directory.join(format!("lib{index}"))));
        }
    }
    for (from, to) in &bases {
        copy_circom_tree(from, to)?;
    }
    let locate = |path: &Path| {
        bases
            .iter()
            .find_map(|(from, to)| path.strip_prefix(from).ok().map(|rest| to.join(rest)))
    };
    for (file, insertions) in &plan.insertions {
        let (text, _) = apply(&fs::read_to_string(file)?, insertions);
        let target = locate(file).with_context(|| {
            format!(
                "{} is outside the copied project and libraries",
                file.display()
            )
        })?;
        if fs::symlink_metadata(&target).is_ok_and(|meta| meta.file_type().is_symlink()) {
            fs::remove_file(&target)?;
        }
        fs::create_dir_all(target.parent().context("copy has no parent")?)?;
        fs::write(&target, text)?;
    }
    let entry = locate(request.entrypoint).context("entrypoint is outside the project root")?;
    let libraries = std::iter::once(directory.join("root"))
        .chain(
            request
                .library_paths
                .iter()
                .map(|library| locate(library).unwrap_or_else(|| library.clone())),
        )
        .collect();
    Ok((entry, libraries, bases))
}

fn copy_circom_tree(from: &Path, to: &Path) -> Result<()> {
    for entry in walkdir::WalkDir::new(from).follow_links(false) {
        let entry = entry?;
        let target = to.join(entry.path().strip_prefix(from)?);
        if entry.file_type().is_symlink() {
            fs::create_dir_all(target.parent().context("copy target has no parent")?)?;
            #[cfg(unix)]
            std::os::unix::fs::symlink(fs::read_link(entry.path())?, &target)?;
        } else if entry.file_type().is_file()
            && entry.path().extension().is_some_and(|ext| ext == "circom")
        {
            fs::create_dir_all(target.parent().context("copy target has no parent")?)?;
            fs::copy(entry.path(), &target)?;
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------------------
// Reading the compiled copy

/// Capture-signal wires from `.sym`, read line by line: wire -> (instance path, signal).
fn read_capture_symbols(sym: &Path) -> Result<HashMap<u32, (String, String)>> {
    let file = fs::File::open(sym).with_context(|| format!("open {}", sym.display()))?;
    let mut wires = HashMap::new();
    for line in BufReader::new(file).lines() {
        let line = line?;
        if !line.contains(CAPTURE_PREFIX) {
            continue;
        }
        let mut fields = line.splitn(4, ',');
        let (_, Some(wire), _, Some(name)) =
            (fields.next(), fields.next(), fields.next(), fields.next())
        else {
            continue;
        };
        let Some((instance, signal)) = name.rsplit_once('.') else {
            continue;
        };
        if !signal.starts_with(CAPTURE_PREFIX) {
            continue;
        }
        let wire: i64 = wire.parse().context("sym wire")?;
        if let Ok(wire) = u32::try_from(wire) {
            wires.insert(wire, (instance.to_owned(), signal.to_owned()));
        }
    }
    Ok(wires)
}

/// Streams the R1CS and collects, per capture wire, the constants `v` of its `s === v`
/// constraints in file order. Returns the prime and the number of capture constraints.
fn read_capture_values(
    r1cs: &Path,
    wires: &HashMap<u32, (String, String)>,
) -> Result<(BigUint, HashMap<u32, Vec<BigUint>>, usize)> {
    let mut file = fs::File::open(r1cs).with_context(|| format!("open {}", r1cs.display()))?;
    let mut header = [0u8; 12];
    file.read_exact(&mut header)?;
    ensure!(&header[..4] == b"r1cs", "invalid R1CS magic");
    let sections = u32::from_le_bytes(header[8..12].try_into()?);
    let mut offsets = HashMap::new();
    let mut position = 12u64;
    for _ in 0..sections {
        let mut entry = [0u8; 12];
        file.seek(SeekFrom::Start(position))?;
        file.read_exact(&mut entry)?;
        let kind = u32::from_le_bytes(entry[..4].try_into()?);
        let length = u64::from_le_bytes(entry[4..12].try_into()?);
        offsets.insert(kind, position + 12);
        position += 12 + length;
    }
    let header_offset = *offsets.get(&1).context("R1CS header section missing")?;
    file.seek(SeekFrom::Start(header_offset))?;
    let mut reader = BufReader::with_capacity(1 << 20, &mut file);
    let field_bytes = read_u32(&mut reader)? as usize;
    let mut prime_bytes = vec![0u8; field_bytes];
    reader.read_exact(&mut prime_bytes)?;
    let prime = BigUint::from_bytes_le(&prime_bytes);
    let mut rest = [0u8; 16 + 8 + 4];
    reader.read_exact(&mut rest)?;
    let constraints = u32::from_le_bytes(rest[24..28].try_into()?);
    drop(reader);
    let constraint_offset = *offsets.get(&2).context("R1CS constraint section missing")?;
    file.seek(SeekFrom::Start(constraint_offset))?;
    let mut reader = BufReader::with_capacity(1 << 22, file);
    let mut values: HashMap<u32, Vec<BigUint>> = HashMap::new();
    let mut captured = 0usize;
    let mut value = vec![0u8; field_bytes];
    // Coefficients repeat (circom writes ±1), so each inverse is computed once.
    let mut inverses: HashMap<BigUint, BigUint> = HashMap::new();
    let exponent = &prime - BigUint::from(2u32);
    for _ in 0..constraints {
        let mut empty_ab = true;
        let mut terms: Vec<(u32, BigUint)> = Vec::new();
        for part in 0..3 {
            let count = read_u32(&mut reader)?;
            if part < 2 && count > 0 {
                empty_ab = false;
            }
            for _ in 0..count {
                let wire = read_u32(&mut reader)?;
                reader.read_exact(&mut value)?;
                if part == 2 && empty_ab && terms.len() <= 2 {
                    terms.push((wire, BigUint::from_bytes_le(&value)));
                }
            }
        }
        if !empty_ab || terms.is_empty() || terms.len() > 2 {
            continue;
        }
        let Some((wire, coefficient)) = terms
            .iter()
            .find(|(wire, _)| *wire != 0 && wires.contains_key(wire))
            .cloned()
        else {
            continue;
        };
        if terms.iter().any(|(other, _)| *other != 0 && *other != wire) {
            continue;
        }
        let constant = terms
            .iter()
            .find(|(other, _)| *other == 0)
            .map(|(_, c)| c.clone())
            .unwrap_or_default();
        // c·s + k = 0  =>  s = -k / c
        let inverse = inverses
            .entry(coefficient)
            .or_insert_with_key(|coefficient| coefficient.modpow(&exponent, &prime));
        let solved = ((&prime - constant % &prime) % &prime * &*inverse) % &prime;
        values.entry(wire).or_default().push(solved);
        captured += 1;
    }
    Ok((prime, values, captured))
}

fn read_u32(reader: &mut impl Read) -> Result<u32> {
    let mut bytes = [0u8; 4];
    reader.read_exact(&mut bytes)?;
    Ok(u32::from_le_bytes(bytes))
}

/// Splits `a.b[1].c[2]` into segments at dots outside brackets.
fn segments(path: &str) -> Vec<&str> {
    let mut parts = Vec::new();
    let mut depth = 0usize;
    let mut start = 0;
    for (index, character) in path.char_indices() {
        match character {
            '[' => depth += 1,
            ']' => depth = depth.saturating_sub(1),
            '.' if depth == 0 => {
                parts.push(&path[start..index]);
                start = index + 1;
            }
            _ => {}
        }
    }
    parts.push(&path[start..]);
    parts
}

/// `Name_<line>_<offset>` or `Name_<line>_<offset>[k]`: (name, line, offset, k).
fn anonymous_segment(segment: &str) -> Option<(String, usize, usize, usize)> {
    let (base, index) = match segment.split_once('[') {
        Some((base, rest)) => (base, rest.trim_end_matches(']').parse().ok()?),
        None => (segment, 0),
    };
    let mut parts = base.rsplitn(3, '_');
    let offset = parts.next()?.parse().ok()?;
    let line = parts.next()?.parse().ok()?;
    let name = parts.next()?.to_owned();
    Some((name, line, offset, index))
}

/// Maps an offset in an instrumented file back to the original file, given the insertions as
/// (original position, length). A token at original offset X sits at X plus the lengths of all
/// insertions at positions up to X.
fn original_offset(insertions: &[(usize, usize)], diagnostic: usize) -> usize {
    let mut ordered = insertions.to_vec();
    ordered.sort_unstable();
    let mut shift = 0usize;
    for (position, length) in ordered {
        if position + shift + length <= diagnostic {
            shift += length;
        } else {
            break;
        }
    }
    diagnostic - shift
}

struct Execution {
    indices: Vec<String>,
    /// Argument position -> the array, interned in the capture's `arrays`.
    arrays: HashMap<usize, CapturedValue>,
}

/// The executions of one site in one parent instance.
struct SiteExecutions {
    list: Vec<Execution>,
    /// Component index values -> first execution with them (named sites).
    by_indices: HashMap<Vec<String>, usize>,
}

/// Captured values of one instance by capture signal name.
type InstanceSequences = HashMap<String, Vec<BigUint>>;

fn sequence<'a>(signals: Option<&'a InstanceSequences>, name: &str) -> &'a [BigUint] {
    signals
        .and_then(|signals| signals.get(name))
        .map_or(&[], Vec::as_slice)
}

/// Horner evaluation of the row-major values at [`FINGERPRINT_BASE`], as the copy computes it.
fn fingerprint(values: &[BigUint], prime: &BigUint) -> BigUint {
    let base = BigUint::from(FINGERPRINT_BASE);
    values.iter().fold(BigUint::default(), |hash, value| {
        (hash * &base + value) % prime
    })
}

/// Splits a site's capture sequences in one parent instance into executions. `captured` lists
/// (argument position, dimension count) of the site's captured array arguments; recorded
/// arrays are interned into `arrays`.
fn site_executions(
    site: &Site,
    captured: &[(usize, usize)],
    signals: Option<&InstanceSequences>,
    prime: &BigUint,
    arrays: &mut BTreeMap<String, CapturedValue>,
) -> std::result::Result<SiteExecutions, String> {
    let prefix = format!("{CAPTURE_PREFIX}s{}", site.id);
    let count = sequence(signals, &format!("{prefix}_n")).len();
    let mut executions = (0..count)
        .map(|_| Execution {
            indices: Vec::new(),
            arrays: HashMap::new(),
        })
        .collect::<Vec<_>>();
    if let Some((_, indices)) = &site.component {
        for position in 0..indices.len() {
            let values = sequence(signals, &format!("{prefix}_i{position}"));
            if values.len() != count {
                return Err(format!(
                    "site at line {} recorded {count} executions but {} values of index {position}",
                    site.line,
                    values.len()
                ));
            }
            for (execution, value) in executions.iter_mut().zip(values) {
                execution.indices.push(value.to_string());
            }
        }
    }
    for &(position, levels) in captured {
        let values = sequence(signals, &format!("{prefix}_a{position}"));
        let fingerprints = sequence(signals, &format!("{prefix}_f{position}"));
        if fingerprints.len() != count {
            return Err(format!(
                "site at line {} recorded {count} executions but {} array fingerprints",
                site.line,
                fingerprints.len()
            ));
        }
        let dimensions = (0..levels)
            .map(|level| sequence(signals, &format!("{prefix}_d{position}_{level}")))
            .collect::<Vec<_>>();
        // Full values are recorded at the first execution and whenever the fingerprint
        // differs from the previous execution's; otherwise the previous values stand.
        let mut cursor = 0;
        let mut previous: Option<(Vec<usize>, CapturedValue)> = None;
        for (number, execution) in executions.iter_mut().enumerate() {
            let mut shape = Vec::with_capacity(levels);
            for dimension in &dimensions {
                let dimension = dimension
                    .get(number)
                    .and_then(|value| usize::try_from(value).ok())
                    .ok_or_else(|| {
                        format!("site at line {} lacks a dimension capture", site.line)
                    })?;
                shape.push(dimension);
            }
            let recorded = number == 0 || fingerprints[number] != fingerprints[number - 1];
            if recorded {
                let size = shape.iter().product::<usize>();
                let Some(slice) = values.get(cursor..cursor + size) else {
                    return Err(format!(
                        "site at line {} recorded fewer array values than its dimensions",
                        site.line
                    ));
                };
                cursor += size;
                if fingerprint(slice, prime) != fingerprints[number] {
                    return Err(format!(
                        "site at line {}: a recorded array does not match its fingerprint",
                        site.line
                    ));
                }
                let array = CapturedValue::Array {
                    dims: shape.clone(),
                    values: slice.iter().map(ToString::to_string).collect(),
                };
                let sha256 = array.array_hash();
                arrays.entry(sha256.clone()).or_insert(array);
                previous = Some((shape.clone(), CapturedValue::ArrayRef { sha256 }));
            }
            match &previous {
                Some((previous_shape, value)) if *previous_shape == shape => {
                    execution.arrays.insert(position, value.clone());
                }
                _ => {
                    return Err(format!(
                        "site at line {}: array dimensions changed without a new recording",
                        site.line
                    ))
                }
            }
        }
        if cursor != values.len() {
            return Err(format!(
                "site at line {} recorded more array values than its executions use",
                site.line
            ));
        }
    }
    let mut by_indices = HashMap::new();
    for (number, execution) in executions.iter().enumerate() {
        by_indices
            .entry(execution.indices.clone())
            .or_insert(number);
    }
    Ok(SiteExecutions {
        list: executions,
        by_indices,
    })
}

// ---------------------------------------------------------------------------------------
// Entry point

pub fn capture_instances(request: &CaptureRequest) -> Result<InstanceCapture> {
    let entrypoint = fs::canonicalize(request.entrypoint)?;
    let project_root = fs::canonicalize(request.project_root)?;
    let library_paths = request
        .library_paths
        .iter()
        .map(fs::canonicalize)
        .collect::<std::io::Result<Vec<_>>>()?;
    let request = CaptureRequest {
        entrypoint: &entrypoint,
        project_root: &project_root,
        library_paths: &library_paths,
        circom_bin: request.circom_bin,
        work_dir: request.work_dir,
        timeout_seconds: request.timeout_seconds,
    };
    fs::create_dir_all(request.work_dir)?;
    let mut capture = InstanceCapture {
        schema: CAPTURE_SCHEMA.to_owned(),
        entrypoint: entrypoint.clone(),
        project_root: project_root.clone(),
        library_paths: library_paths.clone(),
        status: "scan_failed".to_owned(),
        failure: None,
        prime: None,
        instances: Vec::new(),
        unsupported: Vec::new(),
        templates: Vec::new(),
        compile: None,
        compile_attempts: 0,
        compile_seconds: 0.0,
        scan_seconds: 0.0,
        read_seconds: 0.0,
        assemble_seconds: 0.0,
        capture_signals: 0,
        capture_constraints: 0,
        diagnostic_r1cs: None,
        diagnostic_sym: None,
        arrays: BTreeMap::new(),
        main_literal_parameters: Vec::new(),
    };
    let started = Instant::now();
    let scan = match scan_closure(&entrypoint, &project_root, &library_paths) {
        Ok(scan) => scan,
        Err(error) => {
            capture.failure = Some(format!("{error:#}"));
            return Ok(capture);
        }
    };
    capture.scan_seconds = started.elapsed().as_secs_f64();
    capture.unsupported.extend(scan.issues.clone());
    let mut assumed = HashSet::new();
    let mut skipped = HashSet::new();
    let mut compiled = None;
    let mut plan = plan_instrumentation(&scan, &assumed, &skipped);
    let output = request.work_dir.join("diagnostic-build");
    for attempt in 0..=MAX_RETRIES {
        let (entry, libraries, copies) =
            write_copy(&request, &plan, &request.work_dir.join("diagnostic-copy"))?;
        if output.exists() {
            fs::remove_dir_all(&output)?;
        }
        fs::create_dir_all(&output)?;
        let mut args = vec![
            entry.to_string_lossy().into_owned(),
            "--r1cs".to_owned(),
            "--sym".to_owned(),
            "--O0".to_owned(),
            "--output".to_owned(),
            output.to_string_lossy().into_owned(),
        ];
        for library in &libraries {
            args.push("-l".to_owned());
            args.push(library.to_string_lossy().into_owned());
        }
        let tool = capture_tool(
            request.circom_bin,
            args,
            &format!("capture-compile-{attempt}"),
            request.work_dir,
            request.timeout_seconds,
        )?;
        capture.compile_attempts += 1;
        capture.compile_seconds += tool.elapsed_seconds;
        let success = tool.success;
        let timed_out = tool.timed_out;
        let stderr = fs::read_to_string(&tool.stderr_path).unwrap_or_default()
            + &fs::read_to_string(&tool.stdout_path).unwrap_or_default();
        capture.compile = Some(tool);
        if success {
            compiled = Some(entry);
            break;
        }
        if timed_out {
            capture.status = "compile_timed_out".to_owned();
            capture.failure = Some(format!(
                "the diagnostic copy did not compile within {} seconds",
                request.timeout_seconds
            ));
            return Ok(capture);
        }
        // A rejected capture statement: retry with that parameter treated as an array, or
        // without that site's captures. Anything else is a compile failure of the copy.
        let blamed = blame(&stderr, &plan, &scan, &copies);
        let mut progressed = false;
        for statement in blamed {
            match statement {
                CaptureStatement::Parameter(template, parameter) => {
                    progressed |= assumed.insert((template, parameter));
                }
                CaptureStatement::Site(template, site) => {
                    progressed |= skipped.insert((template, site));
                }
                CaptureStatement::Marker(_) => {}
            }
        }
        if !progressed || attempt == MAX_RETRIES {
            capture.status = "compile_failed".to_owned();
            capture.failure = Some(format!(
                "the diagnostic copy does not compile: {}",
                first_error(&stderr)
            ));
            return Ok(capture);
        }
        plan = plan_instrumentation(&scan, &assumed, &skipped);
    }
    let Some(_entry) = compiled else {
        capture.status = "compile_failed".to_owned();
        return Ok(capture);
    };
    let stem = entrypoint
        .file_stem()
        .context("entrypoint has no stem")?
        .to_string_lossy()
        .into_owned();
    let r1cs = output.join(format!("{stem}.r1cs"));
    let sym = output.join(format!("{stem}.sym"));
    capture.diagnostic_r1cs = artifact(&r1cs).ok();
    capture.diagnostic_sym = artifact(&sym).ok();
    let started = Instant::now();
    let read = read_capture_symbols(&sym)
        .and_then(|wires| read_capture_values(&r1cs, &wires).map(|values| (wires, values)));
    capture.read_seconds = started.elapsed().as_secs_f64();
    let (wires, (prime, mut values, constraints)) = match read {
        Ok(read) => read,
        Err(error) => {
            capture.status = "read_failed".to_owned();
            capture.failure = Some(format!("{error:#}"));
            return Ok(capture);
        }
    };
    capture.prime = Some(prime.to_string());
    capture.capture_signals = wires.len();
    capture.capture_constraints = constraints;
    let started = Instant::now();
    let mut sequences: HashMap<String, InstanceSequences> = HashMap::new();
    for (wire, (instance, signal)) in wires {
        sequences
            .entry(instance)
            .or_default()
            .insert(signal, values.remove(&wire).unwrap_or_default());
    }
    assemble(&mut capture, &scan, &plan, &sequences, &prime)?;
    capture.assemble_seconds = started.elapsed().as_secs_f64();
    capture.status = "captured".to_owned();
    capture.templates = scan
        .templates
        .iter()
        .map(|template| TemplateRecord {
            id: template.id,
            name: template.name.clone(),
            source_path: template.file.clone(),
            start_line: template.start_line,
            end_line: template.end_line,
            instrumented: !template.custom,
            array_parameters: {
                let mut list = plan.arrays[template.id].iter().cloned().collect::<Vec<_>>();
                list.sort();
                list
            },
        })
        .collect();
    Ok(capture)
}

fn artifact(path: &Path) -> Result<ArtifactRecord> {
    let mut file = fs::File::open(path)?;
    let mut hasher = Sha256::new();
    let bytes = std::io::copy(&mut file, &mut hasher)?;
    Ok(ArtifactRecord {
        path: path.to_path_buf(),
        sha256: format!("{:x}", hasher.finalize()),
        bytes,
    })
}

fn first_error(stderr: &str) -> String {
    let cleaned = strip_ansi(stderr);
    cleaned
        .lines()
        .find(|line| line.contains("error"))
        .unwrap_or_else(|| cleaned.lines().next().unwrap_or(""))
        .trim()
        .chars()
        .take(300)
        .collect()
}

fn strip_ansi(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut chars = text.chars().peekable();
    while let Some(character) = chars.next() {
        if character == '\u{1b}' {
            for next in chars.by_ref() {
                if next.is_ascii_alphabetic() {
                    break;
                }
            }
            continue;
        }
        out.push(character);
    }
    out
}

/// The inserted statements a compiler error points at (`"file":line:column`, 1-based).
fn blame(
    stderr: &str,
    plan: &Plan,
    scan: &Scan,
    copies: &[(PathBuf, PathBuf)],
) -> Vec<CaptureStatement> {
    let cleaned = strip_ansi(stderr);
    let pattern = regex::Regex::new(r#""([^"]+)":(\d+):(\d+)"#).expect("location pattern");
    let mut blamed = Vec::new();
    for found in pattern.captures_iter(&cleaned) {
        let (Ok(line), Ok(column)) = (found[2].parse::<usize>(), found[3].parse::<usize>()) else {
            continue;
        };
        let reported = PathBuf::from(&found[1]);
        let reported = fs::canonicalize(&reported).unwrap_or(reported);
        let Some(original) = scan.files.iter().find(|file| {
            copies.iter().any(|(from, to)| {
                file.strip_prefix(from)
                    .is_ok_and(|rest| reported == to.join(rest) || reported.ends_with(rest))
            })
        }) else {
            continue;
        };
        let Some(insertions) = plan.insertions.get(original) else {
            continue;
        };
        let (text, starts) = apply(&scan.sources[original], insertions);
        let Some(line_text) = text.split('\n').nth(line.saturating_sub(1)) else {
            continue;
        };
        let line_start = text
            .split_inclusive('\n')
            .take(line.saturating_sub(1))
            .map(str::len)
            .sum::<usize>();
        let column_bytes = line_text
            .char_indices()
            .nth(column.saturating_sub(1))
            .map_or(line_text.len(), |(byte, _)| byte);
        let offset = line_start + column_bytes;
        for (insertion, start) in insertions.iter().zip(&starts) {
            if offset < *start || offset >= start + insertion.text.len() {
                continue;
            }
            let relative = offset - start;
            if let Some((_, statement)) = insertion
                .parts
                .iter()
                .find(|(range, _)| range.contains(&relative))
            {
                blamed.push(statement.clone());
            }
        }
    }
    blamed
}

fn assemble(
    capture: &mut InstanceCapture,
    scan: &Scan,
    plan: &Plan,
    sequences: &HashMap<String, InstanceSequences>,
    prime: &BigUint,
) -> Result<()> {
    // Markers name instances and their templates.
    let mut templates_of = BTreeMap::new();
    for (instance, signals) in sequences {
        for (signal, values) in signals {
            if let Some(id) = signal
                .strip_prefix(CAPTURE_PREFIX)
                .and_then(|rest| rest.strip_prefix('t'))
                .and_then(|id| id.parse::<usize>().ok())
            {
                ensure!(
                    id < scan.templates.len()
                        && values.len() == 1
                        && values[0] == BigUint::from(id),
                    "marker {signal} of {instance} does not record its template id"
                );
                templates_of.insert(instance.clone(), id);
            }
        }
    }
    // (template id, site id) -> (argument position, dimension count) of captured arrays.
    let mut captured_positions: HashMap<(usize, usize), Vec<(usize, usize)>> = HashMap::new();
    for ((template, site, position), how) in &plan.array_arguments {
        if let ArrayArgument::Captured { dims, .. } = how {
            captured_positions
                .entry((*template, *site))
                .or_default()
                .push((*position, dims.len()));
        }
    }
    for positions in captured_positions.values_mut() {
        positions.sort_unstable();
    }
    let mut insertions_of: HashMap<PathBuf, Vec<(usize, usize)>> = HashMap::new();
    let mut arrays = BTreeMap::new();
    // No site passes the main component's arguments; array ones come from its literals.
    let main_literals = match scan.sources.get(&capture.entrypoint) {
        Some(source) => crate::targets::main_literal_arguments(&capture.entrypoint, source, prime),
        None => Err("the entrypoint source was not scanned".to_owned()),
    };
    let mut main_literal_parameters = Vec::new();
    // Shallow paths first, so a parent's arguments resolve before its children's.
    let mut paths = templates_of.keys().cloned().collect::<Vec<_>>();
    paths.sort_by_cached_key(|path| (segments(path).len(), path.clone()));
    let mut resolved: HashMap<String, CapturedInstance> = HashMap::new();
    // Diagnostic path -> path with anonymous offsets of the original sources.
    let mut renamed: HashMap<String, String> =
        HashMap::from([("main".to_owned(), "main".to_owned())]);
    let mut executions_cache: HashMap<
        (String, usize),
        std::result::Result<SiteExecutions, String>,
    > = HashMap::new();
    for path in paths {
        let template = &scan.templates[templates_of[&path]];
        let parts = segments(&path);
        let parent = (1..parts.len())
            .rev()
            .map(|length| parts[..length].join("."))
            .find(|prefix| templates_of.contains_key(prefix));
        let mut instance = CapturedInstance {
            path: path.clone(),
            template_name: template.name.clone(),
            source_path: template.file.clone(),
            arguments: None,
            parent: parent.clone(),
            component_name: None,
            line: None,
            unsupported: None,
        };
        let mut failure: Option<String> = None;
        let mut arguments = Vec::new();
        // The creating site in the parent, and this instance's execution there.
        let mut execution: Option<(usize, usize)> = None;
        if let Some(parent_path) = &parent {
            let parent_template = &scan.templates[templates_of[parent_path]];
            let segment = path[parent_path.len() + 1..].to_owned();
            let anonymous = anonymous_segment(&segment).and_then(|(name, line, offset, k)| {
                let insertions = insertions_of
                    .entry(parent_template.file.clone())
                    .or_insert_with(|| plan.file_insertions(&parent_template.file));
                let original = original_offset(insertions, offset);
                parent_template
                    .sites
                    .iter()
                    .find(|site| {
                        site.callee == name
                            && site.line == line
                            && site.anonymous_offset.is_some_and(|(byte, character)| {
                                original == byte || original == character
                            })
                    })
                    .map(|site| (site.id, k, line, site.anonymous_offset.map(|(_, c)| c)))
            });
            let parent_renamed = renamed
                .get(parent_path)
                .cloned()
                .unwrap_or_else(|| parent_path.clone());
            renamed.insert(path.clone(), format!("{parent_renamed}.{segment}"));
            if let Some((site, k, line, char_offset)) = anonymous {
                let site_ref = &parent_template.sites[site];
                let suffix = segment.find('[').map_or("", |at| &segment[at..]);
                renamed.insert(
                    path.clone(),
                    format!(
                        "{parent_renamed}.{}_{line}_{}{suffix}",
                        site_ref.callee,
                        site_ref
                            .anonymous_offset
                            .map(|(byte, _)| byte)
                            .unwrap_or_default()
                    ),
                );
                instance.component_name = Some(format!(
                    "@anonymous:{line}:{}",
                    char_offset.unwrap_or_default()
                ));
                instance.line = Some(line);
                execution = Some((site, k));
            } else {
                instance.component_name = Some(segment.clone());
                let (name, indices) = match segment.split_once('[') {
                    Some((name, rest)) => (
                        name.to_owned(),
                        rest.trim_end_matches(']')
                            .split("][")
                            .map(str::to_owned)
                            .collect::<Vec<_>>(),
                    ),
                    None => (segment.clone(), Vec::new()),
                };
                for site in parent_template.sites.iter().filter(|site| {
                    site.component
                        .as_ref()
                        .is_some_and(|(component, site_indices)| {
                            component == &name && site_indices.len() == indices.len()
                        })
                }) {
                    let found = executions_cache
                        .entry((parent_path.clone(), site.id))
                        .or_insert_with(|| {
                            site_executions(
                                site,
                                captured_positions
                                    .get(&(parent_template.id, site.id))
                                    .map_or(&[], Vec::as_slice),
                                sequences.get(parent_path.as_str()),
                                prime,
                                &mut arrays,
                            )
                        });
                    match found {
                        Ok(found) => {
                            if let Some(&number) = found.by_indices.get(&indices) {
                                instance.line = Some(site.line);
                                execution = Some((site.id, number));
                                break;
                            }
                        }
                        Err(reason) => failure = Some(reason.clone()),
                    }
                }
                if execution.is_none() && failure.is_none() {
                    failure = Some(format!(
                        "no instantiation statement in {} recorded component {segment}",
                        parent_template.name
                    ));
                }
            }
        }
        for (position, parameter) in template.parameters.iter().enumerate() {
            if failure.is_some() {
                break;
            }
            if !plan.arrays[template.id].contains(parameter) {
                let name = format!("{CAPTURE_PREFIX}p{position}");
                match sequence(sequences.get(path.as_str()), &name) {
                    [value] => arguments.push(CapturedValue::Scalar {
                        value: value.to_string(),
                    }),
                    _ => failure = Some(format!("parameter {parameter} was not captured")),
                }
                continue;
            }
            let (Some(parent_path), Some((site, number))) = (&parent, execution) else {
                let literal = match &main_literals {
                    _ if parent.is_some() => Err("its creating site was not found".to_owned()),
                    Ok((name, values)) if *name == template.name => values
                        .get(position)
                        .cloned()
                        .unwrap_or_else(|| Err("the main call has fewer arguments".to_owned())),
                    Ok((name, _)) => Err(format!("the main call names {name}")),
                    Err(reason) => Err(reason.clone()),
                };
                match literal {
                    Ok(value @ CapturedValue::Array { .. }) => {
                        let sha256 = value.array_hash();
                        arrays.entry(sha256.clone()).or_insert(value);
                        arguments.push(CapturedValue::ArrayRef { sha256 });
                        main_literal_parameters.push(parameter.clone());
                        continue;
                    }
                    Ok(_) => {
                        failure = Some(format!(
                            "array parameter {parameter} of the main component receives a scalar"
                        ))
                    }
                    Err(reason) => {
                        failure = Some(format!(
                            "array parameter {parameter} of the main component is not captured: {reason}"
                        ))
                    }
                }
                break;
            };
            let parent_template = &scan.templates[templates_of[parent_path]];
            match plan
                .array_arguments
                .get(&(parent_template.id, site, position))
            {
                Some(ArrayArgument::Captured { .. }) => {
                    let site_ref = &parent_template.sites[site];
                    let found = executions_cache
                        .entry((parent_path.clone(), site))
                        .or_insert_with(|| {
                            site_executions(
                                site_ref,
                                captured_positions
                                    .get(&(parent_template.id, site))
                                    .map_or(&[], Vec::as_slice),
                                sequences.get(parent_path.as_str()),
                                prime,
                                &mut arrays,
                            )
                        });
                    match found {
                        Ok(found) => {
                            match found.list.get(number).and_then(|e| e.arrays.get(&position)) {
                                Some(value) => arguments.push(value.clone()),
                                None => {
                                    failure = Some(format!(
                                        "array argument {parameter} was not recorded at its site"
                                    ))
                                }
                            }
                        }
                        Err(reason) => failure = Some(reason.clone()),
                    }
                }
                Some(ArrayArgument::PassThrough(name)) => {
                    let index = parent_template.parameters.iter().position(|p| p == name);
                    match (index, resolved.get(parent_path).and_then(|p| p.arguments.as_ref())) {
                        (Some(index), Some(values)) => arguments.push(values[index].clone()),
                        _ => {
                            failure = Some(format!(
                                "array argument {parameter} comes from {}'s parameter {name}, which was not captured",
                                parent_template.name
                            ))
                        }
                    }
                }
                Some(ArrayArgument::Uncapturable(reason)) => failure = Some(reason.clone()),
                None => {
                    failure = Some(format!(
                        "array argument {parameter} has no capture at its instantiation site"
                    ))
                }
            }
        }
        if failure.is_none() {
            // Signed key tokens must be formable.
            for value in &arguments {
                value.key_token(prime)?;
            }
            instance.arguments = Some(arguments);
        } else {
            instance.unsupported = failure.clone();
            capture.unsupported.push(UnsupportedCase {
                source_path: parent
                    .as_ref()
                    .map(|p| scan.templates[templates_of[p]].file.clone())
                    .unwrap_or_else(|| template.file.clone()),
                line: instance.line,
                construct: format!("{} ({})", path, template.name),
                reason: format!("instance capture: {}", failure.unwrap_or_default()),
            });
        }
        resolved.insert(path, instance);
    }
    for instance in resolved.values_mut() {
        if let Some(path) = renamed.get(&instance.path) {
            instance.path = path.clone();
        }
        if let Some(parent) = instance.parent.as_ref().and_then(|p| renamed.get(p)) {
            instance.parent = Some(parent.clone());
        }
    }
    // Instantiations of templates the copy could not mark (custom templates).
    let called = scan
        .templates
        .iter()
        .flat_map(|template| template.sites.iter().map(|site| site.callee.clone()))
        .collect::<HashSet<_>>();
    for template in &scan.templates {
        if template.custom && called.contains(&template.name) {
            capture.unsupported.push(UnsupportedCase {
                source_path: template.file.clone(),
                line: Some(template.start_line),
                construct: format!("template custom {}", template.name),
                reason: "instance capture cannot add constraints to a custom template".into(),
            });
        }
    }
    let mut instances = resolved.into_values().collect::<Vec<_>>();
    instances.sort_by(|a, b| a.path.cmp(&b.path));
    // Keep the arrays some instance refers to.
    let referenced = instances
        .iter()
        .flat_map(|instance| instance.arguments.iter().flatten())
        .filter_map(|value| match value {
            CapturedValue::ArrayRef { sha256 } => Some(sha256.as_str()),
            _ => None,
        })
        .collect::<HashSet<_>>();
    arrays.retain(|sha256, _| referenced.contains(sha256.as_str()));
    capture.arrays = arrays;
    capture.main_literal_parameters = main_literal_parameters;
    capture.instances = instances;
    Ok(())
}

/// Output of `zkfDO capture`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CaptureCommandReport {
    pub capture_path: PathBuf,
    pub status: String,
    pub failure: Option<String>,
    pub complete: bool,
    pub instances: usize,
    pub unsupported: usize,
    pub compile_seconds: f64,
    pub neutrality: Option<NeutralityReport>,
    pub original_compile: Option<ToolCapture>,
}

pub fn capture_command(
    project: &Path,
    entrypoint: &Path,
    library_paths: &[PathBuf],
    output: &Path,
    circom_bin: &Path,
    timeout_seconds: u64,
    verify_neutrality: bool,
) -> Result<CaptureCommandReport> {
    ensure!(
        !output.exists(),
        "output {} already exists",
        output.display()
    );
    fs::create_dir_all(output)?;
    let capture = capture_instances(&CaptureRequest {
        entrypoint,
        project_root: project,
        library_paths,
        circom_bin,
        work_dir: output,
        timeout_seconds,
    })?;
    let capture_path = output.join("instance-capture.json");
    fs::write(&capture_path, serde_json::to_vec(&capture.interned())?)?;
    let mut report = CaptureCommandReport {
        capture_path,
        status: capture.status.clone(),
        failure: capture.failure.clone(),
        complete: capture.complete(),
        instances: capture.instances.len(),
        unsupported: capture.unsupported.len(),
        compile_seconds: capture.compile_seconds,
        neutrality: None,
        original_compile: None,
    };
    if verify_neutrality && capture.status == "captured" {
        let build = output.join("original-build");
        fs::create_dir_all(&build)?;
        let mut args = vec![
            capture.entrypoint.to_string_lossy().into_owned(),
            "--r1cs".to_owned(),
            "--sym".to_owned(),
            "--O0".to_owned(),
            "--output".to_owned(),
            build.to_string_lossy().into_owned(),
        ];
        for library in std::iter::once(&capture.project_root).chain(&capture.library_paths) {
            args.push("-l".to_owned());
            args.push(library.to_string_lossy().into_owned());
        }
        let tool = capture_tool(
            circom_bin,
            args,
            "original-compile",
            output,
            timeout_seconds,
        )?;
        if tool.success {
            let stem = capture
                .entrypoint
                .file_stem()
                .context("entrypoint has no stem")?
                .to_string_lossy()
                .into_owned();
            let renamer = anonymous_renamer(&capture)?;
            let (r1cs, sym) = (
                capture
                    .diagnostic_r1cs
                    .as_ref()
                    .context("no diagnostic R1CS")?,
                capture
                    .diagnostic_sym
                    .as_ref()
                    .context("no diagnostic SYM")?,
            );
            report.neutrality = Some(neutrality(
                &build.join(format!("{stem}.r1cs")),
                &build.join(format!("{stem}.sym")),
                &r1cs.path,
                &sym.path,
                &renamer,
            )?);
        }
        report.original_compile = Some(tool);
    }
    fs::write(
        output.join("capture-report.json"),
        serde_json::to_vec_pretty(&report)?,
    )?;
    Ok(report)
}

// ---------------------------------------------------------------------------------------
// Neutrality

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct NeutralityReport {
    pub original_constraints: usize,
    pub diagnostic_constraints: usize,
    pub capture_constraints_removed: usize,
    pub capture_signals_removed: usize,
    pub signals_compared: usize,
    pub identical: bool,
    pub first_difference: Option<String>,
}

/// Checks that the diagnostic O0 R1CS without capture signals and the constraints that mention
/// them equals the original O0 R1CS, constraint by constraint in order, with wires matched by
/// signal name (anonymous offsets mapped back to the original sources).
pub fn neutrality(
    original_r1cs: &Path,
    original_sym: &Path,
    capture_r1cs: &Path,
    capture_sym: &Path,
    rename: &dyn Fn(&str) -> String,
) -> Result<NeutralityReport> {
    use crate::candidate_review::r1cs::{R1cs, SymbolTable};
    let original = R1cs::parse(&fs::read(original_r1cs)?)?;
    let original_names = SymbolTable::parse(&fs::read(original_sym)?, &original)?;
    let diagnostic = R1cs::parse(&fs::read(capture_r1cs)?)?;
    let diagnostic_names = SymbolTable::parse(&fs::read(capture_sym)?, &diagnostic)?;
    let mut report = NeutralityReport {
        original_constraints: original.constraints.len(),
        diagnostic_constraints: diagnostic.constraints.len(),
        capture_constraints_removed: 0,
        capture_signals_removed: 0,
        signals_compared: 0,
        identical: false,
        first_difference: None,
    };
    let mut map: HashMap<u32, u32> = HashMap::from([(0, 0)]);
    let mut capture_wires = HashSet::new();
    for (wire, names) in diagnostic_names.wire_to_names.iter().enumerate().skip(1) {
        let Some(name) = names.first() else {
            continue;
        };
        if name
            .rsplit('.')
            .next()
            .is_some_and(|signal| signal.starts_with(CAPTURE_PREFIX))
        {
            capture_wires.insert(wire as u32);
            report.capture_signals_removed += 1;
            continue;
        }
        let renamed = rename(name);
        let Some(symbol) = original_names.by_name.get(&renamed) else {
            report.first_difference = Some(format!("signal {renamed} is not in the original"));
            return Ok(report);
        };
        map.insert(wire as u32, symbol.wire as u32);
        report.signals_compared += 1;
    }
    if report.signals_compared + 1 != original.shape.wires {
        report.first_difference = Some(format!(
            "{} non-capture signals against {} original wires",
            report.signals_compared + 1,
            original.shape.wires
        ));
        return Ok(report);
    }
    let mut kept = Vec::new();
    for constraint in &diagnostic.constraints {
        let wires = constraint
            .a
            .keys()
            .chain(constraint.b.keys())
            .chain(constraint.c.keys());
        if wires.clone().any(|wire| capture_wires.contains(wire)) {
            report.capture_constraints_removed += 1;
            continue;
        }
        let remap = |lc: &crate::candidate_review::r1cs::LinearCombination| {
            lc.iter()
                .map(|(wire, value)| (map[wire], value.clone()))
                .collect::<BTreeMap<_, _>>()
        };
        kept.push((
            remap(&constraint.a),
            remap(&constraint.b),
            remap(&constraint.c),
        ));
    }
    if kept.len() != original.constraints.len() {
        report.first_difference = Some(format!(
            "{} constraints remain against {} original constraints",
            kept.len(),
            original.constraints.len()
        ));
        return Ok(report);
    }
    for (index, (constraint, (a, b, c))) in original.constraints.iter().zip(&kept).enumerate() {
        if &constraint.a != a || &constraint.b != b || &constraint.c != c {
            report.first_difference = Some(format!("constraint {index} differs"));
            return Ok(report);
        }
    }
    report.identical = true;
    Ok(report)
}

/// Maps a diagnostic signal name to the original one: anonymous-component offsets inside
/// instrumented files are shifted back. The plan is rebuilt from the recorded array parameters.
pub fn anonymous_renamer(capture: &InstanceCapture) -> Result<impl Fn(&str) -> String> {
    let scan = scan_closure(
        &capture.entrypoint,
        &capture.project_root,
        &capture.library_paths,
    )?;
    let assumed = capture
        .templates
        .iter()
        .flat_map(|template| {
            template
                .array_parameters
                .iter()
                .map(move |parameter| (template.id, parameter.clone()))
        })
        .collect::<HashSet<_>>();
    let plan = plan_instrumentation(&scan, &assumed, &HashSet::new());
    // (callee, line) -> candidate (insertion table, original offsets) of anonymous sites.
    type Candidates = Vec<(Vec<(usize, usize)>, usize)>;
    let mut sites: HashMap<(String, usize), Candidates> = HashMap::new();
    for parent in &scan.templates {
        for site in &parent.sites {
            if let Some((byte, _)) = site.anonymous_offset {
                sites
                    .entry((site.callee.clone(), site.line))
                    .or_default()
                    .push((plan.file_insertions(&parent.file), byte));
            }
        }
    }
    Ok(move |name: &str| {
        segments(name)
            .into_iter()
            .map(|segment| {
                if let Some((template, line, offset, _)) = anonymous_segment(segment) {
                    if let Some(candidates) = sites.get(&(template.clone(), line)) {
                        for (insertions, byte) in candidates {
                            if original_offset(insertions, offset) == *byte {
                                let suffix = segment.find('[').map_or("", |at| &segment[at..]);
                                return format!("{template}_{line}_{byte}{suffix}");
                            }
                        }
                    }
                }
                segment.to_owned()
            })
            .collect::<Vec<_>>()
            .join(".")
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn values_have_signed_scalar_tokens_and_hashed_arrays() {
        let prime = BigUint::from(101u32);
        let scalar = |v: &str| CapturedValue::Scalar {
            value: v.to_owned(),
        };
        assert_eq!(scalar("7").key_token(&prime).unwrap(), "7");
        assert_eq!(scalar("100").key_token(&prime).unwrap(), "-1");
        assert_eq!(scalar("50").key_token(&prime).unwrap(), "50");
        assert_eq!(scalar("51").key_token(&prime).unwrap(), "-50");
        let array = CapturedValue::Array {
            dims: vec![2, 2],
            values: ["1", "2", "3", "100"].map(str::to_owned).to_vec(),
        };
        assert_eq!(
            array.canonical(),
            r#"{"dims":[2,2],"values":["1","2","3","100"]}"#
        );
        assert_eq!(array.literal(&prime).unwrap(), "[[1, 2], [3, 100]]");
        let token = array.key_token(&prime).unwrap();
        assert!(token.starts_with("[sha256:") && token.len() == 8 + 64 + 1);
    }

    #[test]
    fn anonymous_offsets_map_back_through_insertions() {
        let insertions = vec![(10usize, 3usize), (20, 5)];
        assert_eq!(original_offset(&insertions, 5), 5);
        assert_eq!(original_offset(&insertions, 15), 12);
        assert_eq!(original_offset(&insertions, 30), 22);
        assert_eq!(original_offset(&insertions, 13), 10);
        assert_eq!(
            anonymous_segment("Leaf_42_789"),
            Some(("Leaf".into(), 42, 789, 0))
        );
        assert_eq!(
            anonymous_segment("Is_Zero_1_2[3]"),
            Some(("Is_Zero".into(), 1, 2, 3))
        );
        assert_eq!(anonymous_segment("leaves[0]"), None);
        assert_eq!(segments("main.a[1].b"), ["main", "a[1]", "b"]);
    }
}
