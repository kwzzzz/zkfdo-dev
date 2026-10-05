//! Minimal Circom text scanning for lifting: template bodies, declared signals, and
//! `<--` statements. It only locates byte ranges; it does not evaluate anything.

use std::{
    collections::BTreeSet,
    path::{Path, PathBuf},
};

use anyhow::{bail, Context, Result};

#[derive(Clone, Debug)]
pub(crate) struct TemplateDef {
    pub(crate) name: String,
    pub(crate) file: PathBuf,
    pub(crate) body_start: usize,
    pub(crate) body_end: usize,
    pub(crate) signals: BTreeSet<String>,
    pub(crate) inputs: BTreeSet<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct HintStatement {
    pub(crate) signal: String,
    /// Index expressions of the assigned signal, as source text.
    pub(crate) indices: Vec<String>,
    /// Byte range of the right-hand side expression (between `<--` and `;`).
    pub(crate) rhs_start: usize,
    pub(crate) rhs_end: usize,
    pub(crate) line: usize,
}

/// Replaces comments and string literals with spaces, keeping every byte offset and newline.
pub(crate) fn mask(source: &str) -> String {
    let bytes = source.as_bytes();
    let mut out = bytes.to_vec();
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index..].starts_with(b"//") {
            while index < bytes.len() && bytes[index] != b'\n' {
                out[index] = b' ';
                index += 1;
            }
        } else if bytes[index..].starts_with(b"/*") {
            while index < bytes.len() && !bytes[index..].starts_with(b"*/") {
                if bytes[index] != b'\n' {
                    out[index] = b' ';
                }
                index += 1;
            }
            for _ in 0..2 {
                if index < bytes.len() {
                    out[index] = b' ';
                    index += 1;
                }
            }
        } else if bytes[index] == b'"' {
            index += 1;
            while index < bytes.len() && bytes[index] != b'"' {
                if bytes[index] != b'\n' {
                    out[index] = b' ';
                }
                index += 1;
            }
            index += 1;
        } else {
            index += 1;
        }
    }
    // Only ASCII bytes were replaced by ASCII spaces inside comments or strings; any
    // multi-byte character there was replaced byte-wise, so rebuild lossily.
    String::from_utf8(out).unwrap_or_else(|error| {
        String::from_utf8_lossy(error.as_bytes())
            .chars()
            .map(|c| if c.is_ascii() { c } else { ' ' })
            .collect()
    })
}

pub(crate) fn parse_templates(file: &Path, source: &str) -> Result<Vec<TemplateDef>> {
    let masked = mask(source);
    let bytes = masked.as_bytes();
    let mut templates = Vec::new();
    let mut index = 0;
    while let Some(found) = find_keyword(bytes, b"template", index) {
        let mut cursor = skip_space(bytes, found + "template".len());
        loop {
            let (word, next) = identifier(bytes, cursor);
            if word == "custom" || word == "parallel" {
                cursor = skip_space(bytes, next);
            } else {
                break;
            }
        }
        let (name, after_name) = identifier(bytes, cursor);
        if name.is_empty() {
            index = found + 1;
            continue;
        }
        let open_paren = skip_space(bytes, after_name);
        if bytes.get(open_paren) != Some(&b'(') {
            index = found + 1;
            continue;
        }
        let close_paren = matching(bytes, open_paren, b'(', b')')
            .with_context(|| format!("unbalanced template header {name} in {}", file.display()))?;
        let open_brace = skip_space(bytes, close_paren + 1);
        if bytes.get(open_brace) != Some(&b'{') {
            bail!("template {name} in {} has no body", file.display());
        }
        let close_brace = matching(bytes, open_brace, b'{', b'}')
            .with_context(|| format!("unbalanced template body {name} in {}", file.display()))?;
        let body = &masked[open_brace + 1..close_brace];
        let (signals, inputs) = declared_signals(body);
        templates.push(TemplateDef {
            name: name.to_owned(),
            file: file.to_path_buf(),
            body_start: open_brace + 1,
            body_end: close_brace,
            signals,
            inputs,
        });
        index = close_brace + 1;
    }
    Ok(templates)
}

