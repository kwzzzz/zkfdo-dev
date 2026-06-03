use std::path::PathBuf;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct TargetFeatures {
    pub path: PathBuf,
    pub signal_count: usize,
    pub constraint_count_estimate: usize,
    pub template_count: usize,
}

impl TargetFeatures {
    pub fn empty(path: impl Into<PathBuf>) -> Self {
        Self {
            path: path.into(),
            signal_count: 0,
            constraint_count_estimate: 0,
            template_count: 0,
        }
    }
}
