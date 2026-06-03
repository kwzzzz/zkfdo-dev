use thiserror::Error;

#[derive(Debug, Error)]
pub enum ZkfdoError {
    #[error("a target Circom file is required")]
    MissingTarget,

    #[error("the configured budget must be greater than zero")]
    InvalidBudget,
}
