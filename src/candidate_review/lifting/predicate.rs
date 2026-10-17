//! L-05 step 2: the assumption predicate of a broken `LessThan` condition, judged in the
//! entrypoint.
//!
//! The predicate is zkFuzz's own condition, negated: at the instance that corresponds to the
//! broken component instance, `out` differs from the integer comparison `in[0] < in[1]` (the
//! inputs left the range the comparator assumes and the comparison wrapped). The question is
//! whether some entrypoint witness satisfies it:
//!
//! - `assumption_violation_reachable`: a witness from a generator whose constraints equal the
//!   original's satisfies the original R1CS in both checkers, and the predicate holds on it
//!   (the candidate's own reached witness, or one found by the repair search). The predicate
//!   is itself a semantic deviation, so `semantic_deviation_observed` is set with it.
//! - `assumption_excluded_in_context`: z3 finds no solution to a cone of O0 constraints around
//!   the instance with nothing fixed, plus range facts that every witness satisfies
//!   (bit-decomposition intervals, boolean classes, constants). A subset of the constraints
//!   plus implied facts without a solution proves that no witness exists.
//! - `unknown` otherwise.
//!
//! L-07: the predicate belongs to the (entrypoint, instance), not to the candidate. With an
//! instance store, a verdict proved for an instance (a checked witness, or an exclusion) is
//! shared with every later request on the same entrypoint; `experiment lift-instances` joins
//! the verdicts of a set of results independently of their order. When the candidate breaks
//! no known instance (for example a fixed component rejects its inputs), every `LessThan`
//! instance of the component is judged. A reach records which top-level inputs differ from
//! the base input, split by the entrypoint's public inputs.

use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::Path,
    time::{Duration, Instant},
};

use num_bigint::{BigInt, BigUint};
use num_traits::{One, Signed, Zero};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use super::super::r1cs::SymbolTable;
use super::bitrange;
use super::repair::{self, encode, encode_predicate, run_z3, Predicate, RepairRecord, Requirement};
use super::synth::constraint_wires;
use super::{
    generate_witness, snarkjs_check, write_json, ClassResult, Compiled, EvalContext, Ledger,
    Verdict,
};

const EXCLUSION_TIMEOUT: Duration = Duration::from_secs(10);
const EXCLUSION_CONSTRAINTS: usize = 4_000;
/// Passes of interval propagation through linear constraints.
const PROPAGATION_ROUNDS: usize = 8;
const STORE_SCHEMA: &str = "zkfdo-instance-predicate-v2";

pub const VIOLATION_REACHABLE: &str = "assumption_violation_reachable";
pub const EXCLUDED: &str = "assumption_excluded_in_context";

#[derive(Debug, Serialize, Clone)]
pub struct PredicateResult {
    /// The component instance whose condition the candidate breaks (e.g. `main.lt[16]`).
    pub component_instance: String,
    /// The corresponding entrypoint instance at the class representative.
    pub instance: String,
    /// `assumption_violation_reachable`, `assumption_excluded_in_context`, or `unknown`.
    pub verdict: String,
    pub reason: String,
    /// `candidate_witness`, `predicate_search`, `predicate_search_hint_injection`, or
    /// `z3_cone_with_range_facts`.
    pub method: Option<String>,
    pub semantic_deviation_observed: bool,
    pub rust_unsatisfied: Option<usize>,
    pub snarkjs: Option<String>,
    /// The O0 witness used for the predicate equals the checked O1 witness on every O1 wire.
    pub o0_o1_agree: Option<bool>,
    pub search: Option<RepairRecord>,
    pub evidence: BTreeMap<String, String>,
    /// `broken_by_candidate`, or `component_lessthan_instances` when the candidate breaks no
    /// known instance.
    pub target_basis: String,
    /// For a reach: which top-level inputs differ from the base input.
    pub reach_inputs: Option<ReachInputs>,
    /// The request whose judgment this verdict reuses (instance store).
    pub shared_from: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, Clone, PartialEq)]
pub struct ReachInputs {
    /// `private_only` (no public input differs from the base input) or
    /// `public_inputs_changed`.
    pub classification: String,
    pub public_changed: Vec<String>,
    pub public_changed_count: usize,
    pub private_changed_count: usize,
    /// Hint statements were rewritten to reach the witness (witness freedom, never public).
    pub hint_injection: bool,
}

/// One proved instance verdict in the store, keyed by entrypoint and instance.
#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct StoredVerdict {
    pub schema: String,
    pub record_sha256: String,
    pub evidence_files: BTreeMap<String, String>,
    pub entry_key: String,
    pub instance: String,
    pub verdict: String,
    pub method: Option<String>,
    pub reason: String,
    pub request_id: String,
    pub rust_unsatisfied: Option<usize>,
    pub snarkjs: Option<String>,
    pub o0_o1_agree: Option<bool>,
    pub reach_inputs: Option<ReachInputs>,
    pub evidence: BTreeMap<String, String>,
}

