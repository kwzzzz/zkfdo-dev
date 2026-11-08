//! L-05 step 3, and the witness search of step 2: when a generator aborts, or computes other
//! values than a requirement needs, locate the failing constraint instances and re-choose
//! `<--` hint values in a small cone.
//!
//! Localization uses a diagnostic copy of the sources in which each aborting `===` or `assert`
//! statement is blanked out, so the generator runs to the end. Its witness is mapped by signal
//! name onto the original O0 R1CS, and the unsatisfied constraint indices name the failing
//! instances exactly. The copy only locates: every verdict still rests on a witness from a
//! generator whose O0 R1CS (and O1 R1CS and `.sym`) equal the original's, checked against the
//! original R1CS by both checkers.
//!
//! A repair cone holds the failing instance's own constraints, the links that assign its
//! inputs, and, if those alone do not admit a solution, the shortest upstream constraint paths
//! from its boundary to the nearest hint-assigned wires (or free entrypoint inputs, where
//! allowed). Every other wire keeps its current value, and z3 proposes values; changed hint
//! values are injected as in L-04, keyed by their instance inputs. An unsatisfiable repair cone
//! is never an exclusion: it fixes values that the candidate does not determine.
//!
//! "Upstream" follows circom's signal semantics, not template names: an input signal of a
//! component is assigned only by its parent, so a path never enters an input signal through the
//! parent's link (that link computes it), and leaves an input signal only through that link.

use std::{
    collections::{BTreeMap, BTreeSet, VecDeque},
    fmt::Write as _,
    fs,
    path::{Path, PathBuf},
    time::{Duration, Instant},
};

use anyhow::{bail, ensure, Context, Result};
use num_bigint::BigUint;
use num_traits::{One, Zero};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use super::super::r1cs::{LinearCombination, R1cs, SymbolTable};
use super::condition::{lessthan_holds, natural_key, TemplateNames};
use super::source::{check_statement_at_line, hint_statements, TemplateDef};
use super::synth::{constraint_wires, parse_values, residual};
use super::{
    class_pattern, classify_abort, compile, display_relative, generate_witness, leaf_base,
    plan_rewrites, set_input_leaf, sha256_file, split_instance, write_edits_workspace, write_json,
    Compiled, EvalContext, Ledger, RewriteRecord,
};

/// Source edits in original byte coordinates: (start, end, replacement) per file.
pub(crate) type Edits = BTreeMap<PathBuf, Vec<(usize, usize, String)>>;

const MAX_ITERATIONS: usize = 6;
const MAX_BLANKED: usize = 6;
const MAX_SOLVES: usize = 6;
const PATH_DEPTH: usize = 24;
const PATH_VISITS: usize = 20_000;
const LEAVES_PER_START: usize = 3;
const REGION_CONSTRAINTS: usize = 2_000;
/// Most constraints a hint leaf may add to a repair cone when closed over its uses.
const LEAF_CLOSURE: usize = 200;
/// Wires used by more constraints than this (shared parameters) are never traversed.
pub(crate) const HUB_DEGREE: usize = 32;
pub(crate) const SOLVE_TIMEOUT: Duration = Duration::from_secs(10);

/// Hint values to inject, by O0 signal name, and the instance-input values that key them.
#[derive(Clone, Default)]
pub(crate) struct Overrides {
    pub(crate) rewrite: BTreeMap<String, BigUint>,
    pub(crate) keys: BTreeMap<String, BigUint>,
}

/// zkFuzz's `LessThan` condition broken at one entrypoint instance: O0 wires of `in[0]`,
/// `in[1]`, and `out`.
#[derive(Clone)]
pub(crate) struct Predicate {
    pub(crate) instance: String,
    pub(crate) wires: [usize; 3],
}

impl Predicate {
    pub(crate) fn holds(&self, witness: &[BigUint]) -> bool {
        let [in0, in1, out] = self.wires;
        !lessthan_holds(&witness[in0], &witness[in1], &witness[out])
    }
}

/// What a witness must show: the candidate's site values, and/or a broken `LessThan`.
#[derive(Clone, Default)]
pub(crate) struct Requirement {
    pub(crate) targets: Vec<(usize, BigUint)>,
    pub(crate) predicate: Option<Predicate>,
}

impl Requirement {
    fn met(&self, witness: &[BigUint]) -> bool {
        self.targets
            .iter()
            .all(|(wire, value)| &witness[*wire] == value)
            && self
                .predicate
                .as_ref()
                .is_none_or(|predicate| predicate.holds(witness))
    }
}

#[derive(Clone)]
pub(crate) struct Start {
    pub(crate) label: &'static str,
    /// Ledger stage for this search's steps.
    pub(crate) stage: &'static str,
    pub(crate) input: Value,
    pub(crate) overrides: Overrides,
    /// Carry the TCCT candidate's own site hints (the deviated generator).
    pub(crate) candidate_hints: bool,
    /// A site whose wires the repair must leave alone (it carries the candidate).
    pub(crate) protected_site: Option<String>,
    /// Whether entrypoint inputs other than `pinned` and shared ones may change.
    pub(crate) inputs_free: bool,
    pub(crate) pinned: BTreeSet<usize>,
}

pub(crate) struct Reached {
    pub(crate) input: Value,
    pub(crate) o0: Compiled,
    pub(crate) o1: Compiled,
    /// TCCT: the same injections without the candidate's site hints.
    pub(crate) comparator: Option<Compiled>,
    pub(crate) witness_o0: Vec<BigUint>,
    pub(crate) statements: usize,
    pub(crate) instances: usize,
}

#[derive(Debug, Serialize, Default, Clone, Deserialize)]
pub struct RepairRecord {
    pub start: String,
    pub iterations: usize,
    pub localizations: Vec<Localization>,
    pub solves: Vec<SolveRecord>,
    /// `reached`, `no_progress`, `cycle`, `iteration_limit`, or `error`.
    pub outcome: String,
    pub rewritten_statements: usize,
    pub injected_instances: usize,
    /// The `<--` statements rewritten outside the candidate's own hints (no values).
    pub rewritten: Vec<RewriteRecord>,
    pub changed_inputs: Vec<String>,
    pub note: Option<String>,
    pub error_kind: Option<String>,
}

#[derive(Debug, Serialize, Clone, Deserialize)]
pub struct Localization {
    pub iteration: usize,
    pub blanked_checks: Vec<BlankedCheck>,
    pub unsatisfied_constraints: usize,
    pub failing_instances: Vec<FailingGroup>,
}

#[derive(Debug, Serialize, Clone, PartialEq, Eq, Deserialize)]
pub struct BlankedCheck {
    pub template: String,
    pub file: String,
    pub line: usize,
    pub kind: String,
}

#[derive(Debug, Serialize, Clone, Deserialize)]
pub struct FailingGroup {
    /// Instance path with numeric indices replaced by `*`.
    pub pattern: String,
    pub instances: usize,
    pub representative: String,
    /// Unsatisfied O0 constraint indices in the representative (at most five).
    pub constraints: Vec<usize>,
}

#[derive(Debug, Serialize, Clone, Deserialize)]
pub struct SolveRecord {
    #[serde(default)]
    pub carry: String,
    #[serde(default)]
    pub carried_constraints: usize,
    #[serde(default)]
    pub carried_dropped: usize,
    pub iteration: usize,
    /// `abort`, `target`, or `predicate`.
    pub cause: String,
    pub region: String,
    pub with_paths: bool,
    pub unknowns: usize,
    pub constraints: usize,
    /// z3's answer (`sat`, `unsat`, `unknown`), or why no query was made.
    pub outcome: String,
    pub hints_changed: usize,
    pub inputs_changed: usize,
}

/// Signal roles from the sources: which signals are `<--` hints and which are inputs.
pub(crate) struct Structure<'a> {
    names: TemplateNames<'a>,
    sources: &'a BTreeMap<PathBuf, String>,
    by_template: BTreeMap<(PathBuf, usize), BTreeSet<String>>,
    by_instance: BTreeMap<String, (BTreeSet<String>, BTreeSet<String>)>,
}

impl<'a> Structure<'a> {
    pub(crate) fn new(
        sym: &SymbolTable,
        templates: &'a [TemplateDef],
        sources: &'a BTreeMap<PathBuf, String>,
        main_template: Option<String>,
    ) -> Self {
        Self {
            names: TemplateNames::new(sym, templates, sources, main_template),
            sources,
            by_template: BTreeMap::new(),
            by_instance: BTreeMap::new(),
        }
    }

    /// (hint-assigned signal bases, input signal bases) common to every possible definition.
    fn roles(&mut self, instance: &str) -> &(BTreeSet<String>, BTreeSet<String>) {
        if !self.by_instance.contains_key(instance) {
            let mut hints: Option<BTreeSet<String>> = None;
            let mut inputs: Option<BTreeSet<String>> = None;
            for definition in self.names.definitions(instance) {
                let sources = self.sources;
                let assigned = self
                    .by_template
                    .entry((definition.file.clone(), definition.body_start))
                    .or_insert_with(|| {
                        hint_statements(&sources[&definition.file], definition)
                            .map(|(statements, _)| {
                                statements.into_iter().map(|hint| hint.signal).collect()
                            })
                            .unwrap_or_default()
                    })
                    .clone();
                hints = Some(match hints {
                    None => assigned,
                    Some(previous) => previous.intersection(&assigned).cloned().collect(),
                });
                inputs = Some(match inputs {
                    None => definition.inputs.clone(),
                    Some(previous) => previous.intersection(&definition.inputs).cloned().collect(),
                });
            }
            self.by_instance.insert(
                instance.to_owned(),
                (hints.unwrap_or_default(), inputs.unwrap_or_default()),
            );
        }
        &self.by_instance[instance]
    }

    pub(crate) fn is_hint(&mut self, name: &str) -> bool {
        let (instance, leaf) = split_instance(name);
        let base = leaf_base(leaf).to_owned();
        self.roles(instance).0.contains(&base)
    }

    pub(crate) fn is_input(&mut self, name: &str) -> bool {
        let (instance, leaf) = split_instance(name);
        let base = leaf_base(leaf).to_owned();
        instance != "main" && self.roles(instance).1.contains(&base)
    }
}

/// Everything a search reads from the request.
#[derive(Clone, Copy)]
struct View<'c> {
    r1cs: &'c R1cs,
    sym: &'c SymbolTable,
    index: &'c [Vec<usize>],
    first_input: usize,
    inputs: usize,
}

impl View<'_> {
    fn name(&self, wire: usize) -> &str {
        self.sym.wire_to_names[wire]
            .first()
            .map(String::as_str)
            .unwrap_or("")
    }

    fn is_main_input(&self, wire: usize) -> bool {
        (self.first_input..self.first_input + self.inputs).contains(&wire)
    }

    fn is_hub(&self, wire: usize) -> bool {
        self.index[wire].len() > HUB_DEGREE
    }

    fn within(&self, wire: usize, instance: &str) -> bool {
        self.name(wire)
            .strip_prefix(instance)
            .is_some_and(|rest| rest.starts_with('.'))
    }

    fn wires_under(&self, instance: &str) -> BTreeSet<usize> {
        self.sym
            .by_name
            .range(format!("{instance}.")..format!("{instance}/"))
            .filter_map(|(_, symbol)| usize::try_from(symbol.wire).ok())
            .collect()
    }
}

/// The failing instance: the deepest instance that contains every wire of the constraint.
fn constraint_instance(view: &View, constraint: usize) -> String {
    let owners = constraint_wires(&view.r1cs.constraints[constraint])
        .into_iter()
        .filter(|wire| *wire != 0)
        .map(|wire| segments(split_instance(view.name(wire)).0))
        .collect::<Vec<_>>();
    let Some(first) = owners.first() else {
        return String::new();
    };
    let mut common = first.clone();
    for owner in &owners[1..] {
        let shared = common
            .iter()
            .zip(owner)
            .take_while(|(left, right)| left == right)
            .count();
        common.truncate(shared);
    }
    common.join(".")
}

