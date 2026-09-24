use std::{
    collections::BTreeSet,
    fs::{self, File},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    thread,
    time::{Duration, Instant},
};

use anyhow::{ensure, Context, Result};
use chrono::{DateTime, Utc};
use regex::Regex;
use serde::{Deserialize, Serialize};

pub const STRUCTURAL_METRIC: &str = "root_ast_if_plus_while";

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct RootAstStats {
    pub template_name: String,
    pub num_statements: u64,
    pub num_if_then_else: u64,
    pub num_while: u64,
}

impl RootAstStats {
    pub fn complexity(&self) -> Result<u64> {
        self.num_if_then_else
            .checked_add(self.num_while)
            .context("root AST control-flow count overflow")
    }
}

/// A compiler/front-end invocation. This type has no fuzzing outcome or bug count.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct ToolCapture {
    pub requested: bool,
    pub purpose: String,
    pub binary: PathBuf,
    pub args: Vec<String>,
    pub started_at: DateTime<Utc>,
    pub finished_at: DateTime<Utc>,
    pub elapsed_seconds: f64,
    pub timeout_seconds: u64,
    pub exit_code: Option<i32>,
    pub success: bool,
    pub timed_out: bool,
    pub stdout_path: PathBuf,
    pub stderr_path: PathBuf,
    pub error: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct StructureProfile {
    pub profile_kind: String,
    pub complete: bool,
    pub entrypoint: PathBuf,
    pub root_template: String,
    pub prime: String,
    pub compile_args: Vec<String>,
    pub size: Option<u64>,
    pub size_source: Option<String>,
    pub r1cs_path: Option<PathBuf>,
    pub complexity: Option<u64>,
    pub metric: String,
    pub parameter_reflected: bool,
    pub compile_success: bool,
    pub ast_success: bool,
    pub ast_requested: bool,
    pub ast_stats: Option<RootAstStats>,
    pub compile: ToolCapture,
    pub ast: ToolCapture,
    pub circom_version: ToolCapture,
    pub zkfuzz_version: ToolCapture,
    pub limitations: Vec<String>,
    pub errors: Vec<String>,
    pub profile_path: PathBuf,
}

pub fn parse_root_ast_csv(stdout: &str, root_template: &str) -> Result<RootAstStats> {
    ensure!(
        !root_template.trim().is_empty(),
        "root template is required"
    );
    let mut reader = csv::ReaderBuilder::new()
        .trim(csv::Trim::All)
        .from_reader(stdout.as_bytes());
    let header = reader.headers().context("invalid AST CSV header")?.clone();
    let mut seen = BTreeSet::new();
    for name in &header {
        ensure!(seen.insert(name), "duplicate AST CSV column: {name}");
    }
    let column = |name: &str| -> Result<usize> {
        header
            .iter()
            .position(|value| value == name)
            .with_context(|| format!("missing AST CSV column: {name}"))
    };
    let name_column = column("template_name")?;
    let statements_column = column("num_statements")?;
    let conditionals_column = column("num_if_then_else")?;
    let loops_column = column("num_while")?;
    let mut selected = None;
    for record in reader.records() {
        let row = record.context("invalid AST CSV row")?;
        if row.get(name_column) != Some(root_template) {
            continue;
        }
        ensure!(
            selected.is_none(),
            "duplicate AST CSV row for root template: {root_template}"
        );
        let count = |index: usize, name: &str| -> Result<u64> {
            row.get(index)
                .context("missing AST CSV cell")?
                .parse::<u64>()
                .with_context(|| format!("invalid {name} for root template {root_template}"))
        };
        let stats = RootAstStats {
            template_name: root_template.to_owned(),
            num_statements: count(statements_column, "num_statements")?,
            num_if_then_else: count(conditionals_column, "num_if_then_else")?,
            num_while: count(loops_column, "num_while")?,
        };
        ensure!(
            stats.complexity()? <= stats.num_statements,
            "AST control-flow count exceeds statement count"
        );
        selected = Some(stats);
    }
    selected.with_context(|| format!("AST CSV does not contain root template: {root_template}"))
}

