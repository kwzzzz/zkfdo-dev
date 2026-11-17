//! Opt-in completion and diagnostics. No legacy verdict is changed here.
use super::*;
use std::cell::RefCell;

#[derive(Clone, Debug, Default, Serialize)]
pub struct BoostOptions {
    pub constraint_witness: bool,
    pub class_sweep_budget_seconds: Option<u64>,
    pub injection_diagnostics: bool,
    pub aligned_diagnostics: bool,
    /// Diagnostic only; never changes the legacy cache key or result contract.
    #[serde(skip_serializing)]
    pub post_limit_probe_site: Option<String>,
}
impl BoostOptions {
    pub(crate) fn active(&self) -> bool {
        self.constraint_witness
            || self.class_sweep_budget_seconds.is_some()
            || self.injection_diagnostics
            || self.aligned_diagnostics
    }
}
pub(super) struct State {
    pub options: BoostOptions,
    records: RefCell<Vec<Value>>,
    probe_jobs: RefCell<Vec<repair::PostLimitProbe>>,
}
impl State {
    pub fn new(options: BoostOptions) -> Self {
        Self {
            options,
            records: RefCell::new(Vec::new()),
            probe_jobs: RefCell::new(Vec::new()),
        }
    }
    pub fn push(&self, value: Value) {
        self.records.borrow_mut().push(value);
    }
    pub(crate) fn latest_record(&self) -> Option<Value> {
        self.records.borrow().last().cloned()
    }
    pub(crate) fn queue_probe(&self, probe: repair::PostLimitProbe) {
        self.probe_jobs.borrow_mut().push(probe);
    }
    pub(crate) fn take_probe_jobs(&self) -> Vec<repair::PostLimitProbe> {
        std::mem::take(&mut *self.probe_jobs.borrow_mut())
    }
    pub fn write(&self, folder: &Path) -> Result<()> {
        if self.options.active() {
            write_json(
                &folder.join("j-boost.json"),
                &serde_json::json!({
                    "schema":"j-boost-v1", "options":self.options, "records":*self.records.borrow(),
                    "legacy_verdicts_unchanged":true
                }),
            )?;
        }
        Ok(())
    }
}
pub(super) struct Snapshot {
    pub start: Vec<BigUint>,
    /// All queried wires, including constants substituted into the solver query.
    pub query: BTreeMap<usize, BigUint>,
    pub scope: BTreeMap<usize, BigUint>,
    pub origin: String,
}

fn assemble(r: &R1cs, snapshot: &Snapshot) -> Result<Vec<BigUint>> {
    // Diagnostic starting assignments may violate constraints, but must have a valid shape.
    r.validate_assignment(&snapshot.start)?;
    let mut values = snapshot.start.clone();
    for (&wire, value) in &snapshot.query {
        *values.get_mut(wire).context("query_wire_missing")? = value.clone();
    }
    r.validate_assignment(&values)?;
    ensure!(
        snapshot
            .scope
            .iter()
            .all(|(&wire, v)| values.get(wire) == Some(v)),
        "input_scope_not_met"
    );
    Ok(values)
}
#[cfg(test)]
fn complete(r: &R1cs, snapshot: &Snapshot) -> Result<Vec<BigUint>> {
    let values = assemble(r, snapshot)?;
    ensure!(
        r.failed_constraint_indices(&values)?.is_empty(),
        "original_o0_constraints_rejected"
    );
    Ok(values)
}

fn timed<T>(
    times: &mut BTreeMap<String, f64>,
    stage: &str,
    f: impl FnOnce() -> Result<T>,
) -> Result<T> {
    let start = Instant::now();
    let result = f();
    *times.entry(stage.to_owned()).or_default() += start.elapsed().as_secs_f64();
    result
}

/// R1CS/SYM carry wire names, not source-statement ownership. Report the common
/// enclosing instance of all named wires and explicitly label that limitation.
fn constraint_location(r: &R1cs, sym: &SymbolTable, index: usize) -> Value {
    let c = &r.constraints[index];
    let wires =
        c.a.keys()
            .chain(c.b.keys())
            .chain(c.c.keys())
            .copied()
            .filter(|w| *w != 0)
            .collect::<BTreeSet<_>>();
    let mut paths = Vec::new();
    let mut missing = Vec::new();
    for w in wires {
        let names = sym.wire_to_names.get(w as usize);
        if let Some(names) = names.filter(|n| !n.is_empty()) {
            paths.extend(names.iter().map(|n| split_instance(n).0.to_owned()));
        } else {
            missing.push(w);
        }
    }
    let mut common = paths
        .first()
        .map(|p| p.split('.').collect::<Vec<_>>())
        .unwrap_or_default();
    for path in &paths[1..] {
        let n = common
            .iter()
            .copied()
            .zip(path.split('.'))
            .take_while(|(a, b)| a == b)
            .count();
        common.truncate(n);
    }
    serde_json::json!({"first_failed_constraint_index":index,"index_base":0,
        "component_path":if missing.is_empty() && !common.is_empty() {Some(common.join("."))} else {None},
        "component_path_basis":"common_enclosing_instance_of_constraint_wire_aliases; not source statement ownership",
        "wire_component_paths":paths,"unmapped_wires":missing})
}

