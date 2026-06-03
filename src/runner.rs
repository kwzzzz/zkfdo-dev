use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct ZkFuzzCommand {
    pub binary: PathBuf,
    pub args: Vec<String>,
}

impl ZkFuzzCommand {
    pub fn as_shell_words(&self) -> Vec<String> {
        let mut words = Vec::with_capacity(self.args.len() + 1);
        words.push(self.binary.display().to_string());
        words.extend(self.args.clone());
        words
    }
}

#[derive(Debug, Clone)]
pub struct ZkFuzzCommandBuilder {
    binary: PathBuf,
    target: PathBuf,
    budget_seconds: Option<u64>,
    extra_args: Vec<String>,
}

impl ZkFuzzCommandBuilder {
    pub fn new(binary: impl Into<PathBuf>, target: impl Into<PathBuf>) -> Self {
        Self {
            binary: binary.into(),
            target: target.into(),
            budget_seconds: None,
            extra_args: Vec::new(),
        }
    }

    pub fn budget_seconds(mut self, budget_seconds: u64) -> Self {
        self.budget_seconds = Some(budget_seconds);
        self
    }

    pub fn extra_arg(mut self, arg: impl Into<String>) -> Self {
        self.extra_args.push(arg.into());
        self
    }

    pub fn build(self) -> ZkFuzzCommand {
        let mut args = vec![self.target.display().to_string()];

        if let Some(seconds) = self.budget_seconds {
            args.push("--budget-seconds".to_string());
            args.push(seconds.to_string());
        }

        args.extend(self.extra_args);

        ZkFuzzCommand {
            binary: self.binary,
            args,
        }
    }
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct DryRunResult {
    pub command: ZkFuzzCommand,
}

pub fn build_dry_run(
    binary: impl AsRef<Path>,
    target: impl AsRef<Path>,
    budget_seconds: Option<u64>,
) -> DryRunResult {
    let mut builder = ZkFuzzCommandBuilder::new(binary.as_ref(), target.as_ref());

    if let Some(seconds) = budget_seconds {
        builder = builder.budget_seconds(seconds);
    }

    DryRunResult {
        command: builder.build(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn builds_dry_run_command_with_budget() {
        let dry_run = build_dry_run("zkfuzz", "circuits/main.circom", Some(60));

        assert_eq!(
            dry_run.command.as_shell_words(),
            vec!["zkfuzz", "circuits/main.circom", "--budget-seconds", "60"]
        );
    }
}