/// Every `<--` statement in the template body. `-->` statements are returned as an error
/// list of signal names so callers can refuse them explicitly.
pub(crate) fn hint_statements(
    source: &str,
    template: &TemplateDef,
) -> Result<(Vec<HintStatement>, BTreeSet<String>)> {
    let masked = mask(source);
    let bytes = masked.as_bytes();
    let mut hints = Vec::new();
    let mut reverse = BTreeSet::new();
    let mut index = template.body_start;
    while index + 3 <= template.body_end {
        if &bytes[index..index + 3] == b"<--" {
            let start = statement_start(bytes, template.body_start, index);
            let end = statement_end(bytes, index, template.body_end).with_context(|| {
                format!(
                    "unterminated `<--` statement at line {}",
                    line_of(source, index)
                )
            })?;
            let (signal, indices) = parse_lhs(&masked[start..index]).with_context(|| {
                format!(
                    "unsupported `<--` target at line {}",
                    line_of(source, index)
                )
            })?;
            hints.push(HintStatement {
                signal,
                indices,
                rhs_start: index + 3,
                rhs_end: end,
                line: line_of(source, index),
            });
            index = end;
        } else if &bytes[index..index + 3] == b"-->" {
            let end = statement_end(bytes, index, template.body_end).unwrap_or(template.body_end);
            if let Ok((signal, _)) = parse_lhs(&masked[index + 3..end]) {
                reverse.insert(signal);
            }
            index = end;
        } else {
            index += 1;
        }
    }
    Ok((hints, reverse))
}

/// The `===` or `assert` statement on 1-based `line` of the template body, as a byte range
/// that includes its `;`, with its kind (`constraint` or `assert`).
pub(crate) fn check_statement_at_line(
    source: &str,
    template: &TemplateDef,
    line: usize,
) -> Option<(usize, usize, &'static str)> {
    let masked = mask(source);
    let bytes = masked.as_bytes();
    let line_start = if line <= 1 {
        0
    } else {
        masked
            .match_indices('\n')
            .nth(line - 2)
            .map(|(offset, _)| offset + 1)?
    };
    let line_end = masked[line_start..]
        .find('\n')
        .map_or(masked.len(), |offset| line_start + offset);
    if line_start < template.body_start || line_end > template.body_end {
        return None;
    }
    let text = &masked[line_start..line_end];
    let (offset, kind) = if let Some(offset) = text.find("===") {
        (offset, "constraint")
    } else {
        let offset = find_keyword(text.as_bytes(), b"assert", 0)?;
        (offset, "assert")
    };
    let operator = line_start + offset;
    let start = statement_start(bytes, template.body_start, operator);
    let end = statement_end(bytes, operator, template.body_end)?;
    Some((start, end + 1, kind))
}

fn declared_signals(body: &str) -> (BTreeSet<String>, BTreeSet<String>) {
    let bytes = body.as_bytes();
    let mut signals = BTreeSet::new();
    let mut inputs = BTreeSet::new();
    let mut index = 0;
    while let Some(found) = find_keyword(bytes, b"signal", index) {
        let mut cursor = skip_space(bytes, found + "signal".len());
        let (kind, next) = identifier(bytes, cursor);
        let is_input = kind == "input";
        if kind == "input" || kind == "output" {
            cursor = skip_space(bytes, next);
        }
        if bytes.get(cursor) == Some(&b'{') {
            cursor = matching(bytes, cursor, b'{', b'}').map_or(bytes.len(), |end| end + 1);
            cursor = skip_space(bytes, cursor);
        }
        loop {
            let (name, next) = identifier(bytes, cursor);
            if name.is_empty() {
                break;
            }
            signals.insert(name.to_owned());
            if is_input {
                inputs.insert(name.to_owned());
            }
            cursor = skip_space(bytes, next);
            while bytes.get(cursor) == Some(&b'[') {
                cursor = matching(bytes, cursor, b'[', b']').map_or(bytes.len(), |end| end + 1);
                cursor = skip_space(bytes, cursor);
            }
            if bytes.get(cursor) == Some(&b',') {
                cursor = skip_space(bytes, cursor + 1);
            } else {
                break;
            }
        }
        index = found + 1;
    }
    (signals, inputs)
}

fn parse_lhs(text: &str) -> Result<(String, Vec<String>)> {
    let bytes = text.as_bytes();
    let mut cursor = skip_space(bytes, 0);
    let (first, next) = identifier(bytes, cursor);
    if first == "signal" {
        cursor = skip_space(bytes, next);
        let (kind, next) = identifier(bytes, cursor);
        if kind == "input" || kind == "output" {
            cursor = skip_space(bytes, next);
        }
        if bytes.get(cursor) == Some(&b'{') {
            cursor = matching(bytes, cursor, b'{', b'}').context("unbalanced tag list")? + 1;
            cursor = skip_space(bytes, cursor);
        }
    }
    let (name, next) = identifier(bytes, cursor);
    anyhow::ensure!(!name.is_empty(), "missing assigned signal");
    cursor = skip_space(bytes, next);
    let mut indices = Vec::new();
    while bytes.get(cursor) == Some(&b'[') {
        let end = matching(bytes, cursor, b'[', b']').context("unbalanced index")?;
        indices.push(text[cursor + 1..end].trim().to_owned());
        cursor = skip_space(bytes, end + 1);
    }
    anyhow::ensure!(
        cursor == bytes.len(),
        "assigned expression is not a signal reference"
    );
    Ok((name.to_owned(), indices))
}

