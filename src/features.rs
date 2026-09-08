use std::{
    fs,
    path::{Path, PathBuf},
};

use anyhow::{Context, Result};
use regex::Regex;
use serde::{Deserialize, Serialize};

use crate::scanner::{self, CircomTarget};

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct TargetFeatures {
    pub path: PathBuf,
    pub loc: usize,
    pub signal_count: usize,
    pub signal_input_count: usize,
    pub signal_output_count: usize,
    pub signal_internal_count: usize,
    pub constraint_count_estimate: usize,
    pub template_count: usize,
    pub component_count: usize,
    pub include_count: usize,
    pub unsafe_assign_count: usize,
    pub unsafe_assign_rev_count: usize,
    pub assert_count: usize,
    pub division_count: usize,
    pub modulo_count: usize,
    pub array_access_count: usize,
    pub less_than_pattern_count: usize,
    pub num2bits_pattern_count: usize,
    pub iszero_pattern_count: usize,
}

impl TargetFeatures {
    pub fn empty(path: impl Into<PathBuf>) -> Self {
        Self {
            path: path.into(),
            loc: 0,
            signal_count: 0,
            signal_input_count: 0,
            signal_output_count: 0,
            signal_internal_count: 0,
            constraint_count_estimate: 0,
            template_count: 0,
            component_count: 0,
            include_count: 0,
            unsafe_assign_count: 0,
            unsafe_assign_rev_count: 0,
            assert_count: 0,
            division_count: 0,
            modulo_count: 0,
            array_access_count: 0,
            less_than_pattern_count: 0,
            num2bits_pattern_count: 0,
            iszero_pattern_count: 0,
        }
    }
}

pub fn extract_project_features(project: impl AsRef<Path>) -> Result<Vec<TargetFeatures>> {
    let targets = scanner::scan_project(project)?;
    targets
        .iter()
        .map(extract_target_features)
        .collect::<Result<Vec<_>>>()
}

pub fn extract_target_features(target: &CircomTarget) -> Result<TargetFeatures> {
    let source = fs::read_to_string(&target.path)
        .with_context(|| format!("failed to read Circom target: {}", target.path.display()))?;

    Ok(extract_features_from_source(&target.path, &source))
}