/// A witness the class itself reached (input-assumption property): its input, the O0
/// generator that computes it (None: the original), and the checked O1 witness.
pub(crate) struct ClassWitness {
    pub(crate) input: std::path::PathBuf,
    pub(crate) o0: Option<Compiled>,
    pub(crate) o1_witness: std::path::PathBuf,
}

/// A sound range fact for an O0 equality class.
#[derive(Clone)]
pub(crate) struct RangeFact {
    lo: BigUint,
    hi: BigUint,
    /// Bit-decomposition constraints it comes from (empty for booleans and constants).
    decompositions: Vec<usize>,
    /// Linear constraints the interval was propagated through (L-07).
    linear: Vec<usize>,
}

pub(crate) fn range_facts(context: &mut EvalContext) -> BTreeMap<usize, RangeFact> {
    let r1cs = context.entry_o0_r1cs;
    let bindings = context.bindings;
    if context.range_index.is_none() {
        context.range_index = Some(bitrange::build(r1cs, &|wire| bindings.root(wire)));
    }
    let ranges = context.range_index.as_ref().expect("range index");
    let mut facts: BTreeMap<usize, RangeFact> = BTreeMap::new();
    let mut narrow = |root: usize, lo: BigUint, hi: BigUint, source: Option<usize>| {
        let fact = facts.entry(root).or_insert_with(|| RangeFact {
            lo: lo.clone(),
            hi: hi.clone(),
            decompositions: Vec::new(),
            linear: Vec::new(),
        });
        fact.lo = fact.lo.clone().max(lo);
        fact.hi = fact.hi.clone().min(hi);
        fact.decompositions.extend(source);
    };
    for decomposition in &ranges.decompositions {
        narrow(
            bindings.root(decomposition.target),
            decomposition.interval.lo.clone(),
            decomposition.interval.hi.clone(),
            Some(decomposition.constraint),
        );
    }
    for root in &ranges.boolean_roots {
        narrow(*root, BigUint::default(), BigUint::one(), None);
    }
    for (root, value) in &bindings.constants {
        narrow(*root, value.clone(), value.clone(), None);
    }
    propagate_linear(r1cs, &|wire| bindings.root(wire), &mut facts);
    facts
}

/// Narrows intervals through linear constraints `Σ c·x + k = 0` (by equality class): a class
/// with coefficient ±1 equals an integer expression of the others; when its interval bounds
/// lie in [0, p) no reduction mod p is possible, so the class lies in that interval.
fn propagate_linear(
    r1cs: &super::super::r1cs::R1cs,
    root: &dyn Fn(usize) -> usize,
    facts: &mut BTreeMap<usize, RangeFact>,
) {
    let prime = &r1cs.prime;
    let half = prime >> 1;
    let modulus = BigInt::from(prime.clone());
    let signed = |value: &BigUint| -> BigInt {
        if value > &half {
            BigInt::from(value.clone()) - &modulus
        } else {
            BigInt::from(value.clone())
        }
    };
    let linear = r1cs
        .constraints
        .iter()
        .enumerate()
        .filter(|(_, constraint)| constraint.a.is_empty() || constraint.b.is_empty())
        .filter_map(|(position, constraint)| {
            let mut terms: BTreeMap<usize, BigUint> = BTreeMap::new();
            let mut constant = BigUint::default();
            for (wire, coefficient) in &constraint.c {
                if *wire == 0 {
                    constant = (constant + coefficient) % prime;
                } else {
                    let entry = terms.entry(root(*wire as usize)).or_default();
                    *entry = (&*entry + coefficient) % prime;
                }
            }
            terms.retain(|_, coefficient| !coefficient.is_zero());
            (terms.len() >= 2).then_some((position, terms, signed(&constant)))
        })
        .collect::<Vec<_>>();
    for _ in 0..PROPAGATION_ROUNDS {
        let mut updates = Vec::new();
        for (position, terms, constant) in &linear {
            for (target, coefficient) in terms {
                // c_t·t + Σ c·x + k = 0 with c_t = ±1  =>  t = s·(Σ c·x + k), s = -c_t.
                let sign = if coefficient.is_one() {
                    -BigInt::one()
                } else if *coefficient == prime - BigUint::one() {
                    BigInt::one()
                } else {
                    continue;
                };
                let mut lo = constant * &sign;
                let mut hi = lo.clone();
                let mut sources = Vec::new();
                let mut bounded = true;
                for (other, other_coefficient) in terms {
                    if other == target {
                        continue;
                    }
                    let Some(fact) = facts.get(other) else {
                        bounded = false;
                        break;
                    };
                    let factor = signed(other_coefficient) * &sign;
                    let (a, b) = (
                        BigInt::from(fact.lo.clone()) * &factor,
                        BigInt::from(fact.hi.clone()) * &factor,
                    );
                    lo += a.clone().min(b.clone());
                    hi += a.max(b);
                    sources.extend(fact.decompositions.iter().copied());
                }
                if !bounded || lo.is_negative() || hi >= modulus {
                    continue;
                }
                let (Some(lo), Some(hi)) = (lo.to_biguint(), hi.to_biguint()) else {
                    continue;
                };
                let narrower = facts
                    .get(target)
                    .is_none_or(|fact| lo > fact.lo || hi < fact.hi);
                if narrower {
                    updates.push((*target, lo, hi, *position, sources));
                }
            }
        }
        if updates.is_empty() {
            break;
        }
        for (target, lo, hi, position, sources) in updates {
            let fact = facts.entry(target).or_insert_with(|| RangeFact {
                lo: lo.clone(),
                hi: hi.clone(),
                decompositions: Vec::new(),
                linear: Vec::new(),
            });
            fact.lo = fact.lo.clone().max(lo);
            fact.hi = fact.hi.clone().min(hi);
            fact.linear.push(position);
            for source in sources {
                if !fact.decompositions.contains(&source) {
                    fact.decompositions.push(source);
                }
            }
        }
    }
}

