//! Explicit, fail-closed view of a forwarding wrapper. Wire numbers never change.
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::{Path, PathBuf},
};

use anyhow::{ensure, Context, Result};
use num_bigint::BigUint;
use num_traits::{One, Zero};
use serde::Deserialize;

use super::super::r1cs::{Constraint, R1cs, SymbolTable};
use super::{is_direct_main, sha256_bytes, sha256_file, source};

pub(super) const REQUEST_SCHEMA: &str = "zkfdo-lifting-request-v2.3";

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ViewRef {
    pub spec: PathBuf,
    pub sha256: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct View {
    pub schema: String,
    pub target_prefix: String,
    pub target_template: String,
    pub target_source: PathBuf,
    pub target_source_sha256: String,
    pub wrapper_sha256: String,
    pub original_fragment_spec: PathBuf,
    pub original_fragment_spec_sha256: String,
    pub concrete_arguments: Vec<String>,
    pub attached_without_enforcement: Vec<Tag>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Tag {
    pub input: String,
    pub tag: String,
    pub value: Option<String>,
}

/// None preserves the original bytes and calls the original entry point.
pub(super) fn decode(bytes: &[u8]) -> Result<Option<(Vec<u8>, ViewRef)>> {
    let mut value: serde_json::Value = serde_json::from_slice(bytes)?;
    let object = value.as_object_mut().context("request must be an object")?;
    let Some(view) = object.remove("component_view") else {
        ensure!(
            object.get("schema").and_then(|x| x.as_str()) != Some(REQUEST_SCHEMA),
            "v2.3 schema requires component_view"
        );
        return Ok(None);
    };
    ensure!(
        object.get("schema").and_then(|x| x.as_str()) == Some(REQUEST_SCHEMA),
        "component_view requires explicit v2.3 request schema"
    );
    let view: ViewRef = serde_json::from_value(view)?;
    object.insert("schema".into(), super::LIFTING_REQUEST_SCHEMA.into());
    Ok(Some((serde_json::to_vec(&value)?, view)))
}

pub(super) fn load(reference: &ViewRef, base: &Path) -> Result<View> {
    let raw = fs::read(base.join(&reference.spec)).context("read component view spec")?;
    ensure!(
        sha256_bytes(&raw) == reference.sha256,
        "component view spec SHA mismatch"
    );
    let view: View = serde_json::from_slice(&raw)?;
    ensure!(
        view.schema == "zkfdo-component-view-v1",
        "unsupported component view schema"
    );
    ensure!(
        sha256_file(&base.join(&view.original_fragment_spec))?
            == view.original_fragment_spec_sha256,
        "original fragment spec SHA mismatch"
    );
    let local = view
        .target_prefix
        .strip_prefix("main.")
        .context("prefix must be below main")?;
    ensure!(
        identifier(local),
        "only a direct child target prefix is supported"
    );
    ensure!(
        identifier(&view.target_template),
        "invalid target template name"
    );
    let mut tags = BTreeSet::new();
    for tag in &view.attached_without_enforcement {
        ensure!(
            identifier(&tag.input) && identifier(&tag.tag),
            "invalid attached tag name"
        );
        ensure!(
            tag.value.is_none(),
            "valued tags are not supported by view v1"
        );
        ensure!(
            tags.insert((&tag.input, &tag.tag)),
            "duplicate attached tag"
        );
    }
    Ok(view)
}

fn identifier(s: &str) -> bool {
    let mut chars = s.chars();
    chars
        .next()
        .is_some_and(|c| c.is_ascii_alphabetic() || c == '_')
        && chars.all(|c| c.is_ascii_alphanumeric() || c == '_')
}

impl View {
    /// Accept the forwarding-only source grammar emitted by the preparation adapter.
    /// No hints, asserts, extra components, arithmetic signal assignments or tag values.
    pub(super) fn validate_wrapper(&self, wrapper: &Path, base: &Path) -> Result<()> {
        ensure!(
            sha256_file(wrapper)? == self.wrapper_sha256,
            "wrapper SHA mismatch"
        );
        let target = fs::canonicalize(base.join(&self.target_source))?;
        ensure!(
            sha256_file(&target)? == self.target_source_sha256,
            "target source SHA mismatch"
        );
        let text = fs::read_to_string(wrapper)?;
        let masked = source::mask(&text);
        let defs = source::parse_templates(wrapper, &text)?;
        ensure!(
            defs.len() == 1,
            "view wrapper must define one forwarding template"
        );
        let def = &defs[0];
        let target_text = fs::read_to_string(&target)?;
        let target_defs = source::parse_templates(&target, &target_text)?;
        let target_def = target_defs
            .iter()
            .filter(|d| d.name == self.target_template)
            .collect::<Vec<_>>();
        ensure!(target_def.len() == 1, "ambiguous target definition");
        validate_io_roles(
            &masked[def.body_start..def.body_end],
            &source::mask(&target_text)[target_def[0].body_start..target_def[0].body_end],
        )?;
        let local = &self.target_prefix[5..];
        let header = regex::Regex::new(&format!(
            r"template\s+{}\(([A-Za-z0-9_,\s]*)\)\s*\{{$",
            regex::escape(&def.name)
        ))?;
        let header = header
            .captures(text[..def.body_start].trim())
            .context("unsupported wrapper parameters")?;
        let parameters = header[1]
            .split(',')
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .collect::<Vec<_>>();
        ensure!(
            parameters.iter().all(|s| identifier(s))
                && parameters.len() == self.concrete_arguments.len(),
            "wrapper parameter arity/name mismatch"
        );
        let forwarded = parameters.join(",");
        let component = regex::Regex::new(&format!(
            r"^component\s+{}\s*=\s*{}\(([A-Za-z0-9_,\s]*)\);$",
            regex::escape(local),
            regex::escape(&self.target_template)
        ))?;
        let declaration = regex::Regex::new(
            r"^signal\s+(?:(?:input|output)\s+|\{[A-Za-z0-9_,\s]+\}\s+)?[A-Za-z_][A-Za-z0-9_]*(?:\[[^;{}]+\])*;$",
        )?;
        let variable = regex::Regex::new(r"^var\s+[A-Za-z_][A-Za-z0-9_]*\s*=\s*[^;{}]+;$")?;
        let loop_header = regex::Regex::new(
            r"^for\s*\(var\s+(__s_tag_[io]_[0-9_]+)\s*=\s*0;\s*[^;{}]+;\s*[^;{}]+\)\s*\{$",
        )?;
        let leaf =
            r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?(?:\[[A-Za-z0-9_+*/% ()\\-]+\])*";
        let copy = regex::Regex::new(&format!(r"^({leaf})\s*<==\s*({leaf});$"))?;
        let mut components = 0;
        let mut loop_depth = 0usize;
        for line in masked[def.body_start..def.body_end]
            .lines()
            .map(str::trim)
            .filter(|l| !l.is_empty())
        {
            if let Some(call) = component.captures(line) {
                ensure!(
                    call[1].replace(char::is_whitespace, "") == forwarded,
                    "target parameters are not forwarded exactly"
                );
                components += 1;
            } else if variable.is_match(line) {
                let name = line[4..].split('=').next().unwrap_or("").trim();
                ensure!(
                    !parameters.contains(&name),
                    "wrapper reassigns a template parameter"
                );
            } else if declaration.is_match(line) || copy.is_match(line) {
            } else if loop_header.is_match(line) {
                loop_depth += 1;
            } else if line == "}" && loop_depth > 0 {
                loop_depth -= 1;
            } else {
                anyhow::bail!("unsupported forwarding wrapper statement: {line}");
            }
        }
        ensure!(
            components == 1 && loop_depth == 0,
            "invalid forwarding component/loop structure"
        );
        let main = regex::Regex::new(&format!(
            r"^component\s+main\s*=\s*{}\((.*)\);$",
            regex::escape(&def.name)
        ))?;
        let expected = self
            .concrete_arguments
            .join(",")
            .replace(char::is_whitespace, "");
        let tail = text[def.body_end + 1..].trim();
        let args = main
            .captures(tail)
            .context("unsupported main declaration")?;
        ensure!(
            args[1].replace(char::is_whitespace, "") == expected,
            "concrete argument mismatch"
        );
        // Only pragma and the target include may precede the generated template.
        let template_start = text[..def.body_start]
            .rfind("template")
            .context("missing template header")?;
        let include = format!(
            "include \"{}\";",
            target
                .to_string_lossy()
                .replace('\\', "/")
                .replace('"', "\\\"")
        );
        let head = text[..template_start]
            .lines()
            .map(str::trim)
            .filter(|l| !l.is_empty())
            .collect::<Vec<_>>();
        ensure!(
            head == ["pragma circom 2.1.6;", include.as_str()],
            "wrapper includes more than its target source"
        );
        Ok(())
    }

    pub(super) fn validate_definition(
        &self,
        base: &Path,
        templates: &[source::TemplateDef],
    ) -> Result<()> {
        let target = fs::canonicalize(base.join(&self.target_source))?;
        let matches = templates
            .iter()
            .filter(|t| t.name == self.target_template)
            .collect::<Vec<_>>();
        ensure!(
            matches.len() == 1 && matches[0].file == target,
            "target definition is missing or ambiguous"
        );
        let text = fs::read_to_string(&target)?;
        let masked = source::mask(&text);
        let body = &masked[matches[0].body_start..matches[0].body_end];
        let declarations =
            regex::Regex::new(r"signal\s+input\s*\{([^}]+)\}\s*([A-Za-z_][A-Za-z0-9_]*)")?;
        let mut declared = BTreeSet::new();
        for cap in declarations.captures_iter(body) {
            for tag in cap[1].split(',').map(str::trim) {
                ensure!(identifier(tag), "unsupported tag declaration");
                declared.insert((cap[2].to_owned(), tag.to_owned()));
            }
        }
        let recorded = self
            .attached_without_enforcement
            .iter()
            .map(|t| (t.input.clone(), t.tag.clone()))
            .collect();
        ensure!(
            declared == recorded,
            "attached tag inventory differs from target inputs"
        );
        Ok(())
    }
}

fn validate_io_roles(wrapper: &str, target: &str) -> Result<()> {
    let declarations =
        regex::Regex::new(r"signal\s+(input|output)\s+(?:\{[^}]+\}\s*)?([A-Za-z_][A-Za-z0-9_]*)")?;
    let roles = |text: &str| {
        declarations
            .captures_iter(text)
            .map(|c| (c[1].to_owned(), c[2].to_owned()))
            .collect::<BTreeSet<_>>()
    };
    ensure!(
        roles(wrapper) == roles(target),
        "wrapper/target IO roles differ"
    );
    Ok(())
}

fn root(parent: &[usize], mut wire: usize) -> usize {
    while parent[wire] != wire {
        wire = parent[wire];
    }
    wire
}

fn copy_pair(c: &Constraint, prime: &BigUint) -> Option<(usize, usize)> {
    let mut linear = BTreeMap::new();
    let (factor, terms) = if c.a.is_empty() || c.b.is_empty() {
        (BigUint::zero(), &c.a)
    } else if c.a.keys().all(|w| *w == 0) {
        (c.a.get(&0)?.clone(), &c.b)
    } else if c.b.keys().all(|w| *w == 0) {
        (c.b.get(&0)?.clone(), &c.a)
    } else {
        return None;
    };
    for (w, value) in terms {
        linear.insert(*w, (&factor * value) % prime);
    }
    for (w, value) in &c.c {
        let old = linear.entry(*w).or_insert_with(BigUint::zero);
        *old = (&*old + prime - value) % prime;
    }
    linear.retain(|_, value| !value.is_zero());
    if linear.len() != 2 || linear.contains_key(&0) {
        return None;
    }
    let pairs = linear.iter().collect::<Vec<_>>();
    ((pairs[0].1 + pairs[1].1) % prime)
        .is_zero()
        .then_some((*pairs[0].0 as usize, *pairs[1].0 as usize))
}

pub(super) struct Projection {
    pub candidate: BTreeMap<String, BigUint>,
    pub symbols: SymbolTable,
    pub forwarding_equalities: usize,
}

pub(super) fn project(
    prefix: &str,
    r1cs: &R1cs,
    sym: &SymbolTable,
    candidate: &BTreeMap<String, BigUint>,
    inputs: &[String],
    outputs: &[String],
) -> Result<Projection> {
    let prefix = format!("{prefix}.");
    let target_wires = sym
        .by_name
        .iter()
        .filter(|(n, _)| n.starts_with(&prefix))
        .filter_map(|(_, s)| usize::try_from(s.wire).ok())
        .collect::<BTreeSet<_>>();
    ensure!(!target_wires.is_empty(), "target subtree is empty");
    // Complete raw assignment, canonical field values, and consistent aliases are required.
    let mut assignment = vec![BigUint::zero(); r1cs.shape.wires];
    assignment[0] = BigUint::one();
    for (name, value) in candidate {
        ensure!(
            sym.by_name.contains_key(name),
            "candidate name absent from raw sym: {name}"
        );
        ensure!(value < &r1cs.prime, "noncanonical candidate field value");
    }
    for (wire, names) in sym.wire_to_names.iter().enumerate().skip(1) {
        let values = names
            .iter()
            .filter_map(|n| candidate.get(n))
            .collect::<Vec<_>>();
        ensure!(!values.is_empty(), "candidate missing raw wire {wire}");
        ensure!(
            values.iter().all(|v| *v == values[0]),
            "candidate aliases disagree at wire {wire}"
        );
        assignment[wire] = values[0].clone();
    }
    ensure!(
        r1cs.failed_constraint_indices(&assignment)?.is_empty(),
        "candidate violates raw wrapper constraints"
    );
    let mut parent = (0..r1cs.shape.wires).collect::<Vec<_>>();
    let mut equalities = 0;
    for c in &r1cs.constraints {
        let outside =
            c.a.keys()
                .chain(c.b.keys())
                .chain(c.c.keys())
                .any(|w| *w != 0 && !target_wires.contains(&(*w as usize)));
        if outside {
            let (a, b) =
                copy_pair(c, &r1cs.prime).context("non-copy constraint outside target subtree")?;
            let rb = root(&parent, b);
            parent[rb] = root(&parent, a);
            equalities += 1;
        }
    }
    let mut roots = BTreeMap::<usize, BTreeSet<usize>>::new();
    for w in &target_wires {
        roots.entry(root(&parent, *w)).or_default().insert(*w);
    }
    for wire in 1..r1cs.shape.wires {
        if !target_wires.contains(&wire) {
            ensure!(
                roots
                    .get(&root(&parent, wire))
                    .is_some_and(|r| r.len() == 1),
                "wrapper wire lacks a unique copied target wire"
            );
        }
    }
    for name in inputs.iter().chain(outputs) {
        let leaf = name
            .strip_prefix("main.")
            .filter(|_| is_direct_main(name))
            .context("invalid wrapper IO")?;
        let target = sym
            .by_name
            .get(&format!("{prefix}{leaf}"))
            .context("wrapper/target IO name mismatch")?;
        let original = &sym.by_name[name];
        ensure!(
            target.wire >= 0
                && original.wire >= 0
                && root(&parent, target.wire as usize) == root(&parent, original.wire as usize),
            "wrapper/target IO is not an exact copy: {name}"
        );
    }
    let mut projected = SymbolTable {
        by_name: BTreeMap::new(),
        wire_to_names: vec![Vec::new(); r1cs.shape.wires],
        eliminated_names: BTreeSet::new(),
    };
    let mut values = BTreeMap::new();
    for (name, symbol) in &sym.by_name {
        if let Some(suffix) = name.strip_prefix(&prefix) {
            let name = format!("main.{suffix}");
            projected.by_name.insert(name.clone(), symbol.clone());
            if symbol.wire >= 0 {
                projected.wire_to_names[symbol.wire as usize].push(name.clone());
                values.insert(name, assignment[symbol.wire as usize].clone());
            } else {
                projected.eliminated_names.insert(name.clone());
                if let Some(value) = candidate.get(&format!("{prefix}{suffix}")) {
                    values.insert(name, value.clone());
                }
            }
        }
    }
    Ok(Projection {
        candidate: values,
        symbols: projected,
        forwarding_equalities: equalities,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::candidate_review::{r1cs::Symbol, schema::R1csShape};

    fn fixture() -> (R1cs, SymbolTable, BTreeMap<String, BigUint>) {
        let lc = |values: &[(u32, u32)]| {
            values
                .iter()
                .map(|(w, v)| (*w, BigUint::from(*v)))
                .collect()
        };
        let r = R1cs {
            prime: 257u32.into(),
            shape: R1csShape {
                wires: 6,
                public_outputs: 1,
                public_inputs: 0,
                private_inputs: 1,
                labels: 6,
                constraints: 4,
            },
            wire_labels: (0..6).collect(),
            constraints: vec![
                Constraint {
                    a: lc(&[(3, 1)]),
                    b: lc(&[(3, 1)]),
                    c: lc(&[(4, 1)]),
                },
                Constraint {
                    a: lc(&[]),
                    b: lc(&[]),
                    c: lc(&[(2, 1), (5, 256)]),
                },
                Constraint {
                    a: lc(&[]),
                    b: lc(&[]),
                    c: lc(&[(5, 1), (3, 256)]),
                },
                Constraint {
                    a: lc(&[]),
                    b: lc(&[]),
                    c: lc(&[(1, 1), (4, 256)]),
                },
            ],
        };
        let names = ["main.y", "main.x", "main.c.x", "main.c.y", "main.bridge"];
        let s = SymbolTable {
            by_name: names
                .iter()
                .enumerate()
                .map(|(i, n)| (n.to_string(), Symbol { wire: i as i64 + 1 }))
                .collect(),
            wire_to_names: std::iter::once(vec![])
                .chain(names.iter().map(|n| vec![n.to_string()]))
                .collect(),
            eliminated_names: BTreeSet::new(),
        };
        let v = names
            .iter()
            .zip([4u32, 2, 2, 4, 2])
            .map(|(n, v)| (n.to_string(), v.into()))
            .collect();
        (r, s, v)
    }
    fn check(r: &R1cs, s: &SymbolTable, v: &BTreeMap<String, BigUint>) -> Result<Projection> {
        project("main.c", r, s, v, &["main.x".into()], &["main.y".into()])
    }
    #[test]
    fn no_view_routes_to_legacy_bytes() {
        assert!(decode(br#"{"schema":"zkfdo-lifting-request-v1"}"#)
            .unwrap()
            .is_none());
    }
    #[test]
    fn new_schema_requires_view() {
        assert!(decode(br#"{"schema":"zkfdo-lifting-request-v2.3"}"#).is_err());
    }
    #[test]
    fn legacy_schema_rejects_view() {
        assert!(decode(br#"{"schema":"zkfdo-lifting-request-v1","component_view":{}}"#).is_err());
    }
    #[test]
    fn raw_wire_numbers_and_target_names_are_preserved() {
        let (r, s, v) = fixture();
        let p = check(&r, &s, &v).unwrap();
        assert_eq!(p.symbols.by_name["main.x"].wire, 3);
        assert_eq!(p.candidate["main.x"], 2u32.into());
        assert_eq!(p.forwarding_equalities, 3);
        assert_eq!(p.symbols.by_name.len(), 2);
    }
    #[test]
    fn missing_raw_wire_is_refused() {
        let (r, s, mut v) = fixture();
        v.remove("main.bridge");
        assert!(check(&r, &s, &v)
            .unwrap_err_text()
            .contains("missing raw wire"));
    }
    #[test]
    fn violated_copy_is_refused() {
        let (r, s, mut v) = fixture();
        v.insert("main.bridge".into(), 3u32.into());
        assert!(check(&r, &s, &v).is_err());
    }
    #[test]
    fn noncanonical_value_is_refused() {
        let (r, s, mut v) = fixture();
        v.insert("main.x".into(), 259u32.into());
        assert!(check(&r, &s, &v).is_err());
    }
    #[test]
    fn prefix_does_not_capture_sibling() {
        let (r, s, v) = fixture();
        assert!(project("main.cc", &r, &s, &v, &[], &[]).is_err());
    }
    #[test]
    fn alias_conflict_is_refused() {
        let (r, mut s, mut v) = fixture();
        s.by_name.insert("main.alias".into(), Symbol { wire: 3 });
        s.wire_to_names[3].push("main.alias".into());
        v.insert("main.alias".into(), 3u32.into());
        assert!(check(&r, &s, &v).is_err());
    }
    #[test]
    fn noncopy_wrapper_constraint_is_refused_even_when_satisfied() {
        let (mut r, s, v) = fixture();
        r.constraints.push(Constraint {
            a: BTreeMap::from([(2, BigUint::one())]),
            b: BTreeMap::from([(2, BigUint::one())]),
            c: BTreeMap::from([(1, BigUint::one())]),
        });
        assert!(check(&r, &s, &v).is_err());
    }
    #[test]
    fn io_role_swaps_and_omissions_are_refused() {
        let target = "signal input {binary} x[2]; signal output y[2];";
        assert!(validate_io_roles("signal input x[2]; signal output y[2];", target).is_ok());
        assert!(validate_io_roles("signal output x[2]; signal input y[2];", target).is_err());
        assert!(validate_io_roles("signal input x[2];", target).is_err());
    }
    #[test]
    fn nested_array_names_keep_suffix_and_wire() {
        let (r, mut s, mut v) = fixture();
        let old = "main.c.x";
        let new = "main.c.child[2].x[1]";
        let symbol = s.by_name.remove(old).unwrap();
        s.by_name.insert(new.into(), symbol);
        s.wire_to_names[3] = vec![new.into()];
        let value = v.remove(old).unwrap();
        v.insert(new.into(), value);
        let p = project("main.c", &r, &s, &v, &[], &[]).unwrap();
        assert_eq!(p.symbols.by_name["main.child[2].x[1]"].wire, 3);
        assert_eq!(p.candidate["main.child[2].x[1]"], 2u32.into());
    }
    #[test]
    fn changed_io_leaf_is_refused() {
        let (r, s, v) = fixture();
        assert!(project("main.c", &r, &s, &v, &["main.bridge".into()], &[]).is_err());
    }
    trait ErrorText {
        fn unwrap_err_text(self) -> String;
    }
    impl ErrorText for Result<Projection> {
        fn unwrap_err_text(self) -> String {
            self.err().unwrap().to_string()
        }
    }
}
