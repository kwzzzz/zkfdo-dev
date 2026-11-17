//! Baseline-input observations kept separate from the classification result.
use super::*;
use std::cell::RefCell;

const POLICY: &str = "p1-single-hint-minus-plus-zero-original-v1";
const CONTRACT: &str = "original_baseline_comparator-no-repair-no-solver-v1";
const OUTCOMES: [&str; 9] = [
    "component_candidates_generated",
    "full_generation_successes",
    "positive",
    "verified_output_identical",
    "condition_unmet",
    "generation_failed",
    "no_component_candidate",
    "unsupported",
    "budget_exhausted",
];

#[derive(Clone, Debug)]
pub struct SiteSignalProbeOptions {
    pub enabled: bool,
    pub classes_all: bool,
    pub seconds: u64,
}
impl Default for SiteSignalProbeOptions {
    fn default() -> Self {
        Self {
            enabled: false,
            classes_all: false,
            seconds: 900,
        }
    }
}

#[derive(Default)]
struct State {
    version: bool,
    capture: bool,
    seed: Option<Seed>,
    deadline: Option<Instant>,
}
thread_local! { static STATE: RefCell<State> = RefCell::new(State::default()); }
pub(super) struct Guard;
impl Drop for Guard {
    fn drop(&mut self) {
        STATE.with(|state| *state.borrow_mut() = State::default());
    }
}
pub(super) fn activate(capture: bool) -> Result<Guard> {
    STATE.with(|state| {
        ensure!(!state.borrow().version, "v2.8 request already active");
        *state.borrow_mut() = State {
            version: true,
            capture,
            ..State::default()
        };
        Ok(Guard)
    })
}
pub(super) fn version_enabled() -> bool {
    STATE.with(|state| state.borrow().version)
}
pub(super) fn capture(make: impl FnOnce() -> Seed) {
    STATE.with(|state| {
        if state.borrow().capture {
            state.borrow_mut().seed = Some(make());
        }
    });
}
pub(super) fn tool_timeout() -> Result<Duration> {
    STATE.with(|state| match state.borrow().deadline {
        None => Ok(TOOL_TIMEOUT),
        Some(deadline) => {
            let remaining = deadline.saturating_duration_since(Instant::now());
            ensure!(!remaining.is_zero(), "site signal probe budget exhausted");
            Ok(remaining.min(TOOL_TIMEOUT))
        }
    })
}
fn expired() -> bool {
    tool_timeout().is_err()
}
pub(super) fn checkpoint() -> Result<()> {
    tool_timeout().map(|_| ())
}

pub(super) struct Seed {
    pub source_root: PathBuf,
    pub libraries: Vec<PathBuf>,
    pub wrapper: PathBuf,
    pub entrypoint: PathBuf,
    pub base_input: Value,
    pub base_input_path: PathBuf,
    pub candidate: BTreeMap<String, BigUint>,
    pub component: Compiled,
    pub component_r1cs: R1cs,
    pub component_sym: SymbolTable,
    pub component_inputs: Vec<String>,
    pub component_outputs: Vec<String>,
    pub original: Compiled,
    pub original_o0: Compiled,
    pub entry_r1cs: R1cs,
    pub entry_sym: SymbolTable,
    pub entry_o0_r1cs: R1cs,
    pub entry_o0_sym: SymbolTable,
    pub templates: Vec<TemplateDef>,
    pub sources: BTreeMap<PathBuf, String>,
    pub main_template: Option<String>,
    pub hint_suffixes: BTreeSet<String>,
    pub sites: Vec<String>,
    pub signatures: BTreeMap<String, String>,
    pub supported: bool,
    pub concrete_arguments: Option<Vec<String>>,
}

fn count_map() -> BTreeMap<String, usize> {
    OUTCOMES
        .into_iter()
        .map(|key| (key.to_owned(), 0))
        .collect()
}
fn increment(counts: &mut BTreeMap<String, usize>, key: &str) {
    if let Some(count) = counts.get_mut(key) {
        *count += 1;
    }
}
fn failure_status() -> &'static str {
    if expired() {
        "budget_exhausted"
    } else {
        "condition_unmet"
    }
}

fn observe<T>(ledger: &mut Ledger, label: &str, action: impl FnOnce() -> Result<T>) -> Result<T> {
    measured(ledger, "observation", label, action)
}

fn measured<T>(
    ledger: &mut Ledger,
    stage: &str,
    label: &str,
    action: impl FnOnce() -> Result<T>,
) -> Result<T> {
    let started = Instant::now();
    let result = checkpoint().and_then(|()| action()).and_then(|value| {
        checkpoint()?;
        Ok(value)
    });
    ledger.record(
        stage,
        label,
        started.elapsed().as_secs_f64(),
        if result.is_ok() { "ok" } else { "failed" },
        false,
    );
    result
}

fn confirmed_value_abort(log: &str) -> bool {
    let assertion = log.contains("Error: Assert Failed.")
        || log.contains("Error: Input signal array access exceeds the size");
    assertion && log.contains("Error in template")
}

/// Only a diagnosed circuit assertion can return an absent witness.
#[allow(clippy::too_many_arguments)]
fn generate_probe_witness(
    tools: &Tools,
    compiled: &Compiled,
    input: &Path,
    output: &Path,
    prime: &BigUint,
    ledger: &mut Ledger,
    stage: &str,
    label: &str,
    records: &mut Value,
) -> Result<Option<Vec<BigUint>>> {
    let started = Instant::now();
    let log = output.with_extension("log");
    let mut record = serde_json::json!({
        "stage":stage,"label":label,"exit_code":null,"log":log,
        "timed_out":false,"output_exists":false,"status":"condition_unmet"
    });
    let result = (|| {
        checkpoint()?;
        let js_dir = compiled
            .js_dir
            .as_ref()
            .context("artifact has no generator")?;
        tools.check_tool_identity(&tools.node)?;
        ensure!(
            !output.exists(),
            "witness output already exists before generation"
        );
        let mut command = Command::new(&tools.node);
        command
            .arg(js_dir.join("generate_witness.js"))
            .arg(js_dir.join(format!("{}.wasm", compiled.stem)))
            .arg(input)
            .arg(output);
        let (status, timed_out) = run_bounded_logged(&mut command, tool_timeout()?, &log)?;
        record["exit_code"] = serde_json::json!(status.code());
        record["timed_out"] = timed_out.into();
        record["output_exists"] = output.is_file().into();
        checkpoint()?;
        ensure!(
            !timed_out,
            "witness generation timed out before probe deadline"
        );
        if !status.success() {
            let text = fs::read_to_string(&log).context("generator failure log unavailable")?;
            if status.code().is_some_and(|code| code != 0) && confirmed_value_abort(&text) {
                record["status"] = "confirmed_value_abort".into();
                return Ok(None);
            }
            bail!(
                "unconfirmed generator failure; exit_code={:?}; log={}",
                status.code(),
                log.display()
            );
        }
        ensure!(
            output.is_file(),
            "generator exited successfully without witness output; log={}",
            log.display()
        );
        let values =
            wtns::read_wtns(output, prime).context("generated witness artifact is invalid")?;
        checkpoint()?;
        record["status"] = "ok".into();
        Ok(Some(values))
    })();
    if let Err(error) = &result {
        record["status"] = failure_status().into();
        record["error"] = format!("{error:#}").into();
    }
    ledger.record(
        stage,
        label,
        started.elapsed().as_secs_f64(),
        record["status"].as_str().unwrap(),
        false,
    );
    if !records.is_array() {
        *records = serde_json::json!([]);
    }
    records.as_array_mut().unwrap().push(record);
    result
}
fn value_at<'a>(sym: &SymbolTable, values: &'a [BigUint], name: &str) -> Option<&'a BigUint> {
    let wire = usize::try_from(sym.by_name.get(name)?.wire).ok()?;
    values.get(wire)
}
fn named(sym: &SymbolTable, values: &[BigUint]) -> BTreeMap<String, BigUint> {
    sym.by_name
        .keys()
        .filter_map(|name| value_at(sym, values, name).map(|v| (name.clone(), v.clone())))
        .collect()
}
fn assignment_json(values: &BTreeMap<String, BigUint>) -> Value {
    serde_json::to_value(
        values
            .iter()
            .map(|(name, value)| (name, value.to_string()))
            .collect::<BTreeMap<_, _>>(),
    )
    .unwrap()
}
fn definition_hash(def: &TemplateDef, sources: &BTreeMap<PathBuf, String>) -> String {
    sha256_bytes(&sources[&def.file].as_bytes()[def.definition_start..=def.body_end])
}