/// Step 2 for one class: one predicate judgment per target `LessThan` instance (component
/// paths such as `main.lt[16]`).
#[allow(clippy::too_many_arguments)]
pub(crate) fn judge(
    context: &mut EvalContext,
    class: &mut ClassResult,
    targets: &[String],
    basis: &str,
    witness: Option<&ClassWitness>,
    folder: &Path,
    ledger: &mut Ledger,
) {
    let site = class.representative.clone();
    let mut facts = None;
    let class_hints = class
        .input_origin
        .as_deref()
        .is_some_and(|origin| origin.contains("hint"));
    for (index, component_instance) in targets.iter().enumerate() {
        let suffix = component_instance
            .strip_prefix("main")
            .unwrap_or(component_instance);
        let instance = format!("{site}{suffix}");
        let mut result = PredicateResult {
            component_instance: component_instance.clone(),
            instance: instance.clone(),
            verdict: Verdict::Unknown.name().to_owned(),
            reason: String::new(),
            method: None,
            semantic_deviation_observed: false,
            rust_unsatisfied: None,
            snarkjs: None,
            o0_o1_agree: None,
            search: None,
            evidence: BTreeMap::new(),
            target_basis: basis.to_owned(),
            reach_inputs: None,
            shared_from: None,
        };
        let wire = |leaf: &str| {
            context
                .entry_o0_sym
                .by_name
                .get(&format!("{instance}.{leaf}"))
                .and_then(|symbol| usize::try_from(symbol.wire).ok())
        };
        let (Some(in0), Some(in1), Some(out)) = (wire("in[0]"), wire("in[1]"), wire("out")) else {
            result.reason = "predicate_wires_missing".to_owned();
            class.predicates.push(result);
            continue;
        };
        let predicate = Predicate {
            instance: instance.clone(),
            wires: [in0, in1, out],
        };
        let directory = folder.join(format!("predicate-{index:02}"));
        let _ = fs::create_dir_all(&directory);

        // (1) The class's own reached witness carries the candidate's site values.
        if let Some(witness) = witness {
            let started = Instant::now();
            let checked = class_witness_check(context, witness, &predicate, &directory, ledger);
            ledger.record(
                "predicate",
                "predicate on the class witness",
                started.elapsed().as_secs_f64(),
                if checked == Some(true) {
                    "holds"
                } else {
                    "not_holds"
                },
                false,
            );
            if checked == Some(true) {
                result.verdict = VIOLATION_REACHABLE.to_owned();
                result.reason = "predicate_holds_on_reached_witness".to_owned();
                result.method = Some("candidate_witness".to_owned());
                result.semantic_deviation_observed = true;
                result.rust_unsatisfied = class.rust_unsatisfied;
                result.snarkjs = class.snarkjs.clone();
                result.o0_o1_agree = Some(true);
                result.reach_inputs = fs::read(&witness.input)
                    .ok()
                    .and_then(|bytes| serde_json::from_slice::<Value>(&bytes).ok())
                    .map(|input| reach_inputs(context, &input, class_hints));
                store_write(context, &mut result, &directory, Some(witness));
                class.predicates.push(result);
                continue;
            }
        }

        // (1b) A verdict already proved for this entrypoint instance by another request.
        if let Some(stored) = store_read(context, &instance) {
            result.verdict = stored.verdict;
            result.reason = "instance_verdict_shared".to_owned();
            result.method = Some(format!(
                "shared_instance:{}",
                stored.method.as_deref().unwrap_or("unknown")
            ));
            result.semantic_deviation_observed = result.verdict == VIOLATION_REACHABLE;
            result.rust_unsatisfied = stored.rust_unsatisfied;
            result.snarkjs = stored.snarkjs;
            result.o0_o1_agree = stored.o0_o1_agree;
            result.reach_inputs = stored.reach_inputs;
            result.evidence = stored.evidence;
            result.shared_from = Some(stored.request_id);
            ledger.record("predicate", "instance store hit", 0.0, "shared", true);
            class.predicates.push(result);
            continue;
        }

        // (2) Exclusion: nothing fixed, only implied range facts.
        let facts = facts.get_or_insert_with(|| {
            ledger.timed("predicate", "range facts", || range_facts(context))
        });
        let started = Instant::now();
        let exclusion = exclude(context, &predicate, facts, &directory);
        ledger.record(
            "predicate",
            "z3 predicate exclusion",
            started.elapsed().as_secs_f64(),
            if exclusion.as_ref().is_ok_and(Option::is_some) {
                "unsat"
            } else {
                "not_excluded"
            },
            false,
        );
        match exclusion {
            Ok(Some(evidence)) => {
                result.verdict = EXCLUDED.to_owned();
                result.reason = "predicate_cone_unsat".to_owned();
                result.method = Some("z3_cone_with_range_facts".to_owned());
                result.evidence = evidence;
                store_write(context, &mut result, &directory, None);
                class.predicates.push(result);
                continue;
            }
            Ok(None) => {}
            Err(error) => {
                result
                    .evidence
                    .insert("exclusion_error".to_owned(), format!("{error:#}"));
            }
        }

        // (3) Search for a witness on which the predicate holds.
        // Search identity includes the actual honest O0 generator. Equal R1CS/SYM
        // can still have different unconstrained hints and therefore different searches.
        let generator_hash = context.original_o0.js_dir.as_ref().and_then(|directory| {
            super::sha256_file(&directory.join(format!("{}.wasm", context.original_o0.stem))).ok()
        });
        let job_id = attempt_identity(
            &context.entry_key,
            &instance,
            generator_hash.as_deref().unwrap_or("unavailable"),
        );
        let attempt_path = generator_hash
            .as_ref()
            .and(context.instance_store)
            .map(|store| store.join("attempts-v2.1").join(format!("{job_id}.json")));
        if let Some(cached) = attempt_path
            .as_ref()
            .and_then(|path| fs::read(path).ok())
            .and_then(|bytes| serde_json::from_slice::<StoredAttempt>(&bytes).ok())
            .filter(|attempt| {
                attempt.schema == "zkfdo-predicate-attempt-v2.1"
                    && attempt.job_id == job_id
                    && attempt.record_sha256
                        == super::sha256_bytes(
                            &serde_json::to_vec(&attempt.record).unwrap_or_default(),
                        )
                    && cacheable_attempt(&attempt.record)
            })
        {
            result.reason = "predicate_search_cached_unknown".to_owned();
            result
                .evidence
                .insert("independent_job_id".to_owned(), job_id);
            result
                .evidence
                .insert("search_outcome".to_owned(), cached.record.outcome.clone());
            result
                .evidence
                .insert("search_shared_from".to_owned(), cached.request_id);
            result.search = Some(cached.record);
            ledger.record(
                "predicate",
                "identical failed search hit",
                0.0,
                "unknown",
                true,
            );
            class.predicates.push(result);
            continue;
        }
        context.repair_remaining = 6;
        result
            .evidence
            .insert("independent_job_id".to_owned(), job_id.clone());
        let start = repair::Start {
            label: "predicate",
            stage: "predicate",
            input: context.base_input.clone(),
            overrides: repair::Overrides::default(),
            candidate_hints: false,
            protected_site: None,
            inputs_free: true,
            pinned: BTreeSet::new(),
        };
        let requirement = Requirement {
            targets: Vec::new(),
            predicate: Some(predicate.clone()),
        };
        let (reached, record) = repair::search(
            context,
            start,
            &requirement,
            &directory.join("search"),
            ledger,
        );
        let injected = record.rewritten_statements > 0;
        result.search = Some(record);
        let Some(reached) = reached else {
            if let (Some(path), Some(record)) = (attempt_path, result.search.as_ref()) {
                if cacheable_attempt(record) {
                    let attempt = StoredAttempt {
                        schema: "zkfdo-predicate-attempt-v2.1".to_owned(),
                        job_id,
                        request_id: context.request_id.clone(),
                        record: record.clone(),
                        record_sha256: super::sha256_bytes(
                            &serde_json::to_vec(record).unwrap_or_default(),
                        ),
                    };
                    let _ = fs::create_dir_all(path.parent().unwrap_or(Path::new(".")));
                    if let Ok(value) = serde_json::to_value(attempt) {
                        let _ = write_json(&path, &value);
                    }
                }
            }
            result.reason = "predicate_search_not_reached".to_owned();
            class.predicates.push(result);
            continue;
        };
        let started = Instant::now();
        let verified = verify_reached(context, &reached, &directory, ledger);
        ledger.record(
            "predicate",
            "verify predicate witness",
            started.elapsed().as_secs_f64(),
            "done",
            false,
        );
        result.rust_unsatisfied = verified.rust;
        result.snarkjs = verified.snarkjs.clone();
        result.o0_o1_agree = verified.agree;
        if let Some(hash) = verified.input_sha256 {
            result.evidence.insert("input_sha256".to_owned(), hash);
        }
        if verified.rust == Some(0)
            && verified.snarkjs.as_deref() == Some("correct")
            && verified.agree == Some(true)
            && predicate.holds(&reached.witness_o0)
        {
            result.verdict = VIOLATION_REACHABLE.to_owned();
            result.reason = "predicate_holds_on_found_witness".to_owned();
            result.method = Some(
                if injected {
                    "predicate_search_hint_injection"
                } else {
                    "predicate_search"
                }
                .to_owned(),
            );
            result.semantic_deviation_observed = true;
            result.reach_inputs = Some(reach_inputs(context, &reached.input, injected));
            store_write(context, &mut result, &directory, None);
        } else {
            result.reason = "predicate_witness_not_verified".to_owned();
        }
        class.predicates.push(result);
    }
    class.assumption_predicate_verdict = Some(aggregate(&class.predicates).to_owned());
    class.semantic_deviation_observed = Some(
        class
            .predicates
            .iter()
            .any(|result| result.semantic_deviation_observed),
    );
}

