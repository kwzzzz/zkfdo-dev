//! L-05 step 1: reconstruct the condition zkFuzz reported as violated for a candidate that
//! equals the honest component computation.
//!
//! zkFuzz (072bf1f) reports `UnexpectedInput` when the original program fails on its trace
//! while the constraints hold (`mutation_test_trace_fitness_fn.rs:111-118`). Its only built-in
//! semantic condition is the one appended after every component whose template is named
//! `LessThan` (`symbolic_value.rs:492`; `generate_lessthan_constraint`, `:1044`):
//! `(1 == out && in[0] < in[1]) || (0 == out && in[0] >= in[1])`, where `in[*]` are compared
//! as integers in [0, p) (`evaluate_binary_op_integer_mode`, `:1000`). Identifying `LessThan` by
//! name reproduces that oracle's definition; no other template name is used.
//!
//! The emulation keeps the position of the *last* failing trace element (`failure_pos = i`
//! without stopping, `mutator/utils.rs:465-772`), so with several broken instances zkFuzz names
//! the one that runs last.

use std::collections::{BTreeMap, BTreeSet};

use num_bigint::BigUint;
use num_traits::{One, Zero};
use serde::Serialize;

use super::super::r1cs::SymbolTable;
use super::source::TemplateDef;
use super::{anonymous_template, instantiated_templates, split_instance};

/// The template name zkFuzz attaches its integer-comparison condition to.
pub(crate) const ZKFUZZ_LESSTHAN: &str = "LessThan";

#[derive(Debug, Serialize, Clone)]
pub struct ViolatedCondition {
    /// `lessthan_semantic`, `original_assert_failure`, or `condition_not_reconstructed`.
    pub kind: String,
    /// Component instances whose template is named `LessThan`.
    pub lessthan_instances: usize,
    /// Instances with `in`/`out` signals whose template name could not be determined.
    pub unresolved_instances: usize,
    /// Broken `LessThan` instances (component paths), in natural index order.
    pub broken: Vec<BrokenCondition>,
    /// Whether the original program's checks failed on the candidate inputs: `not_observed`
    /// when the honest component computation completed, `honest_component_aborted` otherwise.
    pub original_assert_failure: String,
}

#[derive(Debug, Serialize, Clone)]
pub struct BrokenCondition {
    pub instance: String,
    /// `0`, `1`, or `other` (out is not boolean).
    pub out: String,
    /// `in[0] < in[1]` as integers in [0, p).
    pub integer_less: bool,
}

/// zkFuzz's `LessThan` condition on canonical values.
pub(crate) fn lessthan_holds(in0: &BigUint, in1: &BigUint, out: &BigUint) -> bool {
    (out.is_one() && in0 < in1) || (out.is_zero() && in0 >= in1)
}

/// Every instance of `sym` (paths such as `main.lt[3]`) and its direct signal base names.
pub(crate) fn instance_signals(sym: &SymbolTable) -> BTreeMap<String, BTreeSet<String>> {
    let mut signals: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    for name in sym.by_name.keys() {
        let (instance, leaf) = split_instance(name);
        signals
            .entry(instance.to_owned())
            .or_default()
            .insert(leaf.split('[').next().unwrap_or(leaf).to_owned());
    }
    signals
}

/// Possible template names of every instance, from its declared signal set, circom's naming
/// of `main` and anonymous components, and the parent's instantiation statements.
pub(crate) struct TemplateNames<'a> {
    signals: BTreeMap<String, BTreeSet<String>>,
    templates: &'a [TemplateDef],
    sources: &'a BTreeMap<std::path::PathBuf, String>,
    main_template: Option<String>,
    memo: BTreeMap<String, Vec<&'a TemplateDef>>,
}

impl<'a> TemplateNames<'a> {
    pub(crate) fn new(
        sym: &SymbolTable,
        templates: &'a [TemplateDef],
        sources: &'a BTreeMap<std::path::PathBuf, String>,
        main_template: Option<String>,
    ) -> Self {
        Self {
            signals: instance_signals(sym),
            templates,
            sources,
            main_template,
            memo: BTreeMap::new(),
        }
    }

    pub(crate) fn instances(&self) -> impl Iterator<Item = &String> {
        self.signals.keys()
    }