/// The policy is applied in the field before removing repeats and the normal value.
fn values(normal: &BigUint, original: &BigUint, prime: &BigUint) -> Vec<BigUint> {
    let normal = normal % prime;
    let mut seen = BTreeSet::from([normal.clone()]);
    [
        (&normal + prime - BigUint::one()) % prime,
        (&normal + BigUint::one()) % prime,
        BigUint::zero(),
        original % prime,
    ]
    .into_iter()
    .filter(|value| seen.insert(value.clone()))
    .collect()
}

fn declaration_offset(
    def: &TemplateDef,
    sources: &BTreeMap<PathBuf, String>,
    name: &str,
    component: bool,
) -> Result<usize> {
    let body = source::mask(&sources[&def.file][def.body_start..def.body_end]);
    let declarations = regex::Regex::new(if component {
        r"\bcomponent\s+([^;]+);"
    } else {
        r"\bsignal\s+([^;]+);"
    })?;
    let identifier = regex::Regex::new(r"^[A-Za-z_$][A-Za-z0-9_$]*")?;
    for declaration in declarations.captures_iter(&body) {
        let captured = declaration.get(1).unwrap();
        let mut tail = captured.as_str().trim_start();
        for role in ["input", "output"] {
            if tail
                .strip_prefix(role)
                .is_some_and(|rest| rest.starts_with(char::is_whitespace))
            {
                tail = tail[role.len()..].trim_start();
            }
        }
        if tail.starts_with('{') {
            tail = tail
                .split_once('}')
                .context("unterminated signal tags")?
                .1
                .trim_start();
        }
        loop {
            let Some(found) = identifier.find(tail) else {
                break;
            };
            if found.as_str() == leaf_base(name) {
                return Ok(captured.start() + captured.as_str().len() - tail.len());
            }
            let mut depth = 0usize;
            let mut next = None;
            for (index, character) in tail.char_indices() {
                match character {
                    '[' | '(' => depth += 1,
                    ']' | ')' => depth = depth.saturating_sub(1),
                    ',' if depth == 0 => {
                        next = Some(index + 1);
                        break;
                    }
                    '=' | '<' if depth == 0 => break,
                    _ => {}
                }
            }
            let Some(next) = next else {
                break;
            };
            tail = tail[next..].trim_start();
        }
    }
    bail!("declaration order unavailable for {name}")
}

fn ordered_hints(seed: &Seed) -> Result<Vec<String>> {
    let signals = reuse_v25::build_instance_signals(&seed.component_sym);
    let mut resolved = BTreeMap::new();
    let mut ordered = Vec::new();
    for suffix in &seed.hint_suffixes {
        let name = format!("main.{suffix}");
        let segments = name.split('.').collect::<Vec<_>>();
        let mut key = Vec::new();
        for index in 1..segments.len() {
            let parent = segments[..index].join(".");
            let def = resolve_instance(
                &parent,
                &signals,
                &seed.templates,
                &seed.sources,
                seed.main_template.as_deref(),
                &mut resolved,
            )
            .map_err(|e| anyhow::anyhow!(e.detail))?;
            key.push((
                declaration_offset(
                    def,
                    &seed.sources,
                    segments[index],
                    index + 1 < segments.len(),
                )?,
                index_vector(segments[index]),
            ));
        }
        ordered.push((key, suffix.clone()));
    }
    ordered.sort_by(|left, right| left.0.cmp(&right.0));
    Ok(ordered.into_iter().map(|(_, name)| name).collect())
}

fn check_rust(r1cs: &R1cs, values: &[BigUint], ledger: &mut Ledger, label: &str) -> Result<usize> {
    let started = Instant::now();
    let outcome = (|| {
        checkpoint()?;
        r1cs.validate_assignment(values)?;
        let mut failed = 0;
        for constraint in &r1cs.constraints {
            checkpoint()?;
            let evaluate = |terms: &super::super::r1cs::LinearCombination| -> Result<BigUint> {
                let mut total = BigUint::zero();
                for (wire, coefficient) in terms {
                    checkpoint()?;
                    total += coefficient * &values[*wire as usize];
                }
                Ok(total % &r1cs.prime)
            };
            if evaluate(&constraint.a)? * evaluate(&constraint.b)? % &r1cs.prime
                != evaluate(&constraint.c)?
            {
                failed += 1;
            }
        }
        Ok(failed)
    })();
    ledger.record(
        "check",
        label,
        started.elapsed().as_secs_f64(),
        if outcome.is_ok() { "ok" } else { "failed" },
        false,
    );
    outcome
}

/// All aliases on an O1 wire must agree in the unchanged O0 generator assignment.
fn project_o1(seed: &Seed, baseline: &[BigUint]) -> Result<Vec<BigUint>> {
    let mut result = vec![BigUint::one()];
    for names in seed.entry_sym.wire_to_names.iter().skip(1) {
        checkpoint()?;
        let values = names
            .iter()
            .map(|name| value_at(&seed.entry_o0_sym, baseline, name))
            .collect::<Option<Vec<_>>>()
            .context("original O1 alias has no O0 value")?
            .into_iter()
            .collect::<BTreeSet<_>>();
        ensure!(
            values.len() == 1,
            "original O1 wire has missing or inconsistent O0 aliases"
        );
        result.push((*values.into_iter().next().unwrap()).clone());
    }
    seed.entry_r1cs.validate_assignment(&result)?;
    Ok(result)
}

struct Baseline {
    o0: Vec<BigUint>,
    o1: Vec<BigUint>,
    witness: PathBuf,
    o0_rust: usize,
    rust: usize,
    snarkjs: String,
}
fn baseline(
    seed: &Seed,
    tools: &Tools,
    raw: &Path,
    ledger: &mut Ledger,
    records: &mut Value,
) -> Result<Baseline> {
    checkpoint()?;
    let input = raw.join("base-input.json");
    write_json(&input, &seed.base_input)?;
    let o0 = generate_probe_witness(
        tools,
        &seed.original_o0,
        &input,
        &raw.join("base-comparator-o0.wtns"),
        &seed.entry_o0_r1cs.prime,
        ledger,
        "witness",
        "original baseline O0 witness",
        records,
    )?
    .context("original baseline generator aborted")?;
    let o0_rust = check_rust(
        &seed.entry_o0_r1cs,
        &o0,
        ledger,
        "original comparator O0 Rust check",
    )?;
    ensure!(
        o0_rust == 0,
        "original baseline O0 witness violates constraints"
    );
    let o1 = observe(ledger, "project original O0 comparator to O1", || {
        project_o1(seed, &o0)
    })?;
    let witness = raw.join("comparator.wtns");
    wtns::write_wtns(&witness, &seed.entry_r1cs.prime, &o1)?;
    let rust = check_rust(
        &seed.entry_r1cs,
        &o1,
        ledger,
        "original comparator Rust check",
    )?;
    let snarkjs = snarkjs_check(tools, &seed.original.r1cs, &witness, ledger)?;
    checkpoint()?;
    ensure!(
        rust == 0 && snarkjs == "correct",
        "original comparator failed constraints"
    );
    Ok(Baseline {
        o0,
        o1,
        witness,
        o0_rust,
        rust,
        snarkjs,
    })
}