fn segments(path: &str) -> Vec<String> {
    let mut parts = Vec::new();
    let mut depth = 0usize;
    let mut current = String::new();
    for character in path.chars() {
        match character {
            '[' => depth += 1,
            ']' => depth = depth.saturating_sub(1),
            '.' if depth == 0 => {
                parts.push(std::mem::take(&mut current));
                continue;
            }
            _ => {}
        }
        current.push(character);
    }
    if !current.is_empty() {
        parts.push(current);
    }
    parts
}

/// The constraints of an instance and the links that assign its inputs, with the outside
/// wires those links read. Links that only use the instance's outputs are left out: their
/// other wires are computed from the instance, not the other way round.
struct Region {
    wires: BTreeSet<usize>,
    constraints: BTreeSet<usize>,
    boundary: BTreeSet<usize>,
}

fn instance_region(view: &View, structure: &mut Structure, instance: &str) -> Option<Region> {
    let wires = view.wires_under(instance);
    let inputs = wires
        .iter()
        .copied()
        .filter(|wire| {
            let name = view.name(*wire);
            split_instance(name).0 == instance && structure.is_input(name)
        })
        .collect::<BTreeSet<_>>();
    let mut constraints = BTreeSet::new();
    let mut boundary = BTreeSet::new();
    for wire in &wires {
        for &position in &view.index[*wire] {
            let touched = constraint_wires(&view.r1cs.constraints[position]);
            let outside = touched
                .iter()
                .copied()
                .filter(|other| *other != 0 && !wires.contains(other))
                .collect::<Vec<_>>();
            if outside.is_empty() || touched.iter().any(|other| inputs.contains(other)) {
                constraints.insert(position);
                boundary.extend(outside);
            }
        }
        if constraints.len() > REGION_CONSTRAINTS {
            return None;
        }
    }
    Some(Region {
        wires,
        constraints,
        boundary,
    })
}

/// For a failing constraint whose instance is too broad for [`instance_region`] (for example
/// `main`): the hint wires it reads are the unknowns, with every constraint that uses them;
/// its other wires are the boundary.
fn constraint_region(
    view: &View,
    structure: &mut Structure,
    failing: &[usize],
    protected: Option<&str>,
) -> Region {
    let touched = failing
        .iter()
        .flat_map(|position| constraint_wires(&view.r1cs.constraints[*position]))
        .filter(|wire| *wire != 0)
        .collect::<BTreeSet<_>>();
    let wires = touched
        .iter()
        .copied()
        .filter(|wire| {
            !view.is_main_input(*wire)
                && !protected.is_some_and(|site| view.within(*wire, site))
                && structure.is_hint(view.name(*wire))
        })
        .collect::<BTreeSet<_>>();
    let mut constraints = failing.iter().copied().collect::<BTreeSet<_>>();
    for wire in &wires {
        constraints.extend(view.index[*wire].iter().copied());
    }
    Region {
        boundary: touched.difference(&wires).copied().collect(),
        wires,
        constraints,
    }
}

/// A target wire (a site input) and the links that assign it from outside the site.
fn target_region(view: &View, site: &str, wire: usize) -> Region {
    let mut constraints = BTreeSet::new();
    let mut boundary = BTreeSet::new();
    for &position in &view.index[wire] {
        let outside = constraint_wires(&view.r1cs.constraints[position])
            .into_iter()
            .filter(|other| *other != 0 && *other != wire && !view.within(*other, site))
            .collect::<Vec<_>>();
        if !outside.is_empty() {
            constraints.insert(position);
            boundary.extend(outside);
        }
    }
    Region {
        wires: BTreeSet::from([wire]),
        constraints,
        boundary,
    }
}

/// Shortest upstream constraint paths from `start` to leaves; adds their constraints and
/// wires. Returns the number of leaves found.
#[allow(clippy::too_many_arguments)]
fn upstream_paths(
    view: &View,
    structure: &mut Structure,
    start: usize,
    blocked: &dyn Fn(usize) -> bool,
    leaf: &dyn Fn(&mut Structure, usize) -> bool,
    constraints: &mut BTreeSet<usize>,
    unknowns: &mut BTreeSet<usize>,
) -> usize {
    if leaf(structure, start) {
        unknowns.insert(start);
        return 1;
    }
    let mut parent: BTreeMap<usize, (usize, usize)> = BTreeMap::new();
    let mut seen = BTreeSet::from([start]);
    let mut queue = VecDeque::from([(start, 0usize)]);
    let mut found = 0;
    while let Some((wire, depth)) = queue.pop_front() {
        if depth >= PATH_DEPTH || seen.len() > PATH_VISITS {
            break;
        }
        let owner = split_instance(view.name(wire)).0.to_owned();
        let wire_is_input = structure.is_input(view.name(wire));
        for &position in &view.index[wire] {
            let touched = constraint_wires(&view.r1cs.constraints[position]);
            // An input signal is computed only by the parent's link that assigns it.
            if wire_is_input
                && !touched
                    .iter()
                    .any(|other| *other != 0 && !view.within(*other, &owner))
            {
                continue;
            }
            for &next in &touched {
                if next == 0 || seen.contains(&next) || blocked(next) {
                    continue;
                }
                // That link computes `next` from the others: it lies downstream.
                let next_owner = split_instance(view.name(next)).0.to_owned();
                if structure.is_input(view.name(next))
                    && touched.iter().any(|other| {
                        *other != 0 && *other != next && !view.within(*other, &next_owner)
                    })
                {
                    continue;
                }
                seen.insert(next);
                parent.insert(next, (wire, position));
                if leaf(structure, next) {
                    unknowns.insert(next);
                    let mut cursor = next;
                    while let Some(&(previous, constraint)) = parent.get(&cursor) {
                        constraints.insert(constraint);
                        unknowns.insert(previous);
                        cursor = previous;
                    }
                    found += 1;
                    if found >= LEAVES_PER_START {
                        return found;
                    }
                } else if !view.is_hub(next) && !view.is_main_input(next) {
                    queue.push_back((next, depth + 1));
                }
            }
        }
    }
    found
}

/// SMT-LIB text for `constraints` over `unknowns` (others take `value`). A constraint whose
/// only unknown has exactly the roots {0, 1} is written as that bound, an equivalent encoding.
pub(crate) fn encode(
    r1cs: &R1cs,
    constraints: &BTreeSet<usize>,
    unknowns: &BTreeSet<usize>,
    value: &dyn Fn(usize) -> BigUint,
    timeout: Duration,
) -> String {
    let _profile = super::profile_v24::span("repair.encode_query");
    let prime = &r1cs.prime;
    let mut text = String::new();
    let _ = writeln!(text, "(set-option :timeout {})", timeout.as_millis());
    for wire in unknowns {
        let _ = writeln!(text, "(declare-const w{wire} Int)");
        let _ = writeln!(text, "(assert (and (<= 0 w{wire}) (< w{wire} {prime})))");
    }
    for &position in constraints {
        let constraint = &r1cs.constraints[position];
        let unknown = constraint_wires(constraint)
            .into_iter()
            .filter(|wire| unknowns.contains(wire))
            .collect::<Vec<_>>();
        let at = |single: usize, trial: u32| {
            residual(constraint, prime, |other| {
                if other == single {
                    BigUint::from(trial)
                } else {
                    value(other)
                }
            })
        };
        match unknown.as_slice() {
            [] => {
                if !residual(constraint, prime, value).is_zero() {
                    let _ = writeln!(text, "(assert false)");
                }
                continue;
            }
            [single]
                if at(*single, 0).is_zero()
                    && at(*single, 1).is_zero()
                    && !at(*single, 2).is_zero() =>
            {
                let _ = writeln!(text, "(assert (<= w{single} 1))");
                continue;
            }
            _ => {}
        }
        let [a, b, c] = [&constraint.a, &constraint.b, &constraint.c]
            .map(|combination| smt_combination(combination, unknowns, value, prime));
        let _ = writeln!(text, "(assert (= (mod (- (* {a} {b}) {c}) {prime}) 0))");
    }
    text
}

fn smt_combination(
    combination: &LinearCombination,
    unknowns: &BTreeSet<usize>,
    value: &dyn Fn(usize) -> BigUint,
    prime: &BigUint,
) -> String {
    let mut constant = BigUint::zero();
    let mut terms = Vec::new();
    for (wire, coefficient) in combination {
        let wire = *wire as usize;
        if wire != 0 && unknowns.contains(&wire) {
            terms.push(format!("(* {coefficient} w{wire})"));
        } else {
            let known = if wire == 0 {
                BigUint::one()
            } else {
                value(wire)
            };
            constant = (constant + coefficient * known) % prime;
        }
    }
    terms.push(constant.to_string());
    if terms.len() == 1 {
        terms.pop().unwrap_or_default()
    } else {
        format!("(+ {})", terms.join(" "))
    }
}

/// The negation of zkFuzz's `LessThan` condition over the predicate wires.
pub(crate) fn encode_predicate(
    predicate: &Predicate,
    unknowns: &BTreeSet<usize>,
    value: &dyn Fn(usize) -> BigUint,
) -> String {
    let term = |wire: usize| {
        if unknowns.contains(&wire) {
            format!("w{wire}")
        } else {
            value(wire).to_string()
        }
    };
    let [in0, in1, out] = predicate.wires.map(term);
    format!(
        "(assert (not (or (and (= {out} 1) (< {in0} {in1})) (and (= {out} 0) (>= {in0} {in1})))))\n"
    )
}

/// Runs z3 on `text` (with `check-sat` and `get-value` for `unknowns` appended): the first line
/// of its answer and, when satisfiable, the model.
pub(crate) fn run_z3(
    z3: &Path,
    mut text: String,
    unknowns: &BTreeSet<usize>,
    scratch: &Path,
    timeout: Duration,
) -> Result<(String, BTreeMap<usize, BigUint>)> {
    let _profile = super::profile_v24::span("repair.solve_and_parse_model");
    text.push_str("(check-sat)\n");
    if !unknowns.is_empty() {
        let names = unknowns
            .iter()
            .map(|wire| format!("w{wire}"))
            .collect::<Vec<_>>()
            .join(" ");
        let _ = writeln!(text, "(get-value ({names}))");
    }
    let output = super::solver::run(z3, text, scratch, timeout)?;
    let timed_out = output.starts_with("timeout\n");
    let verdict = output.lines().next().unwrap_or("").trim().to_owned();
    if timed_out {
        return Ok(("timeout".to_owned(), BTreeMap::new()));
    }
    let model = if verdict == "sat" && !unknowns.is_empty() {
        let model = parse_values(&output)?;
        ensure!(
            model.keys().copied().collect::<BTreeSet<_>>() == *unknowns,
            "z3 model does not cover exactly the requested wires"
        );
        model
    } else {
        BTreeMap::new()
    };
    Ok((verdict, model))
}

/// An ineffective regional SAT uses the existing with-paths slot; UNSAT here is
/// only failure of a search with frozen boundary values.
fn try_paths_after(outcome: &str) -> bool {
    matches!(outcome, "sat_no_effect" | "unsat" | "unknown" | "timeout")
}

/// A replay attempt must spend an existing slot; revisiting the initial state is
/// already a cycle. This controller cannot produce a witness or an exclusion.
struct SearchHistory {
    seen: BTreeSet<String>,
    allowed: usize,
    used: usize,
}
impl SearchHistory {
    fn new(initial: String, allowed: usize) -> Self {
        Self {
            seen: BTreeSet::from([initial]),
            allowed: allowed.min(MAX_ITERATIONS),
            used: 0,
        }
    }
    fn next_iteration(&mut self) -> Option<usize> {
        if self.used == self.allowed {
            return None;
        }
        let iteration = self.used;
        self.used += 1;
        Some(iteration)
    }
    fn observe(&mut self, state: String) -> bool {
        self.seen.insert(state)
    }
}

struct Search<'s, 'c> {
    context: &'s EvalContext<'c>,
    start: &'s Start,
    requirement: &'s Requirement,
    view: View<'c>,
    z3: &'c Path,
    record: RepairRecord,
    overrides: Overrides,
    input: Value,
    changed_inputs: BTreeSet<String>,
    iterations_allowed: usize,
    failed_constraints: BTreeSet<usize>,
    attempted_controls: Vec<BTreeMap<usize, BigUint>>,
    snapshots: Vec<super::boost::Snapshot>,
    post_queries: Vec<PostQuery>,
}