/// Top-level inputs of `input` that differ from the base input, split by the entrypoint's
/// public inputs. Values are compared as field elements.
fn reach_inputs(context: &EvalContext, input: &Value, hint_injection: bool) -> ReachInputs {
    let prime = &context.entry_r1cs.prime;
    let (base, reached) = (
        flatten_input(context.base_input, prime),
        flatten_input(input, prime),
    );
    let changed = base
        .keys()
        .chain(reached.keys())
        .filter(|name| base.get(*name) != reached.get(*name))
        .cloned()
        .collect::<BTreeSet<_>>();
    let public = changed
        .iter()
        .filter(|name| context.public_inputs.contains(*name))
        .cloned()
        .collect::<Vec<_>>();
    ReachInputs {
        classification: if public.is_empty() {
            "private_only"
        } else {
            "public_inputs_changed"
        }
        .to_owned(),
        public_changed_count: public.len(),
        private_changed_count: changed.len() - public.len(),
        public_changed: public.into_iter().take(20).collect(),
        hint_injection,
    }
}

/// `{"a": ["1", ["2"]]}` as `a[0] -> 1`, `a[1][0] -> 2`, reduced mod p.
fn flatten_input(value: &Value, prime: &BigUint) -> BTreeMap<String, BigUint> {
    fn walk(name: String, value: &Value, prime: &BigUint, out: &mut BTreeMap<String, BigUint>) {
        match value {
            Value::Array(items) => {
                for (index, item) in items.iter().enumerate() {
                    walk(format!("{name}[{index}]"), item, prime, out);
                }
            }
            Value::String(text) => {
                let parsed = if let Some(hex) = text.strip_prefix("0x") {
                    BigUint::parse_bytes(hex.as_bytes(), 16)
                } else if let Some(negative) = text.strip_prefix('-') {
                    negative
                        .parse::<BigUint>()
                        .ok()
                        .map(|magnitude| (prime - magnitude % prime) % prime)
                } else {
                    text.parse::<BigUint>().ok()
                };
                if let Some(value) = parsed {
                    out.insert(name, value % prime);
                }
            }
            Value::Number(number) => {
                if let Some(value) = number.as_u64() {
                    out.insert(name, BigUint::from(value) % prime);
                } else if let Some(value) = number.as_i64() {
                    let magnitude = BigUint::from(value.unsigned_abs()) % prime;
                    out.insert(name, (prime - magnitude) % prime);
                }
            }
            _ => {}
        }
    }
    let mut out = BTreeMap::new();
    if let Value::Object(fields) = value {
        for (name, value) in fields {
            walk(name.clone(), value, prime, &mut out);
        }
    }
    out
}

