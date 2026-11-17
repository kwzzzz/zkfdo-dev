//! Bounded local refutation: show that a small subset of the original R1CS constraints has
//! no solution once the public inputs are fixed. A subset without a solution proves that
//! the whole system has none, so a refutation is a sound exclusion. Failing to refute
//! proves nothing.

use std::collections::{BTreeMap, BTreeSet};

use num_bigint::BigUint;
use num_traits::{One, Zero};

use super::super::r1cs::{Constraint, LinearCombination, R1cs};

/// Limits that keep the search local and cheap.
const MAX_DEPTH: usize = 4;
const MAX_CONSTRAINTS: usize = 256;
const MAX_UNKNOWNS: usize = 96;
const MAX_BOOLEANS: usize = 16;

pub(crate) struct Refutation {
    pub(crate) constraints: Vec<usize>,
    pub(crate) unknowns: usize,
    pub(crate) booleans: usize,
}

/// Wire → indices of the constraints that mention it.
pub(crate) fn constraint_index(r1cs: &R1cs) -> Vec<Vec<usize>> {
    let mut index = vec![Vec::new(); r1cs.shape.wires];
    for (position, constraint) in r1cs.constraints.iter().enumerate() {
        let wires = constraint
            .a
            .keys()
            .chain(constraint.b.keys())
            .chain(constraint.c.keys())
            .copied()
            .collect::<BTreeSet<_>>();
        for wire in wires {
            index[wire as usize].push(position);
        }
    }
    index
}

/// Grows constraint subsets around `start` wires layer by layer and tries to refute each.
pub(crate) fn refute(
    r1cs: &R1cs,
    index: &[Vec<usize>],
    fixed: &BTreeMap<u32, BigUint>,
    start: &[u32],
) -> Option<Refutation> {
    let mut chosen = BTreeSet::new();
    let mut frontier = start.iter().copied().collect::<BTreeSet<_>>();
    let mut seen_wires = frontier.clone();
    for _ in 0..MAX_DEPTH {
        let mut layer = BTreeSet::new();
        for wire in &frontier {
            for position in &index[*wire as usize] {
                if !chosen.contains(position) {
                    layer.insert(*position);
                }
            }
        }
        if layer.is_empty() || chosen.len() + layer.len() > MAX_CONSTRAINTS {
            return None;
        }
        chosen.extend(layer.iter().copied());
        let subset = chosen
            .iter()
            .map(|position| (*position, &r1cs.constraints[*position]))
            .collect::<Vec<_>>();
        let unknowns = subset
            .iter()
            .flat_map(|(_, constraint)| wires_of(constraint))
            .filter(|wire| *wire != 0 && !fixed.contains_key(wire))
            .collect::<BTreeSet<_>>();
        if unknowns.len() > MAX_UNKNOWNS {
            return None;
        }
        if let Some(refutation) = refute_subset(&subset, &unknowns, fixed, &r1cs.prime) {
            return Some(refutation);
        }
        frontier = unknowns
            .iter()
            .copied()
            .filter(|wire| seen_wires.insert(*wire))
            .collect();
        if frontier.is_empty() {
            return None;
        }
    }
    None
}

pub(crate) fn refute_subset(
    subset: &[(usize, &Constraint)],
    unknowns: &BTreeSet<u32>,
    fixed: &BTreeMap<u32, BigUint>,
    prime: &BigUint,
) -> Option<Refutation> {
    let mut base = fixed.clone();
    base.insert(0, BigUint::one());
    // A wire is boolean when some constraint mentions only it among the unknowns and is
    // satisfied by exactly {0, 1} among {0, 1, 2} (a degree-two polynomial with those roots).
    let mut booleans = BTreeSet::new();
    for (_, constraint) in subset {
        let free = wires_of(constraint)
            .into_iter()
            .filter(|wire| unknowns.contains(wire))
            .collect::<Vec<_>>();
        if let [wire] = free.as_slice() {
            let at = |value: u32| residual(constraint, &base, Some((*wire, value)), prime);
            if at(0).is_some_and(|r| r.is_zero())
                && at(1).is_some_and(|r| r.is_zero())
                && at(2).is_some_and(|r| !r.is_zero())
            {
                booleans.insert(*wire);
            }
        }
    }
    if booleans.len() > MAX_BOOLEANS {
        return None;
    }
    let booleans = booleans.into_iter().collect::<Vec<_>>();
    for mask in 0u32..(1u32 << booleans.len()) {
        let mut assignment = base.clone();
        for (bit, wire) in booleans.iter().enumerate() {
            assignment.insert(*wire, BigUint::from((mask >> bit) & 1));
        }
        if !propagation_refutes(subset, &mut assignment, prime) {
            return None;
        }
    }
    Some(Refutation {
        constraints: subset.iter().map(|(position, _)| *position).collect(),
        unknowns: unknowns.len(),
        booleans: booleans.len(),
    })
}