struct PostQuery {
    iteration: usize,
    path: PathBuf,
    constraints: BTreeSet<usize>,
    unknowns: BTreeSet<usize>,
    boundary: BTreeMap<usize, BigUint>,
    assigned: BTreeMap<usize, BigUint>,
    model: BTreeMap<usize, BigUint>,
    applied: BTreeMap<usize, BigUint>,
}

pub(super) struct PostLimitProbe {
    site: String,
    start: Start,
    requirement: Requirement,
    input: Value,
    overrides: Overrides,
    failed_constraints: BTreeSet<usize>,
    queries: Vec<PostQuery>,
    directory: PathBuf,
    iteration: usize,
    state_sha256: String,
}

/// Finds an entrypoint input and hint injections whose generator meets `requirement`.
pub(crate) fn search(
    context: &mut EvalContext,
    start: Start,
    requirement: &Requirement,
    directory: &Path,
    ledger: &mut Ledger,
) -> (Option<Reached>, RepairRecord) {
    let _profile = super::profile_v24::span("repair.search");
    let mut record = RepairRecord {
        start: start.label.to_owned(),
        ..RepairRecord::default()
    };
    let Some(z3) = context.z3 else {
        record.outcome = "error".to_owned();
        record.note = Some("z3 is not available".to_owned());
        return (None, record);
    };
    if context.o0_constraint_index.is_none() {
        let r1cs = context.entry_o0_r1cs;
        context.o0_constraint_index = Some(std::rc::Rc::new(ledger.timed(
            start.stage,
            "index O0 constraints",
            || super::refute::constraint_index(r1cs),
        )));
    }
    let index = context.o0_constraint_index.clone().unwrap_or_default();
    if context.structure.is_none() {
        context.structure = Some(ledger.timed(start.stage, "index signal roles", || {
            Structure::new(
                context.entry_o0_sym,
                context.templates,
                context.sources,
                context.entry_main_template.clone(),
            )
        }));
    }
    let mut structure = context.structure.take().expect("signal roles");
    let r1cs = context.entry_o0_r1cs;
    let view = View {
        r1cs,
        sym: context.entry_o0_sym,
        index: &index,
        first_input: 1 + r1cs.shape.public_outputs,
        inputs: r1cs.shape.public_inputs + r1cs.shape.private_inputs,
    };
    let mut state = Search {
        context,
        start: &start,
        requirement,
        view,
        z3,
        record,
        overrides: start.overrides.clone(),
        input: start.input.clone(),
        changed_inputs: BTreeSet::new(),
        iterations_allowed: context.repair_remaining.min(MAX_ITERATIONS),
        failed_constraints: BTreeSet::new(),
        attempted_controls: Vec::new(),
        snapshots: Vec::new(),
        post_queries: Vec::new(),
    };
    let outcome = state.run(&mut structure, directory, ledger);
    let snapshots = std::mem::take(&mut state.snapshots);
    for snapshot in snapshots {
        if let Some(site) = ledger.site.clone() {
            super::boost::capture(state.context, &site, &snapshot, ledger);
        }
    }
    let mut record = std::mem::take(&mut state.record);
    record.changed_inputs = state.changed_inputs.iter().cloned().collect();
    let reached = match outcome {
        Ok(reached) => reached,
        Err(error) => {
            record.outcome = "error".to_owned();
            let detail = format!("{error:#}");
            record.error_kind = Some(
                if detail.contains("R1CS") || detail.contains("SYM") {
                    "evidence_invariant"
                } else if detail.contains("timed out") {
                    "tool_timeout"
                } else if detail.contains("too many constraints") {
                    "region_limit"
                } else if detail.contains("diagnostic") {
                    "diagnostic_failure"
                } else if error.downcast_ref::<std::io::Error>().is_some() {
                    "io"
                } else {
                    "tool_or_unsupported"
                }
                .to_owned(),
            );
            record.note = Some(detail);
            None
        }
    };
    if let Some(reached) = &reached {
        record.outcome = "reached".to_owned();
        record.rewritten_statements = reached.statements;
        record.injected_instances = reached.instances;
    }
    context.repair_remaining = context.repair_remaining.saturating_sub(record.iterations);
    context.structure = Some(structure);
    (reached, record)
}

fn post_values(values: &BTreeMap<usize, BigUint>) -> BTreeMap<String, String> {
    values
        .iter()
        .map(|(wire, value)| (wire.to_string(), value.to_string()))
        .collect()
}

fn post_constraint(view: &View, witness: &[BigUint], position: usize) -> Value {
    let constraint = &view.r1cs.constraints[position];
    let part = |terms: &BTreeMap<u32, BigUint>| {
        terms
            .iter()
            .map(|(wire, coefficient)| {
                serde_json::json!({"wire":wire,"name":view.name(*wire as usize),
                    "coefficient":coefficient.to_string(),"value":witness[*wire as usize].to_string()})
            })
            .collect::<Vec<_>>()
    };
    serde_json::json!({"index":position,"index_base":0,
        "component_path":constraint_instance(view, position),
        "residual":residual(constraint,&view.r1cs.prime,|wire:usize|witness[wire].clone()).to_string(),
        "A":part(&constraint.a),"B":part(&constraint.b),"C":part(&constraint.c)})
}

fn post_failures(view: &View, witness: &[BigUint], queries: &[PostQuery]) -> Result<Value> {
    let failed = super::check_constraints(view.r1cs, witness)?;
    let covered = queries
        .iter()
        .flat_map(|query| query.constraints.iter().copied())
        .collect::<BTreeSet<_>>();
    let inside = failed
        .iter()
        .copied()
        .filter(|position| covered.contains(position))
        .collect::<Vec<_>>();
    let outside = failed
        .iter()
        .copied()
        .filter(|position| !covered.contains(position))
        .collect::<Vec<_>>();
    let per_query = queries
        .iter()
        .map(|query| {
            serde_json::json!({"smt2":query.path,"inside_failed":failed.iter()
                .filter(|position|query.constraints.contains(position)).count()})
        })
        .collect::<Vec<_>>();
    Ok(
        serde_json::json!({"total":failed.len(),"inside_any_query":inside.len(),
        "outside_all_queries":outside.len(),"per_query":per_query,
        "first_index":failed.first(),
        "inside_examples":inside.iter().take(4).map(|&i|post_constraint(view,witness,i)).collect::<Vec<_>>(),
        "outside_examples":outside.iter().take(4).map(|&i|post_constraint(view,witness,i)).collect::<Vec<_>>() }),
    )
}

fn inspect_post_limit(context: &EvalContext, job: &PostLimitProbe, folder: &Path) -> Result<Value> {
    fs::create_dir_all(folder)?;
    let state = format!(
        "{:?}{:?}{}",
        job.overrides.rewrite, job.overrides.keys, job.input
    );
    ensure!(
        sha256_text(&state) == job.state_sha256,
        "captured_state_hash_mismatch"
    );
    let raw_queries = job
        .queries
        .iter()
        .map(|query| {
            serde_json::json!({"iteration":query.iteration,"smt2":query.path,
                "smt2_sha256":sha256_file(&query.path).ok(),
                "constraints":query.constraints,"unknowns":query.unknowns,
                "boundary":post_values(&query.boundary),"assigned":post_values(&query.assigned),
                "model":post_values(&query.model),"applied":post_values(&query.applied)})
        })
        .collect::<Vec<_>>();
    write_json(
        &folder.join("post-limit-state.json"),
        &serde_json::json!({"site":job.site,"iteration":job.iteration,
            "state_sha256":job.state_sha256,"input":job.input,
            "rewrite":job.overrides.rewrite.iter().map(|(k,v)|(k,v.to_string())).collect::<BTreeMap<_,_>>(),
            "keys":job.overrides.keys.iter().map(|(k,v)|(k,v.to_string())).collect::<BTreeMap<_,_>>(),
            "candidate_hints":job.start.candidate_hints,"protected_site":job.start.protected_site,
            "inputs_free":job.start.inputs_free,"pinned":job.start.pinned,
            "targets":job.requirement.targets.iter().map(|(w,v)|serde_json::json!([w,v.to_string()])).collect::<Vec<_>>(),
            "queries":raw_queries,"previous_failed_constraints":job.failed_constraints}),
    )?;
    let index = context
        .o0_constraint_index
        .as_ref()
        .context("post_limit_constraint_index_missing")?;
    let r1cs = context.entry_o0_r1cs;
    let view = View {
        r1cs,
        sym: context.entry_o0_sym,
        index,
        first_input: 1 + r1cs.shape.public_outputs,
        inputs: r1cs.shape.public_inputs + r1cs.shape.private_inputs,
    };
    let z3 = context.z3.context("post_limit_z3_missing")?;
    let mut search = Search {
        context,
        start: &job.start,
        requirement: &job.requirement,
        view,
        z3,
        record: RepairRecord::default(),
        overrides: job.overrides.clone(),
        input: job.input.clone(),
        changed_inputs: BTreeSet::new(),
        iterations_allowed: 0,
        failed_constraints: job.failed_constraints.clone(),
        attempted_controls: Vec::new(),
        snapshots: Vec::new(),
        post_queries: Vec::new(),
    };
    let mut ledger = Ledger {
        steps: Vec::new(),
        site: Some(job.site.clone()),
    };
    let edits = search.plan(true)?;
    let generator = search.variant(&edits, folder, true, &mut ledger)?;
    let input_path = folder.join("input.json");
    write_json(&input_path, &search.input)?;
    let output = folder.join("o0.wtns");
    let witness = generate_witness(
        context.tools,
        generator.as_ref().unwrap_or(context.original_o0),
        &input_path,
        &output,
        &r1cs.prime,
        &mut ledger,
        "post_limit_probe",
        "regenerate final applied state",
    )?;
    let contract_input_equal = search.input == *context.base_input;
    let result = if let Some(witness) = witness {
        let failures = post_failures(&search.view, &witness, &job.queries)?;
        let goal_met = search.requirement.met(&witness);
        let status = if failures["total"].as_u64().unwrap_or(0) > 0 {
            "o0_constraints_violated"
        } else if !goal_met {
            "target_not_met"
        } else {
            "o0_and_target_met"
        };
        let mut result = serde_json::json!({"status":status,"witness_kind":"original_o0_generator",
            "o0_witness":output,"o0_witness_sha256":sha256_file(&output)?,
            "o0_constraint_count":r1cs.constraints.len(),"failures":failures,
            "goal_met":goal_met,"contract_input_equal":contract_input_equal,
            "input_sha256":sha256_file(&input_path)?,"state_sha256":job.state_sha256});
        if status == "o0_and_target_met" {
            super::boost::capture(
                context,
                &job.site,
                &super::boost::Snapshot {
                    start: witness,
                    query: BTreeMap::new(),
                    scope: BTreeMap::new(),
                    origin: "post_limit_probe".to_owned(),
                },
                &mut ledger,
            );
            result["full_completion"] = context.boost.latest_record().unwrap_or(Value::Null);
        }
        result
    } else {
        let abort = classify_abort(
            &output.with_extension("log"),
            context.templates,
            context.sources,
        );
        let confirmed_abort = matches!(abort.kind.as_str(), "constraint" | "assert");
        let mut result = serde_json::json!({"status":if confirmed_abort {"generator_aborted"} else {"tool_error"},
            "abort_kind":abort.kind,"abort_template":abort.template,"abort_line":abort.line,
            "contract_input_equal":contract_input_equal,"input_sha256":sha256_file(&input_path)?,
            "state_sha256":job.state_sha256});
        if confirmed_abort {
            match search.locate(
                &edits,
                &input_path,
                &folder.join("abort-localize"),
                job.iteration + 1,
                &mut ledger,
            ) {
                Ok((localization, vector, _)) => {
                    result["diagnostic_vector_kind"] =
                        "blanked_check_copy_not_original_witness".into();
                    result["localization"] = serde_json::to_value(localization)?;
                    result["diagnostic_failures"] =
                        post_failures(&search.view, &vector, &job.queries)?;
                }
                Err(error) => result["localization_error"] = format!("{error:#}").into(),
            }
        }
        result
    };
    Ok(result)
}

