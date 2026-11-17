//! L-02 reverse input synthesis: find entrypoint public inputs whose honest computation
//! produces given values on intermediate wires (the call-site inputs of a candidate).
//!
//! Both stages only propose inputs. A proposal counts only after the honest O0 generator,
//! run on it, reproduces every target value; the caller then re-verifies the full witness.
//!
//! (a) Concrete back-propagation: walk a shortest constraint path from a target to a free
//!     public input, keep every wire off the path at its current honest value, and solve
//!     each constraint for the next wire when it is linear in that wire.
//! (b) Bounded local solving: encode the constraints around the targets (off-cone wires
//!     frozen) as integer arithmetic modulo p for z3, with a time limit.

use std::{
    collections::{BTreeMap, BTreeSet, VecDeque},
    fmt::Write as _,
    path::Path,
    time::Duration,
};

use anyhow::{bail, Context, Result};
use num_bigint::BigUint;
use num_traits::{One, Zero};

use super::super::r1cs::{Constraint, LinearCombination, R1cs};
use super::refute;

/// Limits for stage (a).
pub(crate) const MAX_PATHS: usize = 6;
pub(crate) const MAX_TRIES: usize = 12;
pub(crate) const MAX_ROUNDS: usize = 3;
const PATH_SEARCH_WIRES: usize = 20_000;
const PATH_SEARCH_DEPTH: usize = 48;

/// Limits for stage (b).
pub(crate) const CONE_DEPTH: usize = 6;
const CONE_UNKNOWNS: usize = 300;
const CONE_CONSTRAINTS: usize = 600;
/// Wires used by more constraints than this (shared parameters such as a scaling input)
/// are frozen at their reference value instead of pulling every user into the cone.
const HUB_DEGREE: usize = 32;
pub(crate) const SOLVER_TIMEOUT: Duration = Duration::from_secs(20);
/// Per-branch timeout and per-site budget for the exclusion sweep.
pub(crate) const BRANCH_TIMEOUT: Duration = Duration::from_secs(5);
/// Total time the exclusion sweep may use per candidate (all sites together).
pub(crate) const CANDIDATE_SWEEP_BUDGET: Duration = Duration::from_secs(20);

/// Fixed reservations cannot let an earlier class spend a later class's search time.
/// Remainder nanoseconds go to the earliest classes in the existing class order.
pub(crate) fn class_sweep_budget(
    total: Duration,
    class_count: usize,
    class_index: usize,
) -> Duration {
    if class_count == 0 || class_index >= class_count {
        return Duration::ZERO;
    }
    let count = class_count as u128;
    let nanos =
        total.as_nanos() / count + u128::from((class_index as u128) < total.as_nanos() % count);
    Duration::new(
        (nanos / 1_000_000_000) as u64,
        (nanos % 1_000_000_000) as u32,
    )
}

/// Only unused earlier reservations are carried; future reservations remain untouched.
pub(crate) fn class_sweep_assignment(
    total: Duration,
    class_count: usize,
    class_index: usize,
    carry: Duration,
) -> Duration {
    class_sweep_budget(total, class_count, class_index) + carry
}

/// The O0 view shared by both stages.
pub(crate) struct Graph<'a> {
    pub(crate) r1cs: &'a R1cs,
    /// Wire → constraints that mention it.
    pub(crate) index: &'a [Vec<usize>],
    /// Wires that may never change: inputs bound directly to the site, and wires inside
    /// the site instance (they are computed from the site inputs, not the other way).
    pub(crate) blocked: &'a dyn Fn(usize) -> bool,
    /// Wires inside the site instance. Constraints that mention them (other than the
    /// targets) describe the component, not its context, and stay out of the solver cone.
    pub(crate) internal: &'a dyn Fn(usize) -> bool,
}

impl Graph<'_> {
    fn public_inputs(&self) -> std::ops::Range<usize> {
        let first = 1 + self.r1cs.shape.public_outputs;
        first..first + self.r1cs.shape.public_inputs + self.r1cs.shape.private_inputs
    }

    pub(crate) fn is_free_input(&self, wire: usize) -> bool {
        self.public_inputs().contains(&wire) && !(self.blocked)(wire)
    }
}

/// One path step: the constraint and the wire it is solved for.
pub(crate) type ConstraintPath = Vec<(usize, usize)>;

/// Shortest constraint paths from `start` to free public inputs, several per input when
/// the layered (breadth-first) graph branches, shortest first.
pub(crate) fn find_paths(graph: &Graph, start: usize, limit: usize) -> Vec<ConstraintPath> {
    let _profile = super::profile_v24::span("synthesis.find_paths");
    // Layer the graph by breadth-first distance from `start`; inputs end a path.
    let mut distance = BTreeMap::from([(start, 0usize)]);
    let mut queue = VecDeque::from([start]);
    while let Some(wire) = queue.pop_front() {
        if distance.len() > PATH_SEARCH_WIRES {
            break;
        }
        let level = distance[&wire];
        if level >= PATH_SEARCH_DEPTH || (wire != start && graph.is_free_input(wire)) {
            continue;
        }
        for &position in &graph.index[wire] {
            for next in constraint_wires(&graph.r1cs.constraints[position]) {
                if next != 0 && !(graph.blocked)(next) && !distance.contains_key(&next) {
                    distance.insert(next, level + 1);
                    queue.push_back(next);
                }
            }
        }
    }
    // Enumerate paths that step one layer outward each time.
    let mut paths = Vec::new();
    let mut stack = Vec::new();
    let mut budget = PATH_SEARCH_WIRES;
    enumerate(
        graph,
        &distance,
        start,
        start,
        &mut stack,
        &mut paths,
        limit * 4,
        &mut budget,
    );
    paths.sort_by_key(Vec::len);
    paths.truncate(limit);
    paths
}

