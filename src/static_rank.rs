use std::{collections::BTreeSet, fmt, path::PathBuf, str::FromStr};

use anyhow::{bail, ensure, Context, Result};
use serde::{Deserialize, Serialize};

pub const RANDOM_ALGORITHM: &str = "splitmix64-fisher-yates-rejection-v1";

#[derive(Debug, Clone, Copy, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum RankingStrategy {
    PathOrder,
    Random,
    SmallFirst,
    Legacy,
    WarningFirst,
    RiskOnly,
    RiskGrouped,
}

impl fmt::Display for RankingStrategy {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::PathOrder => "path-order",
            Self::Random => "random",
            Self::SmallFirst => "small-first",
            Self::Legacy => "legacy",
            Self::WarningFirst => "warning-first",
            Self::RiskOnly => "risk-only",
            Self::RiskGrouped => "risk-grouped",
        })
    }
}

impl FromStr for RankingStrategy {
    type Err = anyhow::Error;

    fn from_str(value: &str) -> Result<Self> {
        match value {
            "path-order" => Ok(Self::PathOrder),
            "random" => Ok(Self::Random),
            "small-first" => Ok(Self::SmallFirst),
            "legacy" => Ok(Self::Legacy),
            "warning-first" => Ok(Self::WarningFirst),
            "risk-only" => Ok(Self::RiskOnly),
            "risk-grouped" => Ok(Self::RiskGrouped),
            _ => bail!("unknown static ranking strategy: {value}"),
        }
    }
}

/// Scores and their provenance are supplied by the target/feature adapter.
/// None means unavailable, never a zero-risk or zero-size observation.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct RankingInput {
    pub target_id: String,
    pub path: PathBuf,
    pub risk_score: Option<u64>,
    pub warning_count: Option<u64>,
    pub complexity: Option<u64>,
    pub size: Option<u64>,
    pub legacy_score: Option<f64>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct StaticRankingConfig {
    pub schema_version: u32,
    pub complexity_groups: Option<ComplexityGroups>,
}

impl Default for StaticRankingConfig {
    fn default() -> Self {
        Self {
            schema_version: 1,
            complexity_groups: None,
        }
    }
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ComplexityGroups {
    pub metric: String,
    /// Inclusive upper bounds; values above the last bound form one more group.
    pub upper_bounds: Vec<u64>,
    /// A permutation of 0..=upper_bounds.len(), fixed before comparison runs.
    pub group_order: Vec<usize>,
    pub provenance: String,
}

impl ComplexityGroups {
    pub fn validate(&self) -> Result<()> {
        ensure!(
            !self.metric.trim().is_empty(),
            "complexity metric is required"
        );
        ensure!(
            !self.provenance.trim().is_empty(),
            "complexity boundary provenance is required"
        );
        ensure!(
            self.upper_bounds.windows(2).all(|pair| pair[0] < pair[1]),
            "complexity upper bounds must be strictly increasing"
        );
        let expected = (0..=self.upper_bounds.len()).collect::<BTreeSet<_>>();
        let actual = self.group_order.iter().copied().collect::<BTreeSet<_>>();
        ensure!(
            self.group_order.len() == expected.len() && actual == expected,
            "complexity group_order must contain every group index exactly once"
        );
        Ok(())
    }

