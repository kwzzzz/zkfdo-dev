//! Sound range reasoning over bit decompositions, ahead of cone solving.
//!
//! A linear constraint `x = Σ dᵢ·bᵢ + e` whose `bᵢ` are boolean (some wire in their O0
//! equality class carries `b·(b − 1) = 0`) bounds `x` to `[e, e + Σ dᵢ]` when every `dᵢ`
//! is a small positive field element and the sum does not wrap. Values forced from fixed
//! wires (single-unknown linear solving) and these intervals are propagated through linear
//! constraints; an empty intersection or a violated fully-valued constraint means no
//! witness exists with the fixed values. Nothing is enumerated. (Interval reasoning of this
//! kind is prior art, e.g. CCC-Check's value inference; this is not a new technique.)

use std::collections::{BTreeMap, BTreeSet, VecDeque};

use num_bigint::BigUint;
use num_traits::{One, Zero};

use super::super::r1cs::{Constraint, R1cs};

/// Inclusive integer interval with `lo <= hi < p`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct Interval {
    pub(crate) lo: BigUint,
    pub(crate) hi: BigUint,
}

impl Interval {
    fn point(value: &BigUint) -> Self {
        Self {
            lo: value.clone(),
            hi: value.clone(),
        }
    }

    fn intersect(&self, other: &Interval) -> Option<Interval> {
        let lo = (&self.lo).max(&other.lo).clone();
        let hi = (&self.hi).min(&other.hi).clone();
        (lo <= hi).then_some(Interval { lo, hi })
    }
}

#[derive(Clone, Debug)]
pub(crate) struct Decomposition {
    pub(crate) constraint: usize,
    pub(crate) target: usize,
    pub(crate) bits: usize,
    pub(crate) interval: Interval,
}

pub(crate) struct RangeIndex {
    pub(crate) decompositions: Vec<Decomposition>,
    by_target: BTreeMap<usize, Vec<usize>>,
    pub(crate) boolean_roots: BTreeSet<usize>,
}

/// A proof that no witness exists with the fixed values.
#[derive(Clone, Debug)]
pub(crate) struct Contradiction {
    /// The constraint whose interval or value check failed.
    pub(crate) constraint: usize,
    pub(crate) wire: usize,
    /// The bit decomposition involved, if any.
    pub(crate) decomposition: Option<Decomposition>,
    pub(crate) detail: String,
}

fn is_linear(constraint: &Constraint) -> bool {
    constraint.a.is_empty() || constraint.b.is_empty()
}

fn inverse(value: &BigUint, prime: &BigUint) -> BigUint {
    value.modpow(&(prime - BigUint::from(2u32)), prime)
}

/// Finds boolean classes and bit decompositions. `root` maps a wire to its O0 equality
/// class representative.
pub(crate) fn build(r1cs: &R1cs, root: &dyn Fn(usize) -> usize) -> RangeIndex {
    let prime = &r1cs.prime;
    let mut boolean_roots = BTreeSet::new();
    for constraint in &r1cs.constraints {
        let wires = wires_of(constraint);
        let variables = wires
            .iter()
            .copied()
            .filter(|wire| *wire != 0)
            .collect::<Vec<_>>();
        if let [wire] = variables.as_slice() {
            let at = |trial: u32| {
                residual(constraint, prime, &|other| {
                    if other == *wire {
                        Some(BigUint::from(trial))
                    } else {
                        Some(BigUint::one())
                    }
                })
                .unwrap_or_default()
            };
            if at(0).is_zero() && at(1).is_zero() && !at(2).is_zero() {
                boolean_roots.insert(root(*wire));
            }
        }
    }
    let half = prime >> 1;
    let mut decompositions = Vec::new();
    for (position, constraint) in r1cs.constraints.iter().enumerate() {
        if !is_linear(constraint) {
            continue;
        }
        let terms = &constraint.c;
        let (bits, others): (Vec<_>, Vec<_>) = terms
            .iter()
            .filter(|(wire, coefficient)| **wire != 0 && !coefficient.is_zero())
            .partition(|(wire, _)| boolean_roots.contains(&root(**wire as usize)));
        let [(target, alpha)] = others.as_slice() else {
            continue;
        };
        if bits.len() < 2 {
            continue;
        }
        // x = -(Σ βᵢ bᵢ + γ) / α
        let scale = (prime - inverse(alpha, prime)) % prime;
        let mut total = BigUint::zero();
        let mut valid = true;
        for (_, beta) in &bits {
            let d = (*beta * &scale) % prime;
            if d > half {
                valid = false;
                break;
            }
            total += d;
        }
        let gamma = terms.get(&0).cloned().unwrap_or_default();
        let e = (gamma * &scale) % prime;
        let hi = &e + &total;
        if !valid || &hi >= prime {
            continue;
        }
        decompositions.push(Decomposition {
            constraint: position,
            target: **target as usize,
            bits: bits.len(),
            interval: Interval { lo: e, hi },
        });
    }
    let mut by_target: BTreeMap<usize, Vec<usize>> = BTreeMap::new();
    for (index, decomposition) in decompositions.iter().enumerate() {
        by_target
            .entry(decomposition.target)
            .or_default()
            .push(index);
    }
    RangeIndex {
        decompositions,
        by_target,
        boolean_roots,
    }
}