pub fn parse_constraint_count(output: &str) -> Result<u64> {
    let ansi = Regex::new(r"\x1b\[[0-9;]*[A-Za-z]").expect("ANSI regex");
    let plain = ansi.replace_all(output, "");
    let mut nonlinear = None;
    let mut linear = None;
    for line in plain.lines().map(str::trim) {
        let (slot, value, name) = if let Some(value) = line.strip_prefix("non-linear constraints:")
        {
            (&mut nonlinear, value, "non-linear constraints")
        } else if let Some(value) = line.strip_prefix("linear constraints:") {
            (&mut linear, value, "linear constraints")
        } else {
            continue;
        };
        ensure!(slot.is_none(), "duplicate compiler {name} summary");
        *slot = Some(
            value
                .trim()
                .parse::<u64>()
                .with_context(|| format!("invalid compiler {name} count"))?,
        );
    }
    nonlinear
        .context("missing compiler non-linear constraints count")?
        .checked_add(linear.context("missing compiler linear constraints count")?)
        .context("compiler constraint count overflow")
}

#[allow(clippy::too_many_arguments)]
pub fn profile_target(
    entrypoint: &Path,
    root_template: &str,
    circom_bin: &Path,
    zkfuzz_bin: &Path,
    prime: &str,
    compile_args: &[String],
    output_dir: &Path,
    timeout_seconds: u64,
) -> Result<StructureProfile> {
    profile_target_with_ast(
        entrypoint,
        root_template,
        circom_bin,
        zkfuzz_bin,
        prime,
        compile_args,
        output_dir,
        timeout_seconds,
        true,
    )
}

