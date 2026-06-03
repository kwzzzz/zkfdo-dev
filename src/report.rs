use std::path::PathBuf;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct ReportRequest {
    pub input_run_dir: PathBuf,
    pub output_dir: PathBuf,
}

pub fn report_placeholder(request: ReportRequest) -> ReportRequest {
    request
}