#[derive(Serialize, Deserialize)]
struct StoredAttempt {
    schema: String,
    job_id: String,
    request_id: String,
    record: RepairRecord,
    record_sha256: String,
}

fn attempt_identity(entry_key: &str, instance: &str, generator_sha256: &str) -> String {
    super::sha256_bytes(
        format!("{entry_key}\0{instance}\0{generator_sha256}\0predicate-base-empty-hints-v2.1")
            .as_bytes(),
    )
}

fn cacheable_attempt(record: &RepairRecord) -> bool {
    matches!(
        record.outcome.as_str(),
        "cycle" | "no_progress" | "iteration_limit"
    ) && record.error_kind.is_none()
        && !record
            .solves
            .iter()
            .any(|solve| matches!(solve.outcome.as_str(), "unknown" | "timeout" | "tool_error"))
}

fn store_path(context: &EvalContext, instance: &str) -> Option<std::path::PathBuf> {
    use sha2::{Digest, Sha256};
    let store = context.instance_store?;
    let key = Sha256::digest(format!(
        "{STORE_SCHEMA}\0{}\0{instance}\0lessthan_semantic",
        context.entry_key
    ));
    Some(store.join(format!("{key:x}.json")))
}

fn store_read(context: &EvalContext, instance: &str) -> Option<StoredVerdict> {
    let stored: StoredVerdict =
        serde_json::from_slice(&fs::read(store_path(context, instance)?).ok()?).ok()?;
    (stored.entry_key == context.entry_key && stored.instance == instance && valid_stored(&stored))
        .then_some(stored)
}