#[allow(clippy::too_many_arguments)]
pub fn profile_target_with_ast(
    entrypoint: &Path,
    root_template: &str,
    circom_bin: &Path,
    zkfuzz_bin: &Path,
    prime: &str,
    compile_args: &[String],
    output_dir: &Path,
    timeout_seconds: u64,
    collect_ast: bool,
) -> Result<StructureProfile> {
    ensure!(
        timeout_seconds > 0,
        "tool timeout must be greater than zero"
    );
    ensure!(
        !root_template.trim().is_empty(),
        "root template is required"
    );
    ensure!(!prime.trim().is_empty(), "prime is required");
    let libraries = ast_library_args(compile_args)?;
    let entrypoint = fs::canonicalize(entrypoint).context("entrypoint is unavailable")?;
    fs::create_dir_all(output_dir).context("failed to create structure output directory")?;
    let output_dir = fs::canonicalize(output_dir)?;
    let artifacts = output_dir.join("r1cs");
    fs::create_dir_all(&artifacts)?;
    let circom_version = capture_tool(
        circom_bin,
        vec!["--version".to_owned()],
        "circom-version",
        &output_dir,
        timeout_seconds,
    )?;
    let zkfuzz_version = if collect_ast {
        capture_tool(
            zkfuzz_bin,
            vec!["--version".to_owned()],
            "zkfuzz-version",
            &output_dir,
            timeout_seconds,
        )?
    } else {
        not_requested(zkfuzz_bin, "zkfuzz-version", &output_dir)
    };
    let mut compile_command = vec![
        path_arg(&entrypoint)?,
        "--r1cs".to_owned(),
        "--prime".to_owned(),
        prime.to_owned(),
        "--output".to_owned(),
        path_arg(&artifacts)?,
    ];
    compile_command.extend_from_slice(compile_args);
    let compile = capture_tool(
        circom_bin,
        compile_command,
        "compile-r1cs",
        &output_dir,
        timeout_seconds,
    )?;
    let mut ast_command = vec![
        path_arg(&entrypoint)?,
        "--show_stats_of_ast".to_owned(),
        "--prime".to_owned(),
        prime.to_owned(),
    ];
    ast_command.extend(libraries);
    let ast = if collect_ast {
        capture_tool(
            zkfuzz_bin,
            ast_command,
            "root-ast-only",
            &output_dir,
            timeout_seconds,
        )?
    } else {
        not_requested(zkfuzz_bin, "root-ast-only", &output_dir)
    };
    let mut errors = Vec::new();
    for tool in [&circom_version, &zkfuzz_version, &compile, &ast] {
        if tool.requested && !tool.success {
            errors.push(format!(
                "{} failed (exit {:?}, timed_out {}): {}",
                tool.purpose,
                tool.exit_code,
                tool.timed_out,
                tool.error.as_deref().unwrap_or("see captured output")
            ));
        }
    }
    let mut size = None;
    let mut r1cs_path = None;
    if compile.success {
        let parsed = (|| -> Result<u64> {
            let stem = entrypoint
                .file_stem()
                .and_then(|name| name.to_str())
                .context("entrypoint has no UTF-8 file stem")?;
            let expected = artifacts.join(format!("{stem}.r1cs"));
            ensure!(
                expected.is_file(),
                "successful compiler did not produce expected R1CS artifact: {}",
                expected.display()
            );
            let output = format!(
                "{}\n{}",
                fs::read_to_string(&compile.stdout_path)?,
                fs::read_to_string(&compile.stderr_path)?
            );
            let count = parse_constraint_count(&output)?;
            r1cs_path = Some(expected);
            Ok(count)
        })();
        match parsed {
            Ok(value) => size = Some(value),
            Err(error) => errors.push(format!("constraint size unavailable: {error:#}")),
        }
    }
    let mut ast_stats = None;
    if ast.success {
        match fs::read_to_string(&ast.stdout_path)
            .context("cannot read AST output")
            .and_then(|text| parse_root_ast_csv(&text, root_template))
        {
            Ok(stats) => ast_stats = Some(stats),
            Err(error) => errors.push(format!("root AST unavailable: {error:#}")),
        }
    }
    let complexity = ast_stats
        .as_ref()
        .map(RootAstStats::complexity)
        .transpose()?;
    let profile = StructureProfile {
        profile_kind: "structure_only_no_fuzz_search".to_owned(),
        complete: errors.is_empty() && size.is_some() && (!collect_ast || complexity.is_some()),
        entrypoint,
        root_template: root_template.to_owned(),
        prime: prime.to_owned(),
        compile_args: compile_args.to_vec(),
        size,
        size_source: size.map(|_| "Circom R1CS compiler summary: non-linear constraints + linear constraints under recorded compile settings".to_owned()),
        r1cs_path,
        complexity,
        metric: STRUCTURAL_METRIC.to_owned(),
        parameter_reflected: false,
        compile_success: compile.success,
        ast_success: ast.success,
        ast_requested: collect_ast,
        ast_stats,
        compile,
        ast,
        circom_version,
        zkfuzz_version,
        limitations: vec![
            "Complexity counts only IfThenElse and While nodes in the named root template definition, not reachable dependency templates.".to_owned(),
            "AST control-flow nodes are not expanded for concrete parameters, loop iterations, or Circom constraint optimizations.".to_owned(),
            "num_statements counts visited AST statement nodes, including blocks; it is not source lines or constraints.".to_owned(),
            "R1CS constraint count is a separate concrete compiled size measure, not LEOPARD structural complexity.".to_owned(),
            "zkFuzz --show_stats_of_ast exits after parse/type analysis; this invocation provides no fuzzing or defect-reproduction evidence.".to_owned(),
        ],
        errors,
        profile_path: output_dir.join("structure-profile.json"),
    };
    let temporary = output_dir.join("structure-profile.json.tmp");
    fs::write(&temporary, serde_json::to_vec_pretty(&profile)?)?;
    fs::rename(temporary, &profile.profile_path)?;
    Ok(profile)
}

fn path_arg(path: &Path) -> Result<String> {
    path.to_str()
        .map(str::to_owned)
        .context("tool path is not valid UTF-8")
}