pub(super) fn run(
    options: &LiftOptions,
    probe: &SiteSignalProbeOptions,
    result: &LiftResult,
) -> Result<()> {
    let started = Instant::now();
    let deadline = started
        .checked_add(Duration::from_secs(probe.seconds))
        .context("probe budget exceeds clock range")?;
    STATE.with(|state| state.borrow_mut().deadline = Some(deadline));
    let seed = STATE.with(|state| state.borrow_mut().seed.take());
    let raw = options.output.join("raw/site-signal-probe");
    fs::create_dir_all(&raw)?;
    let raw = fs::canonicalize(&raw)?;
    let mut ledger = Ledger {
        steps: Vec::new(),
        site: None,
    };
    let mut report = serde_json::json!({
        "schema":"zkfdo-site-signal-probe-v1", "enabled":true, "budget_seconds":probe.seconds,
        "classes_policy":if probe.classes_all {"all"} else {"unknown_or_excluded_in_context"},
        "value_policy":POLICY,"contract":CONTRACT,"repair_attempts":0,
        "request_sha256":result.request_sha256,"candidate_sha256":result.candidate_sha256,
        "classes":[],"counts":count_map(),"ordered_hint_suffixes":[],"original":{},
        "identity":{"request_sha256":result.request_sha256,"candidate_sha256":result.candidate_sha256,
            "budget_seconds":probe.seconds,"value_policy":POLICY,"predicate":"component_output_violation_and_top_output_difference",
            "contract":CONTRACT},
    });
    let mut total_counts = count_map();
    let search = search_v27::activate()?;
    let execution = (|| -> Result<()> {
        let Some(seed) = seed.as_ref() else {
            report["status"] = "unsupported".into();
            report["reasons"] =
                serde_json::json!(["component preparation did not supply probe artifacts"]);
            return Ok(());
        };
        report["identity"]["base_input_sha256"] = sha256_file(&seed.base_input_path)?.into();
        report["original"] = serde_json::json!({
            "original_r1cs":seed.original.r1cs,"original_sym":seed.original.sym,
            "original_r1cs_sha256":sha256_file(&seed.original.r1cs)?,
            "original_sym_sha256":sha256_file(&seed.original.sym)?,
        });
        let hints = if expired() {
            Vec::new()
        } else {
            observe(&mut ledger, "order component hints", || ordered_hints(seed))?
        };
        report["ordered_hint_suffixes"] = serde_json::json!(hints);
        report["identity"]["ordered_hint_suffixes"] = serde_json::json!(hints);
        let tools = Tools {
            circom: resolve_executable(&options.circom_bin)?,
            node: resolve_executable(&options.node_bin)?,
            snarkjs: resolve_executable(&options.snarkjs_bin)?,
            verified_digests: None,
        };
        let any_target = result.classes.iter().any(|class| {
            probe.classes_all
                || matches!(class.verdict, Verdict::Unknown | Verdict::ExcludedInContext)
        });
        let base = if seed.supported && any_target && !expired() {
            Some(baseline(
                seed,
                &tools,
                &raw,
                &mut ledger,
                &mut report["baseline_generation"],
            ))
        } else {
            None
        };
        let entry_index = if matches!(base.as_ref(), Some(Ok(_))) {
            Some(observe(
                &mut ledger,
                "build entry O0 instance index",
                || EntryIndex::build(seed),
            ))
        } else {
            None
        };
        let mut classes = Vec::new();
        for (index, class) in result.classes.iter().enumerate() {
            ledger.site = Some(class.representative.clone());
            let mut row = serde_json::json!({"class_index":index,"pattern":class.pattern,"representative":class.representative,
                "existing_verdict":class.verdict.name(),"status":"unsupported","reasons":[],"attempts":[],"counts":count_map(),"identity":report["identity"]});
            let mut counts = count_map();
            if !probe.classes_all
                && !matches!(class.verdict, Verdict::Unknown | Verdict::ExcludedInContext)
            {
                row["status"] = "skipped".into();
                row["reasons"] = serde_json::json!(["existing verdict outside selected classes"]);
            } else if expired() {
                row["status"] = "budget_exhausted".into();
                row["reasons"] =
                    serde_json::json!(["site signal probe budget exhausted before this class"]);
            } else if !seed.supported {
                row["reasons"] = serde_json::json!([
                    "requires normal component output deviation and deviated hint signals"
                ]);
            } else if let Some(Ok(base)) = base.as_ref() {
                let folder = raw.join(format!("class-{index:03}"));
                if let Err(error) = probe_class(
                    seed,
                    &tools,
                    options,
                    probe,
                    class,
                    &hints,
                    entry_index
                        .as_ref()
                        .context("entry instance index unavailable")?
                        .as_ref()
                        .map_err(|error| anyhow::anyhow!("{error:#}"))?,
                    base,
                    &folder,
                    &mut ledger,
                    &mut row,
                    &mut counts,
                ) {
                    row["status"] = failure_status().into();
                    row["reasons"] = serde_json::json!([format!("{error:#}")]);
                }
            } else {
                row["status"] = failure_status().into();
                row["reasons"] = serde_json::json!([base
                    .as_ref()
                    .and_then(|value| value.as_ref().err())
                    .map(|error| format!("{error:#}"))
                    .unwrap_or_else(|| "baseline unavailable".into())]);
            }
            if row["attempts"].as_array().is_none_or(Vec::is_empty) {
                increment(
                    &mut counts,
                    row["status"].as_str().unwrap_or("condition_unmet"),
                );
            }
            for (name, count) in &counts {
                *total_counts.get_mut(name).unwrap() += count;
            }
            row["counts"] = serde_json::to_value(counts)?;
            let class_steps = ledger
                .steps
                .iter()
                .filter(|step| step.site.as_deref() == Some(class.representative.as_str()))
                .cloned()
                .collect::<Vec<_>>();
            let mut by_stage = BTreeMap::<String, f64>::new();
            for step in &class_steps {
                *by_stage.entry(step.stage.clone()).or_default() += step.seconds;
            }
            row["costs"] = serde_json::json!({"by_stage":by_stage,"total_seconds":by_stage.values().sum::<f64>(),"steps":class_steps});
            classes.push(row);
        }
        report["classes"] = classes.into();
        report["status"] = if expired() {
            "budget_exhausted"
        } else {
            "complete"
        }
        .into();
        if report["status"] == "budget_exhausted" {
            report["reasons"] = serde_json::json!([
                "site signal probe budget exhausted; unfinished scope remains unobserved"
            ]);
        }
        Ok(())
    })();
    drop(search);
    if let Err(error) = execution {
        report["status"] = failure_status().into();
        report["reasons"] = serde_json::json!([format!("{error:#}")]);
        if report["classes"].as_array().is_none_or(Vec::is_empty) {
            report["classes"] = result.classes.iter().enumerate().map(|(index,class)| {
                let selected = probe.classes_all || matches!(class.verdict, Verdict::Unknown | Verdict::ExcludedInContext);
                let status = if selected { failure_status() } else { "skipped" };
                let mut counts = count_map();
                increment(&mut counts, status);
                increment(&mut total_counts, status);
                serde_json::json!({
                    "class_index":index,"pattern":class.pattern,"representative":class.representative,
                    "existing_verdict":class.verdict.name(),"status":status,"reasons":[format!("{error:#}")],"counts":counts,"attempts":[]
                })
            }).collect::<Vec<_>>().into();
        }
    }
    let mut by_stage = BTreeMap::<String, f64>::new();
    for step in &ledger.steps {
        *by_stage.entry(step.stage.clone()).or_default() += step.seconds;
    }
    let recorded = by_stage.values().sum::<f64>();
    let overhead = (started.elapsed().as_secs_f64() - recorded).max(0.0);
    ledger.site = None;
    ledger.record(
        "probe_control",
        "probe setup and residual bookkeeping before final serialization",
        overhead,
        "ok",
        false,
    );
    by_stage.insert("probe_control".into(), overhead);
    report["counts"] = serde_json::to_value(total_counts)?;
    report["costs"] = serde_json::to_value(CostSummary {
        total_seconds: by_stage.values().sum(),
        wall_seconds: started.elapsed().as_secs_f64(),
        by_stage,
        steps: ledger.steps,
        ..CostSummary::default()
    })?;
    report["identity_sha256"] = sha256_bytes(&serde_json::to_vec(&report["identity"])?).into();
    write_json(&options.output.join("site-signal-probe.json"), &report)
}

