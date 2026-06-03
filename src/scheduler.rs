use std::path::PathBuf;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct ScheduledTarget {
    pub path: PathBuf,
    pub budget_seconds: u64,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct FuzzingSchedule {
    pub total_budget_seconds: u64,
    pub targets: Vec<ScheduledTarget>,
}

pub fn schedule_placeholder(total_budget_seconds: u64) -> FuzzingSchedule {
    FuzzingSchedule {
        total_budget_seconds,
        targets: Vec::new(),
    }
}