fn stored_digest(stored: &StoredVerdict) -> String {
    let mut unsigned = stored.clone();
    unsigned.record_sha256.clear();
    super::sha256_bytes(&serde_json::to_vec(&unsigned).unwrap_or_default())
}

fn valid_stored(stored: &StoredVerdict) -> bool {
    stored.schema == STORE_SCHEMA
        && stored.record_sha256 == stored_digest(stored)
        && !stored.evidence_files.is_empty()
        && stored.evidence_files.iter().all(|(path, hash)| {
            super::sha256_file(Path::new(path)).is_ok_and(|actual| actual == *hash)
        })
        && match stored.verdict.as_str() {
            VIOLATION_REACHABLE => {
                stored.rust_unsatisfied == Some(0)
                    && stored.snarkjs.as_deref() == Some("correct")
                    && stored.o0_o1_agree == Some(true)
            }
            EXCLUDED => {
                stored.method.as_deref() == Some("z3_cone_with_range_facts")
                    && stored.evidence.contains_key("excluded_by")
            }
            _ => false,
        }
}

/// Records a proved verdict for the instance. A stored verdict that contradicts it is never
/// overwritten; the contradiction is noted on the result (it would be an engine error).
fn store_write(
    context: &EvalContext,
    result: &mut PredicateResult,
    directory: &Path,
    witness: Option<&ClassWitness>,
) {
    let Some(path) = store_path(context, &result.instance) else {
        return;
    };
    if let Some(existing) = store_read(context, &result.instance) {
        if existing.verdict != result.verdict {
            result.evidence.insert(
                "instance_store_conflict".to_owned(),
                format!("{} by {}", existing.verdict, existing.request_id),
            );
        }
        return;
    }
    result
        .evidence
        .entry("verified_at_unix_ms".to_owned())
        .or_insert_with(|| {
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|time| time.as_millis().to_string())
                .unwrap_or_default()
        });
    let mut stored = StoredVerdict {
        record_sha256: String::new(),
        evidence_files: BTreeMap::new(),
        schema: STORE_SCHEMA.to_owned(),
        entry_key: context.entry_key.clone(),
        instance: result.instance.clone(),
        verdict: result.verdict.clone(),
        method: result.method.clone(),
        reason: result.reason.clone(),
        request_id: context.request_id.clone(),
        rust_unsatisfied: result.rust_unsatisfied,
        snarkjs: result.snarkjs.clone(),
        o0_o1_agree: result.o0_o1_agree,
        reach_inputs: result.reach_inputs.clone(),
        evidence: result.evidence.clone(),
    };
    let files = if result.verdict == VIOLATION_REACHABLE {
        if let Some(witness) = witness {
            vec![
                witness.input.clone(),
                witness.o1_witness.clone(),
                directory.join("class-o0.wtns"),
            ]
        } else {
            vec![
                directory.join("found-input.json"),
                directory.join("found.wtns"),
            ]
        }
    } else {
        [0, 1]
            .into_iter()
            .flat_map(|depth| {
                [
                    directory.join(format!("exclusion-{depth}.smt2")),
                    directory.join(format!("exclusion-{depth}.z3.log")),
                ]
            })
            .filter(|path| path.is_file())
            .collect()
    };
    for file in files {
        let Ok(hash) = super::sha256_file(&file) else {
            return;
        };
        let Ok(file) = file.canonicalize() else {
            return;
        };
        stored
            .evidence_files
            .insert(file.to_string_lossy().into_owned(), hash);
    }
    stored.record_sha256 = stored_digest(&stored);
    if !valid_stored(&stored) {
        return;
    }
    let _ = fs::create_dir_all(path.parent().unwrap_or(Path::new(".")));
    let temporary = path.with_extension(format!("{}.tmp", std::process::id()));
    if serde_json::to_vec_pretty(&stored)
        .ok()
        .and_then(|bytes| fs::write(&temporary, bytes).ok())
        .is_some()
    {
        let _ = fs::rename(&temporary, &path);
    }
}

/// Reachable if any broken instance is, excluded if every one is, unknown otherwise.
pub(crate) fn aggregate(results: &[PredicateResult]) -> &'static str {
    if results.is_empty() {
        "not_applicable"
    } else if results
        .iter()
        .any(|result| result.verdict == VIOLATION_REACHABLE)
    {
        VIOLATION_REACHABLE
    } else if results.iter().all(|result| result.verdict == EXCLUDED) {
        EXCLUDED
    } else {
        "unknown"
    }
}

