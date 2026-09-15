use std::{collections::BTreeSet, path::PathBuf};

use zkfdo::static_rank::{
    rank_targets, ComplexityGroups, RankingInput, RankingStrategy, StaticRankingConfig,
    RANDOM_ALGORITHM,
};

const STRATEGIES: [RankingStrategy; 7] = [
    RankingStrategy::PathOrder,
    RankingStrategy::Random,
    RankingStrategy::SmallFirst,
    RankingStrategy::Legacy,
    RankingStrategy::WarningFirst,
    RankingStrategy::RiskOnly,
    RankingStrategy::RiskGrouped,
];

fn target(id: &str, risk: u64, complexity: u64) -> RankingInput {
    RankingInput {
        target_id: id.to_owned(),
        path: PathBuf::from(format!("{id}.circom")),
        risk_score: Some(risk),
        warning_count: Some(risk),
        complexity: Some(complexity),
        size: Some(complexity),
        legacy_score: Some(risk as f64),
    }
}

fn config() -> StaticRankingConfig {
    StaticRankingConfig {
        schema_version: 1,
        complexity_groups: Some(ComplexityGroups {
            metric: "test-fixture-structure-count".to_owned(),
            upper_bounds: vec![10, 20],
            group_order: vec![0, 1, 2],
            provenance: "Synthetic unit test boundaries, not corpus-derived defaults".to_owned(),
        }),
    }
}

fn ids(targets: &[RankingInput]) -> Vec<&str> {
    targets
        .iter()
        .map(|target| target.target_id.as_str())
        .collect()
}

fn rank(targets: &[RankingInput], strategy: RankingStrategy) -> Vec<RankingInput> {
    rank_targets(targets, strategy, &config(), Some(42)).expect("valid ranking")
}

#[test]
fn empty_input_returns_empty_for_every_strategy() {
    for strategy in STRATEGIES {
        assert!(rank(&[], strategy).is_empty());
    }
}

#[test]
fn tied_scores_use_target_id_independently_of_input_order() {
    let targets = vec![target("C", 2, 8), target("A", 2, 8), target("B", 2, 8)];
    for strategy in STRATEGIES {
        if strategy == RankingStrategy::Random {
            continue;
        }
        assert_eq!(ids(&rank(&targets, strategy)), ["A", "B", "C"]);
        let mut reversed = targets.clone();
        reversed.reverse();
        assert_eq!(rank(&targets, strategy), rank(&reversed, strategy));
    }
}

#[test]
fn path_order_uses_path_then_id_but_risk_ties_use_only_id() {
    let mut a = target("A", 1, 1);
    let mut b = target("B", 1, 1);
    let c = target("C", 1, 1);
    a.path = PathBuf::from("Z.circom");
    b.path = PathBuf::from("Z.circom");
    let targets = vec![b, c, a];
    assert_eq!(
        ids(&rank(&targets, RankingStrategy::PathOrder)),
        ["C", "A", "B"]
    );
    assert_eq!(
        ids(&rank(&targets, RankingStrategy::RiskOnly)),
        ["A", "B", "C"]
    );
}

#[test]
fn grouped_selects_one_per_group_in_configured_order_with_risk_ties() {
    let targets = vec![
        target("small-low", 1, 5),
        target("large-b", 4, 21),
        target("middle-high", 6, 15),
        target("small-high", 5, 10),
        target("large-a", 4, 40),
        target("middle-low", 2, 20),
        target("large-low", 0, 30),
    ];
    let mut settings = config();
    settings.complexity_groups.as_mut().unwrap().group_order = vec![2, 0, 1];
    let grouped = rank_targets(&targets, RankingStrategy::RiskGrouped, &settings, None).unwrap();
    assert_eq!(
        ids(&grouped),
        [
            "large-a",
            "small-high",
            "middle-high",
            "large-b",
            "small-low",
            "middle-low",
            "large-low"
        ]
    );
    for selected in grouped {
        let original = targets
            .iter()
            .find(|item| item.target_id == selected.target_id)
            .unwrap();
        assert_eq!(
            &selected, original,
            "grouping must not alter scores or features"
        );
    }
}