/// Separate, opt-in evidence after all legacy class decisions. Errors stay in the sidecar.
pub(super) fn run_post_limit_probes(context: &EvalContext) {
    let jobs = context.boost.take_probe_jobs();
    let selected = context.boost.options.post_limit_probe_site.as_deref();
    let root = context.raw.join("post-limit-probe.json");
    if jobs.len() != 1 {
        let _ = write_json(
            &root,
            &serde_json::json!({"schema":"j-post-limit-probe-v1",
            "site":selected,"status":if jobs.is_empty() {"not_captured"} else {"ambiguous_capture"},
            "captured_jobs":jobs.len(),"legacy_verdicts_unchanged":true}),
        );
        return;
    }
    let job = &jobs[0];
    let folder = job.directory.join("post-limit-probe");
    let started = std::time::Instant::now();
    let mut report = match inspect_post_limit(context, job, &folder) {
        Ok(value) => value,
        Err(error) => serde_json::json!({"status":"tool_error","detail":format!("{error:#}")}),
    };
    report["schema"] = "j-post-limit-probe-v1".into();
    report["site"] = job.site.clone().into();
    report["iteration"] = job.iteration.into();
    report["seconds"] = started.elapsed().as_secs_f64().into();
    report["legacy_verdicts_unchanged"] = true.into();
    let _ = write_json(&folder.join("post-limit-probe.json"), &report);
    let _ = write_json(
        &root,
        &serde_json::json!({"schema":"j-post-limit-probe-v1",
        "site":job.site,"status":report["status"],"detail":folder.join("post-limit-probe.json"),
        "seconds":report["seconds"],"legacy_verdicts_unchanged":true}),
    );
}

#[cfg(test)]
pub(super) fn boost_test_post_limit_probe(
    context: &EvalContext,
    directory: &Path,
    site: &str,
    input: Value,
    targets: Vec<(usize, BigUint)>,
) {
    let overrides = Overrides::default();
    let state_sha256 = sha256_text(&format!(
        "{:?}{:?}{}",
        overrides.rewrite, overrides.keys, input
    ));
    context.boost.queue_probe(PostLimitProbe {
        site: site.to_owned(),
        start: Start {
            label: "model",
            stage: "test",
            input: input.clone(),
            overrides: overrides.clone(),
            candidate_hints: false,
            protected_site: Some(site.to_owned()),
            inputs_free: false,
            pinned: BTreeSet::new(),
        },
        requirement: Requirement {
            targets,
            predicate: None,
        },
        input,
        overrides,
        failed_constraints: BTreeSet::new(),
        queries: Vec::new(),
        directory: directory.to_path_buf(),
        iteration: MAX_ITERATIONS - 1,
        state_sha256,
    });
    run_post_limit_probes(context);
}

impl Search<'_, '_> {
    fn run(
        &mut self,
        structure: &mut Structure,
        directory: &Path,
        ledger: &mut Ledger,
    ) -> Result<Option<Reached>> {
        let _profile = super::profile_v24::span("repair.iterations");
        fs::create_dir_all(directory)?;
        let prime = &self.view.r1cs.prime;
        let mut history = SearchHistory::new(
            sha256_text(&format!(
                "{:?}{:?}{}",
                self.overrides.rewrite, self.overrides.keys, self.input
            )),
            self.iterations_allowed,
        );
        while let Some(iteration) = history.next_iteration() {
            self.record.iterations = iteration + 1;
            let folder = directory.join(format!("iteration-{iteration:02}"));
            if folder.exists() {
                fs::remove_dir_all(&folder)?;
            }
            fs::create_dir_all(&folder)?;
            let edits = self.plan(true)?;
            let generator = self.variant(&edits, &folder, true, ledger)?;
            let input_path = folder.join("input.json");
            write_json(&input_path, &self.input)?;
            let witness = generate_witness(
                self.context.tools,
                generator.as_ref().unwrap_or(self.context.original_o0),
                &input_path,
                &folder.join("o0.wtns"),
                prime,
                ledger,
                self.start.stage,
                "search O0 witness",
            )?;
            let progressed = match witness {
                Some(witness) if self.requirement.met(&witness) => {
                    return self.finish(generator, witness, &folder, ledger).map(Some);
                }
                Some(witness) => {
                    self.repair_requirement(structure, &witness, iteration, &folder)?
                }
                None => {
                    let (localization, vector, failed) =
                        self.locate(&edits, &input_path, &folder, iteration, ledger)?;
                    let groups = localization.failing_instances.clone();
                    self.record.localizations.push(localization);
                    let progressed = self
                        .repair_aborts(structure, &vector, &failed, &groups, iteration, &folder)?;
                    self.failed_constraints.extend(failed.iter().copied());
                    progressed
                }
            };
            if !progressed {
                self.record.outcome = "no_progress".to_owned();
                return Ok(None);
            }
            // Repairs that return to an earlier state cannot converge.
            let state = format!(
                "{:?}{:?}{}",
                self.overrides.rewrite, self.overrides.keys, self.input
            );
            if !history.observe(sha256_text(&state)) {
                self.record.outcome = "cycle".to_owned();
                return Ok(None);
            }
        }
        self.record.outcome = "iteration_limit".to_owned();
        if self.post_selected() && !self.post_queries.is_empty() {
            let state_sha256 = sha256_text(&format!(
                "{:?}{:?}{}",
                self.overrides.rewrite, self.overrides.keys, self.input
            ));
            self.context.boost.queue_probe(PostLimitProbe {
                site: self.start.protected_site.clone().unwrap_or_default(),
                start: self.start.clone(),
                requirement: self.requirement.clone(),
                input: self.input.clone(),
                overrides: self.overrides.clone(),
                failed_constraints: self.failed_constraints.clone(),
                queries: std::mem::take(&mut self.post_queries),
                directory: directory.to_path_buf(),
                iteration: self.record.iterations.saturating_sub(1),
                state_sha256,
            });
        }
        Ok(None)
    }

    fn post_selected(&self) -> bool {
        self.start.label == "model"
            && self.context.boost.options.post_limit_probe_site.as_deref()
                == self.start.protected_site.as_deref()
    }

    /// Source edits for the current overrides, with the candidate's site hints when the
    /// search carries the candidate and `candidate` is set.
    fn plan(&self, candidate: bool) -> Result<Edits> {
        self.plan_records(candidate).map(|(edits, _)| edits)
    }

    /// [`Self::plan`] with the rewritten statements (value-free).
    fn plan_records(&self, candidate: bool) -> Result<(Edits, Vec<RewriteRecord>)> {
        let _profile = super::profile_v24::span("repair.plan_rewrites");
        let context = self.context;
        let mut pseudo = self.overrides.keys.clone();
        pseudo.extend(self.overrides.rewrite.clone());
        let mut deviated = self
            .overrides
            .rewrite
            .keys()
            .cloned()
            .collect::<BTreeSet<_>>();
        if candidate && self.start.candidate_hints {
            if let Some(site) = &self.start.protected_site {
                for (name, value) in context.candidate {
                    if let Some(suffix) = name.strip_prefix("main.") {
                        pseudo.insert(format!("{site}.{suffix}"), value.clone());
                    }
                }
                for suffix in &context.plan.hint_suffixes {
                    deviated.insert(format!("{site}.{suffix}"));
                }
            }
        }
        if deviated.is_empty() {
            return Ok((Edits::new(), Vec::new()));
        }
        let plan = plan_rewrites(
            &pseudo,
            context.entry_o0_sym,
            &deviated,
            false,
            context.templates,
            context.sources,
            context.entry_main_template.as_deref(),
            context.rewrite_structure.as_ref(),
        )
        .map_err(|failure| anyhow::anyhow!("{}: {}", failure.reason, failure.detail))?;
        let records = plan
            .records
            .iter()
            .map(|record| RewriteRecord {
                template: record.template.clone(),
                file: display_relative(&record.file, context.source_root, context.libraries),
                line: record.line,
                signal: record.signal.clone(),
                clauses: record.clauses,
            })
            .collect();
        Ok((plan.edits, records))
    }

    /// Compiles a generator from `edits` (None: the original, nothing to compile). Hint edits
    /// must leave the O0 R1CS (and at O1 the R1CS and `.sym`) identical to the original.
    fn variant(
        &self,
        edits: &Edits,
        folder: &Path,
        o0: bool,
        ledger: &mut Ledger,
    ) -> Result<Option<Compiled>> {
        let _profile = super::profile_v24::span("repair.variant");
        if edits.is_empty() {
            return Ok(None);
        }
        let context = self.context;
        let compiled = compile_edits(
            context,
            edits,
            &folder.join(if o0 { "variant-o0" } else { "variant-o1" }),
            o0,
            ledger,
            if o0 {
                "compile injected generator --O0"
            } else {
                "compile injected generator"
            },
        )?;
        let _invariants = super::profile_v24::span("repair.variant_invariants");
        if o0 {
            sym_equivalence(
                &super::profile_v24::measure("sym_read", || {
                    fs::read_to_string(&context.original_o0.sym)
                })?,
                &super::profile_v24::measure("sym_read", || fs::read_to_string(&compiled.sym))?,
            )
            .context("the injected O0 generator changes the original SYM")?;
            ensure!(
                super::artifact_bytes_equal(
                    "r1cs_bytes_read_compare",
                    &compiled.r1cs,
                    &context.original_o0.r1cs,
                )?,
                "the injected O0 generator changes the O0 R1CS"
            );
        } else {
            ensure!(
                super::artifact_bytes_equal(
                    "r1cs_bytes_read_compare",
                    &compiled.r1cs,
                    &context.original.r1cs,
                )?,
                "the injected generator changes the original R1CS"
            );
            sym_equivalence(
                &super::profile_v24::measure("sym_read", || {
                    fs::read_to_string(&context.original.sym)
                })?,
                &super::profile_v24::measure("sym_read", || fs::read_to_string(&compiled.sym))?,
            )
            .context("the injected generator changes the original SYM")?;
        }
        Ok(Some(compiled))
    }

    fn finish(
        &mut self,
        o0: Option<Compiled>,
        witness: Vec<BigUint>,
        folder: &Path,
        ledger: &mut Ledger,
    ) -> Result<Reached> {
        let _profile = super::profile_v24::span("repair.finish");
        let context = self.context;
        let o1 = self.variant(&self.plan(true)?, folder, false, ledger)?;
        let comparator = if self.start.candidate_hints {
            let edits = self.plan(false)?;
            if edits.is_empty() {
                None
            } else {
                let compiled = compile_edits(
                    context,
                    &edits,
                    &folder.join("comparator-o1"),
                    false,
                    ledger,
                    "compile comparator generator",
                )?;
                let _invariants = super::profile_v24::span("repair.comparator_invariants");
                ensure!(
                    super::artifact_bytes_equal(
                        "r1cs_bytes_read_compare",
                        &compiled.r1cs,
                        &context.original.r1cs,
                    )?,
                    "the comparator generator changes the original R1CS"
                );
                sym_equivalence(
                    &super::profile_v24::measure("sym_read", || {
                        fs::read_to_string(&context.original.sym)
                    })?,
                    &super::profile_v24::measure("sym_read", || fs::read_to_string(&compiled.sym))?,
                )
                .context("the comparator generator changes the original SYM")?;
                Some(compiled)
            }
        } else {
            None
        };
        let (_, rewritten) = self.plan_records(false)?;
        let statements = rewritten.len();
        self.record.rewritten = rewritten;
        let instances = self
            .overrides
            .rewrite
            .keys()
            .map(|name| split_instance(name).0.to_owned())
            .collect::<BTreeSet<_>>()
            .len();
        Ok(Reached {
            input: self.input.clone(),
            o0: o0.unwrap_or_else(|| context.original_o0.clone()),
            o1: o1.unwrap_or_else(|| context.original.clone()),
            comparator,
            witness_o0: witness,
            statements,
            instances,
        })
    }