fn aligned_outcome(l1: Option<bool>, log: &str) -> Value {
    match l1 {
        Some(true) => serde_json::json!({"reason":"output_differs","violation":true}),
        Some(false) => serde_json::json!({"reason":"outputs_equal","violation":false}),
        None => {
            // Generated Circom runtime errors contain both the assertion message
            // and its template/line context. Arbitrary nonzero Node exits do not.
            let assertion = log.contains("Error: Assert Failed.")
                && log.contains("Error in template")
                && log.contains("line:");
            let infrastructure = [
                "ENOENT",
                "MODULE_NOT_FOUND",
                "SyntaxError",
                "out of memory",
                "Not all inputs have been set",
                "Too many values",
                "Signal not found",
            ]
            .iter()
            .any(|s| log.contains(s));
            if assertion && !infrastructure {
                serde_json::json!({"reason":"honest_aborted","violation":true,"abort_evidence":"circom_assert_with_template_and_line"})
            } else {
                serde_json::json!({"reason":"unknown","violation":null,"detail":"generator_failure_not_confirmed_as_assert"})
            }
        }
    }
}

pub(super) fn class_diagnostic(state: &State, class: &ClassResult) {
    if !state.options.aligned_diagnostics {
        return;
    }
    let records = state.records.borrow();
    let direct = records
        .iter()
        .filter(|r| r["method"] == "constraint_witness" && r["site"] == class.representative)
        .collect::<Vec<_>>();
    let reached = direct.iter().any(|r| r["status"] == "reached");
    let synth = class.synthesis.as_ref();
    let hint_failed = synth.is_some_and(|s| {
        s.b_outcome.as_deref() == Some("model_not_reproduced")
            || s.cause_before_budget.as_deref() == Some("synthesis_model_not_reproduced")
    });
    let repair_model = synth.is_some_and(|s| {
        s.repair
            .iter()
            .chain(s.injection.iter())
            .any(|r| r.solves.iter().any(|s| s.outcome.starts_with("sat")))
    });
    let model_present = !direct.is_empty() || hint_failed || repair_model;
    let failures = direct
        .iter()
        .filter_map(|r| r.get("failure_diagnostic").cloned())
        .collect::<Vec<_>>();
    let seconds: f64 = direct.iter().filter_map(|r| r["seconds"].as_f64()).sum();
    let row = serde_json::json!({"kind":"direct_class_diagnostic","site":class.representative,
        "direct_reached":reached,"model_present":model_present,
        "model_scope":"J lifting solver model; S candidate is already supplied",
        "no_solver_model":!model_present,"model_hint_realization_failed":hint_failed,
        "legacy_reason":class.reason,"cause_before_budget":synth.and_then(|s|s.cause_before_budget.as_ref()),
        "failure_diagnostics":failures,"direct_seconds":seconds,
        "not_attempted_reason":if direct.is_empty() {Some(if model_present {"model_without_completion_snapshot"} else {"no_completion_model_observed"})} else {None}});
    drop(records);
    state.push(row);
}
fn role(r: &R1cs, wire: usize) -> u8 {
    let first = 1 + r.shape.public_outputs;
    if (first..first + r.shape.public_inputs).contains(&wire) {
        1
    } else if (first + r.shape.public_inputs
        ..first + r.shape.public_inputs + r.shape.private_inputs)
        .contains(&wire)
    {
        2
    } else {
        0
    }
}
/// Every live O1 alias must exist in O0 and agree; no missing value is synthesized.
fn map_o1(
    r0: &R1cs,
    s0: &SymbolTable,
    r1: &R1cs,
    s1: &SymbolTable,
    values: &[BigUint],
) -> Result<Vec<BigUint>> {
    ensure!(r0.prime == r1.prime, "field_mapping_mismatch");
    ensure!(
        r0.shape.public_inputs == r1.shape.public_inputs
            && r0.shape.private_inputs == r1.shape.private_inputs
            && r0.shape.public_outputs == r1.shape.public_outputs,
        "interface_mapping_mismatch"
    );
    let first0 = 1 + r0.shape.public_outputs;
    let count = r0.shape.public_inputs + r0.shape.private_inputs;
    let names = main_signals(r0, s0, first0, count)?;
    let mut mapped_inputs = BTreeSet::new();
    for (offset, name) in names.iter().enumerate() {
        let w1 = s1
            .by_name
            .get(name)
            .and_then(|s| usize::try_from(s.wire).ok())
            .with_context(|| format!("input_mapping_missing:{name}"))?;
        ensure!(
            role(r0, first0 + offset) == role(r1, w1),
            "input_role_mapping_mismatch:{name}"
        );
        ensure!(
            mapped_inputs.insert(w1),
            "input_mapping_not_bijective:{name}"
        );
    }
    ensure!(mapped_inputs.len() == count, "input_mapping_incomplete");
    let mut mapped = vec![BigUint::one()];
    for wire in 1..r1.shape.wires {
        let names = s1
            .wire_to_names
            .get(wire)
            .context("o1_wire_mapping_missing")?;
        ensure!(!names.is_empty(), "o1_wire_mapping_missing:{wire}");
        let mut agreed: Option<BigUint> = None;
        for name in names {
            let w0 = s0
                .by_name
                .get(name)
                .and_then(|s| usize::try_from(s.wire).ok())
                .with_context(|| format!("o0_alias_mapping_missing:{name}"))?;
            let v = values.get(w0).context("o0_wire_mapping_missing")?;
            ensure!(
                agreed.as_ref().is_none_or(|old| old == v),
                "alias_values_disagree:{name}"
            );
            agreed = Some(v.clone());
        }
        mapped.push(agreed.context("o1_wire_mapping_missing")?);
    }
    r1.validate_assignment(&mapped)?;
    ensure!(
        r1.failed_constraint_indices(&mapped)?.is_empty(),
        "original_o1_constraints_rejected"
    );
    Ok(mapped)
}
fn exact_goal(context: &EvalContext, site: &str, values: &[BigUint]) -> Result<()> {
    for (name, expected) in context.candidate {
        let suffix = name
            .strip_prefix("main.")
            .context("candidate_name_not_main")?;
        let name = format!("{site}.{suffix}");
        let wire = context
            .entry_o0_sym
            .by_name
            .get(&name)
            .and_then(|s| usize::try_from(s.wire).ok())
            .with_context(|| format!("goal_mapping_missing:{name}"))?;
        ensure!(
            values.get(wire) == Some(expected),
            "exact_candidate_goal_not_met:{name}"
        );
    }
    Ok(())
}

