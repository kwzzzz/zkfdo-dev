use std::path::PathBuf;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct CircomTarget {
    pub path: PathBuf,
}

pub fn scan_placeholder() -> Vec<CircomTarget> {
    Vec::new()
}