    /// Runs a diagnostic copy with each aborting check blanked until the generator finishes;
    /// returns the localization, its witness mapped onto the original O0 wires, and the
    /// unsatisfied O0 constraint indices.
    fn locate(
        &mut self,
        base: &Edits,
        input: &Path,
        folder: &Path,
        iteration: usize,
        ledger: &mut Ledger,
    ) -> Result<(Localization, Vec<BigUint>, Vec<usize>)> {
        let _profile = super::profile_v24::span("repair.localize");
        let context = self.context;
        let mut blanked: Vec<(PathBuf, usize, usize)> = Vec::new();
        let mut checks = Vec::new();
        for round in 0..=MAX_BLANKED {
            let mut edits = base.clone();
            for (file, start, end) in &blanked {
                let text = &context.sources[file][*start..*end];
                edits
                    .entry(file.clone())
                    .or_default()
                    .push((*start, *end, blank(text)));
            }
            let directory = folder.join(format!("diagnostic-{round}"));
            let compiled = compile_edits(
                context,
                &edits,
                &directory,
                true,
                ledger,
                "compile diagnostic copy --O0",
            )?;
            let output = directory.join("diagnostic.wtns");
            let values = generate_witness(
                context.tools,
                &compiled,
                input,
                &output,
                &self.view.r1cs.prime,
                ledger,
                self.start.stage,
                "diagnostic witness",
            )?;
            if let Some(values) = values {
                // Blanking keeps every signal: the copy's O0 wires are the original's, which
                // the symbol files confirm line by line (up to anonymous-component offsets).
                let started = Instant::now();
                let _mapping = super::profile_v24::span("mapping.other");
                {
                    let original = super::profile_v24::measure("mapping.sym_read", || {
                        fs::read_to_string(&context.original_o0.sym)
                    })?;
                    let diagnostic = super::profile_v24::measure("mapping.sym_read", || {
                        fs::read_to_string(&compiled.sym)
                    })?;
                    super::profile_v24::measure("mapping.full_sym_equivalence", || {
                        sym_equivalence(&original, &diagnostic)
                    })
                    .context("the diagnostic copy's signals differ from the original O0 signals")?;
                }
                ensure!(
                    values.len() == self.view.r1cs.shape.wires,
                    "the diagnostic witness has a different wire count"
                );
                let vector = values;
                let failed = super::profile_v24::measure("mapping.full_constraint_check", || {
                    super::check_constraints(self.view.r1cs, &vector)
                })?;
                let failing_instances =
                    super::profile_v24::measure("mapping.group_failures", || self.group(&failed));
                ledger.record(
                    self.start.stage,
                    "map diagnostic witness onto the original O0 R1CS",
                    started.elapsed().as_secs_f64(),
                    "ok",
                    false,
                );
                return Ok((
                    Localization {
                        iteration,
                        blanked_checks: checks,
                        unsatisfied_constraints: failed.len(),
                        failing_instances,
                    },
                    vector,
                    failed,
                ));
            }
            if round == MAX_BLANKED {
                break;
            }
            let abort = classify_abort(
                &output.with_extension("log"),
                context.templates,
                context.sources,
            );
            let stripped = abort
                .template
                .rsplit_once('_')
                .filter(|(_, id)| !id.is_empty() && id.bytes().all(|byte| byte.is_ascii_digit()))
                .map_or(abort.template.as_str(), |(base, _)| base);
            let mut added = false;
            for template in context
                .templates
                .iter()
                .filter(|template| template.name == stripped || template.name == abort.template)
            {
                let Some((start, end, kind)) =
                    check_statement_at_line(&context.sources[&template.file], template, abort.line)
                else {
                    continue;
                };
                let span = (template.file.clone(), start, end);
                if blanked.contains(&span) {
                    continue;
                }
                blanked.push(span);
                checks.push(BlankedCheck {
                    template: template.name.clone(),
                    file: display_relative(&template.file, context.source_root, context.libraries),
                    line: abort.line,
                    kind: kind.to_owned(),
                });
                added = true;
            }
            ensure!(
                added,
                "the generator aborted in {} line {} ({}) and no new statement there can be blanked",
                abort.template,
                abort.line,
                abort.kind
            );
        }
        bail!("the diagnostic copy still aborts after blanking {MAX_BLANKED} checks")
    }

    fn group(&self, failed: &[usize]) -> Vec<FailingGroup> {
        let mut by_instance: BTreeMap<String, Vec<usize>> = BTreeMap::new();
        for position in failed {
            by_instance
                .entry(constraint_instance(&self.view, *position))
                .or_default()
                .push(*position);
        }
        let mut by_pattern: BTreeMap<String, Vec<String>> = BTreeMap::new();
        for instance in by_instance.keys() {
            by_pattern
                .entry(class_pattern(instance))
                .or_default()
                .push(instance.clone());
        }
        by_pattern
            .into_iter()
            .map(|(pattern, mut instances)| {
                instances.sort_by_key(|instance| natural_key(instance));
                let representative = instances[0].clone();
                FailingGroup {
                    pattern,
                    instances: instances.len(),
                    constraints: by_instance[&representative]
                        .iter()
                        .take(5)
                        .copied()
                        .collect(),
                    representative,
                }
            })
            .collect()
    }

    fn repair_aborts(
        &mut self,
        structure: &mut Structure,
        vector: &[BigUint],
        failed: &[usize],
        groups: &[FailingGroup],
        iteration: usize,
        folder: &Path,
    ) -> Result<bool> {
        let _profile = super::profile_v24::span("repair.abort_regions");
        let mut by_instance: BTreeMap<String, Vec<usize>> = BTreeMap::new();
        for position in failed {
            by_instance
                .entry(constraint_instance(&self.view, *position))
                .or_default()
                .push(*position);
        }
        // Up to two instances per failing pattern (identical batch copies share a key).
        let mut chosen = Vec::new();
        for group in groups {
            let mut members = by_instance
                .keys()
                .filter(|instance| class_pattern(instance) == group.pattern)
                .cloned()
                .collect::<Vec<_>>();
            members.sort_by_key(|instance| natural_key(instance));
            chosen.extend(members.into_iter().take(2));
        }
        let mut regions = Vec::new();
        for instance in chosen.into_iter().take(MAX_SOLVES) {
            let protected = self.start.protected_site.clone();
            if protected
                .as_ref()
                .is_some_and(|site| instance == *site || instance.starts_with(&format!("{site}.")))
            {
                self.record.solves.push(SolveRecord {
                    carry: "without".to_owned(),
                    carried_constraints: 0,
                    carried_dropped: 0,
                    iteration,
                    cause: "abort".to_owned(),
                    region: instance,
                    with_paths: false,
                    unknowns: 0,
                    constraints: 0,
                    outcome: "inside_carried_site".to_owned(),
                    hints_changed: 0,
                    inputs_changed: 0,
                });
                continue;
            }
            let region = if instance.is_empty() || instance == "main" {
                None
            } else {
                instance_region(&self.view, structure, &instance)
            }
            .unwrap_or_else(|| {
                constraint_region(
                    &self.view,
                    structure,
                    &by_instance[&instance],
                    protected.as_deref(),
                )
            });
            regions.push((instance, region));
        }
        // Repairing the aborts alone and the requirement alone can undo each other (a target
        // moved upstream re-breaks a range check downstream): when the requirement is unmet
        // too, solve everything in one query first.
        if let Some((target, assigned, predicate)) = self.requirement_region(structure, vector) {
            let mut joint = Region {
                wires: BTreeSet::new(),
                constraints: BTreeSet::new(),
                boundary: BTreeSet::new(),
            };
            for (_, region) in regions
                .iter()
                .map(|(label, region)| (label, region))
                .chain([(&String::new(), &target)])
            {
                joint.wires.extend(region.wires.iter().copied());
                joint.constraints.extend(region.constraints.iter().copied());
                joint.boundary.extend(region.boundary.iter().copied());
            }
            let boundary = joint.boundary.difference(&joint.wires).copied().collect();
            joint.boundary = boundary;
            if joint.constraints.len() <= REGION_CONSTRAINTS * 2
                && self.solve_region(
                    structure,
                    vector,
                    joint,
                    &assigned,
                    predicate.as_ref(),
                    "joint",
                    &format!("{} failing instances and the requirement", regions.len()),
                    self.start.inputs_free,
                    iteration,
                    &folder.join("repair-joint"),
                )?
            {
                return Ok(true);
            }
        }
        let mut progressed = false;
        for (index, (instance, region)) in regions.into_iter().enumerate() {
            let scratch = folder.join(format!("repair-{index}"));
            progressed |= self.solve_region(
                structure,
                vector,
                region,
                &BTreeMap::new(),
                None,
                "abort",
                &instance,
                false,
                iteration,
                &scratch,
            )?;
        }
        Ok(progressed)
    }

    /// The region, target values, and predicate of the requirement where `witness` misses it.
    #[allow(clippy::type_complexity)]
    fn requirement_region(
        &self,
        structure: &mut Structure,
        witness: &[BigUint],
    ) -> Option<(Region, BTreeMap<usize, BigUint>, Option<Predicate>)> {
        let _profile = super::profile_v24::span("repair.requirement_region");
        let mut region = Region {
            wires: BTreeSet::new(),
            constraints: BTreeSet::new(),
            boundary: BTreeSet::new(),
        };
        let mut predicate = None;
        if let Some(wanted) = &self.requirement.predicate {
            if !wanted.holds(witness) {
                let part = instance_region(&self.view, structure, &wanted.instance)?;
                region.wires.extend(part.wires);
                region.constraints.extend(part.constraints);
                region.boundary.extend(part.boundary);
                predicate = Some(wanted.clone());
            }
        }
        let site = self.start.protected_site.clone().unwrap_or_default();
        let assigned = self
            .requirement
            .targets
            .iter()
            .filter(|(wire, value)| &witness[*wire] != value)
            .cloned()
            .collect::<BTreeMap<_, _>>();
        for wire in assigned.keys() {
            let part = target_region(&self.view, &site, *wire);
            region.wires.extend(part.wires);
            region.constraints.extend(part.constraints);
            region.boundary.extend(part.boundary);
        }
        (predicate.is_some() || !assigned.is_empty()).then_some((region, assigned, predicate))
    }

    fn repair_requirement(
        &mut self,
        structure: &mut Structure,
        witness: &[BigUint],
        iteration: usize,
        folder: &Path,
    ) -> Result<bool> {
        let _profile = super::profile_v24::span("repair.requirement_search");
        let mut progressed = false;
        if let Some(predicate) = self.requirement.predicate.clone() {
            if !predicate.holds(witness) {
                let Some(region) = instance_region(&self.view, structure, &predicate.instance)
                else {
                    bail!("the predicate instance has too many constraints");
                };
                progressed |= self.solve_region(
                    structure,
                    witness,
                    region,
                    &BTreeMap::new(),
                    Some(&predicate),
                    "predicate",
                    &predicate.instance,
                    self.start.inputs_free,
                    iteration,
                    &folder.join("repair-predicate"),
                )?;
            }
        }
        let unmet = self
            .requirement
            .targets
            .iter()
            .filter(|(wire, value)| &witness[*wire] != value)
            .cloned()
            .collect::<Vec<_>>();
        if !unmet.is_empty() {
            let site = self.start.protected_site.clone().unwrap_or_default();
            let mut region = Region {
                wires: BTreeSet::new(),
                constraints: BTreeSet::new(),
                boundary: BTreeSet::new(),
            };
            for (wire, _) in &unmet {
                let part = target_region(&self.view, &site, *wire);
                region.wires.extend(part.wires);
                region.constraints.extend(part.constraints);
                region.boundary.extend(part.boundary);
            }
            let assigned = unmet.into_iter().collect::<BTreeMap<_, _>>();
            progressed |= self.solve_region(
                structure,
                witness,
                region,
                &assigned,
                None,
                "target",
                &site,
                self.start.inputs_free,
                iteration,
                &folder.join("repair-target"),
            )?;
        }
        Ok(progressed)
    }

