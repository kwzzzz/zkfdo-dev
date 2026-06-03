use std::path::PathBuf;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct RankedTarget {
    pub path: PathBuf,
    pub risk_score: f64,
    pub cost_score: f64,
    pub rank_score: f64,
}

pub fn rank_placeholder() -> Vec<RankedTarget> {
    Vec::new()
}