#[allow(clippy::too_many_arguments)]
fn probe_class(
    seed: &Seed,
    tools: &Tools,
    options: &LiftOptions,
    probe: &SiteSignalProbeOptions,
    class: &ClassResult,
    hints: &[String],
    entry_index: &EntryIndex,
    base: &Baseline,
    folder: &Path,
    ledger: &mut Ledger,
    row: &mut Value,
    counts: &mut BTreeMap<String, usize>,
) -> Result<()> {
    checkpoint()?;
    fs::create_dir_all(folder)?;
    let mut input_leaves = Vec::new();
    for name in &seed.component_inputs {
        let suffix = name.trim_start_matches("main.");
        let value = value_at(
            &seed.entry_o0_sym,
            &base.o0,
            &format!("{}.{suffix}", class.representative),
        )
        .with_context(|| format!("baseline site input {suffix} is unobservable"))?;
        input_leaves.push((suffix.to_owned(), value.clone()));
    }
    let input = folder.join("component-input.json");
    write_json(&input, &build_input(&input_leaves)?)?;
    let normal = generate_probe_witness(
        tools,
        &seed.component,
        &input,
        &folder.join("component-normal.wtns"),
        &seed.component_r1cs.prime,
        ledger,
        "component_generation",
        "normal component at baseline site inputs",
        &mut row["generation"],
    )?
    .context("normal component reference aborted at baseline site inputs")?;
    ensure!(
        check_rust(
            &seed.component_r1cs,
            &normal,
            ledger,
            "normal component Rust check"
        )? == 0,
        "normal component violates original O0 constraints"
    );
    let normal_named = named(&seed.component_sym, &normal);
    write_json(
        &folder.join("component-normal-assignment.json"),
        &assignment_json(&normal_named),
    )?;
    let allowed = seed
        .sites
        .iter()
        .filter(|site| {
            class_pattern(site) == class.pattern
                && seed.signatures.get(*site) == seed.signatures.get(&class.representative)
        })
        .cloned()
        .collect::<BTreeSet<_>>();
    row["identity"]["representative"] = class.representative.clone().into();
    row["identity"]["class_members"] = serde_json::json!(allowed);
    row["identity"]["site_inputs"] = assignment_json(&input_leaves.iter().cloned().collect());
    row["identity"]["instance_parameters"] = serde_json::json!({"view_concrete_arguments":seed.concrete_arguments,
        "wrapper_instantiation":main_instantiation(&seed.sources[&seed.wrapper]),"representative_indices":index_vector(&class.representative)});
    let mut all_monitored = BTreeSet::new();
    let mut parameter_identities = BTreeMap::new();
    let observations = observe(ledger, "class firing lists and parameters", || {
        let mut observations = BTreeMap::new();
        for hint in hints {
            checkpoint()?;
            let observation = firing_instances(seed, entry_index, &normal_named, hint, &base.o0)?;
            all_monitored.extend(observation.1.iter().cloned());
            parameter_identities.insert(hint.clone(), hint_parameters(seed, hint)?);
            observations.insert(hint.clone(), observation);
        }
        Ok(observations)
    })?;
    let all_monitored = all_monitored.into_iter().collect::<Vec<_>>();
    let mut full_candidates = 0;
    let mut attempts = Vec::new();
    let mut policy_order = Vec::new();
    for hint in hints {
        let name = format!("main.{hint}");
        let honest = normal_named
            .get(&name)
            .context("normal hint value unavailable")?;
        let original = seed
            .candidate
            .get(&name)
            .context("original candidate hint value unavailable")?;
        for value in values(honest, original, &seed.component_r1cs.prime) {
            policy_order.push(serde_json::json!({"hint":hint,"requested_value":value.to_string()}));
        }
    }
    row["identity"]["attempt_order"] = serde_json::json!(policy_order);
    row["identity"]["budget_seconds"] = probe.seconds.into();
    for item in policy_order {
        if full_candidates == 2 {
            break;
        }
        let hint = item["hint"].as_str().unwrap();
        let value: BigUint = item["requested_value"].as_str().unwrap().parse()?;
        let index = attempts.len();
        let attempt_dir = folder.join(format!("attempt-{index:03}"));
        let mut attempt = serde_json::json!({"attempt_index":index,"hint":hint,"requested_value":value.to_string(),
            "rewrite_targets":[hint],"honest_aborted":false,"status":"no_component_candidate",
            "reasons":[],"repair_attempts":0,"firing_instances":[],"value_differences":[],"evidence":{},
            "checks":{"component_hint_requested":value.to_string(),"component_hint_actual":null,"component_hint_matches":false},
            "identity":row["identity"]});
        let execution = (|| -> Result<()> {
            checkpoint()?;
            fs::create_dir_all(&attempt_dir)?;
            let mut intervention = normal_named.clone();
            intervention.insert(format!("main.{hint}"), value.clone());
            write_json(
                &attempt_dir.join("intervention.json"),
                &serde_json::json!({
                "hint":hint,"normal_value":normal_named[&format!("main.{hint}")].to_string(),"requested_value":value.to_string(),
                "rewrite_targets":[hint],"honest_aborted":false,"value_policy":POLICY}),
            )?;
            let targets = BTreeSet::from([format!("main.{hint}")]);
            let component_plan = plan_rewrites(
                &intervention,
                &seed.component_sym,
                &targets,
                false,
                &seed.templates,
                &seed.sources,
                seed.main_template.as_deref(),
                None,
            )
            .map_err(|error| anyhow::anyhow!(error.detail))?;
            ensure!(
                component_plan.hint_suffixes == BTreeSet::from([hint.to_owned()]),
                "rewrite set is not the singleton intervention"
            );
            let (firing, _monitored, template_hash) = &observations[hint];
            attempt["firing_instances"] = serde_json::json!(firing);
            attempt["identity"]["firing_instances"] = serde_json::json!(firing);
            attempt["identity"]["template_definition_sha256"] = template_hash.clone().into();
            attempt["identity"]["concrete_template_parameters"] =
                serde_json::to_value(&parameter_identities[hint])?;
            attempt["identity"]["intervention"] =
                serde_json::json!({"hint":hint,"value":value.to_string()});
            attempt["identity_sha256"] =
                sha256_bytes(&serde_json::to_vec(&attempt["identity"])?).into();
            attempt["probe_cache_key"] = attempt["identity_sha256"].clone();
            let component_edited = edited(
                seed,
                tools,
                options,
                &component_plan.edits,
                &seed.wrapper,
                true,
                &attempt_dir.join("component"),
                ledger,
                "single hint component compile",
            )?;
            ensure!(
                artifact_bytes_equal(
                    "component probe equivalence",
                    &seed.component.r1cs,
                    &component_edited.r1cs
                )?,
                "component rewrite changed R1CS"
            );
            repair::sym_equivalence(
                &fs::read_to_string(&seed.component.sym)?,
                &fs::read_to_string(&component_edited.sym)?,
            )?;
            let generated = generate_probe_witness(
                tools,
                &component_edited,
                &input,
                &attempt_dir.join("component-generated.wtns"),
                &seed.component_r1cs.prime,
                ledger,
                "component_generation",
                "single hint component regeneration",
                &mut attempt["generation"],
            )?;
            let Some(generated) = generated else {
                attempt["reasons"] = serde_json::json!([
                    "component generator confirmed assertion or range-check abort"
                ]);
                return Ok(());
            };
            let complete = named(&seed.component_sym, &generated);
            write_json(
                &attempt_dir.join("component-generated-assignment.json"),
                &assignment_json(&complete),
            )?;
            attempt["evidence"]["component_assignment"] = attempt_dir
                .join("component-generated-assignment.json")
                .display()
                .to_string()
                .into();
            attempt["evidence"]["intervention"] = attempt_dir
                .join("intervention.json")
                .display()
                .to_string()
                .into();
            let actual = complete.get(&format!("main.{hint}"));
            attempt["checks"]["component_hint_requested"] = value.to_string().into();
            attempt["checks"]["component_hint_actual"] =
                serde_json::json!(actual.map(ToString::to_string));
            attempt["checks"]["component_hint_matches"] = (actual == Some(&value)).into();
            ensure!(
                actual == Some(&value),
                "요청 개입값이 재생성 결과에서 확인되지 않음"
            );
            let failed = check_rust(
                &seed.component_r1cs,
                &generated,
                ledger,
                "regenerated component original O0 check",
            )?;
            let outputs = seed
                .component_outputs
                .iter()
                .map(|name| {
                    value_at(&seed.component_sym, &normal, name).zip(value_at(
                        &seed.component_sym,
                        &generated,
                        name,
                    ))
                })
                .collect::<Option<Vec<_>>>()
                .context("component output observation is missing")?;
            let changed = outputs.iter().filter(|(left, right)| left != right).count();
            attempt["checks"]["component_rust_unsatisfied"] = failed.into();
            attempt["checks"]["component_candidate_outputs_differing"] = changed.into();
            if failed != 0 || changed == 0 {
                attempt["reasons"] = serde_json::json!(["requested hint confirmed but original component constraints or output difference did not pass"]);
                return Ok(());
            }
            increment(counts, "component_candidates_generated");
            full_candidates += 1;
            attempt["component_candidate"] = true.into();
            execute_full(
                seed,
                tools,
                options,
                class,
                base,
                &component_plan.edits,
                hint,
                &value,
                &allowed,
                firing,
                &all_monitored,
                &attempt_dir,
                ledger,
                &mut attempt,
                counts,
            )
        })();
        if let Err(error) = execution {
            attempt["status"] = failure_status().into();
            attempt["reasons"] = serde_json::json!([format!("{error:#}")]);
        }
        if expired() {
            attempt["status"] = "budget_exhausted".into();
            attempt["reasons"] = serde_json::json!(["site signal probe budget exhausted"]);
        }
        let status = attempt["status"].as_str().unwrap().to_owned();
        increment(counts, &status);
        attempts.push(attempt);
        if status == "positive" || status == "budget_exhausted" {
            break;
        }
    }
    let status = [
        "positive",
        "budget_exhausted",
        "verified_output_identical",
        "condition_unmet",
        "generation_failed",
        "no_component_candidate",
    ]
    .into_iter()
    .find(|status| attempts.iter().any(|attempt| attempt["status"] == *status))
    .unwrap_or("no_component_candidate");
    row["status"] = status.into();
    row["attempts"] = attempts.into();
    Ok(())
}