    /// Solves `region` (first alone, then with upstream paths to leaves) and folds the model
    /// into the overrides and the input. Returns whether anything changed.
    #[allow(clippy::too_many_arguments)]
    fn solve_region(
        &mut self,
        structure: &mut Structure,
        current: &[BigUint],
        region: Region,
        assigned: &BTreeMap<usize, BigUint>,
        predicate: Option<&Predicate>,
        cause: &str,
        label: &str,
        inputs_free: bool,
        iteration: usize,
        scratch: &Path,
    ) -> Result<bool> {
        let _profile = super::profile_v24::span("repair.solve_region");
        let protected = self.start.protected_site.clone();
        let pinned = self.start.pinned.clone();
        let value = |wire: usize| {
            assigned
                .get(&wire)
                .cloned()
                .unwrap_or_else(|| current[wire].clone())
        };
        let owned_view = self.view;
        let view = &owned_view;
        let blocked = |wire: usize| {
            region.wires.contains(&wire)
                || pinned.contains(&wire)
                || (view.is_main_input(wire) && !inputs_free)
                || protected
                    .as_ref()
                    .is_some_and(|site| view.within(wire, site))
        };
        let leaf = |structure: &mut Structure, wire: usize| {
            if view.is_main_input(wire) {
                inputs_free && !pinned.contains(&wire) && !view.is_hub(wire)
            } else {
                structure.is_hint(view.name(wire))
            }
        };
        for with_paths in [false, true] {
            let mut constraints = region.constraints.clone();
            let mut unknowns = region.wires.clone();
            unknowns.retain(|wire| !assigned.contains_key(wire) || region.wires.contains(wire));
            if with_paths {
                for &start in &region.boundary {
                    if blocked(start) || view.is_hub(start) {
                        continue;
                    }
                    upstream_paths(
                        view,
                        structure,
                        start,
                        &blocked,
                        &leaf,
                        &mut constraints,
                        &mut unknowns,
                    );
                }
                // A hint leaf is also read elsewhere (a bit is checked to be boolean, a quotient
                // is multiplied back): close it over those constraints, freeing their other
                // wires and the checks of any component input among them.
                let leaves = unknowns
                    .iter()
                    .copied()
                    .filter(|wire| {
                        !region.wires.contains(wire)
                            && !view.is_main_input(*wire)
                            && structure.is_hint(view.name(*wire))
                    })
                    .collect::<Vec<_>>();
                for leaf_wire in leaves {
                    let mut added = BTreeSet::new();
                    let mut freed = BTreeSet::new();
                    for &position in &view.index[leaf_wire] {
                        added.insert(position);
                        for other in constraint_wires(&view.r1cs.constraints[position]) {
                            if other == 0 || unknowns.contains(&other) {
                                continue;
                            }
                            if (blocked(other) && !region.wires.contains(&other))
                                || view.is_hub(other)
                            {
                                continue;
                            }
                            freed.insert(other);
                            if structure.is_input(view.name(other)) {
                                added.extend(view.index[other].iter().copied());
                            }
                        }
                    }
                    for position in &added {
                        for other in constraint_wires(&view.r1cs.constraints[*position]) {
                            if other != 0
                                && !unknowns.contains(&other)
                                && !blocked(other)
                                && !view.is_hub(other)
                            {
                                freed.insert(other);
                            }
                        }
                    }
                    if added.len() <= LEAF_CLOSURE {
                        constraints.extend(added);
                        unknowns.extend(freed);
                    }
                }
                if unknowns.len() == region.wires.len() {
                    self.record.solves.push(SolveRecord {
                        carry: "without".to_owned(),
                        carried_constraints: 0,
                        carried_dropped: 0,
                        iteration,
                        cause: cause.to_owned(),
                        region: label.to_owned(),
                        with_paths,
                        unknowns: unknowns.len(),
                        constraints: constraints.len(),
                        outcome: "no_upstream_leaf".to_owned(),
                        hints_changed: 0,
                        inputs_changed: 0,
                    });
                    return Ok(false);
                }
            }
            let (carried, carried_dropped) =
                carried_constraints(view.r1cs, &self.failed_constraints, &unknowns, &value);
            // Retry without carry in the same slot and iteration for every non-SAT answer.
            let variants = if carried.is_empty() {
                vec![carried]
            } else {
                vec![carried, BTreeSet::new()]
            };
            for carry in variants {
                ensure!(
                    constraints.len() <= REGION_CONSTRAINTS * 2,
                    "repair region has too many constraints"
                );
                let query_constraints = constraints.union(&carry).copied().collect();
                let mut text = encode(
                    view.r1cs,
                    &query_constraints,
                    &unknowns,
                    &value,
                    SOLVE_TIMEOUT,
                );
                for (wire, target) in assigned {
                    if unknowns.contains(wire) {
                        let _ = writeln!(text, "(assert (= w{wire} {target}))");
                    }
                }
                if let Some(predicate) = predicate {
                    text.push_str(&encode_predicate(predicate, &unknowns, &value));
                }
                // Block repeated controllable proposals only in search queries. These
                // clauses must never enter predicate/closed-cone exclusion queries.
                for previous in &self.attempted_controls {
                    if !previous.is_empty() && previous.keys().all(|wire| unknowns.contains(wire)) {
                        let terms = previous
                            .iter()
                            .map(|(wire, value)| format!("(= w{wire} {value})"))
                            .collect::<Vec<_>>()
                            .join(" ");
                        let _ = writeln!(text, "(assert (not (and {terms})))");
                    }
                }
                let query_path = scratch.with_file_name(format!(
                    "{}-{}-{}",
                    scratch.file_name().unwrap_or_default().to_string_lossy(),
                    if with_paths { "paths" } else { "alone" },
                    if carry.is_empty() { "without" } else { "with" }
                ));
                let (verdict, model) =
                    run_z3(self.z3, text, &unknowns, &query_path, SOLVE_TIMEOUT)?;
                let mut solve = SolveRecord {
                    carry: if carry.is_empty() { "without" } else { "with" }.to_owned(),
                    carried_constraints: carry.len(),
                    carried_dropped,
                    iteration,
                    cause: cause.to_owned(),
                    region: label.to_owned(),
                    with_paths,
                    unknowns: unknowns.len(),
                    constraints: query_constraints.len(),
                    outcome: verdict.clone(),
                    hints_changed: 0,
                    inputs_changed: 0,
                };
                if verdict == "sat" {
                    let post_query =
                        if self.post_selected() && iteration + 1 == self.iterations_allowed {
                            let mut boundary = BTreeMap::new();
                            for &position in &query_constraints {
                                for wire in constraint_wires(&view.r1cs.constraints[position]) {
                                    if !unknowns.contains(&wire) {
                                        boundary.insert(wire, value(wire));
                                    }
                                }
                            }
                            Some(PostQuery {
                                iteration,
                                path: query_path.with_extension("smt2"),
                                constraints: query_constraints.clone(),
                                unknowns: unknowns.clone(),
                                boundary,
                                assigned: (*assigned).clone(),
                                model: model.clone(),
                                applied: BTreeMap::new(),
                            })
                        } else {
                            None
                        };
                    if self.context.boost.options.constraint_witness
                        && self.requirement.predicate.is_none()
                    {
                        let mut query = BTreeMap::new();
                        for &position in &query_constraints {
                            for wire in constraint_wires(&view.r1cs.constraints[position]) {
                                query.insert(wire, value(wire));
                            }
                        }
                        query.extend(assigned.clone());
                        query.extend(model.clone());
                        let mut scope = self
                            .start
                            .pinned
                            .iter()
                            .map(|&wire| (wire, current[wire].clone()))
                            .collect::<BTreeMap<_, _>>();
                        if !inputs_free {
                            for (wire, value) in current
                                .iter()
                                .enumerate()
                                .skip(view.first_input)
                                .take(view.inputs)
                            {
                                scope.insert(wire, value.clone());
                            }
                        }
                        self.snapshots.push(super::boost::Snapshot {
                            start: current.to_vec(),
                            query,
                            scope,
                            origin: "repair_region".into(),
                        });
                    }
                    let (hints, inputs, changed, controls) =
                        self.apply(structure, current, &model, inputs_free);
                    if changed {
                        if let Some(mut query) = post_query {
                            query.applied = controls.clone();
                            self.post_queries.push(query);
                        }
                    }
                    if !controls.is_empty() {
                        self.attempted_controls.push(controls);
                    }
                    solve.hints_changed = hints;
                    solve.inputs_changed = inputs;
                    solve.outcome = if changed {
                        "sat_applied"
                    } else {
                        "sat_no_effect"
                    }
                    .to_owned();
                    let alternative = try_paths_after(&solve.outcome);
                    self.record.solves.push(solve);
                    if changed {
                        return Ok(true);
                    }
                    if !alternative {
                        return Ok(false);
                    }
                    break;
                }
                self.record.solves.push(solve);
            }
        }
        Ok(false)
    }

    fn apply(
        &mut self,
        structure: &mut Structure,
        current: &[BigUint],
        model: &BTreeMap<usize, BigUint>,
        inputs_free: bool,
    ) -> (usize, usize, bool, BTreeMap<usize, BigUint>) {
        let _profile = super::profile_v24::span("repair.apply_model");
        ModelApplication {
            view: &self.view,
            start: self.start,
            overrides: &mut self.overrides,
            input: &mut self.input,
            changed_inputs: &mut self.changed_inputs,
        }
        .apply(structure, current, model, inputs_free)
    }
}

/// The concrete effects of a solver proposal, isolated from compilation/checking so
/// protected-input and ineffective-SAT invariants can be tested directly.
struct ModelApplication<'s, 'c> {
    view: &'s View<'c>,
    start: &'s Start,
    overrides: &'s mut Overrides,
    input: &'s mut Value,
    changed_inputs: &'s mut BTreeSet<String>,
}
impl ModelApplication<'_, '_> {
    fn apply(
        &mut self,
        structure: &mut Structure,
        current: &[BigUint],
        model: &BTreeMap<usize, BigUint>,
        inputs_free: bool,
    ) -> (usize, usize, bool, BTreeMap<usize, BigUint>) {
        let view = &self.view;
        let mut applied = BTreeMap::new();
        let mut inputs = 0;
        let mut changed = false;
        let mut touched = BTreeSet::new();
        for (wire, value) in model {
            if self.start.pinned.contains(wire)
                || self
                    .start
                    .protected_site
                    .as_ref()
                    .is_some_and(|site| view.within(*wire, site))
            {
                continue;
            }
            if &current[*wire] == value {
                continue;
            }
            let name = view.name(*wire).to_owned();
            if view.is_main_input(*wire) {
                if inputs_free
                    && set_input_leaf(self.input, name.trim_start_matches("main."), value).is_ok()
                {
                    self.changed_inputs
                        .insert(name.trim_start_matches("main.").to_owned());
                    applied.insert(*wire, value.clone());
                    inputs += 1;
                    changed = true;
                }
            } else if structure.is_hint(&name) {
                touched.insert(split_instance(&name).0.to_owned());
            }
        }
        // A rewritten hint fires only when its instance's inputs equal the key, so an
        // instance's hints are re-chosen together with its key. Hints chosen earlier for other
        // input values are dropped unless this model sets them again.
        let mut hints = 0;
        for instance in touched {
            let members = view
                .sym
                .by_name
                .range(format!("{instance}.")..format!("{instance}/"))
                .filter(|(member, _)| split_instance(&member[instance.len() + 1..]).0.is_empty())
                .filter_map(|(member, symbol)| {
                    Some((member.clone(), usize::try_from(symbol.wire).ok()?))
                })
                .collect::<Vec<_>>();
            let key_changed = members.iter().any(|(member, wire)| {
                structure.is_input(member)
                    && self.overrides.keys.get(member)
                        != Some(model.get(wire).unwrap_or(&current[*wire]))
            });
            for (member, wire) in &members {
                if structure.is_hint(member) {
                    match model.get(wire) {
                        Some(value) => {
                            hints += usize::from(value != &current[*wire]);
                            if value != &current[*wire] {
                                applied.insert(*wire, value.clone());
                            }
                            if self
                                .overrides
                                .rewrite
                                .insert(member.clone(), value.clone())
                                .as_ref()
                                != Some(value)
                            {
                                changed = true;
                            }
                        }
                        None if key_changed => {
                            changed |= self.overrides.rewrite.remove(member).is_some();
                        }
                        None => {}
                    }
                }
                let key = model.get(wire).unwrap_or(&current[*wire]).clone();
                if self.overrides.keys.insert(member.clone(), key.clone()) != Some(key) {
                    changed = true;
                }
            }
        }
        (hints, inputs, changed, applied)
    }
}