/// Propagates forced values and intervals from `fixed` through at most `budget` constraint
/// visits. Returns a contradiction if one is found.
pub(crate) fn propagate(
    r1cs: &R1cs,
    index: &[Vec<usize>],
    ranges: &RangeIndex,
    root: &dyn Fn(usize) -> usize,
    fixed: &BTreeMap<usize, BigUint>,
    budget: usize,
) -> Option<Contradiction> {
    let prime = &r1cs.prime;
    let half = prime >> 1;
    let mut values = fixed.clone();
    let mut intervals: BTreeMap<usize, Interval> = BTreeMap::new();
    let mut queue = fixed.keys().copied().collect::<VecDeque<_>>();
    let mut queued = queue.iter().copied().collect::<BTreeSet<_>>();
    let mut visits = 0usize;
    let interval_of = |wire: usize,
                       values: &BTreeMap<usize, BigUint>,
                       intervals: &BTreeMap<usize, Interval>|
     -> Option<Interval> {
        if let Some(value) = values.get(&wire) {
            return Some(Interval::point(value));
        }
        let mut known = intervals.get(&wire).cloned();
        if ranges.boolean_roots.contains(&root(wire)) {
            let unit = Interval {
                lo: BigUint::zero(),
                hi: BigUint::one(),
            };
            known = Some(known.map_or(unit.clone(), |interval| {
                interval.intersect(&unit).unwrap_or(unit)
            }));
        }
        for index in ranges.by_target.get(&wire).into_iter().flatten() {
            let decomposition = &ranges.decompositions[*index].interval;
            known = Some(match known {
                Some(interval) => interval.intersect(decomposition)?,
                None => decomposition.clone(),
            });
        }
        known
    };

    while let Some(wire) = queue.pop_front() {
        queued.remove(&wire);
        // A forced value must lie in every decomposition interval of its wire.
        if let Some(value) = values.get(&wire) {
            for index in ranges.by_target.get(&wire).into_iter().flatten() {
                let decomposition = &ranges.decompositions[*index];
                if value < &decomposition.interval.lo || value > &decomposition.interval.hi {
                    return Some(Contradiction {
                        constraint: decomposition.constraint,
                        wire,
                        decomposition: Some(decomposition.clone()),
                        detail: format!(
                            "forced value lies outside the {}-bit decomposition range",
                            decomposition.bits
                        ),
                    });
                }
            }
        }
        for &position in &index[wire] {
            visits += 1;
            if visits > budget {
                return None;
            }
            let constraint = &r1cs.constraints[position];
            let wires = wires_of(constraint);
            let unknown = wires
                .iter()
                .copied()
                .filter(|other| *other != 0 && !values.contains_key(other))
                .collect::<Vec<_>>();
            match unknown.as_slice() {
                [] => {
                    let value = |other: usize| {
                        if other == 0 {
                            Some(BigUint::one())
                        } else {
                            values.get(&other).cloned()
                        }
                    };
                    if residual(constraint, prime, &value).is_some_and(|r| !r.is_zero()) {
                        return Some(Contradiction {
                            constraint: position,
                            wire,
                            decomposition: None,
                            detail: "a constraint over forced values is violated".to_owned(),
                        });
                    }
                }
                [single] => {
                    let at = |trial: u32| {
                        residual(constraint, prime, &|other| {
                            if other == 0 {
                                Some(BigUint::one())
                            } else if other == *single {
                                Some(BigUint::from(trial))
                            } else {
                                values.get(&other).cloned()
                            }
                        })
                        .unwrap_or_default()
                    };
                    let (f0, f1, f2) = (at(0), at(1), at(2));
                    let second = (&f2 + &f0 + prime + prime - &f1 - &f1) % prime;
                    let slope = (&f1 + prime - &f0) % prime;
                    if second.is_zero() && !slope.is_zero() {
                        let solved = (prime - &f0) % prime * inverse(&slope, prime) % prime;
                        values.insert(*single, solved);
                        if queued.insert(*single) {
                            queue.push_back(*single);
                        }
                    }
                }
                _ => {}
            }
            // Interval reasoning on linear constraints: bound each wire by the others.
            if is_linear(constraint) && unknown.len() <= 3 {
                let terms = constraint
                    .c
                    .iter()
                    .filter(|(other, coefficient)| **other != 0 && !coefficient.is_zero())
                    .map(|(other, coefficient)| (*other as usize, coefficient.clone()))
                    .collect::<Vec<_>>();
                let gamma = constraint.c.get(&0).cloned().unwrap_or_default();
                for (target, alpha) in &terms {
                    if values.contains_key(target) {
                        continue;
                    }
                    let scale = (prime - inverse(alpha, prime)) % prime;
                    // target = Σ dᵢ·wᵢ + e over the other wires, as signed integers.
                    let mut lo = num_bigint::BigInt::from((&gamma * &scale) % prime);
                    let mut hi = lo.clone();
                    let mut bounded = true;
                    for (other, beta) in &terms {
                        if other == target {
                            continue;
                        }
                        let Some(interval) = interval_of(*other, &values, &intervals) else {
                            bounded = false;
                            break;
                        };
                        let d = (beta * &scale) % prime;
                        let (low, high) = (
                            num_bigint::BigInt::from(interval.lo),
                            num_bigint::BigInt::from(interval.hi),
                        );
                        if d <= half {
                            let d = num_bigint::BigInt::from(d);
                            lo += &d * &low;
                            hi += &d * &high;
                        } else {
                            let d = num_bigint::BigInt::from(prime - &d);
                            lo -= &d * &high;
                            hi -= &d * &low;
                        }
                    }
                    if !bounded {
                        continue;
                    }
                    // Keep only intervals that map to one non-wrapping field range.
                    let p = num_bigint::BigInt::from(prime.clone());
                    let (lo, hi) = if lo >= num_bigint::BigInt::zero() && hi < p {
                        (lo, hi)
                    } else if lo > -p.clone() && hi < num_bigint::BigInt::zero() {
                        (lo + &p, hi + &p)
                    } else {
                        continue;
                    };
                    let implied = Interval {
                        lo: lo.to_biguint().unwrap_or_default(),
                        hi: hi.to_biguint().unwrap_or_default(),
                    };
                    let current = interval_of(*target, &values, &intervals);
                    let narrowed = match &current {
                        Some(existing) => match existing.intersect(&implied) {
                            Some(narrowed) => narrowed,
                            None => {
                                let decomposition = ranges
                                    .by_target
                                    .get(target)
                                    .and_then(|list| list.first())
                                    .map(|index| ranges.decompositions[*index].clone());
                                return Some(Contradiction {
                                    constraint: position,
                                    wire: *target,
                                    decomposition,
                                    detail: "the interval implied by this linear constraint misses the wire's range".to_owned(),
                                });
                            }
                        },
                        None => implied,
                    };
                    if current.as_ref() != Some(&narrowed) {
                        intervals.insert(*target, narrowed);
                        if queued.insert(*target) {
                            queue.push_back(*target);
                        }
                    }
                }
            }
        }
    }
    None
}