    pub fn group_index(&self, complexity: u64) -> usize {
        self.upper_bounds
            .partition_point(|upper| complexity > *upper)
    }
}

pub fn rank_targets(
    inputs: &[RankingInput],
    strategy: RankingStrategy,
    config: &StaticRankingConfig,
    ranking_seed: Option<u64>,
) -> Result<Vec<RankingInput>> {
    ensure!(
        config.schema_version == 1,
        "unsupported static ranking config version: {}",
        config.schema_version
    );
    if strategy == RankingStrategy::Random {
        ensure!(
            ranking_seed.is_some(),
            "random ranking requires a ranking seed"
        );
    }
    if strategy == RankingStrategy::RiskGrouped {
        config
            .complexity_groups
            .as_ref()
            .context("risk-grouped requires explicit complexity groups from development profiling")?
            .validate()?;
    }

    let mut ids = BTreeSet::new();
    for target in inputs {
        ensure!(
            !target.target_id.trim().is_empty(),
            "target ID must not be empty"
        );
        ensure!(
            ids.insert(&target.target_id),
            "duplicate target ID: {}",
            target.target_id
        );
        let required = match strategy {
            RankingStrategy::SmallFirst => Some(("size", target.size)),
            RankingStrategy::WarningFirst => Some(("warning_count", target.warning_count)),
            RankingStrategy::RiskOnly | RankingStrategy::RiskGrouped => {
                Some(("risk_score", target.risk_score))
            }
            _ => None,
        };
        if let Some((name, value)) = required {
            ensure!(
                value.is_some(),
                "{strategy}: target {} is missing {name}",
                target.target_id
            );
        }
        if strategy == RankingStrategy::RiskGrouped {
            ensure!(
                target.complexity.is_some(),
                "risk-grouped: target {} is missing complexity",
                target.target_id
            );
        }
        if strategy == RankingStrategy::Legacy {
            ensure!(
                target.legacy_score.is_some_and(f64::is_finite),
                "legacy: target {} needs a finite legacy_score",
                target.target_id
            );
        }
    }

    let mut ranked = inputs.to_vec();
    match strategy {
        RankingStrategy::PathOrder => ranked.sort_by(|a, b| {
            a.path
                .cmp(&b.path)
                .then_with(|| a.target_id.cmp(&b.target_id))
        }),
        RankingStrategy::Random => {
            // Canonical input order makes the seeded permutation independent of discovery order.
            ranked.sort_by(|a, b| a.target_id.cmp(&b.target_id));
            let mut random = SplitMix64(ranking_seed.context("missing ranking seed")?);
            for index in (1..ranked.len()).rev() {
                let other = random.below((index + 1) as u64) as usize;
                ranked.swap(index, other);
            }
        }
        RankingStrategy::SmallFirst => ranked.sort_by(|a, b| {
            a.size
                .cmp(&b.size)
                .then_with(|| a.target_id.cmp(&b.target_id))
        }),
        RankingStrategy::WarningFirst => ranked.sort_by(|a, b| {
            b.warning_count
                .cmp(&a.warning_count)
                .then_with(|| a.target_id.cmp(&b.target_id))
        }),
        RankingStrategy::Legacy => ranked.sort_by(|a, b| {
            b.legacy_score
                .partial_cmp(&a.legacy_score)
                .expect("validated finite legacy scores")
                .then_with(|| a.target_id.cmp(&b.target_id))
        }),
        RankingStrategy::RiskOnly => ranked.sort_by(risk_order),
        RankingStrategy::RiskGrouped => {
            let settings = config
                .complexity_groups
                .as_ref()
                .context("missing groups")?;
            let mut groups = vec![Vec::new(); settings.upper_bounds.len() + 1];
            ranked.sort_by(risk_order);
            for target in ranked {
                let group = settings.group_index(target.complexity.context("missing complexity")?);
                groups[group].push(target);
            }
            let mut groups = groups.into_iter().map(Vec::into_iter).collect::<Vec<_>>();
            ranked = Vec::with_capacity(inputs.len());
            loop {
                let before = ranked.len();
                for &group in &settings.group_order {
                    if let Some(target) = groups[group].next() {
                        ranked.push(target);
                    }
                }
                if ranked.len() == before {
                    break;
                }
            }
        }
    }
    Ok(ranked)
}

fn risk_order(a: &RankingInput, b: &RankingInput) -> std::cmp::Ordering {
    b.risk_score
        .cmp(&a.risk_score)
        .then_with(|| a.target_id.cmp(&b.target_id))
}

// SplitMix64 with its standard fixed constants; wrapping arithmetic is intentional.
struct SplitMix64(u64);

impl SplitMix64 {
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9e3779b97f4a7c15);
        let mut value = self.0;
        value = (value ^ (value >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
        value = (value ^ (value >> 27)).wrapping_mul(0x94d049bb133111eb);
        value ^ (value >> 31)
    }

    fn below(&mut self, bound: u64) -> u64 {
        let threshold = bound.wrapping_neg() % bound;
        loop {
            let value = self.next();
            if value >= threshold {
                return value % bound;
            }
        }
    }
}