/// Compiles the sources with `edits` applied, under `directory`.
/// Compiles the sources with `edits` applied. With a cache, the build is kept under
/// `<cache>/edits/<key>` and reused; the key covers the compiler, the flags, the source and
/// library locations, every source text and the edits, so a hit is the same compilation.
fn compile_edits(
    context: &EvalContext,
    edits: &Edits,
    directory: &Path,
    o0: bool,
    ledger: &mut Ledger,
    label: &str,
) -> Result<Compiled> {
    let _profile = super::profile_v24::span("repair.compile_edits");
    if directory.exists() {
        fs::remove_dir_all(directory)?;
    }
    let build = match context.cache {
        None => directory.join("build"),
        Some(cache) => {
            let folder = cache
                .join("edits")
                .join(edits_cache_key(context, edits, o0)?);
            let stem = context
                .entry_relative
                .file_stem()
                .context("entrypoint has no file stem")?
                .to_string_lossy()
                .into_owned();
            // Callers write witnesses next to the build.
            fs::create_dir_all(directory)?;
            if folder.join("complete").exists() {
                ledger.record("compile", &format!("{label} (cache hit)"), 0.0, "ok", true);
                return Ok(Compiled {
                    r1cs: folder.join(format!("{stem}.r1cs")),
                    sym: folder.join(format!("{stem}.sym")),
                    js_dir: Some(folder.join(format!("{stem}_js"))),
                    stem,
                });
            }
            if folder.exists() {
                fs::remove_dir_all(&folder)?;
            }
            folder
        }
    };
    let workspace = directory.join("workspace");
    let (root, libraries) = super::profile_v24::measure("repair.workspace_prepare", || {
        write_edits_workspace(
            &workspace,
            context.source_root,
            context.libraries,
            context.sources,
            edits,
        )
    })?;
    let entry = root.join(&context.entry_relative);
    let compiled = compile(
        context.tools,
        &entry,
        &build,
        &root,
        &libraries,
        o0,
        true,
        ledger,
        Some(label),
    )?;
    if context.cache.is_some() {
        fs::write(build.join("complete"), b"")?;
    }
    Ok(compiled)
}

fn edits_cache_key(context: &EvalContext, edits: &Edits, o0: bool) -> Result<String> {
    super::edits_key(
        context.tools,
        &context.entry_relative,
        context.source_root,
        context.libraries,
        context.sources,
        edits,
        o0,
    )
}

fn sha256_text(text: &str) -> String {
    use sha2::{Digest, Sha256};
    format!("{:x}", Sha256::digest(text.as_bytes()))
}

/// Spaces in place of every character but newlines, so line numbers stay the same.
fn blank(text: &str) -> String {
    text.chars()
        .map(|character| if character == '\n' { '\n' } else { ' ' })
        .collect()
}

/// Checks that two `.sym` texts describe the same signal-to-wire mapping: every line has
/// the same label, wire, and component fields, and the names differ at most by a consistent
/// one-to-one renaming of anonymous components (`Template_<line>_<offset>`). circom derives
/// that offset from the byte position in the source file, so a rewritten `<--` statement
/// earlier in the same file moves it without changing any signal, wire, or constraint.
/// Returns the number of renamed anonymous components.
pub(crate) fn sym_equivalence(original: &str, other: &str) -> Result<usize> {
    super::speed_v24::sym_equivalence(original, other)
}

pub(crate) fn sym_equivalence_uncached(original: &str, other: &str) -> Result<usize> {
    sym_equivalence_lines(original, other, false)
}

/// Checks every row on every call. Exact row equality proves equal metadata and
/// signal paths, so only redundant tokenization is avoided; no earlier result is reused.
pub(crate) fn sym_equivalence_fast(original: &str, other: &str) -> Result<usize> {
    sym_equivalence_lines(original, other, true)
}

fn sym_equivalence_lines(original: &str, other: &str, exact_rows: bool) -> Result<usize> {
    let left = original.lines().collect::<Vec<_>>();
    let right = other.lines().collect::<Vec<_>>();
    ensure!(
        left.len() == right.len(),
        "the .sym files have {} and {} lines",
        left.len(),
        right.len()
    );
    let mut forward: BTreeMap<String, String> = BTreeMap::new();
    let mut backward: BTreeMap<String, String> = BTreeMap::new();
    let mut count = 0usize;
    for (number, (a, b)) in left.iter().zip(&right).enumerate() {
        if exact_rows && a == b {
            // Even equal malformed rows must fail at the same line as the old checker.
            ensure!(
                a.splitn(4, ',').count() == 4,
                ".sym line {} differs in label, wire, or component",
                number + 1
            );
            // Equal segments never update either renaming map in the legacy algorithm.
            continue;
        }
        let fields_a = a.splitn(4, ',').collect::<Vec<_>>();
        let fields_b = b.splitn(4, ',').collect::<Vec<_>>();
        ensure!(
            fields_a.len() == 4 && fields_b.len() == 4 && fields_a[..3] == fields_b[..3],
            ".sym line {} differs in label, wire, or component",
            number + 1
        );
        let (names_a, names_b) = (segments(fields_a[3]), segments(fields_b[3]));
        ensure!(
            names_a.len() == names_b.len(),
            ".sym line {} names a different path",
            number + 1
        );
        let mut prefix = String::new();
        for (segment_a, segment_b) in names_a.iter().zip(&names_b) {
            if segment_a != segment_b {
                let (base_a, index_a) =
                    segment_a.split_at(segment_a.find('[').unwrap_or(segment_a.len()));
                let (base_b, index_b) =
                    segment_b.split_at(segment_b.find('[').unwrap_or(segment_b.len()));
                let anonymous = |base: &str| {
                    let parts = base.rsplitn(3, '_').collect::<Vec<_>>();
                    (parts.len() == 3
                        && [parts[0], parts[1]].iter().all(|part| {
                            !part.is_empty() && part.bytes().all(|byte| byte.is_ascii_digit())
                        }))
                    .then(|| (parts[2].to_owned(), parts[1].to_owned()))
                };
                ensure!(
                    index_a == index_b
                        && anonymous(base_a).is_some()
                        && anonymous(base_a) == anonymous(base_b),
                    ".sym line {} renames {segment_a} to {segment_b}",
                    number + 1
                );
                let key = format!("{prefix}.{base_a}");
                let value = format!("{prefix}.{base_b}");
                match forward.get(&key) {
                    Some(existing) => ensure!(existing == &value, "inconsistent renaming of {key}"),
                    None => {
                        ensure!(
                            backward.insert(value.clone(), key.clone()).is_none(),
                            "two components renamed to {value}"
                        );
                        forward.insert(key, value);
                        count += 1;
                    }
                }
            }
            prefix.push('.');
            prefix.push_str(segment_a);
        }
    }
    Ok(count)
}

// Carry selection is isolated for regression coverage.
fn carried_constraints(
    r1cs: &R1cs,
    history: &BTreeSet<usize>,
    unknowns: &BTreeSet<usize>,
    value: &impl Fn(usize) -> BigUint,
) -> (BTreeSet<usize>, usize) {
    let kept: BTreeSet<_> = history
        .iter()
        .copied()
        .filter(|position| {
            let constraint = &r1cs.constraints[*position];
            constraint_wires(constraint)
                .iter()
                .any(|wire| unknowns.contains(wire))
                && residual(constraint, &r1cs.prime, value).is_zero()
        })
        .collect();
    let dropped = history.len() - kept.len();
    (kept, dropped)
}

#[cfg(test)]
pub(super) fn boost_test_model(
    r: &R1cs,
    targets: &BTreeMap<usize, BigUint>,
    folder: &Path,
) -> Result<BTreeMap<usize, BigUint>> {
    let wires = (1..r.shape.wires).collect();
    let constraints = (0..r.constraints.len()).collect();
    let value = |_: usize| BigUint::one();
    let mut query = encode(r, &constraints, &wires, &value, SOLVE_TIMEOUT);
    for (wire, value) in targets {
        writeln!(query, "(assert (= w{wire} {value}))")?;
    }
    let first = 1 + r.shape.public_outputs;
    for wire in first..first + r.shape.public_inputs + r.shape.private_inputs {
        if !targets.contains_key(&wire) {
            writeln!(query, "(assert (= w{wire} 0))")?;
        }
    }
    let z3 = super::resolve_executable(Path::new("z3"))?;
    let (verdict, model) = run_z3(&z3, query, &wires, &folder.join("model"), SOLVE_TIMEOUT)?;
    ensure!(verdict == "sat", "synthetic solver: {verdict}");
    Ok(model)
}