/// Runs the class's O0 generator on its input and evaluates the predicate there, after
/// checking that the O0 witness equals the checked O1 witness on every O1 wire.
fn class_witness_check(
    context: &EvalContext,
    witness: &ClassWitness,
    predicate: &Predicate,
    directory: &Path,
    ledger: &mut Ledger,
) -> Option<bool> {
    let prime = &context.entry_r1cs.prime;
    let o0 = generate_witness(
        context.tools,
        witness.o0.as_ref().unwrap_or(context.original_o0),
        &witness.input,
        &directory.join("class-o0.wtns"),
        prime,
        ledger,
        "predicate",
        "class O0 witness",
    )
    .ok()
    .flatten()?;
    let o1 = super::wtns::read_wtns(&witness.o1_witness, prime).ok()?;
    if !agree(context.entry_sym, &o1, context.entry_o0_sym, &o0) {
        return Some(false);
    }
    Some(predicate.holds(&o0))
}

pub(crate) fn agree(
    o1_sym: &SymbolTable,
    o1: &[BigUint],
    o0_sym: &SymbolTable,
    o0: &[BigUint],
) -> bool {
    o1_sym
        .wire_to_names
        .iter()
        .enumerate()
        .skip(1)
        .all(|(wire, names)| {
            names.first().is_some_and(|name| {
                o0_sym
                    .by_name
                    .get(name)
                    .and_then(|symbol| usize::try_from(symbol.wire).ok())
                    .is_some_and(|position| o0.get(position) == o1.get(wire))
            })
        })
}

struct Verified {
    rust: Option<usize>,
    snarkjs: Option<String>,
    agree: Option<bool>,
    input_sha256: Option<String>,
}

/// The found witness at O1 against the original R1CS, in both checkers.
fn verify_reached(
    context: &EvalContext,
    reached: &repair::Reached,
    directory: &Path,
    ledger: &mut Ledger,
) -> Verified {
    let mut verified = Verified {
        rust: None,
        snarkjs: None,
        agree: None,
        input_sha256: None,
    };
    let input = directory.join("found-input.json");
    if write_json(&input, &reached.input).is_err() {
        return verified;
    }
    verified.input_sha256 = super::sha256_file(&input).ok();
    let witness_path = directory.join("found.wtns");
    let Ok(Some(o1)) = generate_witness(
        context.tools,
        &reached.o1,
        &input,
        &witness_path,
        &context.entry_r1cs.prime,
        ledger,
        "predicate",
        "found O1 witness",
    ) else {
        return verified;
    };
    let started = Instant::now();
    verified.rust = context
        .entry_r1cs
        .failed_constraint_indices(&o1)
        .ok()
        .map(|failed| failed.len());
    ledger.record(
        "check",
        "rust r1cs evaluation",
        started.elapsed().as_secs_f64(),
        "ok",
        false,
    );
    verified.snarkjs =
        snarkjs_check(context.tools, &context.original.r1cs, &witness_path, ledger).ok();
    verified.agree = Some(agree(
        context.entry_sym,
        &o1,
        context.entry_o0_sym,
        &reached.witness_o0,
    ));
    verified
}