fn statement_start(bytes: &[u8], floor: usize, operator: usize) -> usize {
    let mut index = operator;
    while index > floor {
        if matches!(bytes[index - 1], b';' | b'{' | b'}') {
            return index;
        }
        index -= 1;
    }
    floor
}

fn statement_end(bytes: &[u8], from: usize, ceiling: usize) -> Option<usize> {
    let mut depth = 0i32;
    for (offset, byte) in bytes[from..ceiling].iter().enumerate() {
        match byte {
            b'(' | b'[' => depth += 1,
            b')' | b']' => depth -= 1,
            b';' if depth == 0 => return Some(from + offset),
            _ => {}
        }
    }
    None
}

fn find_keyword(bytes: &[u8], keyword: &[u8], from: usize) -> Option<usize> {
    let mut index = from;
    while index + keyword.len() <= bytes.len() {
        if &bytes[index..index + keyword.len()] == keyword
            && (index == 0 || !is_ident(bytes[index - 1]))
            && bytes
                .get(index + keyword.len())
                .is_none_or(|byte| !is_ident(*byte))
        {
            return Some(index);
        }
        index += 1;
    }
    None
}

fn identifier(bytes: &[u8], from: usize) -> (&str, usize) {
    let mut end = from;
    while end < bytes.len() && is_ident(bytes[end]) {
        end += 1;
    }
    if end > from && bytes[from].is_ascii_digit() {
        return ("", from);
    }
    (std::str::from_utf8(&bytes[from..end]).unwrap_or(""), end)
}

fn is_ident(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || byte == b'_' || byte == b'$'
}

fn skip_space(bytes: &[u8], mut index: usize) -> usize {
    while index < bytes.len() && bytes[index].is_ascii_whitespace() {
        index += 1;
    }
    index
}

fn matching(bytes: &[u8], open_index: usize, open: u8, close: u8) -> Option<usize> {
    let mut depth = 0usize;
    for (offset, byte) in bytes[open_index..].iter().enumerate() {
        if *byte == open {
            depth += 1;
        } else if *byte == close {
            depth -= 1;
            if depth == 0 {
                return Some(open_index + offset);
            }
        }
    }
    None
}

fn line_of(source: &str, offset: usize) -> usize {
    source.as_bytes()[..offset.min(source.len())]
        .iter()
        .filter(|byte| **byte == b'\n')
        .count()
        + 1
}

#[cfg(test)]
mod tests {
    use super::*;

    const SOURCE: &str = r#"
pragma circom 2.0.0;
include "a//b.circom";
// template Fake() {}
template Pair(n) {
    signal input in[2];
    signal input k, j;
    signal output out;
    signal {binary} bits[n];
    signal inv <-- in[0] != 0 ? 1 / in[0] : 0; /* <-- not here */
    for (var i = 0; i < n; i++) {
        bits[i] <-- (in[1] >> i) & 1;
    }
    out <== inv * in[0];
}
"#;

    #[test]
    fn templates_signals_and_hints_are_located() {
        let templates = parse_templates(Path::new("x.circom"), SOURCE).unwrap();
        assert_eq!(templates.len(), 1);
        let template = &templates[0];
        assert_eq!(template.name, "Pair");
        assert_eq!(
            template.signals.iter().cloned().collect::<Vec<_>>(),
            ["bits", "in", "inv", "j", "k", "out"]
        );
        assert_eq!(
            template.inputs.iter().cloned().collect::<Vec<_>>(),
            ["in", "j", "k"]
        );
        let (hints, reverse) = hint_statements(SOURCE, template).unwrap();
        assert!(reverse.is_empty());
        assert_eq!(hints.len(), 2);
        assert_eq!(hints[0].signal, "inv");
        assert!(hints[0].indices.is_empty());
        assert_eq!(
            SOURCE[hints[0].rhs_start..hints[0].rhs_end].trim(),
            "in[0] != 0 ? 1 / in[0] : 0"
        );
        assert_eq!(hints[1].signal, "bits");
        assert_eq!(hints[1].indices, ["i"]);
    }

    #[test]
    fn checks_are_located_by_line_with_their_terminator() {
        let source =
            "template T() {\n    signal input a;\n    assert(a < 4);\n    a * (a - 1) === 0;\n}\n";
        let templates = parse_templates(Path::new("t.circom"), source).unwrap();
        let (start, end, kind) = check_statement_at_line(source, &templates[0], 4).unwrap();
        assert_eq!(
            (source[start..end].trim(), kind),
            ("a * (a - 1) === 0;", "constraint")
        );
        let (start, end, kind) = check_statement_at_line(source, &templates[0], 3).unwrap();
        assert_eq!(
            (source[start..end].trim(), kind),
            ("assert(a < 4);", "assert")
        );
        assert!(check_statement_at_line(source, &templates[0], 2).is_none());
        assert!(check_statement_at_line(source, &templates[0], 9).is_none());
    }
}