pub(super) fn capture(context: &EvalContext, site: &str, snapshot: &Snapshot, ledger: &mut Ledger) {
    let id = context.boost.records.borrow().len();
    let folder = context.raw.join(format!("constraint-witness-{id:05}"));
    let started = Instant::now();
    let mut times = BTreeMap::new();
    let mut phase = "completion";
    let mut failed_location = Value::Null;
    let outcome = (|| -> Result<Value> {
        fs::create_dir_all(&folder)?;
        let strings = |map: &BTreeMap<usize, BigUint>| {
            map.iter()
                .map(|(w, v)| (w.to_string(), v.to_string()))
                .collect::<BTreeMap<_, _>>()
        };
        write_json(
            &folder.join("query.json"),
            &serde_json::json!({"query":strings(&snapshot.query), "scope":strings(&snapshot.scope), "start":snapshot.start.iter().map(ToString::to_string).collect::<Vec<_>>()}),
        )?;
        let completed = timed(&mut times, "completion", || {
            assemble(context.entry_o0_r1cs, snapshot)
        })?;
        phase = "o0_check";
        timed(&mut times, "o0_check", || {
            let failed = context
                .entry_o0_r1cs
                .failed_constraint_indices(&completed)?;
            if let Some(&index) = failed.first() {
                if context.boost.options.aligned_diagnostics {
                    failed_location =
                        constraint_location(context.entry_o0_r1cs, context.entry_o0_sym, index);
                }
                bail!("original_o0_constraints_rejected");
            }
            Ok(())
        })?;
        phase = "goal";
        timed(&mut times, "goal", || exact_goal(context, site, &completed))?;
        let o0 = folder.join("completed-o0.wtns");
        wtns::write_wtns(&o0, &context.entry_o0_r1cs.prime, &completed)?;
        phase = "snarkjs_o0";
        ensure!(
            timed(&mut times, "snarkjs_o0", || snarkjs_check(
                context.tools,
                &context.original_o0.r1cs,
                &o0,
                ledger
            ))? == "correct",
            "o0_external_check_unresolved"
        );
        phase = "o1_mapping";
        let mapped = timed(&mut times, "o1_mapping", || {
            map_o1(
                context.entry_o0_r1cs,
                context.entry_o0_sym,
                context.entry_r1cs,
                context.entry_sym,
                &completed,
            )
        })?;
        let final_path = folder.join("constraint-witness.wtns");
        wtns::write_wtns(&final_path, &context.entry_r1cs.prime, &mapped)?;
        // Check the serialized file too; no generator ever writes this path.
        let persisted = wtns::read_wtns(&final_path, &context.entry_r1cs.prime)?;
        ensure!(
            persisted == mapped
                && context
                    .entry_r1cs
                    .failed_constraint_indices(&persisted)?
                    .is_empty(),
            "serialized_witness_rejected"
        );
        phase = "snarkjs_o1";
        ensure!(
            timed(&mut times, "snarkjs_o1", || snarkjs_check(
                context.tools,
                &context.original.r1cs,
                &final_path,
                ledger
            ))? == "correct",
            "o1_external_check_unresolved"
        );
        let first = 1 + context.entry_r1cs.shape.public_outputs;
        let count =
            context.entry_r1cs.shape.public_inputs + context.entry_r1cs.shape.private_inputs;
        let names = main_signals(context.entry_r1cs, context.entry_sym, first, count)?;
        let leaves = names
            .iter()
            .enumerate()
            .map(|(i, n)| {
                (
                    n.trim_start_matches("main.").to_owned(),
                    mapped[first + i].clone(),
                )
            })
            .collect::<Vec<_>>();
        let input = folder.join("input.json");
        write_json(&input, &build_input(&leaves)?)?;
        // Only the honest comparator is regenerated, in a distinct file.
        phase = "honest_calculation";
        let honest = timed(&mut times, "honest_calculation", || {
            generate_witness(
                context.tools,
                context.original,
                &input,
                &folder.join("honest.wtns"),
                &context.entry_r1cs.prime,
                ledger,
                "constraint_witness",
                "honest comparator",
            )
        })?;
        let (l1, influence) = match honest {
            Some(honest) => {
                context.entry_r1cs.validate_assignment(&honest)?;
                ensure!(
                    context
                        .entry_r1cs
                        .failed_constraint_indices(&honest)?
                        .is_empty(),
                    "honest_comparator_rejected"
                );
                ensure!(
                    honest[first..first + count] == mapped[first..first + count],
                    "all_inputs_differ"
                );
                let different = honest[1..first] != mapped[1..first];
                (
                    Some(different),
                    if different {
                        "output_differs"
                    } else {
                        "no_top_output_effect"
                    },
                )
            }
            None => (None, "honest_comparator_aborted"),
        };
        let mut row = serde_json::json!({"status":"reached", "scope":"exact_candidate_and_recorded_input_pins", "l1":l1, "influence":influence, "witness":final_path, "witness_sha256":sha256_file(&final_path)?, "o0_witness":o0, "rust":"correct", "snarkjs":"correct"});
        if context.boost.options.aligned_diagnostics {
            let log = fs::read_to_string(folder.join("honest.log")).unwrap_or_default();
            row["aligned"] = aligned_outcome(l1, &log);
            row["entrypoint_public_outputs"] = context.entry_r1cs.shape.public_outputs.into();
        }
        Ok(row)
    })();
    let mut row = match outcome {
        Ok(row) => row,
        Err(error) => {
            let reason = format!("{error:#}");
            serde_json::json!({"status":if reason.contains("constraints_rejected") || reason.contains("goal_not_met") || reason.contains("scope_not_met") {"rejected"} else {"unknown"}, "reason":reason, "l1":null})
        }
    };
    if context.boost.options.aligned_diagnostics {
        row["stage_seconds"] = serde_json::to_value(&times).unwrap_or_default();
        row["diagnostic_folder"] = folder.to_string_lossy().into_owned().into();
        if row["status"] != "reached" {
            row["aligned"] =
                serde_json::json!({"reason":"unknown","violation":null,"detail":row["reason"]});
            row["failure_diagnostic"] = serde_json::json!({"stage":phase,
                "category":match phase {
                    "o0_check" => "original_constraints_violated",
                    "goal" => "goal_not_met",
                    "snarkjs_o0" | "snarkjs_o1" => "original_verification_tool_failure",
                    "o1_mapping" => "o1_mapping_or_constraints_failure",
                    "honest_calculation" => "honest_comparator_failure",
                    _ => "completion_shape_or_input_scope_failure",
                },"constraint":failed_location,"detail":row["reason"]});
        }
    }
    row["method"] = "constraint_witness".into();
    row["site"] = site.into();
    row["origin"] = snapshot.origin.clone().into();
    row["seconds"] = started.elapsed().as_secs_f64().into();
    context.boost.push(row);
}