#[test]
fn empty_groups_are_skipped_and_single_group_matches_risk_only() {
    let targets = vec![target("A", 1, 1), target("B", 3, 8), target("C", 2, 2)];
    assert_eq!(
        rank(&targets, RankingStrategy::RiskGrouped),
        rank(&targets, RankingStrategy::RiskOnly)
    );
    let mut settings = config();
    let groups = settings.complexity_groups.as_mut().unwrap();
    groups.upper_bounds.clear();
    groups.group_order = vec![0];
    assert_eq!(
        rank_targets(&targets, RankingStrategy::RiskGrouped, &settings, None).unwrap(),
        rank(&targets, RankingStrategy::RiskOnly)
    );
}

#[test]
fn inclusive_boundaries_and_overflow_bin_are_exact() {
    let groups = config().complexity_groups.unwrap();
    for (value, expected) in [(0, 0), (10, 0), (11, 1), (20, 1), (21, 2), (u64::MAX, 2)] {
        assert_eq!(groups.group_index(value), expected);
    }
}

#[test]
fn every_strategy_preserves_the_complete_target_set() {
    let targets = (0..47)
        .map(|i| target(&format!("id-{i:02}"), i % 7, i))
        .collect::<Vec<_>>();
    let expected = ids(&targets).into_iter().collect::<BTreeSet<_>>();
    for strategy in STRATEGIES {
        let result = rank(&targets, strategy);
        assert_eq!(result.len(), targets.len());
        assert_eq!(ids(&result).into_iter().collect::<BTreeSet<_>>(), expected);
    }
}

#[test]
fn duplicate_or_empty_target_ids_are_errors_for_every_strategy() {
    for strategy in STRATEGIES {
        let duplicate = [target("A", 1, 5), target("A", 2, 15)];
        let error = rank_targets(&duplicate, strategy, &config(), Some(42)).unwrap_err();
        assert!(error.to_string().contains("duplicate target ID: A"));
        assert!(rank_targets(&[target(" ", 1, 5)], strategy, &config(), Some(42)).is_err());
    }
}

#[test]
fn missing_required_features_fail_instead_of_becoming_zero() {
    let cases = [
        (RankingStrategy::SmallFirst, "size"),
        (RankingStrategy::WarningFirst, "warning_count"),
        (RankingStrategy::RiskOnly, "risk_score"),
        (RankingStrategy::RiskGrouped, "risk_score"),
        (RankingStrategy::RiskGrouped, "complexity"),
        (RankingStrategy::Legacy, "legacy_score"),
    ];
    for (strategy, field) in cases {
        let mut incomplete = target("unknown", 1, 5);
        match field {
            "size" => incomplete.size = None,
            "warning_count" => incomplete.warning_count = None,
            "risk_score" => incomplete.risk_score = None,
            "complexity" => incomplete.complexity = None,
            "legacy_score" => incomplete.legacy_score = None,
            _ => unreachable!(),
        }
        let error = rank_targets(&[incomplete], strategy, &config(), Some(42)).unwrap_err();
        assert!(error.to_string().contains(field), "{error}");
        assert!(error.to_string().contains("unknown"), "{error}");
    }
}

#[test]
fn simple_baselines_do_not_require_unrelated_analysis() {
    let mut unknown = target("A", 0, 0);
    unknown.risk_score = None;
    unknown.warning_count = None;
    unknown.complexity = None;
    unknown.size = None;
    unknown.legacy_score = None;
    for strategy in [RankingStrategy::PathOrder, RankingStrategy::Random] {
        assert!(rank_targets(
            &[unknown.clone()],
            strategy,
            &StaticRankingConfig::default(),
            Some(5)
        )
        .is_ok());
    }
}