/// Solves single-unknown linear constraints until a fixpoint. Returns true only when some
/// constraint is violated under every consequence of the assignment.
fn propagation_refutes(
    subset: &[(usize, &Constraint)],
    assignment: &mut BTreeMap<u32, BigUint>,
    prime: &BigUint,
) -> bool {
    loop {
        let mut progress = false;
        for (_, constraint) in subset {
            let free = wires_of(constraint)
                .into_iter()
                .filter(|wire| !assignment.contains_key(wire))
                .collect::<Vec<_>>();
            match free.as_slice() {
                [] => {
                    if residual(constraint, assignment, None, prime).is_some_and(|r| !r.is_zero()) {
                        return true;
                    }
                }
                [wire] => {
                    let at = |value: u32| {
                        residual(constraint, assignment, Some((*wire, value)), prime)
                            .unwrap_or_default()
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
                        continue;
                    }
                    let inverse = slope.modpow(&(prime - BigUint::from(2u32)), prime);
                    let value = ((prime - &f0) % prime * inverse) % prime;
                    assignment.insert(*wire, value);
                    progress = true;
                }
                _ => {}
            }
        }
        if !progress {
            // Nothing violated and nothing left to solve: the subset may have a solution
            // under this assignment.
            return false;
        }
    }
}

fn wires_of(constraint: &Constraint) -> Vec<u32> {
    constraint
        .a
        .keys()
        .chain(constraint.b.keys())
        .chain(constraint.c.keys())
        .copied()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect()
}

/// `A·B − C` under the assignment (with one optional trial value), or None if a wire is
/// unassigned.
fn residual(
    constraint: &Constraint,
    assignment: &BTreeMap<u32, BigUint>,
    trial: Option<(u32, u32)>,
    prime: &BigUint,
) -> Option<BigUint> {
    let evaluate = |combination: &LinearCombination| -> Option<BigUint> {
        let mut total = BigUint::zero();
        for (wire, coefficient) in combination {
            let value = match trial {
                Some((trial_wire, trial_value)) if trial_wire == *wire => {
                    BigUint::from(trial_value)
                }
                _ => assignment.get(wire)?.clone(),
            };
            total = (total + coefficient * value) % prime;
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
    use crate::candidate_review::schema::R1csShape;

    fn lc(terms: &[(u32, u64)], prime: &BigUint) -> LinearCombination {
        terms
            .iter()
            .map(|(wire, coefficient)| (*wire, BigUint::from(*coefficient) % prime))
            .collect()
    }

    /// Wire 1 is a fixed input x; wires 2..=4 are bits with x = b0 + 2·b1 + 4·b2.
    fn three_bit_range() -> R1cs {
        let prime = BigUint::from(101u32);
        let minus = |value: u64| 101 - value;
        let mut constraints = Vec::new();
        for bit in 2..=4u32 {
            constraints.push(Constraint {
                a: lc(&[(bit, 1)], &prime),
                b: lc(&[(bit, 1), (0, minus(1))], &prime),
                c: LinearCombination::new(),
            });
        }
        constraints.push(Constraint {
            a: LinearCombination::new(),
            b: LinearCombination::new(),
            c: lc(
                &[(1, 1), (2, minus(1)), (3, minus(2)), (4, minus(4))],
                &prime,
            ),
        });
        R1cs {
            prime,
            shape: R1csShape {
                wires: 5,
                labels: 5,
                public_outputs: 0,
                public_inputs: 1,
                private_inputs: 0,
                constraints: 4,
            },
            constraints,
            wire_labels: (0..5).collect(),
        }
    }

    #[test]
    fn out_of_range_input_is_refuted_and_in_range_input_is_not() {
        let r1cs = three_bit_range();
        let index = constraint_index(&r1cs);
        let fixed = |x: u32| BTreeMap::from([(1u32, BigUint::from(x))]);
        let refutation = refute(&r1cs, &index, &fixed(8), &[1]).expect("8 needs four bits");
        assert_eq!(refutation.booleans, 3);
        assert!(refute(&r1cs, &index, &fixed(5), &[1]).is_none());
    }
}