fn ast_library_args(args: &[String]) -> Result<Vec<String>> {
    let mut libraries = Vec::new();
    let mut index = 0;
    while index < args.len() {
        let arg = &args[index];
        ensure!(
            !arg.starts_with("-p")
                && !arg.starts_with("-o")
                && !matches!(
                    arg.as_str(),
                    "--" | "-o" | "--output" | "-p" | "--prime" | "--r1cs"
                )
                && !arg.starts_with("--output=")
                && !arg.starts_with("--prime="),
            "compile argument {arg} conflicts with recorded profile settings"
        );
        if arg == "-l" {
            libraries.push(arg.clone());
            index += 1;
            let start = index;
            while index < args.len() && !args[index].starts_with('-') {
                libraries.push(args[index].clone());
                index += 1;
            }
            ensure!(index > start, "-l requires at least one library directory");
        } else {
            index += 1;
        }
    }
    Ok(libraries)
}

pub(crate) fn capture_tool(
    binary: &Path,
    args: Vec<String>,
    purpose: &str,
    output_dir: &Path,
    timeout_seconds: u64,
) -> Result<ToolCapture> {
    let started_at = Utc::now();
    let timer = Instant::now();
    let timeout = Duration::from_secs(timeout_seconds);
    let stdout_path = output_dir.join(format!("{purpose}.stdout.log"));
    let stderr_path = output_dir.join(format!("{purpose}.stderr.log"));
    let mut command = Command::new(binary);
    command
        .args(&args)
        .stdout(Stdio::from(File::create(&stdout_path)?))
        .stderr(Stdio::from(File::create(&stderr_path)?));
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }
    let mut exit_code = None;
    let mut success = false;
    let mut timed_out = false;
    let mut error = None;
    match command.spawn() {
        Err(problem) => error = Some(format!("failed to spawn tool: {problem}")),
        Ok(mut child) => loop {
            match child.try_wait() {
                Ok(Some(status)) => {
                    exit_code = status.code();
                    success = status.success();
                    break;
                }
                Err(problem) => {
                    error = Some(format!("failed to poll tool: {problem}"));
                    let _ = kill_group(&mut child);
                    let _ = child.wait();
                    break;
                }
                Ok(None) => {}
            }
            let remaining = timeout.saturating_sub(timer.elapsed());
            if remaining.is_zero() {
                timed_out = true;
                if let Err(problem) = kill_group(&mut child) {
                    error = Some(format!("failed to terminate tool: {problem:#}"));
                }
                match child.wait() {
                    Ok(status) => exit_code = status.code(),
                    Err(problem) => error = Some(format!("failed to reap tool: {problem}")),
                }
                break;
            }
            thread::sleep(Duration::from_millis(25).min(remaining));
        },
    }
    Ok(ToolCapture {
        requested: true,
        purpose: purpose.to_owned(),
        binary: binary.to_path_buf(),
        args,
        started_at,
        finished_at: Utc::now(),
        elapsed_seconds: timer.elapsed().as_secs_f64(),
        timeout_seconds,
        exit_code,
        success,
        timed_out,
        stdout_path,
        stderr_path,
        error,
    })
}

fn not_requested(binary: &Path, purpose: &str, output_dir: &Path) -> ToolCapture {
    let now = Utc::now();
    ToolCapture {
        requested: false,
        purpose: purpose.to_owned(),
        binary: binary.to_path_buf(),
        args: Vec::new(),
        started_at: now,
        finished_at: now,
        elapsed_seconds: 0.0,
        timeout_seconds: 0,
        exit_code: None,
        success: false,
        timed_out: false,
        stdout_path: output_dir.join(format!("{purpose}.stdout.log")),
        stderr_path: output_dir.join(format!("{purpose}.stderr.log")),
        error: Some("not requested; no process or log files created".to_owned()),
    }
}

fn kill_group(child: &mut Child) -> Result<()> {
    #[cfg(unix)]
    {
        let pid = i32::try_from(child.id()).context("child pid exceeds pid_t")?;
        // The child was created in its own group, so this does not signal the calling process.
        if unsafe { libc::kill(-pid, libc::SIGKILL) } == -1 {
            let error = std::io::Error::last_os_error();
            if error.raw_os_error() != Some(libc::ESRCH) {
                let _ = child.kill();
                return Err(error.into());
            }
        }
        Ok(())
    }
    #[cfg(not(unix))]
    child.kill().map_err(Into::into)
}