#[allow(clippy::too_many_arguments)]
fn enumerate(
    graph: &Graph,
    distance: &BTreeMap<usize, usize>,
    start: usize,
    wire: usize,
    stack: &mut ConstraintPath,
    paths: &mut Vec<ConstraintPath>,
    limit: usize,
    budget: &mut usize,
) {
    if paths.len() >= limit || *budget == 0 {
        return;
    }
    *budget -= 1;
    if wire != start && graph.is_free_input(wire) {
        paths.push(stack.clone());
        return;
    }
    let level = distance[&wire];
    for &position in &graph.index[wire] {
        for next in constraint_wires(&graph.r1cs.constraints[position]) {
            if distance.get(&next) == Some(&(level + 1)) {
                stack.push((position, next));
                enumerate(graph, distance, start, next, stack, paths, limit, budget);
                stack.pop();
            }
        }
    }
}

/// Solves the path for its final public input, given `target = value` and the current
/// honest values for every wire not yet solved. None when a step is not linear in the
/// wire it must solve for, or its coefficient is zero.
pub(crate) fn solve_path(
    r1cs: &R1cs,
    current: &[BigUint],
    target: usize,
    value: &BigUint,
    path: &ConstraintPath,
) -> Option<(usize, BigUint)> {
    let _profile = super::profile_v24::span("synthesis.solve_path");
    let prime = &r1cs.prime;
    let mut overlay = BTreeMap::from([(target, value.clone())]);
    for &(position, wire) in path {
        let constraint = &r1cs.constraints[position];
        let at = |trial: u32| {
            residual(constraint, prime, |w| {
                if w == wire {
                    BigUint::from(trial)
                } else {
                    overlay.get(&w).unwrap_or(&current[w]).clone()
                }
            })
        };
        let (f0, f1, f2) = (at(0), at(1), at(2));
        let second = (&f2 + &f0 + prime + prime - &f1 - &f1) % prime;
        let slope = (&f1 + prime - &f0) % prime;
        if !second.is_zero() || slope.is_zero() {
            return None;
        }
        let inverse = slope.modpow(&(prime - BigUint::from(2u32)), prime);
        let solved = (prime - &f0) % prime * inverse % prime;
        overlay.insert(wire, solved);
    }
    let (_, last) = *path.last()?;
    Some((last, overlay.remove(&last)?))
}

/// A closed cone: every wire outside `unknowns` is the constant wire or has a value in
/// `fixed` (only candidate-determined values: the site's input values and the entrypoint
/// inputs bound directly to them). Shared high-degree wires are left free and not expanded
/// (a relaxation), so an unsatisfiable cone holds for every entrypoint input.
#[derive(Clone)]
pub(crate) struct Cone {
    pub(crate) constraints: Vec<usize>,
    pub(crate) unknowns: BTreeSet<usize>,
}

pub(crate) enum ConeOutcome {
    /// Values of free public inputs from a satisfying model.
    Model(BTreeMap<usize, BigUint>),
    /// Satisfiable, but no model was requested.
    Sat,
    /// z3 returned unsat. `propagation` records whether the cheap pass refuted it too.
    Unsat {
        propagation: bool,
    },
    /// Only the cheap propagation pass refuted it; z3 did not confirm in time.
    PropagationOnly,
    Timeout,
}

pub(crate) struct ConeResult {
    pub(crate) outcome: ConeOutcome,
    pub(crate) cone: Option<Cone>,
}

/// Breadth-first closed cone from `starts`, `depth` layers deep. With `first`, the first
/// layer uses only that constraint (a branch of the start wire). None when it exceeds the
/// size limits.
pub(crate) fn build_cone(
    graph: &Graph,
    fixed: &BTreeMap<usize, BigUint>,
    starts: &[usize],
    first: Option<usize>,
    depth: usize,
) -> Option<Cone> {
    let mut unknowns = BTreeSet::new();
    let mut chosen = BTreeSet::new();
    let mut seen = starts.iter().copied().collect::<BTreeSet<_>>();
    let mut frontier = seen.clone();
    for layer in 0..depth {
        let mut next = BTreeSet::new();
        for wire in &frontier {
            let positions = match (layer, first) {
                (0, Some(position)) => vec![position],
                _ => graph.index[*wire].clone(),
            };
            for position in positions {
                let wires = constraint_wires(&graph.r1cs.constraints[position]);
                // Constraints of the component itself (site-internal wires other than the
                // fixed site inputs) are left out; candidate values satisfy them.
                if wires
                    .iter()
                    .any(|other| (graph.internal)(*other) && !fixed.contains_key(other))
                    || !chosen.insert(position)
                {
                    continue;
                }
                for other in wires {
                    if other == 0 || !seen.insert(other) {
                        continue;
                    }
                    if !fixed.contains_key(&other) {
                        unknowns.insert(other);
                    }
                    if graph.index[other].len() <= HUB_DEGREE {
                        next.insert(other);
                    }
                }
            }
        }
        if unknowns.len() > CONE_UNKNOWNS || chosen.len() > CONE_CONSTRAINTS {
            return None;
        }
        if next.is_empty() {
            break;
        }
        frontier = next;
    }
    Some(Cone {
        constraints: chosen.into_iter().collect(),
        unknowns,
    })
}