fn hint_parameters(seed: &Seed, hint: &str) -> Result<Vec<String>> {
    let name = format!("main.{hint}");
    let (parent, _) = split_instance(&name);
    let signals = reuse_v25::build_instance_signals(&seed.component_sym);
    let def = resolve_instance(
        parent,
        &signals,
        &seed.templates,
        &seed.sources,
        seed.main_template.as_deref(),
        &mut BTreeMap::new(),
    )
    .map_err(|error| anyhow::anyhow!(error.detail))?;
    let header = &seed.sources[&def.file][def.definition_start..def.body_start];
    let parameters = header
        .split_once('(')
        .and_then(|(_, tail)| tail.split_once(')'))
        .map(|(text, _)| text.trim())
        .context("template parameter header unavailable")?;
    if parameters.is_empty() {
        return Ok(Vec::new());
    }
    let values = super::site_probe_identity::concrete_parameters(
        &seed.entrypoint,
        &seed.source_root,
        &seed.libraries,
        "bn128",
        &def.name,
    )?;
    checkpoint()?;
    Ok(values)
}

fn main_instantiation(source_text: &str) -> String {
    let masked = source::mask(source_text);
    regex::Regex::new(r"(?s)\bcomponent\s+main\b[^;]*;")
        .unwrap()
        .find(&masked)
        .map(|found| source_text[found.start()..found.end()].to_owned())
        .unwrap_or_default()
}

#[allow(clippy::too_many_arguments)]
fn edited(
    seed: &Seed,
    tools: &Tools,
    options: &LiftOptions,
    edits: &repair::Edits,
    entry: &Path,
    o0: bool,
    folder: &Path,
    ledger: &mut Ledger,
    label: &str,
) -> Result<Compiled> {
    checkpoint()?;
    let prepared = measured(ledger, "compile", "write single hint workspace", || {
        let plan = super::site_probe_workspace::WorkspacePlan::new(
            entry,
            &seed.source_root,
            &seed.libraries,
            &seed.sources,
        )?;
        let mut edits = edits.clone();
        source::map_edits_to_entrypoint(
            &mut edits,
            &seed.templates,
            &seed.sources,
            entry,
            &seed.source_root,
            &seed.libraries,
        )?;
        plan.write(&folder.join("workspace"), &edits)
    })?;
    checkpoint()?;
    let relative = entry
        .strip_prefix(&seed.source_root)
        .context("component or entrypoint outside source root")?;
    let cache = measured(ledger, "compile", "single hint cache identity", || {
        options
            .cache
            .as_deref()
            .map(|cache| -> Result<_> {
                Ok((
                    cache,
                    edits_key(
                        tools,
                        relative,
                        &seed.source_root,
                        &seed.libraries,
                        &seed.sources,
                        &prepared.edits,
                        o0,
                    )?,
                ))
            })
            .transpose()
    })?;
    measured(
        ledger,
        "check",
        "verify edited workspace source correspondence",
        || prepared.verify(),
    )?;
    compile_edited(
        tools,
        cache,
        &prepared.entry,
        &folder.join("compiled"),
        &prepared.root,
        &prepared.libraries,
        o0,
        ledger,
        label,
    )
}

struct IndexedInstance {
    signals: BTreeSet<String>,
    definition: std::result::Result<String, String>,
}
impl IndexedInstance {
    fn matches(&self, instance: &str, signals: &BTreeSet<String>, hash: &str) -> Result<bool> {
        match &self.definition {
            Ok(definition) => Ok(definition == hash),
            Err(error) if &self.signals == signals => {
                bail!("cannot resolve potential rewritten instance {instance}: {error}")
            }
            Err(_) => Ok(false),
        }
    }
}
struct EntryIndex(BTreeMap<String, IndexedInstance>);
impl EntryIndex {
    fn build(seed: &Seed) -> Result<Self> {
        let mut signals = BTreeMap::<String, BTreeSet<String>>::new();
        for name in seed.entry_o0_sym.by_name.keys() {
            checkpoint()?;
            let (instance, leaf) = split_instance(name);
            signals
                .entry(instance.to_owned())
                .or_default()
                .insert(leaf_base(leaf).to_owned());
        }
        let main = main_template_name(&seed.sources[&seed.entrypoint]);
        let mut memo = BTreeMap::new();
        let mut hashes = BTreeMap::new();
        let mut index = BTreeMap::new();
        for (instance, signal_set) in &signals {
            checkpoint()?;
            let definition = resolve_instance(
                instance,
                &signals,
                &seed.templates,
                &seed.sources,
                main.as_deref(),
                &mut memo,
            )
            .map(|def| {
                hashes
                    .entry((def.file.clone(), def.definition_start, def.body_end))
                    .or_insert_with(|| definition_hash(def, &seed.sources))
                    .clone()
            })
            .map_err(|error| error.detail);
            index.insert(
                instance.clone(),
                IndexedInstance {
                    signals: signal_set.clone(),
                    definition,
                },
            );
        }
        checkpoint()?;
        Ok(Self(index))
    }
}