/// z3 on the instance's constraints (depth 0), then with one more layer (depth 1), with every
/// wire unknown and range facts asserted. Evidence when unsatisfiable.
fn exclude(
    context: &EvalContext,
    predicate: &Predicate,
    facts: &BTreeMap<usize, RangeFact>,
    directory: &Path,
) -> anyhow::Result<Option<BTreeMap<String, String>>> {
    let Some(z3) = context.z3 else {
        anyhow::bail!("z3 is not available");
    };
    let r1cs = context.entry_o0_r1cs;
    let sym = context.entry_o0_sym;
    let index = context
        .o0_constraint_index
        .clone()
        .unwrap_or_else(|| std::rc::Rc::new(super::refute::constraint_index(r1cs)));
    let region = sym
        .by_name
        .range(format!("{}.", predicate.instance)..format!("{}/", predicate.instance))
        .filter_map(|(_, symbol)| usize::try_from(symbol.wire).ok())
        .collect::<BTreeSet<_>>();
    let mut constraints = BTreeSet::new();
    let mut frontier = region.clone();
    let mut seen = region.clone();
    for depth in 0..2 {
        let mut next = BTreeSet::new();
        for wire in &frontier {
            if index[*wire].len() > repair::HUB_DEGREE && !region.contains(wire) {
                continue;
            }
            for &position in &index[*wire] {
                if constraints.insert(position) {
                    for other in constraint_wires(&r1cs.constraints[position]) {
                        if other != 0 && seen.insert(other) {
                            next.insert(other);
                        }
                    }
                }
            }
        }
        if constraints.len() > EXCLUSION_CONSTRAINTS {
            return Ok(None);
        }
        let unknowns = constraints
            .iter()
            .flat_map(|position| constraint_wires(&r1cs.constraints[*position]))
            .filter(|wire| *wire != 0)
            .collect::<BTreeSet<_>>();
        let unused = |_: usize| BigUint::default();
        let mut text = encode(r1cs, &constraints, &unknowns, &unused, EXCLUSION_TIMEOUT);
        let mut used = BTreeSet::new();
        let mut linear = BTreeSet::new();
        for wire in &unknowns {
            if let Some(fact) = facts.get(&context.bindings.root(*wire)) {
                text.push_str(&format!(
                    "(assert (and (<= {} w{wire}) (<= w{wire} {})))\n",
                    fact.lo, fact.hi
                ));
                used.extend(fact.decompositions.iter().copied());
                linear.extend(fact.linear.iter().copied());
            }
        }
        text.push_str(&encode_predicate(predicate, &unknowns, &unused));
        let (verdict, _) = run_z3(
            z3,
            text,
            &BTreeSet::new(),
            &directory.join(format!("exclusion-{depth}")),
            EXCLUSION_TIMEOUT,
        )?;
        if verdict == "unsat" {
            let input_facts = predicate.wires[..2]
                .iter()
                .map(|wire| {
                    let name = sym.wire_to_names[*wire]
                        .first()
                        .cloned()
                        .unwrap_or_default();
                    match facts.get(&context.bindings.root(*wire)) {
                        Some(fact) if !fact.decompositions.is_empty() => format!(
                            "{name}: bit-decomposition range at O0 constraint(s) {:?} ({})",
                            fact.decompositions,
                            fact.decompositions
                                .iter()
                                .map(|position| decomposition_instance(context, *position))
                                .collect::<Vec<_>>()
                                .join(", ")
                        ),
                        Some(_) => format!("{name}: boolean or constant class"),
                        None => format!("{name}: no range fact"),
                    }
                })
                .collect::<Vec<_>>();
            return Ok(Some(BTreeMap::from([
                (
                    "excluded_by".to_owned(),
                    format!(
                        "z3 returned unsat for {} O0 constraints over {} unknown wires around {} (depth {depth}) with nothing fixed, the broken-comparison predicate, and {} implied range facts",
                        constraints.len(),
                        unknowns.len(),
                        predicate.instance,
                        unknowns
                            .iter()
                            .filter(|wire| facts.contains_key(&context.bindings.root(**wire)))
                            .count()
                    ),
                ),
                ("exclusion_basis".to_owned(), "o0_cone_with_range_facts".to_owned()),
                ("exclusion_method".to_owned(), "z3_cone_with_range_facts".to_owned()),
                ("input_range_facts".to_owned(), input_facts.join("; ")),
                (
                    "decomposition_constraints_used".to_owned(),
                    format!("{:?}", used.iter().take(16).collect::<Vec<_>>()),
                ),
                (
                    "linear_propagation_constraints_used".to_owned(),
                    format!("{:?}", linear.iter().take(16).collect::<Vec<_>>()),
                ),
            ])));
        }
        frontier = next;
    }
    Ok(None)
}

fn decomposition_instance(context: &EvalContext, position: usize) -> String {
    let wires = constraint_wires(&context.entry_o0_r1cs.constraints[position]);
    wires
        .into_iter()
        .filter(|wire| *wire != 0)
        .filter_map(|wire| context.entry_o0_sym.wire_to_names[wire].first())
        .map(|name| super::split_instance(name).0.to_owned())
        .min_by_key(|instance| instance.len())
        .unwrap_or_default()
}

#[cfg(test)]
mod reaudit_tests {
    use super::*;
    #[test]
    fn time_or_unknown_limited_attempt_is_not_memoized() {
        let mut record = RepairRecord {
            outcome: "no_progress".to_owned(),
            ..RepairRecord::default()
        };
        assert!(cacheable_attempt(&record));
        record.solves.push(repair::SolveRecord {
            iteration: 0,
            cause: "predicate".to_owned(),
            region: "main.c".to_owned(),
            with_paths: true,
            unknowns: 3,
            constraints: 2,
            outcome: "timeout".to_owned(),
            hints_changed: 0,
            inputs_changed: 0,
        });
        assert!(!cacheable_attempt(&record));
        record.solves[0].outcome = "unknown".to_owned();
        assert!(!cacheable_attempt(&record));
        record.solves[0].outcome = "unsat".to_owned();
        assert!(cacheable_attempt(&record));
        record.error_kind = Some("io".to_owned());
        assert!(!cacheable_attempt(&record));
    }
    #[test]
    fn attempt_key_separates_generator_changes_even_for_same_constraints() {
        assert_ne!(
            attempt_identity("same-r1cs-sym-base-engine", "main.c", "wasm-a"),
            attempt_identity("same-r1cs-sym-base-engine", "main.c", "wasm-b")
        );
    }
}