/// The deepest closed cone within the size limits, or None if even one layer is too large.
pub(crate) fn largest_cone(
    graph: &Graph,
    fixed: &BTreeMap<usize, BigUint>,
    starts: &[usize],
    first: Option<usize>,
) -> Option<Cone> {
    let _profile = super::profile_v24::span("synthesis.largest_cone");
    let mut best = None;
    for depth in 1..=CONE_DEPTH {
        match build_cone(graph, fixed, starts, first, depth) {
            Some(cone) => {
                let grew = best.as_ref().is_none_or(|previous: &Cone| {
                    previous.constraints.len() < cone.constraints.len()
                });
                best = Some(cone);
                if !grew {
                    break;
                }
            }
            None => break,
        }
    }
    best
}

/// Solves a closed cone: the cheap propagation pass first, then z3.
pub(crate) fn solve_cone(
    graph: &Graph,
    fixed: &BTreeMap<usize, BigUint>,
    cone: Cone,
    want_model: bool,
    timeout: Duration,
    z3: &Path,
    scratch: &Path,
) -> Result<ConeResult> {
    let _profile = super::profile_v24::span("synthesis.solve_cone");
    let prime = &graph.r1cs.prime;
    let subset = cone
        .constraints
        .iter()
        .map(|position| (*position, &graph.r1cs.constraints[*position]))
        .collect::<Vec<_>>();
    let fixed32 = fixed
        .iter()
        .map(|(wire, value)| (*wire as u32, value.clone()))
        .collect::<BTreeMap<_, _>>();
    let free = cone.unknowns.iter().map(|wire| *wire as u32).collect();
    let propagation = refute::refute_subset(&subset, &free, &fixed32, prime).is_some();
    let mut text = String::new();
    let timeout_millis = if super::search_v27::enabled() {
        timeout.as_millis().max(1)
    } else {
        timeout.as_millis()
    };
    writeln!(text, "(set-option :timeout {timeout_millis})")?;
    for wire in &cone.unknowns {
        writeln!(text, "(declare-const w{wire} Int)")?;
        writeln!(text, "(assert (and (<= 0 w{wire}) (< w{wire} {prime})))")?;
    }
    for (_, constraint) in &subset {
        let [a, b, c] = [&constraint.a, &constraint.b, &constraint.c]
            .map(|combination| smt_combination(combination, &cone.unknowns, fixed, prime));
        writeln!(text, "(assert (= (mod (- (* {a} {b}) {c}) {prime}) 0))")?;
        // A constraint whose only unknown has exactly the roots {0, 1} also gets the
        // equivalent bound; it does not change the solution set but helps the solver.
        let unknown = constraint_wires(constraint)
            .into_iter()
            .filter(|wire| cone.unknowns.contains(wire))
            .collect::<Vec<_>>();
        if let [wire] = unknown.as_slice() {
            let at = |trial: u32| {
                residual(constraint, prime, |other| {
                    if other == *wire {
                        BigUint::from(trial)
                    } else {
                        fixed.get(&other).cloned().unwrap_or_default()
                    }
                })
            };
            if at(0).is_zero() && at(1).is_zero() && !at(2).is_zero() {
                writeln!(text, "(assert (<= w{wire} 1))")?;
            }
        }
    }
    writeln!(text, "(check-sat)")?;
    // A model reports every unknown: free inputs build the proposed entrypoint input, and
    // hint-assigned wires can be injected when the generator does not reproduce them.
    if want_model && !cone.unknowns.is_empty() {
        let names = cone
            .unknowns
            .iter()
            .map(|wire| format!("w{wire}"))
            .collect::<Vec<_>>()
            .join(" ");
        writeln!(text, "(get-value ({names}))")?;
    }
    let output = super::solver::run(z3, text, scratch, timeout)?;
    let timed_out = output.starts_with("timeout\n");
    let verdict = output.lines().next().unwrap_or("").trim();
    let outcome = if verdict == "unsat" {
        ConeOutcome::Unsat { propagation }
    } else if propagation {
        ConeOutcome::PropagationOnly
    } else if timed_out || verdict == "unknown" || verdict == "timeout" {
        ConeOutcome::Timeout
    } else if verdict == "sat" {
        if want_model && !cone.unknowns.is_empty() {
            let model = parse_values(&output)?;
            anyhow::ensure!(
                model.keys().copied().collect::<BTreeSet<_>>() == cone.unknowns,
                "z3 model does not cover exactly the requested wires"
            );
            ConeOutcome::Model(model)
        } else {
            ConeOutcome::Sat
        }
    } else {
        bail!(
            "unexpected z3 output: {}",
            output.lines().next().unwrap_or("")
        );
    };
    Ok(ConeResult {
        outcome,
        cone: Some(cone),
    })
}