type FiringObservation = (Vec<String>, Vec<(String, String)>, String);

/// The input equality clauses are evaluated on every instance of the edited definition.
fn firing_instances(
    seed: &Seed,
    index: &EntryIndex,
    normal: &BTreeMap<String, BigUint>,
    hint: &str,
    baseline: &[BigUint],
) -> Result<FiringObservation> {
    let name = format!("main.{hint}");
    let (parent, leaf) = split_instance(&name);
    let component_signals = reuse_v25::build_instance_signals(&seed.component_sym);
    let target = resolve_instance(
        parent,
        &component_signals,
        &seed.templates,
        &seed.sources,
        seed.main_template.as_deref(),
        &mut BTreeMap::new(),
    )
    .map_err(|error| anyhow::anyhow!(error.detail))?;
    let hash = definition_hash(target, &seed.sources);
    let mut conditions = Vec::new();
    for input in &target.inputs {
        let prefix = format!("{parent}.{input}");
        let leaves = normal
            .iter()
            .filter(|(name, _)| **name == prefix || name.starts_with(&format!("{prefix}[")))
            .collect::<Vec<_>>();
        ensure!(
            !leaves.is_empty(),
            "intervention template input values are unavailable"
        );
        conditions.extend(
            leaves
                .into_iter()
                .map(|(name, value)| (name[parent.len() + 1..].to_owned(), value)),
        );
    }
    let mut firing = Vec::new();
    let mut monitored = Vec::new();
    let child_path = parent.strip_prefix("main").unwrap();
    for (instance, indexed) in &index.0 {
        checkpoint()?;
        if !indexed.matches(instance, &target.signals, &hash)? {
            continue;
        }
        let owner = if child_path.is_empty() {
            instance.as_str()
        } else {
            instance.strip_suffix(child_path).unwrap_or(instance)
        };
        let full_hint = format!("{instance}.{leaf}");
        monitored.push((owner.to_owned(), full_hint));
        let mut matches = true;
        for (suffix, expected) in &conditions {
            let observed = value_at(
                &seed.entry_o0_sym,
                baseline,
                &format!("{instance}.{suffix}"),
            )
            .with_context(|| format!("firing input unobservable at {instance}.{suffix}"))?;
            matches &= observed == *expected;
        }
        if matches {
            firing.push(instance.clone());
        }
    }
    firing.sort_by_key(|site| (class_pattern(site), index_vector(site)));
    ensure!(
        !monitored.is_empty(),
        "rewritten template has no observable instances"
    );
    Ok((firing, monitored, hash))
}

