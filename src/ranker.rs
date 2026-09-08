use std::path::PathBuf;

use serde::{Deserialize, Serialize};

use crate::features::TargetFeatures;

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct RankedTarget {
    pub path: PathBuf,
    pub risk_score: f64,
    pub cost_score: f64,
    pub rank_score: f64,
}

pub fn rank_targets(features: &[TargetFeatures]) -> Vec<RankedTarget> {
    let mut ranked = features
        .iter()
        .map(|features| {
            let risk_score = static_risk_score(features);
            let cost_score = estimated_cost_score(features);

            RankedTarget {
                path: features.path.clone(),
                risk_score,
                cost_score,
                rank_score: risk_score / cost_score,
            }
        })
        .collect::<Vec<_>>();

    ranked.sort_by(|left, right| {
        right
            .rank_score
            .total_cmp(&left.rank_score)
            .then_with(|| left.path.cmp(&right.path))
    });

    ranked
}

pub fn static_risk_score(features: &TargetFeatures) -> f64 {
    (20 * features.unsafe_assign_count
        + 20 * features.unsafe_assign_rev_count
        + 15 * features.assert_count
        + 8 * features.division_count
        + 6 * features.modulo_count
        + 5 * features.array_access_count
        + 5 * features.less_than_pattern_count
        + 5 * features.num2bits_pattern_count
        + 5 * features.iszero_pattern_count
        + 3 * features.signal_input_count) as f64
}

pub fn estimated_cost_score(features: &TargetFeatures) -> f64 {
    1.0 + ln_1p(features.loc)
        + ln_1p(features.signal_count)
        + ln_1p(features.component_count)
        + ln_1p(features.constraint_count_estimate)
}

fn ln_1p(value: usize) -> f64 {
    (1.0 + value as f64).ln()
}

pub fn rank_placeholder() -> Vec<RankedTarget> {
    Vec::new()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn base_features(path: &str) -> TargetFeatures {
        TargetFeatures::empty(path)
    }

    #[test]
    fn computes_static_risk_from_documented_weights() {
        let mut features = base_features("risky.circom");
        features.unsafe_assign_count = 1;
        features.assert_count = 1;
        features.division_count = 1;
        features.signal_input_count = 2;

        assert_eq!(static_risk_score(&features), 49.0);
    }

    #[test]
    fn ranks_higher_priority_targets_first() {
        let mut risky = base_features("risky.circom");
        risky.unsafe_assign_count = 2;
        risky.signal_input_count = 1;
        risky.loc = 20;

        let mut low_signal = base_features("low.circom");
        low_signal.signal_input_count = 1;
        low_signal.loc = 20;

        let ranked = rank_targets(&[low_signal, risky]);

        assert_eq!(ranked[0].path, PathBuf::from("risky.circom"));
        assert!(ranked[0].rank_score > ranked[1].rank_score);
    }
}