#[cfg(test)]
#[allow(clippy::too_many_arguments)]
pub(super) fn boost_test_projection(
    r: &R1cs,
    sym: &SymbolTable,
    source: &str,
    file: &Path,
    input: &Value,
    current: &[BigUint],
    model: &BTreeMap<usize, BigUint>,
) -> Result<bool> {
    let templates = super::parse_templates(file, source)?;
    let sources = BTreeMap::from([(file.to_path_buf(), source.to_owned())]);
    let mut structure = Structure::new(sym, &templates, &sources, Some("Main".into()));
    let index = super::refute::constraint_index(r);
    let view = View {
        r1cs: r,
        sym,
        index: &index,
        first_input: 1 + r.shape.public_outputs,
        inputs: r.shape.public_inputs + r.shape.private_inputs,
    };
    let start = Start {
        label: "test",
        stage: "test",
        input: input.clone(),
        overrides: Overrides::default(),
        candidate_hints: false,
        protected_site: Some("main".into()),
        inputs_free: true,
        pinned: BTreeSet::new(),
    };
    let mut overrides = Overrides::default();
    let mut input = input.clone();
    let mut changes = BTreeSet::new();
    Ok(ModelApplication {
        view: &view,
        start: &start,
        overrides: &mut overrides,
        input: &mut input,
        changed_inputs: &mut changes,
    }
    .apply(&mut structure, current, model, true)
    .2)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn carry_uses_only_repaired_constraints_sharing_query_unknowns() {
        let lc = |wire| LinearCombination::from([(wire, BigUint::one())]);
        let constraint = |wire| crate::candidate_review::r1cs::Constraint {
            a: lc(wire),
            b: lc(0),
            c: lc(0),
        };
        let r1cs = R1cs {
            prime: 101u32.into(),
            shape: crate::candidate_review::schema::R1csShape {
                wires: 3,
                labels: 3,
                public_outputs: 0,
                public_inputs: 2,
                private_inputs: 0,
                constraints: 2,
            },
            constraints: vec![constraint(1), constraint(2)],
            wire_labels: vec![0, 1, 2],
        };
        let unknowns = BTreeSet::from([1]);
        let history = BTreeSet::from([0, 1]);
        let failed = |wire| if wire == 0 { 1u32.into() } else { 2u32.into() };
        let (carry, dropped) = carried_constraints(&r1cs, &history, &unknowns, &failed);
        assert!(
            carry.is_empty(),
            "simultaneously failing A/B must not be carried"
        );
        assert_eq!(dropped, 2);
        assert!(
            !encode(&r1cs, &carry, &unknowns, &failed, SOLVE_TIMEOUT).contains("(assert false)")
        );
        let repaired = |_wire| BigUint::one();
        let (carry, dropped) = carried_constraints(&r1cs, &history, &unknowns, &repaired);
        assert_eq!(
            carry,
            BTreeSet::from([0]),
            "iteration 1 keeps repaired A only"
        );
        assert_eq!(dropped, 1);
        assert!(
            carried_constraints(&r1cs, &BTreeSet::new(), &unknowns, &repaired)
                .0
                .is_empty(),
            "iteration 0 has no previous failures"
        );
    }

    #[test]
    fn cycles_and_iteration_limits_do_not_grant_more_search_slots() {
        let mut history = SearchHistory::new("initial".to_owned(), MAX_ITERATIONS);
        assert_eq!(history.next_iteration(), Some(0));
        assert!(!history.observe("initial".to_owned()));
        let mut history = SearchHistory::new("initial".to_owned(), MAX_ITERATIONS);
        for iteration in 0..MAX_ITERATIONS {
            assert_eq!(history.next_iteration(), Some(iteration));
            assert!(history.observe(format!("new-{iteration}")));
        }
        assert_eq!(history.next_iteration(), None);
        let mut empty = SearchHistory::new("initial".to_owned(), 0);
        assert_eq!(empty.next_iteration(), None);
    }

    #[test]
    fn concrete_model_keeps_pinned_inputs_and_protected_hints() {
        let r1cs = R1cs {
            prime: BigUint::from(101u32),
            shape: crate::candidate_review::schema::R1csShape {
                wires: 4,
                labels: 4,
                public_outputs: 0,
                public_inputs: 2,
                private_inputs: 0,
                constraints: 0,
            },
            constraints: vec![],
            wire_labels: vec![0, 1, 2, 3],
        };
        let sym = SymbolTable::parse(b"1,1,0,main.x\n2,2,0,main.y\n3,3,1,main.inner.out\n", &r1cs)
            .unwrap();
        let source = "template Inner(){ signal output out; out <-- 3; } template Main(){ signal input x; signal input y; component inner = Inner(); }";
        let file = PathBuf::from("test.circom");
        let templates = super::super::source::parse_templates(&file, source).unwrap();
        let sources = BTreeMap::from([(file, source.to_owned())]);
        let mut structure = Structure::new(&sym, &templates, &sources, Some("Main".to_owned()));
        assert!(structure.is_hint("main.inner.out"));
        let mut index = vec![vec![]; 4];
        index[2] = vec![0; HUB_DEGREE + 1];
        let view = View {
            r1cs: &r1cs,
            sym: &sym,
            index: &index,
            first_input: 1,
            inputs: 2,
        };
        let start = Start {
            label: "test",
            stage: "test",
            input: serde_json::json!({"x":"1", "y":"2"}),
            overrides: Overrides::default(),
            candidate_hints: true,
            protected_site: Some("main.inner".to_owned()),
            inputs_free: true,
            pinned: BTreeSet::from([1]),
        };
        let mut overrides = Overrides::default();
        let mut input = start.input.clone();
        let mut changes = BTreeSet::new();
        let result = ModelApplication {
            view: &view,
            start: &start,
            overrides: &mut overrides,
            input: &mut input,
            changed_inputs: &mut changes,
        }
        .apply(
            &mut structure,
            &[1u32, 1, 2, 3].map(BigUint::from),
            &BTreeMap::from([(1, 9u32.into()), (2, 7u32.into()), (3, 4u32.into())]),
            true,
        );
        assert_eq!(input, serde_json::json!({"x":"1", "y":"7"}));
        assert!(overrides.rewrite.is_empty());
        assert_eq!(result, (0, 1, true, BTreeMap::from([(2, 7u32.into())])));
        let result = ModelApplication {
            view: &view,
            start: &start,
            overrides: &mut overrides,
            input: &mut input,
            changed_inputs: &mut changes,
        }
        .apply(
            &mut structure,
            &[1u32, 1, 7, 3].map(BigUint::from),
            &BTreeMap::from([(1, 9u32.into()), (3, 4u32.into())]),
            true,
        );
        assert_eq!(
            result,
            (0, 0, false, BTreeMap::new()),
            "SAT with no permitted concrete effect must try the existing alternative"
        );
        assert!(try_paths_after("sat_no_effect"));
    }

    #[test]
    fn incomplete_solver_models_are_tool_errors() {
        use std::os::unix::fs::PermissionsExt;
        let dir = tempfile::tempdir().unwrap();
        let fake = dir.path().join("z3");
        fs::write(&fake, "#!/bin/sh\nprintf 'sat\n((w1 0))\n'\n").unwrap();
        fs::set_permissions(&fake, fs::Permissions::from_mode(0o755)).unwrap();
        assert!(run_z3(
            &fake,
            String::new(),
            &BTreeSet::from([1, 2]),
            &dir.path().join("model"),
            Duration::from_secs(1)
        )
        .is_err());
    }

    #[test]
    fn ineffective_sat_tries_paths_but_search_unsat_never_proves_exclusion() {
        assert!(try_paths_after("sat_no_effect"));
        assert!(try_paths_after("unsat"));
        assert!(!try_paths_after("sat_applied"));
        assert!(!try_paths_after("tool_error"));
    }

    #[test]
    fn instances_split_on_unbracketed_dots() {
        assert_eq!(segments("main.a[1].b"), ["main", "a[1]", "b"]);
        assert_eq!(segments("main.x[a.b]"), ["main", "x[a.b]"]);
        assert_eq!(blank("a === b;\n c"), "        \n  ");
    }

    #[test]
    fn sym_files_may_differ_only_by_anonymous_offsets() {
        let original = "1,1,0,main.a\n2,2,1,main.t.AssertBit_13_210[0].in\n3,3,2,main.t.AssertBit_13_210[1].in\n";
        let moved = "1,1,0,main.a\n2,2,1,main.t.AssertBit_13_663[0].in\n3,3,2,main.t.AssertBit_13_663[1].in\n";
        assert_eq!(sym_equivalence(original, original).unwrap(), 0);
        assert_eq!(sym_equivalence(original, moved).unwrap(), 1);
        // A different line, a different wire, an inconsistent renaming, or a non-anonymous
        // rename is not equivalent.
        let other_line = moved.replace("_13_663", "_14_663");
        assert!(sym_equivalence(original, &other_line).is_err());
        assert!(sym_equivalence(original, &moved.replace("2,2,1", "2,3,1")).is_err());
        let split = "1,1,0,main.a\n2,2,1,main.t.AssertBit_13_663[0].in\n3,3,2,main.t.AssertBit_13_700[1].in\n";
        assert!(sym_equivalence(original, split).is_err());
        assert!(sym_equivalence(original, &original.replace("main.a", "main.b")).is_err());
        assert!(sym_equivalence(original, "1,1,0,main.a\n").is_err());
    }

    fn compare_sym_checkers(original: &str, other: &str) -> std::result::Result<usize, String> {
        let legacy =
            sym_equivalence_uncached(original, other).map_err(|error| format!("{error:#}"));
        let fast = sym_equivalence_fast(original, other).map_err(|error| format!("{error:#}"));
        assert_eq!(fast, legacy, "original={original:?}, other={other:?}");
        legacy
    }

    fn sym_differential_rows() -> (Vec<String>, Vec<String>) {
        let original = [
            "1,1,0,main.x",
            "2,2,1,main.Foo_7_10.y",
            // An equal row does not consult or alter the previous renaming maps.
            "3,3,1,main.Foo_7_10.z",
            "4,4,1,main.Foo_7_10[1].x",
            "5,5,2,main.Foo_7_10.Bar_8_20[2].x",
            "6,6,3,main.Foo_7_11.other",
            "7,7,4,main.한글[a.b].δ",
        ]
        .map(str::to_owned)
        .to_vec();
        let other = [
            "1,1,0,main.x",
            "2,2,1,main.Foo_7_12.y",
            "3,3,1,main.Foo_7_10.z",
            "4,4,1,main.Foo_7_12[1].x",
            "5,5,2,main.Foo_7_12.Bar_8_22[2].x",
            "6,6,3,main.Foo_7_13.other",
            "7,7,4,main.한글[a.b].δ",
        ]
        .map(str::to_owned)
        .to_vec();
        (original, other)
    }

    #[test]
    fn fast_sym_rows_preserve_equal_malformed_and_unusual_rows() {
        for row in [
            "",
            "\n",
            "1",
            "1,1",
            "1,1,0",
            "1,1,0,",
            ",,,",
            "1,1,0,main.x,extra",
            "x,+y,,main.한글[a.b].δ",
            "1,1,0,main.x.",
            "1,1,0,main..x",
            "1,1,0,main.x[",
            "1,1,0,main.x]",
            "1,1,0,main.x\r\n2,2,0,main.y\r\n",
        ] {
            let _ = compare_sym_checkers(row, row);
            let text = format!("0,0,0,main.prefix\n{row}");
            let _ = compare_sym_checkers(&text, &text);
        }
        assert_eq!(compare_sym_checkers("", ""), Ok(0));
        assert_eq!(compare_sym_checkers("1,1,0,", "1,1,0,"), Ok(0));
        assert!(compare_sym_checkers("invalid", "invalid").is_err());
        assert_eq!(
            compare_sym_checkers("1,1,0,main.x\r\n", "1,1,0,main.x\n"),
            Ok(0)
        );
        assert_eq!(
            compare_sym_checkers("1,1,0,main.x.", "1,1,0,main.x"),
            Ok(0),
            "preserve the legacy segment parser's treatment of trailing dots"
        );
    }

    #[test]
    fn fast_sym_rows_preserve_cross_line_renaming_and_conflicts() {
        let (original, other) = sym_differential_rows();
        let left = original.join("\n");
        assert_eq!(compare_sym_checkers(&left, &other.join("\n")), Ok(3));
        for (index, replacement) in [
            (0, "1,2,0,main.x"),
            (0, "1,1,1,main.x"),
            (0, "1,1,0,main.x.child"),
            (0, "1,1,0,main.nonanonymous"),
            (3, "4,4,1,main.Foo_7_14[1].x"),
            (3, "4,4,1,main.Foo_7_12[2].x"),
            (3, "4,4,1,main.Foo_8_12[1].x"),
            (4, "5,5,2,main.Foo_7_12.Bar_8_23[3].x"),
            (5, "6,6,3,main.Foo_7_12.other"),
        ] {
            let mut changed = other.clone();
            changed[index] = replacement.to_owned();
            assert!(compare_sym_checkers(&left, &changed.join("\n")).is_err());
        }
    }

    #[test]
    fn fast_sym_rows_match_legacy_for_1000_deterministic_mutations() {
        let mut state = 0x9e37_79b9_7f4a_7c15u64;
        let mut next = || {
            state = state
                .wrapping_mul(6_364_136_223_846_793_005)
                .wrapping_add(1_442_695_040_888_963_407);
            (state >> 32) as usize
        };
        let mut successes = 0;
        let mut failures = 0;
        for case in 0..1000 {
            let (mut original, mut other) = sym_differential_rows();
            let index = next() % original.len();
            match case % 16 {
                0 => {}
                1 => other[index] = original[index].clone(),
                2 => {
                    original[index] = "invalid".to_owned();
                    other[index] = original[index].clone();
                }
                3 => other[index] = format!("{},999,0,main.x", next()),
                4 => other[index].push_str(".extra"),
                5 => {
                    other.remove(index);
                }
                6 => other[index] = original[index].replace("main", "changed"),
                7 => other[3] = "4,4,1,main.Foo_7_14[1].x".to_owned(),
                8 => other[5] = "6,6,3,main.Foo_7_12.other".to_owned(),
                9 => {
                    let equal = format!("{},1,0,main.equal[{}]", next(), next());
                    original.insert(index, equal.clone());
                    other.insert(index, equal);
                }
                10 => {
                    let swap = next() % original.len();
                    original.swap(index, swap);
                    other.swap(index, swap);
                }
                11 => {
                    original[index] = "x,+y,,main.한글[a.b].δ".to_owned();
                    other[index] = original[index].clone();
                }
                12 => {
                    original[index] = "1,1,0,main.same,extra".to_owned();
                    other[index] = original[index].clone();
                }
                13 => other[index].push('['),
                14 => {
                    original[index] = "1,1,0,".to_owned();
                    other[index] = original[index].clone();
                }
                _ => {
                    original[index] = "1,1".to_owned();
                    other[index] = original[index].clone();
                }
            }
            let mut left = original.join(if next() % 2 == 0 { "\n" } else { "\r\n" });
            let mut right = other.join(if next() % 2 == 0 { "\n" } else { "\r\n" });
            if next() % 2 == 0 {
                left.push('\n');
            }
            if next() % 2 == 0 {
                right.push('\n');
            }
            if compare_sym_checkers(&left, &right).is_ok() {
                successes += 1;
            } else {
                failures += 1;
            }
        }
        assert!(successes >= 100 && failures >= 100);
    }
}