#[allow(clippy::too_many_arguments)]
fn execute_full(
    seed: &Seed,
    tools: &Tools,
    options: &LiftOptions,
    class: &ClassResult,
    base: &Baseline,
    edits: &repair::Edits,
    hint: &str,
    requested: &BigUint,
    allowed: &BTreeSet<String>,
    firing: &[String],
    monitored: &[(String, String)],
    folder: &Path,
    ledger: &mut Ledger,
    attempt: &mut Value,
    counts: &mut BTreeMap<String, usize>,
) -> Result<()> {
    checkpoint()?;
    attempt["status"] = "condition_unmet".into();
    let compiled = edited(
        seed,
        tools,
        options,
        edits,
        &seed.entrypoint,
        false,
        &folder.join("entry-o1"),
        ledger,
        "single hint entrypoint compile",
    )?;
    let r1cs_identical = artifact_bytes_equal(
        "probe R1CS equivalence",
        &seed.original.r1cs,
        &compiled.r1cs,
    )?;
    let sym_equivalent = repair::sym_equivalence(
        &fs::read_to_string(&seed.original.sym)?,
        &fs::read_to_string(&compiled.sym)?,
    )
    .is_ok();
    attempt["checks"]["r1cs_identical"] = r1cs_identical.into();
    attempt["checks"]["sym_equivalent"] = sym_equivalent.into();
    ensure!(
        r1cs_identical && sym_equivalent,
        "edited entrypoint changed original artifacts"
    );
    let input = folder.join("base-input.json");
    write_json(&input, &seed.base_input)?;
    let witness_path = folder.join("deviated.wtns");
    let Some(deviated) = generate_probe_witness(
        tools,
        &compiled,
        &input,
        &witness_path,
        &seed.entry_r1cs.prime,
        ledger,
        "witness",
        "single hint full generation without repair",
        &mut attempt["generation"],
    )?
    else {
        attempt["status"] = "generation_failed".into();
        attempt["reasons"] = serde_json::json!([
            "deviated full generator confirmed assertion or range-check abort; no repair attempted"
        ]);
        return Ok(());
    };
    attempt["status"] = "condition_unmet".into();
    increment(counts, "full_generation_successes");
    let rust = check_rust(
        &seed.entry_r1cs,
        &deviated,
        ledger,
        "deviated original O1 Rust check",
    )?;
    let snarkjs = snarkjs_check(tools, &seed.original.r1cs, &witness_path, ledger)?;
    checkpoint()?;
    attempt["evidence"] = serde_json::json!({
        "component_assignment":folder.join("component-generated-assignment.json"),"intervention":folder.join("intervention.json"),
        "original_r1cs":seed.original.r1cs,"original_sym":seed.original.sym,
        "original_r1cs_sha256":sha256_file(&seed.original.r1cs)?,"original_sym_sha256":sha256_file(&seed.original.sym)?,
        "comparator_wtns":base.witness,"deviated_wtns":witness_path,
        "comparator_wtns_sha256":sha256_file(&base.witness)?,"deviated_wtns_sha256":sha256_file(&witness_path)?,
        "comparator_origin":"original_generator_o0_projection","input_origin":"base","input_sha256":sha256_file(&input)?,
    });
    let mut reasons = Vec::<String>::new();
    if base.rust != 0 || base.snarkjs != "correct" || rust != 0 || snarkjs != "correct" {
        reasons.push("both witnesses must pass original full constraints".into());
    }
    let mut check_values = attempt["checks"].clone();
    let checks = check_values.as_object_mut().unwrap();
    checks.insert("comparator_o0_rust_unsatisfied".into(), base.o0_rust.into());
    checks.insert("comparator_rust_unsatisfied".into(), base.rust.into());
    checks.insert("deviated_rust_unsatisfied".into(), rust.into());
    checks.insert("comparator_snarkjs".into(), base.snarkjs.clone().into());
    checks.insert("deviated_snarkjs".into(), snarkjs.into());
    let base_values = flattened_input(&seed.base_input, &seed.entry_r1cs.prime)?;
    let first_input = 1 + seed.entry_r1cs.shape.public_outputs;
    let last_input =
        first_input + seed.entry_r1cs.shape.public_inputs + seed.entry_r1cs.shape.private_inputs;
    let mut input_rows = Vec::new();
    let mut inputs_equal = true;
    for wire in first_input..last_input {
        checkpoint()?;
        let names = &seed.entry_sym.wire_to_names[wire];
        let (fact, equal) = input_wire_fact(wire, names, &base_values, &base.o1, &deviated);
        inputs_equal &= equal;
        input_rows.push(fact);
    }
    checks.insert("input_wires".into(), input_rows.into());
    checks.insert("input_wires_equal_base".into(), inputs_equal.into());
    checks.insert(
        "public_input_count".into(),
        seed.entry_r1cs.shape.public_inputs.into(),
    );
    checks.insert(
        "private_input_count".into(),
        seed.entry_r1cs.shape.private_inputs.into(),
    );
    if !inputs_equal {
        reasons.push("public and private input wires must all equal the baseline".into());
    }
    let hint_parent = split_instance(hint).0;
    let child_path = if hint_parent.is_empty() {
        String::new()
    } else {
        format!(".{hint_parent}")
    };
    let expected_firing = format!("{}{child_path}", class.representative);
    let firing_within = firing.iter().all(|site| {
        site.strip_suffix(&child_path)
            .is_some_and(|owner| allowed.contains(owner))
    }) && firing.contains(&expected_firing);
    checks.insert("firing_within_class".into(), firing_within.into());
    if !firing_within {
        reasons.push(
            "rewrite firing set leaves the representative class or omits its representative".into(),
        );
    }
    let target_hint = format!("{}.{hint}", class.representative);
    let output_names = seed
        .component_outputs
        .iter()
        .map(|name| {
            format!(
                "{}.{}",
                class.representative,
                name.trim_start_matches("main.")
            )
        })
        .collect::<Vec<_>>();
    let observable = |name: &str| {
        value_at(&seed.entry_sym, &base.o1, name).is_some()
            && value_at(&seed.entry_sym, &deviated, name).is_some()
    };
    let need_o0 = !observable(&target_hint)
        || output_names.iter().any(|name| !observable(name))
        || monitored.iter().any(|(_, name)| !observable(name));
    attempt["checks"] = Value::Object(checks.clone());
    let o0_deviated = if need_o0 {
        let compiled_o0 = edited(
            seed,
            tools,
            options,
            edits,
            &seed.entrypoint,
            true,
            &folder.join("entry-o0"),
            ledger,
            "single hint O0 observation compile",
        )?;
        ensure!(
            artifact_bytes_equal(
                "probe O0 equivalence",
                &seed.original_o0.r1cs,
                &compiled_o0.r1cs
            )?,
            "edited O0 changed original constraints"
        );
        repair::sym_equivalence(
            &fs::read_to_string(&seed.original_o0.sym)?,
            &fs::read_to_string(&compiled_o0.sym)?,
        )?;
        let generated = generate_probe_witness(
            tools,
            &compiled_o0,
            &input,
            &folder.join("deviated-o0.wtns"),
            &seed.entry_o0_r1cs.prime,
            ledger,
            "witness",
            "single hint O0 observation generation",
            &mut attempt["generation"],
        )?;
        let Some(generated) = generated else {
            attempt["status"] = "generation_failed".into();
            attempt["reasons"] =
                serde_json::json!(["O0 full generator confirmed assertion or range-check abort"]);
            attempt["checks"] = check_values;
            return Ok(());
        };
        let o0_failed = check_rust(
            &seed.entry_o0_r1cs,
            &generated,
            ledger,
            "deviated observation original O0 Rust check",
        )?;
        checks.insert("deviated_o0_rust_unsatisfied".into(), o0_failed.into());
        ensure!(
            o0_failed == 0,
            "O0 observation violates original full constraints"
        );
        ensure!(
            observe(ledger, "project deviated O0 observation to O1", || {
                project_o1(seed, &generated)
            })? == deviated,
            "O0 observation does not reproduce the full O1 witness"
        );
        Some(generated)
    } else {
        None
    };
    let (output_count, differences) = observe(ledger, "hint and output value differences", || {
        let pair_at = |name: &str| -> Option<(&BigUint, &BigUint)> {
            value_at(&seed.entry_sym, &base.o1, name)
                .zip(value_at(&seed.entry_sym, &deviated, name))
                .or_else(|| {
                    o0_deviated.as_ref().and_then(|right| {
                        value_at(&seed.entry_o0_sym, &base.o0, name).zip(value_at(
                            &seed.entry_o0_sym,
                            right,
                            name,
                        ))
                    })
                })
        };
        let target_matches =
            pair_at(&target_hint).is_some_and(|(left, right)| right == requested && left != right);
        checks.insert("representative_hint_matches".into(), target_matches.into());
        checks.insert(
            "representative_hint_requested".into(),
            requested.to_string().into(),
        );
        checks.insert(
            "representative_hint_actual".into(),
            serde_json::json!(pair_at(&target_hint).map(|(_, right)| right.to_string())),
        );
        if !target_matches {
            reasons.push("요청 개입값이 재생성 결과에서 확인되지 않음".into());
        }
        let outputs = output_names
            .iter()
            .map(|name| pair_at(name))
            .collect::<Vec<_>>();
        let differing = outputs
            .iter()
            .flatten()
            .filter(|(left, right)| left != right)
            .count();
        checks.insert("component_outputs_differing".into(), differing.into());
        checks.insert(
            "observation_optimization".into(),
            if need_o0 { "O0" } else { "O1" }.into(),
        );
        if outputs.iter().any(Option::is_none) || differing == 0 {
            reasons.push(
                "representative component output difference is missing or unobservable".into(),
            );
        }
        let mut differences = Vec::new();
        for (owner, name) in monitored {
            checkpoint()?;
            match pair_at(name) {
                Some((left, right)) if left != right => {
                    differences.push(serde_json::json!({"name":name,"comparator":left.to_string(),"deviated":right.to_string()}));
                    if !allowed.contains(owner) {
                        reasons.push(format!("changed hint outside representative class: {name}"));
                    }
                }
                None => reasons.push(format!("hint difference observation unavailable: {name}")),
                _ => {}
            }
        }
        let output_count = (1..first_input)
            .filter(|wire| base.o1.get(*wire) != deviated.get(*wire))
            .count();
        checks.insert("outputs_differing".into(), output_count.into());
        Ok((output_count, differences))
    })?;
    attempt["checks"] = check_values;
    attempt["value_differences"] = differences.into();
    attempt["status"] = if !reasons.is_empty() {
        "condition_unmet"
    } else if output_count > 0 {
        "positive"
    } else {
        "verified_output_identical"
    }
    .into();
    attempt["reasons"] = serde_json::json!(reasons);
    checkpoint()?;
    Ok(())
}

fn input_wire_fact(
    wire: usize,
    names: &[String],
    base: &BTreeMap<String, BigUint>,
    left: &[BigUint],
    right: &[BigUint],
) -> (Value, bool) {
    let inputs = names
        .iter()
        .filter(|name| base.contains_key(*name))
        .collect::<Vec<_>>();
    let expected = inputs
        .iter()
        .filter_map(|name| base.get(*name))
        .collect::<BTreeSet<_>>();
    let unambiguous = expected.len() == 1;
    let normal = expected.into_iter().next();
    let equal = unambiguous
        && normal
            .is_some_and(|value| left.get(wire) == Some(value) && right.get(wire) == Some(value));
    (
        serde_json::json!({"wire":wire,"name":inputs.first(),"expected":normal.map(ToString::to_string),
        "comparator":left.get(wire).map(ToString::to_string),"deviated":right.get(wire).map(ToString::to_string)}),
        equal,
    )
}