/// Searches the smallest original-constraint subsets before attempting a larger model.
/// Only candidate-determined values belong in `fixed`; the cheap pass merely selects
/// promising subsets, and every returned proof still requires a solver UNSAT answer.
pub(crate) fn candidate_contradiction_sweep(
    graph: &Graph,
    fixed: &BTreeMap<usize, BigUint>,
    starts: &[usize],
    z3: &Path,
    directory: &Path,
    budget: Duration,
) -> Result<Sweep> {
    let started = std::time::Instant::now();
    let mut sweep = Sweep {
        proof: None,
        branches_tried: 0,
        propagation_only: 0,
        exhausted: false,
    };
    let mut visited = BTreeSet::new();
    let mut scanned = 0usize;
    let mut oversized = 0usize;
    'search: for depth in 1..=2 {
        for &start in starts {
            for &position in &graph.index[start] {
                if budget.saturating_sub(started.elapsed()) < Duration::from_millis(1) {
                    sweep.exhausted = true;
                    break 'search;
                }
                let Some(cone) = build_cone(graph, fixed, &[start], Some(position), depth) else {
                    oversized += 1;
                    continue;
                };
                if cone.constraints.is_empty() || !visited.insert(cone.constraints.clone()) {
                    continue;
                }
                scanned += 1;
                if !candidate_subset_contradiction(graph.r1cs, &cone, fixed, started, budget) {
                    continue;
                }
                let remaining = budget.saturating_sub(started.elapsed());
                if remaining < Duration::from_millis(1) {
                    sweep.exhausted = true;
                    break 'search;
                }
                sweep.branches_tried += 1;
                let result = solve_cone(
                    graph,
                    fixed,
                    cone,
                    false,
                    BRANCH_TIMEOUT.min(remaining),
                    z3,
                    &directory.join(format!("candidate-small-{:03}", sweep.branches_tried)),
                )?;
                match result.outcome {
                    ConeOutcome::Unsat { propagation } => {
                        sweep.proof = result.cone.map(|cone| (cone, propagation));
                        break 'search;
                    }
                    ConeOutcome::PropagationOnly => sweep.propagation_only += 1,
                    _ => {}
                }
            }
        }
    }
    super::search_v27::record(serde_json::json!({
        "kind": "candidate_contradiction_sweep",
        "directory": directory,
        "order": "depth_1_then_2_start_wire_constraint_index",
        "fixed_scope": "candidate_only",
        "subsets_scanned": scanned,
        "size_limit_exceeded": oversized,
        "branches_tried": sweep.branches_tried,
        "budget_zero_unattempted": budget.is_zero(),
        "budget_exhausted": sweep.exhausted,
        "proof_found": sweep.proof.is_some(),
    }));
    Ok(sweep)
}

/// This selection pass does no Boolean enumeration. The solver remains responsible for
/// confirming a contradiction; later search still includes subsets skipped here.
fn candidate_subset_contradiction(
    r1cs: &R1cs,
    cone: &Cone,
    fixed: &BTreeMap<usize, BigUint>,
    started: std::time::Instant,
    budget: Duration,
) -> bool {
    let mut known = fixed.clone();
    let prime = &r1cs.prime;
    loop {
        let mut changed = false;
        for &position in &cone.constraints {
            if started.elapsed() >= budget {
                return false;
            }
            let constraint = &r1cs.constraints[position];
            let unknowns = constraint_wires(constraint)
                .into_iter()
                .filter(|wire| *wire != 0 && !known.contains_key(wire))
                .collect::<Vec<_>>();
            match unknowns.as_slice() {
                [] => {
                    if !residual(constraint, prime, |wire| known[&wire].clone()).is_zero() {
                        return true;
                    }
                }
                [wire] => {
                    let at = |trial: u32| {
                        residual(constraint, prime, |other| {
                            if other == *wire {
                                BigUint::from(trial)
                            } else {
                                known[&other].clone()
                            }
                        })
                    };
                    let (f0, f1, f2) = (at(0), at(1), at(2));
                    let second = (&f2 + &f0 + prime + prime - &f1 - &f1) % prime;
                    if !second.is_zero() {
                        continue;
                    }
                    let slope = (&f1 + prime - &f0) % prime;
                    if slope.is_zero() {
                        if !f0.is_zero() {
                            return true;
                        }
                    } else {
                        let inverse = slope.modpow(&(prime - BigUint::from(2u32)), prime);
                        known.insert(*wire, (prime - f0) * inverse % prime);
                        changed = true;
                    }
                }
                _ => {}
            }
        }
        if !changed {
            return false;
        }
    }
}

struct BranchDiagnostics<'a> {
    kind: &'static str,
    directory: &'a Path,
    branches_tried: usize,
    size_limit_exceeded: usize,
    budget_zero_unattempted: bool,
    outcome: &'static str,
}

impl<'a> BranchDiagnostics<'a> {
    fn new(kind: &'static str, directory: &'a Path, budget: Duration) -> Self {
        Self {
            kind,
            directory,
            branches_tried: 0,
            size_limit_exceeded: 0,
            budget_zero_unattempted: budget.is_zero(),
            outcome: "all_branches_finished",
        }
    }
}

impl Drop for BranchDiagnostics<'_> {
    fn drop(&mut self) {
        if !super::search_v27::enabled() {
            return;
        }
        super::search_v27::record(serde_json::json!({
            "kind": self.kind,
            "directory": self.directory,
            "branches_tried": self.branches_tried,
            "size_limit_exceeded": self.size_limit_exceeded,
            "budget_zero_unattempted": self.budget_zero_unattempted,
            "outcome": self.outcome,
        }));
    }
}

fn sweep_time_available(remaining: Duration) -> bool {
    !remaining.is_zero() && (!super::search_v27::enabled() || remaining >= Duration::from_millis(1))
}