    /// Template definitions the instance may be, narrowed as far as the source allows.
    pub(crate) fn definitions(&mut self, instance: &str) -> Vec<&'a TemplateDef> {
        if let Some(found) = self.memo.get(instance) {
            return found.clone();
        }
        let signals = self.signals.get(instance).cloned().unwrap_or_default();
        let mut found = self
            .templates
            .iter()
            .filter(|template| template.signals == signals)
            .collect::<Vec<_>>();
        if found.len() > 1 {
            let segment = instance.rsplit('.').next().unwrap_or(instance);
            let segment = segment.split('[').next().unwrap_or(segment);
            let names = if instance == "main" {
                self.main_template.iter().cloned().collect::<BTreeSet<_>>()
            } else if let Some(name) = anonymous_template(segment) {
                BTreeSet::from([name])
            } else {
                let parent = split_instance(instance).0.to_owned();
                if parent.is_empty() {
                    BTreeSet::new()
                } else {
                    let local = &instance[parent.len() + 1..];
                    let local = local.split('[').next().unwrap_or(local).to_owned();
                    self.definitions(&parent)
                        .into_iter()
                        .flat_map(|definition| {
                            instantiated_templates(
                                &self.sources[&definition.file]
                                    [definition.body_start..definition.body_end],
                                &local,
                            )
                        })
                        .collect()
                }
            };
            if !names.is_empty() {
                found.retain(|template| names.contains(&template.name));
            }
        }
        self.memo.insert(instance.to_owned(), found.clone());
        found
    }

    /// `Some(true)` when every possible definition is named `name`, `Some(false)` when none
    /// is, and `None` when the source leaves it open.
    pub(crate) fn is_named(&mut self, instance: &str, name: &str) -> Option<bool> {
        let names = self
            .definitions(instance)
            .into_iter()
            .map(|template| template.name.as_str())
            .collect::<BTreeSet<_>>();
        match (names.contains(name), names.len()) {
            (_, 0) => None,
            (true, 1) => Some(true),
            (false, _) => Some(false),
            (true, _) => None,
        }
    }
}

/// Step 1 for one candidate. `value` returns the candidate's value of a component signal
/// (falling back to the honest component witness); `honest_completed` says whether the
/// honest component computation on the candidate's inputs finished without an abort.
pub(crate) fn reconstruct(
    names: &mut TemplateNames,
    value: &dyn Fn(&str) -> Option<BigUint>,
    honest_completed: bool,
) -> ViolatedCondition {
    let (lessthan, mut unresolved) = lessthan_instances(names);
    let mut broken = Vec::new();
    for instance in &lessthan {
        let leaf = |suffix: &str| value(&format!("{instance}.{suffix}"));
        let (Some(in0), Some(in1), Some(out)) = (leaf("in[0]"), leaf("in[1]"), leaf("out")) else {
            unresolved += 1;
            continue;
        };
        if !lessthan_holds(&in0, &in1, &out) {
            broken.push(BrokenCondition {
                instance: instance.clone(),
                out: if out.is_zero() {
                    "0"
                } else if out.is_one() {
                    "1"
                } else {
                    "other"
                }
                .to_owned(),
                integer_less: in0 < in1,
            });
        }
    }
    let original_assert_failure = if honest_completed {
        "not_observed"
    } else {
        "honest_component_aborted"
    };
    let kind = if !broken.is_empty() {
        "lessthan_semantic"
    } else if !honest_completed {
        "original_assert_failure"
    } else {
        "condition_not_reconstructed"
    };
    ViolatedCondition {
        kind: kind.to_owned(),
        lessthan_instances: lessthan.len(),
        unresolved_instances: unresolved,
        broken,
        original_assert_failure: original_assert_failure.to_owned(),
    }
}

/// The component's `LessThan` instances (with `in` and `out` signals) in natural order, and
/// the number of such-shaped instances whose template name could not be determined.
pub(crate) fn lessthan_instances(names: &mut TemplateNames) -> (Vec<String>, usize) {
    let mut lessthan = Vec::new();
    let mut unresolved = 0usize;
    let shaped = names
        .instances()
        .filter(|instance| {
            names
                .signals
                .get(*instance)
                .is_some_and(|signals| signals.contains("in") && signals.contains("out"))
        })
        .cloned()
        .collect::<Vec<_>>();
    for instance in shaped {
        match names.is_named(&instance, ZKFUZZ_LESSTHAN) {
            Some(true) => lessthan.push(instance),
            Some(false) => {}
            None => unresolved += 1,
        }
    }
    lessthan.sort_by_key(|instance| natural_key(instance));
    (lessthan, unresolved)
}

/// Orders `a.b[10]` after `a.b[9]`.
pub(crate) fn natural_key(name: &str) -> Vec<(String, u64)> {
    let mut key = Vec::new();
    let mut text = String::new();
    let mut digits = String::new();
    for character in name.chars() {
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_condition_compares_canonical_values_as_integers() {
        let p_minus = |k: u32| {
            BigUint::parse_bytes(
                b"21888242871839275222246405745257275088548364400416034343698204186575808495617",
                10,
            )
            .unwrap()
                - BigUint::from(k)
        };
        let (zero, one) = (BigUint::zero(), BigUint::one());
        // A "negative" first input is a huge integer: in[0] < in[1] is false.
        assert!(!lessthan_holds(&p_minus(47), &BigUint::from(3u32), &one));
        assert!(lessthan_holds(&p_minus(47), &BigUint::from(3u32), &zero));
        assert!(lessthan_holds(&BigUint::from(3u32), &p_minus(47), &one));
        assert!(!lessthan_holds(&one, &one, &one));
        assert!(!lessthan_holds(&zero, &one, &BigUint::from(2u32)));
    }

    #[test]
    fn natural_order_follows_numeric_indices() {
        let mut names = ["main.lt[10]", "main.lt[9]", "main.lt[1]"].to_vec();
        names.sort_by_key(|name| natural_key(name));
        assert_eq!(names, ["main.lt[1]", "main.lt[9]", "main.lt[10]"]);
    }
}
