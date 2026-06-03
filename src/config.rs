use std::path::PathBuf;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ProjectConfig {
    pub project_root: PathBuf,
    pub profile: FuzzingProfile,
    pub zkfuzz: ZkFuzzConfig,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ZkFuzzConfig {
    pub binary: PathBuf,
    pub extra_args: Vec<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct FuzzingProfile {
    pub name: String,
    pub total_budget_seconds: u64,
    pub smoke_budget_seconds: u64,
    pub max_targets: usize,
}

impl FuzzingProfile {
    pub fn fast() -> Self {
        Self {
            name: "fast".to_string(),
            total_budget_seconds: 600,
            smoke_budget_seconds: 30,
            max_targets: 10,
        }
    }
}