/// A branch model is only a proposal. The caller must replay all target values and
/// verify the full original witness. No arbitrary reference boundary is fixed here.
pub(crate) fn small_proposal(
    graph: &Graph,
    fixed: &BTreeMap<usize, BigUint>,
    starts: &[usize],
    z3: &Path,
    directory: &Path,
    budget: Duration,
) -> Result<Option<ConeResult>> {
    let _profile = super::profile_v24::span("synthesis.small_proposal");
    let started = std::time::Instant::now();
    let mut diagnostics = BranchDiagnostics::new("small_proposal", directory, budget);
    let mut visited = BTreeSet::new();
    for &start in starts {
        for &position in &graph.index[start] {
            let remaining = budget.saturating_sub(started.elapsed());
            if !sweep_time_available(remaining) {
                diagnostics.outcome = "time_exhausted";
                return Ok(None);
            }
            if !visited.insert(position) {
                continue;
            }
            let Some(cone) = largest_cone(graph, fixed, &[start], Some(position)) else {
                diagnostics.size_limit_exceeded += 1;
                continue;
            };
            if cone.constraints.is_empty() {
                continue;
            }
            let remaining = if super::search_v27::enabled() {
                budget.saturating_sub(started.elapsed())
            } else {
                remaining
            };
            if !sweep_time_available(remaining) {
                diagnostics.outcome = "time_exhausted";
                return Ok(None);
            }
            diagnostics.branches_tried += 1;
            diagnostics.outcome = "tool_error";
            let result = solve_cone(
                graph,
                fixed,
                cone,
                true,
                BRANCH_TIMEOUT.min(remaining),
                z3,
                &directory.join(format!("small-{position}")),
            )?;
            diagnostics.outcome = "all_branches_finished";
            if matches!(
                result.outcome,
                ConeOutcome::Model(_) | ConeOutcome::Unsat { .. }
            ) {
                diagnostics.outcome = if matches!(result.outcome, ConeOutcome::Model(_)) {
                    "model_proposal"
                } else {
                    "proof_found"
                };
                return Ok(Some(result));
            }
        }
    }
    Ok(None)
}

/// Result of the exclusion sweep over branch cones.
pub(crate) struct Sweep {
    /// The refuted cone and whether the propagation pass also refuted it.
    pub(crate) proof: Option<(Cone, bool)>,
    pub(crate) branches_tried: usize,
    pub(crate) propagation_only: usize,
    /// The budget ran out before every branch was tried.
    pub(crate) exhausted: bool,
}

/// Tries small closed cones, one per (start wire, constraint) branch, for a z3 unsat
/// proof. Any unsatisfiable subset of the constraints refutes the whole system.
pub(crate) fn exclusion_sweep(
    graph: &Graph,
    fixed: &BTreeMap<usize, BigUint>,
    starts: &[usize],
    z3: &Path,
    directory: &Path,
    budget: Duration,
) -> Result<Sweep> {
    let _profile = super::profile_v24::span("synthesis.exclusion_sweep");
    let started = std::time::Instant::now();
    let mut diagnostics = BranchDiagnostics::new("exclusion_sweep", directory, budget);
    let mut sweep = Sweep {
        proof: None,
        branches_tried: 0,
        propagation_only: 0,
        exhausted: false,
    };
    let mut visited = BTreeSet::new();
    for &start in starts {
        for &position in &graph.index[start] {
            let remaining = budget.saturating_sub(started.elapsed());
            if !sweep_time_available(remaining) {
                sweep.exhausted = true;
                diagnostics.outcome = "time_exhausted";
                return Ok(sweep);
            }
            if !visited.insert(position) {
                continue;
            }
            let Some(cone) = largest_cone(graph, fixed, &[start], Some(position)) else {
                diagnostics.size_limit_exceeded += 1;
                continue;
            };
            if cone.constraints.is_empty() {
                continue;
            }
            let remaining = if super::search_v27::enabled() {
                budget.saturating_sub(started.elapsed())
            } else {
                remaining
            };
            if !sweep_time_available(remaining) {
                sweep.exhausted = true;
                diagnostics.outcome = "time_exhausted";
                return Ok(sweep);
            }
            sweep.branches_tried += 1;
            diagnostics.branches_tried += 1;
            diagnostics.outcome = "tool_error";
            let result = solve_cone(
                graph,
                fixed,
                cone,
                false,
                if super::search_v27::enabled() {
                    BRANCH_TIMEOUT.min(remaining)
                } else {
                    BRANCH_TIMEOUT
                        .min(remaining)
                        .max(Duration::from_millis(100))
                },
                z3,
                &directory.join(format!("branch-{:03}", sweep.branches_tried)),
            )?;
            diagnostics.outcome = "all_branches_finished";
            match result.outcome {
                ConeOutcome::Unsat { propagation } => {
                    sweep.proof = result.cone.map(|cone| (cone, propagation));
                    diagnostics.outcome = "proof_found";
                    return Ok(sweep);
                }
                ConeOutcome::PropagationOnly => sweep.propagation_only += 1,
                _ => {}
            }
        }
    }
    Ok(sweep)
}

fn smt_combination(
    combination: &LinearCombination,
    unknowns: &BTreeSet<usize>,
    fixed: &BTreeMap<usize, BigUint>,
    prime: &BigUint,
) -> String {
    let mut constant = BigUint::zero();
    let mut terms = Vec::new();
    for (wire, coefficient) in combination {
        let wire = *wire as usize;
        if wire != 0 && unknowns.contains(&wire) {
            terms.push(format!("(* {coefficient} w{wire})"));
        } else {
            let value = if wire == 0 {
                BigUint::one()
            } else {
                fixed.get(&wire).cloned().unwrap_or_default()
            };
            constant = (constant + coefficient * value) % prime;
        }
    }
    terms.push(constant.to_string());
    if terms.len() == 1 {
        terms.pop().unwrap_or_default()
    } else {
        format!("(+ {})", terms.join(" "))
    }
}