pub fn extract_features_from_source(path: impl Into<PathBuf>, source: &str) -> TargetFeatures {
    let path = path.into();
    let cleaned = strip_comments(source);
    let code = mask_string_literals(&cleaned);

    let signal_input_count = count_regex(&code, r"\bsignal\s+input\b");
    let signal_output_count = count_regex(&code, r"\bsignal\s+output\b");
    let signal_count = count_regex(&code, r"\bsignal\b");
    let signal_internal_count =
        signal_count.saturating_sub(signal_input_count + signal_output_count);

    TargetFeatures {
        path,
        loc: cleaned
            .lines()
            .filter(|line| !line.trim().is_empty())
            .count(),
        signal_count,
        signal_input_count,
        signal_output_count,
        signal_internal_count,
        constraint_count_estimate: count_literal(&code, "<==")
            + count_literal(&code, "==>")
            + count_literal(&code, "==="),
        template_count: count_regex(&code, r"\btemplate\s+[A-Za-z_][A-Za-z0-9_]*"),
        component_count: count_regex(&code, r"\bcomponent\b"),
        include_count: count_regex(&cleaned, r#"\binclude\s+""#),
        unsafe_assign_count: count_literal(&code, "<--"),
        unsafe_assign_rev_count: count_literal(&code, "-->"),
        assert_count: count_regex(&code, r"\bassert\s*\("),
        division_count: count_regex(&code, r"[A-Za-z0-9_\)\]]\s*/\s*[A-Za-z0-9_\(]"),
        modulo_count: count_regex(&code, r"[A-Za-z0-9_\)\]]\s*%\s*[A-Za-z0-9_\(]"),
        array_access_count: count_regex(&code, r"\[[^\]\n]+\]"),
        less_than_pattern_count: count_regex(&code, r"\bLessThan\b"),
        num2bits_pattern_count: count_regex(&code, r"\bNum2Bits\b"),
        iszero_pattern_count: count_regex(&code, r"\bIsZero\b"),
    }
}

fn count_literal(haystack: &str, needle: &str) -> usize {
    haystack.matches(needle).count()
}

fn count_regex(haystack: &str, pattern: &str) -> usize {
    Regex::new(pattern)
        .expect("feature regex should compile")
        .find_iter(haystack)
        .count()
}

fn strip_comments(source: &str) -> String {
    #[derive(Debug, Clone, Copy, PartialEq, Eq)]
    enum State {
        Code,
        String,
        LineComment,
        BlockComment,
    }

    let mut output = String::with_capacity(source.len());
    let mut chars = source.chars().peekable();
    let mut state = State::Code;
    let mut previous_was_escape = false;

    while let Some(ch) = chars.next() {
        match state {
            State::Code => match ch {
                '"' => {
                    output.push(ch);
                    state = State::String;
                    previous_was_escape = false;
                }
                '/' if chars.peek().is_some_and(|next| *next == '/') => {
                    chars.next();
                    state = State::LineComment;
                }
                '/' if chars.peek().is_some_and(|next| *next == '*') => {
                    chars.next();
                    state = State::BlockComment;
                }
                _ => output.push(ch),
            },
            State::String => {
                output.push(ch);

                if ch == '"' && !previous_was_escape {
                    state = State::Code;
                }

                previous_was_escape = ch == '\\' && !previous_was_escape;
            }
            State::LineComment => {
                if ch == '\n' {
                    output.push('\n');
                    state = State::Code;
                }
            }
            State::BlockComment => {
                if ch == '\n' {
                    output.push('\n');
                } else if ch == '*' && chars.peek().is_some_and(|next| *next == '/') {
                    chars.next();
                    state = State::Code;
                }
            }
        }
    }

    output
}

fn mask_string_literals(source: &str) -> String {
    let mut output = String::with_capacity(source.len());
    let mut in_string = false;
    let mut previous_was_escape = false;

    for ch in source.chars() {
        if in_string {
            if ch == '"' && !previous_was_escape {
                output.push('"');
                in_string = false;
            } else if ch == '\n' {
                output.push('\n');
            } else {
                output.push(' ');
            }

            previous_was_escape = ch == '\\' && !previous_was_escape;
            continue;
        }

        if ch == '"' {
            output.push('"');
            in_string = true;
            previous_was_escape = false;
        } else {
            output.push(ch);
        }
    }

    output
}

#[cfg(test)]
mod tests {
    use std::fs;

    use tempfile::tempdir;

    use super::*;

    #[test]
    fn extracts_lexical_features_after_removing_comments() {
        let source = r#"
            include "circomlib/circuits/bitify.circom";

            // signal input ignored;
            template Main() {
                signal input a;
                signal output out;
                signal tmp;
                component bits = Num2Bits(8);
                tmp <-- a / 2;
                out <== tmp % 3;
                assert(out === bits.out[0]);
            }
        "#;

        let features = extract_features_from_source("main.circom", source);

        assert_eq!(features.include_count, 1);
        assert_eq!(features.template_count, 1);
        assert_eq!(features.signal_count, 3);
        assert_eq!(features.signal_input_count, 1);
        assert_eq!(features.signal_output_count, 1);
        assert_eq!(features.signal_internal_count, 1);
        assert_eq!(features.component_count, 1);
        assert_eq!(features.constraint_count_estimate, 2);
        assert_eq!(features.unsafe_assign_count, 1);
        assert_eq!(features.assert_count, 1);
        assert_eq!(features.division_count, 1);
        assert_eq!(features.modulo_count, 1);
        assert_eq!(features.array_access_count, 1);
        assert_eq!(features.num2bits_pattern_count, 1);
    }

    #[test]
    fn extracts_project_features_for_scanned_targets() {
        let temp = tempdir().expect("tempdir");
        let target = temp.path().join("main.circom");
        fs::write(&target, "template Main(){ signal input a; }").expect("target");

        let features = extract_project_features(temp.path()).expect("features");

        assert_eq!(features.len(), 1);
        assert_eq!(features[0].path, target);
        assert_eq!(features[0].template_count, 1);
        assert_eq!(features[0].signal_input_count, 1);
    }
}
