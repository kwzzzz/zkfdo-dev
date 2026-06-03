# Problem Statement

## Motivation

Large Circom projects can contain many files, templates, components, and possible fuzzing entrypoints. Running zkFuzz naively on every candidate target in an arbitrary order can waste a limited fuzzing budget on low-priority targets, expensive targets, or targets that fail before meaningful fuzzing begins.

`zkfDO` is a Rust-based helper CLI for zkFuzz. The name comes from DOUM, or "도움", meaning help. zkfDO helps zkFuzz handle large Circom projects by discovering fuzzing targets, extracting static and cost features, prioritizing targets, scheduling zkFuzz executions under a fixed budget, collecting structured results, and generating reports.

zkfDO does not replace zkFuzz. It is intended to help zkFuzz run more effectively at the project level.

## Project Identity

zkfDO is not just a thin wrapper around a subprocess call. The core research contribution is deciding how zkFuzz should be applied to a large Circom project when time is limited.

The system may technically orchestrate zkFuzz runs, but the name `zkfDO` should not be expanded as "Directed Orchestrator". Its intended meaning is tied to "도움": a helper tool that improves the workflow around zkFuzz.

The project name is also not limited to "ranker". Ranking is one important component, but the full tool may include target discovery, scheduling, result collection, configuration, report generation, experiment automation, and reproducible evaluation support.

## Problem Definition

Given a large Circom project and a limited fuzzing budget, how can we decide which Circom targets should be fuzzed first, and how much time should be allocated to them, so that zkFuzz can discover vulnerabilities more efficiently than naive execution strategies such as random order, size-first order, or warning-first order?

## Input

- A Circom project `P`
- Candidate fuzzing targets `T = {t1, t2, ..., tn}`
- A total fuzzing budget `B`
- An external fuzzing engine `F = zkFuzz`

## Output

- An execution plan or schedule `S`
- Structured fuzzing results `R`

## Goals

- Reduce time-to-first-bug.
- Improve bugs found within a fixed budget.
- Reduce wasted fuzzing time on low-priority or overly expensive targets.
- Make large Circom project fuzzing more manageable and reproducible.
- Provide useful structured outputs for later analysis and reports.

## Assumptions

- zkFuzz already exists and is invoked as an external binary.
- The team has studied the zkFuzz and zkCraft papers.
- zkFuzz and zkCraft are treated as background and related-work context, not implementation targets.
- The first version focuses on project-level target selection and execution management.
- Static analysis features are heuristic signals, not proofs of vulnerability.
- Some optional tools, such as circomspect, may not always be installed.

## Non-Goals

- Do not reimplement zkFuzz.
- Do not reimplement zkCraft.
- Do not modify zkFuzz internals unless explicitly requested later.
- Do not claim guaranteed vulnerability discovery.
- Do not build a web UI yet.
- Do not build an ML ranker yet.
- Do not make the first version depend on LLMs.
- Do not require full support for every possible Circom template parameterization in v1.

## Expected Contributions

- A Circom target discovery workflow for large projects.
- Static and cost feature extraction for candidate fuzzing targets.
- Heuristic target prioritization based on vulnerability-risk and execution-cost signals.
- Budget-aware scheduling for smoke and deep fuzzing phases.
- Adaptive re-ranking using smoke fuzzing feedback.
- Structured result collection for later analysis.
- Report generation for project-level fuzzing runs.
- Empirical comparison against baseline execution strategies.

## Why This Is More Than a Wrapper

A simple wrapper would only expose a convenient command for launching zkFuzz. zkfDO instead adds a project-level decision layer around zkFuzz. It asks which targets should be fuzzed, in what order, for how long, and how the initial plan should change after short smoke runs.

This makes zkfDO a helper system for efficient fuzzing, not merely a command alias.