/// Parses `((w12 5) (w13 7))` from z3's `get-value` answer.
pub(crate) fn parse_values(output: &str) -> Result<BTreeMap<usize, BigUint>> {
    let body = output
        .split_once('\n')
        .map(|(_, rest)| rest)
        .context("z3 printed no model values")?;
    let tokens = body
        .replace(['(', ')'], " ")
        .split_whitespace()
        .map(str::to_owned)
        .collect::<Vec<_>>();
    let mut values = BTreeMap::new();
    for pair in tokens.chunks(2) {
        let [name, value] = pair else {
            bail!("malformed z3 model");
        };
        let wire = name
            .strip_prefix('w')
            .context("unexpected z3 model name")?
            .parse()?;
        values.insert(wire, value.parse().context("z3 model value")?);
    }
    Ok(values)
}

pub(crate) fn constraint_wires(constraint: &Constraint) -> BTreeSet<usize> {
    constraint
        .a
        .keys()
        .chain(constraint.b.keys())
        .chain(constraint.c.keys())
        .map(|wire| *wire as usize)
        .collect()
}

pub(crate) fn residual(
    constraint: &Constraint,
    prime: &BigUint,
    value: impl Fn(usize) -> BigUint,
) -> BigUint {
    let evaluate = |combination: &LinearCombination| {
        combination
            .iter()
            .fold(BigUint::zero(), |total, (wire, coefficient)| {
                let wire_value = if *wire == 0 {
                    BigUint::one()
                } else {
                    value(*wire as usize)
                };
                (total + coefficient * wire_value) % prime
            })
    };
    let (a, b, c) = (
        evaluate(&constraint.a),
        evaluate(&constraint.b),
        evaluate(&constraint.c),
    );
    (a * b % prime + prime - c) % prime
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::candidate_review::lifting::refute::constraint_index;
    use crate::candidate_review::schema::R1csShape;

    fn lc(terms: &[(u32, u64)], prime: &BigUint) -> LinearCombination {
        terms
            .iter()
            .map(|(wire, coefficient)| (*wire, BigUint::from(*coefficient) % prime))
            .collect()
    }

    /// Wires: 1 = public input x, 2 = public input k (blocked), 3 = t = x·k, 4 = s = t + 5.
    fn chain() -> R1cs {
        let prime = BigUint::from(101u32);
        let constraints = vec![
            Constraint {
                a: lc(&[(1, 1)], &prime),
                b: lc(&[(2, 1)], &prime),
                c: lc(&[(3, 1)], &prime),
            },
            Constraint {
                a: LinearCombination::new(),
                b: LinearCombination::new(),
                c: lc(&[(4, 1), (3, 100), (0, 96)], &prime),
            },
        ];
        R1cs {
            prime,
            shape: R1csShape {
                wires: 5,
                labels: 5,
                public_outputs: 0,
                public_inputs: 2,
                private_inputs: 0,
                constraints: 2,
            },
            constraints,
            wire_labels: (0..5).collect(),
        }
    }

    #[test]
    fn local_sat_is_only_a_proposal_when_the_original_witness_fails() {
        let r1cs = chain();
        let index = constraint_index(&r1cs);
        let graph = Graph {
            r1cs: &r1cs,
            index: &index,
            blocked: &|_| false,
            internal: &|_| false,
        };
        let cone = Cone {
            constraints: vec![0],
            unknowns: BTreeSet::from([1, 2, 3]),
        };
        let dir = tempfile::tempdir().unwrap();
        let result = solve_cone(
            &graph,
            &BTreeMap::new(),
            cone,
            true,
            Duration::from_secs(1),
            Path::new("z3"),
            &dir.path().join("local"),
        )
        .unwrap();
        let ConeOutcome::Model(values) = result.outcome else {
            panic!("expected proposal");
        };
        let mut witness = vec![BigUint::one(); 5];
        for (wire, value) in values {
            witness[wire] = value;
        }
        // The omitted constraint requires s=t+5. Deliberately fail full replay.
        witness[4] = witness[3].clone();
        assert!(!r1cs.failed_constraint_indices(&witness).unwrap().is_empty());
    }

    #[test]
    fn back_propagation_solves_a_product_with_a_frozen_factor() {
        let r1cs = chain();
        let index = constraint_index(&r1cs);
        let blocked = |wire: usize| wire == 2;
        let graph = Graph {
            r1cs: &r1cs,
            index: &index,
            blocked: &blocked,
            internal: &|_| false,
        };
        // Honest values at x = 3, k = 4: t = 12, s = 17.
        let current = [1u32, 3, 4, 12, 17].map(BigUint::from).to_vec();
        let paths = find_paths(&graph, 4, MAX_PATHS);
        assert_eq!(paths.len(), 1, "the blocked k is not a free input");
        // Target s = 25: t = 20, x = 20 / 4 = 5.
        let (wire, value) =
            solve_path(&r1cs, &current, 4, &BigUint::from(25u32), &paths[0]).unwrap();
        assert_eq!((wire, value), (1, BigUint::from(5u32)));
    }

    #[test]
    fn paths_branch_to_one_input_through_each_bit() {
        // Wires: 1 = input x, 2 = b0, 3 = b1, 4 = t; x = b0 + 2·b1 and t = b1 + 2·b0.
        let prime = BigUint::from(101u32);
        let r1cs = R1cs {
            prime: prime.clone(),
            shape: R1csShape {
                wires: 5,
                labels: 5,
                public_outputs: 0,
                public_inputs: 1,
                private_inputs: 0,
                constraints: 2,
            },
            constraints: vec![
                Constraint {
                    a: LinearCombination::new(),
                    b: LinearCombination::new(),
                    c: lc(&[(1, 1), (2, 100), (3, 99)], &prime),
                },
                Constraint {
                    a: LinearCombination::new(),
                    b: LinearCombination::new(),
                    c: lc(&[(4, 1), (3, 100), (2, 99)], &prime),
                },
            ],
            wire_labels: (0..5).collect(),
        };
        let index = constraint_index(&r1cs);
        let graph = Graph {
            r1cs: &r1cs,
            index: &index,
            blocked: &|_| false,
            internal: &|_| false,
        };
        let paths = find_paths(&graph, 4, MAX_PATHS);
        assert_eq!(paths.len(), 2);
        assert!(paths
            .iter()
            .all(|path| path.last().map(|step| step.1) == Some(1)));
    }

    #[test]
    fn exclusion_sweep_stops_when_the_candidate_budget_is_spent() {
        let r1cs = chain();
        let index = constraint_index(&r1cs);
        let graph = Graph {
            r1cs: &r1cs,
            index: &index,
            blocked: &|wire| wire == 2,
            internal: &|_| false,
        };
        let fixed = BTreeMap::from([(4usize, BigUint::from(25u32))]);
        let directory = tempfile::tempdir().unwrap();
        // No z3 is needed: the sweep must stop before solving anything.
        let sweep = exclusion_sweep(
            &graph,
            &fixed,
            &[4],
            Path::new("z3-not-called"),
            directory.path(),
            Duration::ZERO,
        )
        .unwrap();
        assert!(sweep.exhausted);
        assert!(sweep.proof.is_none());
        assert_eq!(sweep.branches_tried, 0);
    }

    #[test]
    fn sweep_carries_only_unspent_reservations_and_conserves_twenty_seconds() {
        let total = CANDIDATE_SWEEP_BUDGET;
        let mut carry = Duration::ZERO;
        let mut spent = Duration::ZERO;
        let mut future = total;
        let uses = [
            Duration::ZERO,
            Duration::from_secs(7),
            Duration::from_secs(8),
            Duration::from_secs(4),
        ];
        let expected = [5, 10, 8, 5];
        for index in 0..4 {
            let reserved = class_sweep_budget(total, 4, index);
            let assigned = class_sweep_assignment(total, 4, index, carry);
            assert_eq!(assigned, Duration::from_secs(expected[index]));
            future -= reserved;
            assert!(uses[index] <= assigned);
            carry = assigned - uses[index];
            spent += uses[index];
            assert_eq!(spent + carry + future, total);
        }
        assert_eq!(spent, Duration::from_secs(19));
        assert_eq!(carry, Duration::from_secs(1));
    }

    #[test]
    fn class_reservations_are_exact_and_a_spent_first_share_cannot_starve_later_classes() {
        let _guard = super::super::search_v27::activate().unwrap();
        let total = CANDIDATE_SWEEP_BUDGET + Duration::from_nanos(3);
        let shares = (0..4)
            .map(|class| class_sweep_budget(total, 4, class))
            .collect::<Vec<_>>();
        assert_eq!(shares.iter().copied().sum::<Duration>(), total);
        assert_eq!(shares[0], Duration::from_secs(5) + Duration::from_nanos(1));
        assert_eq!(shares[3], Duration::from_secs(5));
        assert_eq!(class_sweep_budget(total, 0, 0), Duration::ZERO);
        assert_eq!(class_sweep_budget(total, 4, 4), Duration::ZERO);

        let r1cs = chain();
        let index = constraint_index(&r1cs);
        let graph = Graph {
            r1cs: &r1cs,
            index: &index,
            blocked: &|wire| wire == 2,
            internal: &|_| false,
        };
        let fixed = BTreeMap::from([(4usize, BigUint::from(25u32))]);
        let directory = tempfile::tempdir().unwrap();
        let first_remaining = shares[0].saturating_sub(shares[0]);
        let first = exclusion_sweep(
            &graph,
            &fixed,
            &[4],
            Path::new("must-not-run"),
            directory.path(),
            first_remaining,
        )
        .unwrap();
        assert_eq!(first.branches_tried, 0);
        assert!(first.exhausted);
        let last = exclusion_sweep(
            &graph,
            &fixed,
            &[4],
            Path::new("z3"),
            directory.path(),
            shares[3],
        )
        .unwrap();
        assert!(last.branches_tried > 0);
        assert!(last.proof.is_none());
    }

    fn denominator_fixture() -> R1cs {
        let prime = BigUint::from(101u32);
        R1cs {
            prime: prime.clone(),
            shape: R1csShape {
                wires: 6,
                labels: 6,
                public_outputs: 0,
                public_inputs: 2,
                private_inputs: 0,
                constraints: 4,
            },
            constraints: vec![
                // An unrelated branch is visited before the denominator connection.
                Constraint {
                    a: lc(&[(1, 1)], &prime),
                    b: lc(&[(2, 1)], &prime),
                    c: lc(&[(5, 1)], &prime),
                },
                Constraint {
                    a: LinearCombination::new(),
                    b: LinearCombination::new(),
                    c: lc(&[(3, 1), (1, 100)], &prime),
                },
                Constraint {
                    a: lc(&[(3, 1)], &prime),
                    b: lc(&[(4, 1)], &prime),
                    c: lc(&[(0, 1)], &prime),
                },
                Constraint {
                    a: lc(&[(2, 1)], &prime),
                    b: lc(&[(2, 1)], &prime),
                    c: lc(&[(2, 1)], &prime),
                },
            ],
            wire_labels: (0..6).collect(),
        }
    }

    #[test]
    fn candidate_zero_denominator_has_a_small_proof_and_nonzero_candidate_is_not_excluded() {
        let r1cs = denominator_fixture();
        let index = constraint_index(&r1cs);
        let graph = Graph {
            r1cs: &r1cs,
            index: &index,
            blocked: &|wire| wire == 1,
            internal: &|_| false,
        };
        let directory = tempfile::tempdir().unwrap();
        for (candidate, expected_unsat) in [(0u32, true), (2u32, false)] {
            let fixed = BTreeMap::from([(1usize, BigUint::from(candidate))]);
            let result = {
                let _guard = super::super::search_v27::activate().unwrap();
                candidate_contradiction_sweep(
                    &graph,
                    &fixed,
                    &[1],
                    Path::new("z3"),
                    directory.path(),
                    Duration::from_secs(2),
                )
                .unwrap()
            };
            assert_eq!(result.proof.is_some(), expected_unsat);
            if let Some((cone, propagation)) = result.proof {
                assert!(propagation);
                assert_eq!(cone.constraints, [1, 2]);
                assert_eq!(result.branches_tried, 1);
                let query =
                    std::fs::read_to_string(directory.path().join("candidate-small-001.smt2"))
                        .unwrap();
                assert!(
                    !query.contains("w1 Int"),
                    "only the candidate input is fixed"
                );
                assert!(query.contains("w4 Int"), "the inverse remains free");
            } else {
                assert_eq!(result.branches_tried, 0, "SAT subsets cannot become proofs");
                let witness = [1u32, 2, 1, 2, 51, 2].map(BigUint::from);
                assert!(r1cs.failed_constraint_indices(&witness).unwrap().is_empty());
                let cone = build_cone(&graph, &fixed, &[1], Some(1), 2).unwrap();
                let same_branch = solve_cone(
                    &graph,
                    &fixed,
                    cone,
                    false,
                    Duration::from_secs(1),
                    Path::new("z3"),
                    &directory.path().join("same-branch-nonzero"),
                )
                .unwrap();
                assert!(matches!(same_branch.outcome, ConeOutcome::Sat));
            }
            // The original sweep and the new ordering keep the same proof criterion.
            let previous = exclusion_sweep(
                &graph,
                &fixed,
                &[1],
                Path::new("z3"),
                directory.path(),
                Duration::from_secs(2),
            )
            .unwrap();
            assert_eq!(previous.proof.is_some(), expected_unsat);
        }
    }

    #[test]
    fn v27_diagnostics_distinguish_size_limit_from_zero_budget() {
        let _guard = super::super::search_v27::activate().unwrap();
        let mut r1cs = chain();
        r1cs.shape.wires = CONE_UNKNOWNS + 3;
        r1cs.shape.labels = r1cs.shape.wires as u64;
        r1cs.shape.constraints = 1;
        r1cs.wire_labels = (0..r1cs.shape.wires as u64).collect();
        r1cs.constraints = vec![Constraint {
            a: (1..r1cs.shape.wires as u32)
                .map(|wire| (wire, BigUint::one()))
                .collect(),
            b: BTreeMap::from([(0, BigUint::one())]),
            c: BTreeMap::new(),
        }];
        let index = constraint_index(&r1cs);
        let graph = Graph {
            r1cs: &r1cs,
            index: &index,
            blocked: &|_| false,
            internal: &|_| false,
        };
        let fixed = BTreeMap::from([(1usize, BigUint::zero())]);
        let directory = tempfile::tempdir().unwrap();
        for budget in [Duration::from_secs(1), Duration::ZERO] {
            let sweep = exclusion_sweep(
                &graph,
                &fixed,
                &[1],
                Path::new("must-not-run"),
                directory.path(),
                budget,
            )
            .unwrap();
            assert_eq!(sweep.branches_tried, 0);
        }
        super::super::search_v27::write(directory.path()).unwrap();
        let sidecar: serde_json::Value = serde_json::from_slice(
            &std::fs::read(directory.path().join("j-diagnostics.json")).unwrap(),
        )
        .unwrap();
        let events = sidecar["events"].as_array().unwrap();
        assert_eq!(events[0]["size_limit_exceeded"], 1);
        assert_eq!(events[0]["budget_zero_unattempted"], false);
        assert_eq!(events[1]["size_limit_exceeded"], 0);
        assert_eq!(events[1]["budget_zero_unattempted"], true);
    }

    #[test]
    fn z3_model_values_are_parsed() {
        let values = parse_values("sat\n((w12 5)\n (w3 21888))\n").unwrap();
        assert_eq!(values[&12], BigUint::from(5u32));
        assert_eq!(values[&3], BigUint::from(21888u32));
    }
}