fn flattened_input(input: &Value, prime: &BigUint) -> Result<BTreeMap<String, BigUint>> {
    fn visit(
        value: &Value,
        name: String,
        prime: &num_bigint::BigInt,
        out: &mut BTreeMap<String, BigUint>,
    ) -> Result<()> {
        match value {
            Value::Object(fields) => {
                for (key, value) in fields {
                    visit(value, format!("{name}.{key}"), prime, out)?;
                }
            }
            Value::Array(values) => {
                for (index, value) in values.iter().enumerate() {
                    visit(value, format!("{name}[{index}]"), prime, out)?;
                }
            }
            Value::String(_) | Value::Number(_) => {
                let text = value
                    .as_str()
                    .map(str::to_owned)
                    .unwrap_or_else(|| value.to_string());
                let integer: num_bigint::BigInt = text
                    .parse()
                    .with_context(|| format!("invalid baseline input at {name}"))?;
                let canonical = ((integer % prime) + prime) % prime;
                out.insert(
                    name,
                    canonical
                        .to_biguint()
                        .context("negative normalized field value")?,
                );
            }
            _ => bail!("unsupported baseline input at {name}"),
        }
        Ok(())
    }
    let mut out = BTreeMap::new();
    visit(
        input,
        "main".into(),
        &num_bigint::BigInt::from(prime.clone()),
        &mut out,
    )?;
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn indexed_resolution_failure_only_affects_matching_signal_sets() {
        let row = IndexedInstance {
            signals: BTreeSet::from(["x".into(), "h".into()]),
            definition: Err("ambiguous definition".into()),
        };
        assert!(!row
            .matches("main.unrelated", &BTreeSet::from(["x".into()]), "hash")
            .unwrap());
        assert!(row.matches("main.target", &row.signals, "hash").is_err());
        let resolved = IndexedInstance {
            signals: row.signals.clone(),
            definition: Ok("hash".into()),
        };
        assert!(resolved
            .matches("main.target", &row.signals, "hash")
            .unwrap());
        assert!(!resolved
            .matches("main.other", &row.signals, "different")
            .unwrap());
    }

    #[test]
    fn value_abort_requires_circuit_diagnostic_not_generic_tool_errors() {
        assert!(confirmed_value_abort(
            "Error: Assert Failed. Error in template T_0 line: 4"
        ));
        for text in [
            "Error: Assert Failed.",
            "Error: Cannot find module",
            "RangeError: out of memory",
            "RuntimeError: unreachable",
            "Error in template T_0",
        ] {
            assert!(!confirmed_value_abort(text), "{text}");
        }
    }

    #[cfg(unix)]
    #[test]
    fn generator_diagnostics_distinguish_abort_failure_missing_output_and_budget() -> Result<()> {
        use std::os::unix::fs::PermissionsExt;
        let temporary = tempfile::tempdir()?;
        let node = temporary.path().join("generator");
        let compiled = Compiled {
            r1cs: temporary.path().join("unused.r1cs"),
            sym: temporary.path().join("unused.sym"),
            js_dir: Some(temporary.path().to_path_buf()),
            stem: "test".into(),
        };
        let tools = Tools {
            circom: node.clone(),
            node: node.clone(),
            snarkjs: node.clone(),
            verified_digests: None,
        };
        for (index, (body, confirmed)) in [
            (
                "echo 'Error: Assert Failed. Error in template T_0 line: 4'; exit 1",
                true,
            ),
            ("echo 'module not found'; exit 91", false),
            ("exit 0", false),
            ("echo invalid > \"$4\"; exit 0", false),
        ]
        .into_iter()
        .enumerate()
        {
            fs::write(&node, format!("#!/bin/sh\n{body}\n"))?;
            fs::set_permissions(&node, fs::Permissions::from_mode(0o755))?;
            let mut ledger = Ledger {
                steps: vec![],
                site: None,
            };
            let mut records = Value::Null;
            let output = temporary.path().join(format!("{index}.wtns"));
            let result = generate_probe_witness(
                &tools,
                &compiled,
                &temporary.path().join("input.json"),
                &output,
                &97u32.into(),
                &mut ledger,
                "witness",
                "test generation",
                &mut records,
            );
            if confirmed {
                assert!(matches!(result, Ok(None)));
            } else {
                assert!(result.is_err());
            }
            assert_eq!(records[0]["stage"], "witness");
            assert!(records[0]["exit_code"].is_number());
            assert!(Path::new(records[0]["log"].as_str().unwrap()).is_file());
        }
        let _guard = activate(true)?;
        STATE.with(|state| state.borrow_mut().deadline = Some(Instant::now()));
        let mut ledger = Ledger {
            steps: vec![],
            site: None,
        };
        let mut records = Value::Null;
        assert!(generate_probe_witness(
            &tools,
            &compiled,
            &temporary.path().join("input.json"),
            &temporary.path().join("budget.wtns"),
            &97u32.into(),
            &mut ledger,
            "witness",
            "budget generation",
            &mut records
        )
        .is_err());
        assert_eq!(records[0]["status"], "budget_exhausted");
        assert!(records[0]["exit_code"].is_null());
        Ok(())
    }

    #[test]
    fn value_policy_normalizes_and_deduplicates_in_order() {
        let prime = BigUint::from(97u32);
        assert_eq!(
            values(&98u32.into(), &194u32.into(), &prime),
            vec![0u32.into(), 2u32.into()]
        );
        assert_eq!(
            values(&0u32.into(), &196u32.into(), &prime),
            vec![96u32.into(), 1u32.into(), 2u32.into()]
        );
        assert_eq!(
            values(&3u32.into(), &3u32.into(), &prime),
            vec![2u32.into(), 4u32.into(), 0u32.into()]
        );
    }
    #[test]
    fn input_wire_gate_rejects_missing_and_changed_private_values() {
        let names = vec!["main.secret".into()];
        let base = BTreeMap::from([("main.secret".into(), 11u32.into())]);
        let left = vec![1u32.into(), 11u32.into()];
        assert!(input_wire_fact(1, &names, &base, &left, &left).1);
        assert!(!input_wire_fact(1, &names, &BTreeMap::new(), &left, &left).1);
        assert!(!input_wire_fact(1, &names, &base, &left, &[1u32.into(), 12u32.into()]).1);
        assert!(!input_wire_fact(1, &names, &base, &left, &[1u32.into()]).1);
        let mut aliases = base.clone();
        aliases.insert("main.other".into(), 12u32.into());
        assert!(
            !input_wire_fact(
                1,
                &["main.secret".into(), "main.other".into()],
                &aliases,
                &left,
                &left
            )
            .1
        );
    }

    #[test]
    fn input_names_recurse_and_normalize_signed_field_values() {
        let values = flattened_input(
            &serde_json::json!({"a":[-1,"98"],"bus":{"secret":"-98"}}),
            &97u32.into(),
        )
        .unwrap();
        assert_eq!(values["main.a[0]"], 96u32.into());
        assert_eq!(values["main.a[1]"], 1u32.into());
        assert_eq!(values["main.bus.secret"], 96u32.into());
        assert!(flattened_input(&serde_json::json!({"secret":null}), &97u32.into()).is_err());
    }

    #[test]
    fn declaration_order_ignores_rhs_references_and_keeps_comma_order() {
        let file = PathBuf::from("fixture.circom");
        let text = "template T() { signal first <== z; signal z; signal a[12], b[2]; }".to_owned();
        let sources = BTreeMap::from([(file.clone(), text.clone())]);
        let def = &parse_templates(&file, &text).unwrap()[0];
        let z = declaration_offset(def, &sources, "z", false).unwrap();
        let first = declaration_offset(def, &sources, "first", false).unwrap();
        let a = declaration_offset(def, &sources, "a", false).unwrap();
        let b = declaration_offset(def, &sources, "b", false).unwrap();
        assert!(first < z && z < a && a < b);
        assert!(declaration_offset(def, &sources, "missing", false).is_err());
    }

    #[test]
    fn zero_budget_prevents_tool_launch() {
        let _guard = activate(false).unwrap();
        STATE.with(|state| state.borrow_mut().deadline = Some(Instant::now()));
        assert!(tool_timeout().is_err());
    }
}