fn wires_of(constraint: &Constraint) -> BTreeSet<usize> {
    constraint
        .a
        .keys()
        .chain(constraint.b.keys())
        .chain(constraint.c.keys())
        .map(|wire| *wire as usize)
        .collect()
}

fn residual(
    constraint: &Constraint,
    prime: &BigUint,
    value: &dyn Fn(usize) -> Option<BigUint>,
) -> Option<BigUint> {
    let evaluate = |combination: &super::super::r1cs::LinearCombination| -> Option<BigUint> {
        let mut total = BigUint::zero();
        for (wire, coefficient) in combination {
            let wire_value = if *wire == 0 {
                BigUint::one()
            } else {
                value(*wire as usize)?
            };
            total = (total + coefficient * wire_value) % prime;
        }
        Some(total)
    };
    let a = evaluate(&constraint.a)?;
    let b = evaluate(&constraint.b)?;
    let c = evaluate(&constraint.c)?;
    Some((a * b % prime + prime - c) % prime)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::candidate_review::lifting::refute::constraint_index;
    use crate::candidate_review::r1cs::LinearCombination;
    use crate::candidate_review::schema::R1csShape;

    fn lc(terms: &[(u32, u64)], prime: &BigUint) -> LinearCombination {
        terms
            .iter()
            .map(|(wire, coefficient)| (*wire, BigUint::from(*coefficient) % prime))
            .collect()
    }

    /// Wire 1 = x (fixed); wires 2..=9 are eight bits whose boolean constraints sit on copy
    /// wires 10..=17 (as with an `AssertBit()` sub-component); x = Σ bᵢ·2ⁱ.
    fn eight_bits(prime: &BigUint) -> (R1cs, Vec<usize>) {
        let minus = |value: u64| prime - BigUint::from(value);
        let mut constraints = Vec::new();
        let mut parent = (0..18).collect::<Vec<usize>>();
        for bit in 0..8u32 {
            let (wire, copy) = (2 + bit, 10 + bit);
            constraints.push(Constraint {
                a: lc(&[(copy, 1)], prime),
                b: [(copy, BigUint::one()), (0, minus(1))]
                    .into_iter()
                    .collect(),
                c: LinearCombination::new(),
            });
            parent[copy as usize] = wire as usize;
        }
        let mut sum: LinearCombination = [(1u32, BigUint::one())].into_iter().collect();
        for bit in 0..8u32 {
            sum.insert(2 + bit, minus(1 << bit));
        }
        constraints.push(Constraint {
            a: LinearCombination::new(),
            b: LinearCombination::new(),
            c: sum,
        });
        let r1cs = R1cs {
            prime: prime.clone(),
            shape: R1csShape {
                wires: 18,
                labels: 18,
                public_outputs: 0,
                public_inputs: 1,
                private_inputs: 0,
                constraints: constraints.len(),
            },
            constraints,
            wire_labels: (0..18).collect(),
        };
        (r1cs, parent)
    }

    #[test]
    fn decomposition_range_refutes_an_out_of_range_value_and_accepts_an_in_range_one() {
        let prime = BigUint::from(1_000_003u32);
        let (r1cs, parent) = eight_bits(&prime);
        let root = |wire: usize| parent[wire];
        let ranges = build(&r1cs, &root);
        assert_eq!(ranges.decompositions.len(), 1);
        let decomposition = &ranges.decompositions[0];
        assert_eq!((decomposition.target, decomposition.bits), (1, 8));
        assert_eq!(decomposition.interval.hi, BigUint::from(255u32));
        let index = constraint_index(&r1cs);
        let fixed = |x: u32| BTreeMap::from([(1usize, BigUint::from(x))]);
        let contradiction = propagate(&r1cs, &index, &ranges, &root, &fixed(300), 10_000)
            .expect("300 needs nine bits");
        assert_eq!(contradiction.constraint, decomposition.constraint);
        assert!(propagate(&r1cs, &index, &ranges, &root, &fixed(200), 10_000).is_none());
    }
}