#[test]
fn baseline_features_remain_distinct_and_cost_does_not_change_risk() {
    let mut a = target("A", 2, 100);
    let mut b = target("B", 1, 1);
    a.warning_count = Some(2);
    b.warning_count = Some(5);
    a.legacy_score = Some(0.2);
    b.legacy_score = Some(0.5);
    let targets = [b, a];
    assert_eq!(ids(&rank(&targets, RankingStrategy::RiskOnly)), ["A", "B"]);
    for strategy in [
        RankingStrategy::WarningFirst,
        RankingStrategy::SmallFirst,
        RankingStrategy::Legacy,
    ] {
        assert_eq!(ids(&rank(&targets, strategy)), ["B", "A"]);
    }
}

#[test]
fn legacy_rejects_nan_and_infinity_and_treats_signed_zero_as_tie() {
    for score in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
        let mut invalid = target("A", 1, 1);
        invalid.legacy_score = Some(score);
        assert!(rank_targets(&[invalid], RankingStrategy::Legacy, &config(), None).is_err());
    }
    let mut a = target("A", 1, 1);
    let mut b = target("B", 1, 1);
    a.legacy_score = Some(-0.0);
    b.legacy_score = Some(0.0);
    assert_eq!(ids(&rank(&[b, a], RankingStrategy::Legacy)), ["A", "B"]);
}

#[test]
fn invalid_or_absent_group_configuration_is_not_silently_replaced() {
    assert!(rank_targets(
        &[],
        RankingStrategy::RiskGrouped,
        &StaticRankingConfig::default(),
        None
    )
    .is_err());
    for (bounds, order) in [
        (vec![20, 10], vec![0, 1, 2]),
        (vec![10, 10], vec![0, 1, 2]),
        (vec![10, 20], vec![0, 0, 2]),
        (vec![10, 20], vec![0, 1]),
        (vec![10, 20], vec![0, 1, 3]),
    ] {
        let mut settings = config();
        let groups = settings.complexity_groups.as_mut().unwrap();
        groups.upper_bounds = bounds;
        groups.group_order = order;
        assert!(rank_targets(&[], RankingStrategy::RiskGrouped, &settings, None).is_err());
    }
    let mut settings = config();
    settings.schema_version = 2;
    assert!(rank_targets(&[], RankingStrategy::PathOrder, &settings, None).is_err());
}

#[test]
fn seeded_random_is_reproducible_independent_of_discovery_order() {
    let targets = (0..10)
        .map(|i| target(&format!("id-{i}"), 0, 0))
        .collect::<Vec<_>>();
    let mut reversed = targets.clone();
    reversed.reverse();
    let first = rank(&targets, RankingStrategy::Random);
    assert_eq!(first, rank(&targets, RankingStrategy::Random));
    assert_eq!(first, rank(&reversed, RankingStrategy::Random));
    assert_ne!(
        first,
        rank_targets(&targets, RankingStrategy::Random, &config(), Some(43)).unwrap()
    );
    assert!(rank_targets(&targets, RankingStrategy::Random, &config(), None).is_err());
    assert_eq!(RANDOM_ALGORITHM, "splitmix64-fisher-yates-rejection-v1");
    assert_eq!(
        ids(&first),
        ["id-0", "id-9", "id-5", "id-8", "id-6", "id-4", "id-7", "id-2", "id-1", "id-3"]
    );
}

#[test]
fn strategies_and_config_serialize_without_implicit_group_defaults() {
    let settings = config();
    assert_eq!(
        serde_json::from_str::<StaticRankingConfig>(&serde_json::to_string(&settings).unwrap())
            .unwrap(),
        settings
    );
    for strategy in STRATEGIES {
        assert_eq!(
            strategy.to_string().parse::<RankingStrategy>().unwrap(),
            strategy
        );
        assert_eq!(
            serde_json::from_str::<RankingStrategy>(&serde_json::to_string(&strategy).unwrap())
                .unwrap(),
            strategy
        );
    }
    assert!("adaptive".parse::<RankingStrategy>().is_err());
    assert!(serde_json::from_str::<StaticRankingConfig>(
        r#"{"schema_version":1,"complexity_groups":null,"unknown":1}"#
    )
    .is_err());
}