fn mapping_row(
    candidate: &str,
    actual: &str,
    expected: &BigUint,
    sym: &SymbolTable,
    values: &[BigUint],
) -> Value {
    let wire = sym
        .by_name
        .get(actual)
        .and_then(|s| usize::try_from(s.wire).ok());
    let value = wire.and_then(|w| values.get(w));
    serde_json::json!({"candidate_signal":candidate,"entry_signal":actual,"wire":wire,
        "expected":expected.to_string(),"actual":value.map(ToString::to_string),
        "match":value.map(|v|v==expected),"mismatch_signal":if value == Some(expected) {None} else {Some(actual)},
        "reason":if value.is_none() {"mapping_missing"} else if value != Some(expected) {"value_mismatch"} else {"matched"}})
}

pub(super) fn diagnose(
    context: &EvalContext,
    site: &str,
    space: &str,
    sym: &SymbolTable,
    values: &[BigUint],
) {
    let mut instance_signals: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    for name in context.candidate.keys() {
        let (instance, leaf) = split_instance(name);
        instance_signals
            .entry(instance.to_owned())
            .or_default()
            .insert(leaf_base(leaf).to_owned());
    }
    let mut resolved = BTreeMap::new();
    // Resolve component templates by their signal sets, as the original rewrite planner does.
    for suffix in &context.plan.hint_suffixes {
        let candidate_name = format!("main.{suffix}");
        let (instance, leaf) = split_instance(&candidate_name);
        let result = resolve_instance(
            instance,
            &instance_signals,
            context.templates,
            context.sources,
            context.component_main_template.as_deref(),
            &mut resolved,
        );
        match result {
            Ok(template) => {
                let entry_instance = format!("{site}{}", instance.strip_prefix("main").unwrap_or(instance));
                let guards = context.candidate.iter().filter(|(n,_)| {
                    let (i,l) = split_instance(n);
                    i == instance && template.inputs.contains(leaf_base(l))
                }).map(|(name,value)| mapping_row(name,&format!("{entry_instance}.{}",split_instance(name).1),value,sym,values)).collect::<Vec<_>>();
                let statements = hint_statements(&context.sources[&template.file],template).map(|(s,_)| s.into_iter().filter(|s|s.signal==leaf_base(leaf)).map(|s|serde_json::json!({"file":template.file,"line":s.line,"signal":s.signal,"indices":s.indices,"leaf_indices":leaf_indices(leaf)})).collect::<Vec<_>>()).unwrap_or_default();
                context.boost.push(serde_json::json!({"kind":"injection_diagnostic","site":site,"space":space,"instance":entry_instance,"template":template.name,"statements":statements,"guards":guards,"hint":context.candidate.get(&candidate_name).map(|v|mapping_row(&candidate_name,&format!("{site}.{suffix}"),v,sym,values))}));
            }
            Err(error) => context.boost.push(serde_json::json!({"kind":"injection_diagnostic","site":site,"space":space,"signal":suffix,"error":error.detail})),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn post_limit_option_keeps_legacy_cache_key() -> Result<()> {
        let baseline = BoostOptions::default();
        let probe = BoostOptions {
            post_limit_probe_site: Some("main.part".to_owned()),
            ..BoostOptions::default()
        };
        assert!(!baseline.active());
        assert!(!probe.active());
        assert_eq!(serde_json::to_vec(&baseline)?, serde_json::to_vec(&probe)?);
        Ok(())
    }

    #[test]
    fn aligned_does_not_promote_tool_failures() {
        for log in [
            "",
            "Error: ENOENT",
            "Error: Assert Failed.",
            "Not all inputs have been set",
            "Error: Assert Failed. Error in template Main line: 2 MODULE_NOT_FOUND",
        ] {
            assert_eq!(aligned_outcome(None, log)["reason"], "unknown");
        }
    }

    // Real Circom O0/O1 + real solver + both original-R1CS checkers, <= 3 constraints.
    #[test]
    fn synthetic_constraint_completion_and_injection_diagnostics() -> Result<()> {
        let temporary = tempfile::tempdir()?;
        let kept = temporary.keep();
        let root = kept.as_path();
        let tools = Tools {
            circom: resolve_executable(Path::new("circom"))?,
            node: resolve_executable(Path::new("node"))?,
            snarkjs: resolve_executable(Path::new("snarkjs"))?,
            verified_digests: None,
        };
        let z3 = resolve_executable(Path::new("z3"))?;
        let mut ledger = Ledger {
            steps: Vec::new(),
            site: Some("main".into()),
        };
        let mut results = Vec::new();
        for (case, output) in [
            ("model_preserved", "q"),
            ("no_top_effect", "a*a"),
            ("zero_outputs", "q"),
            ("honest_assert", "q"),
        ] {
            let folder = root.join(case);
            fs::create_dir_all(&folder)?;
            let file = folder.join("main.circom");
            let source = format!("pragma circom 2.2.3;\ntemplate Main() {{ signal input a; signal input d; signal output out; signal q; signal h; h <-- a; q <-- a / d; q*d === a; out <== {output}; }}\ncomponent main = Main();\n");
            let source = if case == "zero_outputs" {
                source
                    .replace("signal output out;", "")
                    .replace("out <== q;", "")
            } else if case == "honest_assert" {
                source.replace("q*d === a;", "q*d === a; assert(d == 0);")
            } else {
                source
            };
            fs::write(&file, &source)?;
            let c0 = compile(
                &tools,
                &file,
                &folder.join("o0"),
                &folder,
                &[],
                true,
                true,
                &mut ledger,
                None,
            )?;
            let c1 = compile(
                &tools,
                &file,
                &folder.join("o1"),
                &folder,
                &[],
                false,
                true,
                &mut ledger,
                None,
            )?;
            let r0 = R1cs::parse(&fs::read(&c0.r1cs)?)?;
            let r1 = R1cs::parse(&fs::read(&c1.r1cs)?)?;
            ensure!(r0.shape.constraints <= 1000 && r1.shape.constraints <= 1000);
            let s0 = SymbolTable::parse(&fs::read(&c0.sym)?, &r0)?;
            let s1 = SymbolTable::parse(&fs::read(&c1.sym)?, &r1)?;
            let input = serde_json::json!({"a":"0","d":"0"});
            let input_path = folder.join("input.json");
            write_json(&input_path, &input)?;
            let start = generate_witness(
                &tools,
                &c0,
                &input_path,
                &folder.join("start.wtns"),
                &r0.prime,
                &mut ledger,
                "test",
                "start",
            )?
            .context("synthetic starting witness aborted")?;
            let wire = |n: &str| usize::try_from(s0.by_name[n].wire).unwrap();
            let q = wire("main.q");
            let mut targets = BTreeMap::from([(q, BigUint::one())]);
            if case == "honest_assert" {
                targets.insert(wire("main.d"), BigUint::one());
                targets.insert(wire("main.a"), BigUint::one());
            }
            // Encode all original constraints and request every wire, so the snapshot is an actual model.
            let model = repair::boost_test_model(&r0, &targets, &folder)?;
            let snapshot = Snapshot {
                start: start.clone(),
                query: model,
                scope: BTreeMap::from([
                    (
                        wire("main.a"),
                        if case == "honest_assert" {
                            BigUint::one()
                        } else {
                            BigUint::zero()
                        },
                    ),
                    (
                        wire("main.d"),
                        if case == "honest_assert" {
                            BigUint::one()
                        } else {
                            BigUint::zero()
                        },
                    ),
                ]),
                origin: "synthetic_real_solver".into(),
            };
            // Old repair drops model values inside a protected candidate site.
            let old_changed = repair::boost_test_projection(
                &r0,
                &s0,
                &source,
                &file,
                &input,
                &start,
                &snapshot.query,
            )?;
            if case != "honest_assert" {
                assert!(!old_changed);
            }
            assert_eq!(start[q], BigUint::zero());
            let completed = complete(&r0, &snapshot)?;
            let candidate = s0
                .by_name
                .iter()
                .filter_map(|(n, s)| {
                    usize::try_from(s.wire)
                        .ok()
                        .map(|w| (n.clone(), completed[w].clone()))
                })
                .collect();
            let templates = parse_templates(&file, &source)?;
            let sources = BTreeMap::from([(file.clone(), source.clone())]);
            let eq0 = EqualityIndex::build(&r0);
            let eq1 = EqualityIndex::build(&r1);
            let plan = RewritePlan {
                edits: BTreeMap::new(),
                records: Vec::new(),
                hint_suffixes: BTreeSet::from(["h".into()]),
                propagated: 0,
            };
            let state = State::new(BoostOptions {
                constraint_witness: true,
                injection_diagnostics: true,
                aligned_diagnostics: true,
                ..Default::default()
            });
            let mut context = EvalContext {
                boost: &state,
                component_main_template: Some("Main".into()),
                sites: &[],
                component_inputs: &[],
                component_outputs: &[],
                range_index: None,
                candidate: &candidate,
                plan: &plan,
                base_input: &input,
                bindings: &eq0,
                original_bindings: &eq1,
                entry_o0_sym: &s0,
                rewrite_structure: None,
                entry_o0_r1cs: &r0,
                o0_constraint_index: None,
                entry_r1cs: &r1,
                entry_sym: &s1,
                original: &c1,
                original_o0: &c0,
                hinted: &c1,
                hint_tree: None,
                hinted_o0: None,
                constraint_index: None,
                tools: &tools,
                z3: Some(&z3),
                raw: &folder,
                templates: &templates,
                sources: &sources,
                property: Property::Tcct,
                source_root: &folder,
                libraries: &[],
                cache: None,
                instance_store: None,
                entry_key: String::new(),
                request_id: case.into(),
                public_inputs: BTreeSet::new(),
                entry_relative: PathBuf::from("main.circom"),
                entry_main_template: Some("Main".into()),
                sweep_remaining: Duration::ZERO,
                repair_remaining: 6,
                repair_limit: 6,
                structure: None,
                class_witness: None,
            };
            if matches!(case, "model_preserved" | "honest_assert") {
                context.o0_constraint_index = Some(std::rc::Rc::new(
                    super::super::refute::constraint_index(&r0),
                ));
                let (probe_input, probe_target) = if case == "honest_assert" {
                    (serde_json::json!({"a":"1","d":"1"}), BigUint::one())
                } else {
                    (input.clone(), BigUint::zero())
                };
                repair::boost_test_post_limit_probe(
                    &context,
                    &folder.join("post-limit-fixture"),
                    "main",
                    probe_input,
                    vec![(q, probe_target)],
                );
                let summary: Value =
                    serde_json::from_slice(&fs::read(folder.join("post-limit-probe.json"))?)?;
                assert_eq!(
                    summary["status"],
                    if case == "honest_assert" {
                        "generator_aborted"
                    } else {
                        "o0_and_target_met"
                    }
                );
                let detail: Value = serde_json::from_slice(&fs::read(
                    folder.join("post-limit-fixture/post-limit-probe/post-limit-probe.json"),
                )?)?;
                if case == "model_preserved" {
                    assert_eq!(detail["full_completion"]["status"], "rejected");
                    assert_eq!(detail["full_completion"]["l1"], Value::Null);
                }
            }
            if matches!(case, "model_preserved" | "no_top_effect") {
                let (old_reached, old_repair) = repair::search(
                    &mut context,
                    repair::Start {
                        label: "synthetic_protected_site",
                        stage: "test",
                        input: input.clone(),
                        overrides: repair::Overrides::default(),
                        candidate_hints: false,
                        protected_site: Some("main".into()),
                        inputs_free: false,
                        pinned: snapshot.scope.keys().copied().collect(),
                    },
                    &repair::Requirement {
                        targets: vec![
                            (q, BigUint::one()),
                            (wire("main.out"), completed[wire("main.out")].clone()),
                        ],
                        predicate: None,
                    },
                    &folder.join("old-repair"),
                    &mut ledger,
                );
                assert!(
                    old_reached.is_none(),
                    "legacy repair unexpectedly reproduced the protected model"
                );
                assert_eq!(old_repair.outcome, "no_progress");
                let repair_captures = state
                    .records
                    .borrow()
                    .iter()
                    .filter(|r| r["origin"] == "repair_region")
                    .cloned()
                    .collect::<Vec<_>>();
                assert!(
                    repair_captures.iter().any(|r| r["status"] == "reached"),
                    "{repair_captures:?}"
                );
                results.push(serde_json::json!({"case":format!("{case}_repair_hook"),"old_repair":old_repair,"new":repair_captures}));
            }
            capture(&context, "main", &snapshot, &mut ledger);
            let valid = state.records.borrow().last().unwrap().clone();
            assert_eq!(valid["status"], "reached", "{valid}");
            if case == "honest_assert" {
                assert!(valid["l1"].is_null(), "legacy l1 must stay null: {valid}");
                assert_eq!(valid["aligned"]["reason"], "honest_aborted", "{valid}");
            } else {
                assert_eq!(valid["l1"], case == "model_preserved", "{valid}");
                assert_eq!(
                    valid["aligned"]["reason"],
                    if case == "model_preserved" {
                        "output_differs"
                    } else {
                        "outputs_equal"
                    }
                );
            }
            if case == "zero_outputs" {
                assert_eq!(r1.shape.public_outputs, 0);
                assert_eq!(valid["aligned"]["reason"], "outputs_equal");
            }
            assert!(valid["stage_seconds"]["honest_calculation"]
                .as_f64()
                .is_some());
            results.push(serde_json::json!({"case":case,"constraints":r0.shape.constraints,"old_projection_changed":old_changed,"new":valid}));
            if case == "model_preserved" {
                let mut broken = Snapshot {
                    start: start.clone(),
                    query: snapshot.query.clone(),
                    scope: BTreeMap::new(),
                    origin: "broken_original".into(),
                };
                broken.query.insert(wire("main.d"), BigUint::one());
                capture(&context, "main", &broken, &mut ledger);
                let rejected = state.records.borrow().last().unwrap().clone();
                assert_eq!(rejected["status"], "rejected", "{rejected}");
                assert!(rejected["failure_diagnostic"]["constraint"]
                    ["first_failed_constraint_index"]
                    .as_u64()
                    .is_some());
                assert_eq!(
                    rejected["failure_diagnostic"]["constraint"]["component_path"],
                    "main"
                );
                results.push(serde_json::json!({"case":"original_rejected","new":rejected}));
                let mut missing = SymbolTable::parse(&fs::read(&c0.sym)?, &r0)?;
                missing.by_name.remove("main.out");
                context.entry_o0_sym = &missing;
                capture(&context, "main", &snapshot, &mut ledger);
                let unknown = state.records.borrow().last().unwrap().clone();
                assert_eq!(unknown["status"], "unknown", "{unknown}");
                results.push(serde_json::json!({"case":"missing_mapping","new":unknown}));
                context.entry_o0_sym = &s0;
                let mut different = start.clone();
                different[wire("main.a")] = BigUint::one();
                diagnose(&context, "main", "O0", &s0, &different);
                let diagnostic = state.records.borrow().last().unwrap().clone();
                assert!(
                    diagnostic["guards"]
                        .as_array()
                        .unwrap()
                        .iter()
                        .any(|g| g["reason"] == "value_mismatch"),
                    "{diagnostic}"
                );
                results.push(serde_json::json!({"case":"guard_mismatch","new":diagnostic}));
                let mut missing_input = SymbolTable::parse(&fs::read(&c0.sym)?, &r0)?;
                missing_input.by_name.remove("main.a");
                diagnose(&context, "main", "O1", &missing_input, &start);
                let diagnostic = state.records.borrow().last().unwrap().clone();
                assert!(
                    diagnostic["guards"]
                        .as_array()
                        .unwrap()
                        .iter()
                        .any(|g| g["reason"] == "mapping_missing"),
                    "{diagnostic}"
                );
                results.push(serde_json::json!({"case":"guard_mapping_missing","new":diagnostic}));
                // Independently test alias disagreement and missing O1 wire coverage.
                let mut aliases = SymbolTable::parse(&fs::read(&c1.sym)?, &r1)?;
                aliases.wire_to_names[1].push("main.a".into());
                assert!(map_o1(&r0, &s0, &r1, &aliases, &completed).is_err());
                aliases.wire_to_names[1].clear();
                assert!(map_o1(&r0, &s0, &r1, &aliases, &completed).is_err());
                context.entry_sym = &aliases;
                capture(&context, "main", &snapshot, &mut ledger);
                let unknown = state.records.borrow().last().unwrap().clone();
                assert_eq!(unknown["status"], "unknown", "{unknown}");
                assert!(unknown["reason"]
                    .as_str()
                    .unwrap()
                    .contains("o1_wire_mapping_missing"));
                results.push(serde_json::json!({"case":"o1_mapping_missing","new":unknown}));
                context.entry_sym = &s1;
            }
        }
        if let Some(path) = std::env::var_os("J_BOOST_TEST_RECEIPT") {
            write_json(Path::new(&path), &serde_json::json!({"cases":results}))?;
        }
        Ok(())
    }
}
