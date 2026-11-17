//! Opt-in v2.5 request-local immutable structure and verified tool-key reuse.
//! Neither dynamic rewrite plans nor witness/artifact validation results are cached.
use std::{
    cell::{OnceCell, RefCell},
    collections::{BTreeMap, BTreeSet},
    fs,
    marker::PhantomData,
    path::{Path, PathBuf},
    rc::Rc,
    time::SystemTime,
};

use anyhow::{ensure, Context, Result};
use serde::Serialize;
use serde_json::Value;

use super::{
    leaf_base, sha256_file, source::HintStatement, split_instance, SymbolTable, TemplateDef,
};

type InstanceSignals = BTreeMap<String, BTreeSet<String>>;
type ParsedHints = (Vec<HintStatement>, BTreeSet<String>);
type HintKey = (PathBuf, String, usize, usize);

#[derive(Default, Serialize)]
struct Stats {
    tool_digest_reads: u64,
    tool_digest_hits: u64,
    tool_identity_checks: u64,
    rewrite_structure_builds: u64,
    rewrite_structure_hits: u64,
    hint_parse_calls: u64,
    hint_parse_hits: u64,
}

thread_local! {
    static STATE: RefCell<Option<Stats>> = const { RefCell::new(None) };
}

pub(super) struct Guard(PhantomData<Rc<()>>);

pub(super) fn activate() -> Result<Guard> {
    STATE.with(|slot| {
        let mut state = slot.borrow_mut();
        ensure!(
            state.is_none(),
            "a J v2.5 request is already active on this thread"
        );
        *state = Some(Stats::default());
        Ok(Guard(PhantomData))
    })
}

impl Drop for Guard {
    fn drop(&mut self) {
        STATE.with(|slot| *slot.borrow_mut() = None);
    }
}

pub(super) fn enabled() -> bool {
    STATE.with(|slot| slot.borrow().is_some())
}

fn record(update: impl FnOnce(&mut Stats)) {
    STATE.with(|slot| {
        if let Some(stats) = slot.borrow_mut().as_mut() {
            update(stats);
        }
    });
}

pub(super) fn telemetry() -> Value {
    STATE.with(|slot| serde_json::json!({
        "enabled": slot.borrow().is_some(),
        "scope": "single_request_immutable_borrows",
        "stats": &*slot.borrow(),
        "tool_policy": "first_actual_sha256_for_keys; reject_identity_drift; external_manifest_and_launcher_checks_retained",
        "rewrite_policy": "lazy_instance_signals_and_successful_template_hints_only; dynamic_plan_every_call",
    }))
}

#[derive(Debug, PartialEq, Eq)]
struct Identity {
    bytes: u64,
    modified: SystemTime,
    #[cfg(unix)]
    unix: (u64, u64, u32, i64, i64),
}

fn identity(path: &Path) -> Result<Identity> {
    let metadata = fs::metadata(path).with_context(|| format!("stat tool {}", path.display()))?;
    ensure!(
        metadata.is_file(),
        "tool is not a regular file: {}",
        path.display()
    );
    Ok(Identity {
        bytes: metadata.len(),
        modified: metadata.modified()?,
        #[cfg(unix)]
        unix: {
            use std::os::unix::fs::MetadataExt;
            (
                metadata.dev(),
                metadata.ino(),
                metadata.mode(),
                metadata.ctime(),
                metadata.ctime_nsec(),
            )
        },
    })
}

struct VerifiedDigest {
    identity: Identity,
    sha256: String,
}

/// The same Tools object is created anew for each request. Metadata is a drift alarm,
/// never a replacement for the first content hash or the external execution gate.
#[derive(Default)]
pub(super) struct ToolDigests(RefCell<BTreeMap<PathBuf, VerifiedDigest>>);

impl ToolDigests {
    pub(super) fn digest(&self, path: &Path) -> Result<String> {
        if let Some(verified) = self.0.borrow().get(path) {
            ensure!(
                identity(path)? == verified.identity,
                "tool changed after initial digest: {}",
                path.display()
            );
            record(|stats| stats.tool_digest_hits += 1);
            return Ok(verified.sha256.clone());
        }
        let before = identity(path)?;
        let digest = sha256_file(path)?;
        ensure!(
            before == identity(path)?,
            "tool changed during initial digest: {}",
            path.display()
        );
        self.0.borrow_mut().insert(
            path.to_owned(),
            VerifiedDigest {
                identity: before,
                sha256: digest.clone(),
            },
        );
        record(|stats| stats.tool_digest_reads += 1);
        Ok(digest)
    }

    pub(super) fn check_identity(&self, path: &Path) -> Result<()> {
        let digests = self.0.borrow();
        let verified = digests
            .get(path)
            .context("tool has not been content-hashed in this request")?;
        ensure!(
            identity(path)? == verified.identity,
            "tool changed at execution boundary: {}",
            path.display()
        );
        record(|stats| stats.tool_identity_checks += 1);
        Ok(())
    }
}

pub(super) fn build_instance_signals(symbols: &SymbolTable) -> InstanceSignals {
    let mut signals: InstanceSignals = BTreeMap::new();
    for name in symbols.by_name.keys() {
        let (instance, leaf) = split_instance(name);
        signals
            .entry(instance.to_owned())
            .or_default()
            .insert(leaf_base(leaf).to_owned());
    }
    signals
}

/// Borrowed inputs cannot mutate or disappear while cached structure is live. Component
/// and entrypoint tables have separate instances. Parse failures are deliberately not
/// cached or eagerly evaluated, preserving target order and the first reported error.
pub(super) struct RewriteStructure<'a> {
    symbols: &'a SymbolTable,
    templates: &'a [TemplateDef],
    sources: &'a BTreeMap<PathBuf, String>,
    signals: OnceCell<InstanceSignals>,
    hints: RefCell<BTreeMap<HintKey, Rc<ParsedHints>>>,
}

impl<'a> RewriteStructure<'a> {
    pub(super) fn new(
        symbols: &'a SymbolTable,
        templates: &'a [TemplateDef],
        sources: &'a BTreeMap<PathBuf, String>,
    ) -> Self {
        Self {
            symbols,
            templates,
            sources,
            signals: OnceCell::new(),
            hints: RefCell::new(BTreeMap::new()),
        }
    }

    pub(super) fn matches(
        &self,
        symbols: &SymbolTable,
        templates: &[TemplateDef],
        sources: &BTreeMap<PathBuf, String>,
    ) -> bool {
        std::ptr::eq(self.symbols, symbols)
            && std::ptr::eq(self.templates, templates)
            && std::ptr::eq(self.sources, sources)
    }

    pub(super) fn instance_signals(&self) -> &InstanceSignals {
        if self.signals.get().is_some() {
            record(|stats| stats.rewrite_structure_hits += 1);
        }
        self.signals.get_or_init(|| {
            record(|stats| stats.rewrite_structure_builds += 1);
            build_instance_signals(self.symbols)
        })
    }

    pub(super) fn hints(&self, template: &TemplateDef) -> Result<Rc<ParsedHints>> {
        ensure!(
            self.templates
                .iter()
                .any(|item| std::ptr::eq(item, template)),
            "rewrite template is outside its immutable source context"
        );
        let key = (
            template.file.clone(),
            template.name.clone(),
            template.body_start,
            template.body_end,
        );
        if let Some(parsed) = self.hints.borrow().get(&key) {
            record(|stats| stats.hint_parse_hits += 1);
            return Ok(Rc::clone(parsed));
        }
        record(|stats| stats.hint_parse_calls += 1);
        let parsed = Rc::new(super::hint_statements(
            &self.sources[&template.file],
            template,
        )?);
        self.hints.borrow_mut().insert(key, Rc::clone(&parsed));
        Ok(parsed)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::candidate_review::r1cs::Symbol;
    use num_bigint::BigUint;

    fn symbols(names: &[&str]) -> SymbolTable {
        SymbolTable {
            by_name: names
                .iter()
                .enumerate()
                .map(|(wire, name)| ((*name).to_owned(), Symbol { wire: wire as i64 }))
                .collect(),
            wire_to_names: Vec::new(),
            eliminated_names: BTreeSet::new(),
        }
    }

    #[test]
    fn tool_digest_is_request_local_and_rejects_same_length_replacement() -> Result<()> {
        let temporary = tempfile::tempdir()?;
        let tool = temporary.path().join("tool");
        fs::write(&tool, b"first")?;
        let guard = activate()?;
        let digests = ToolDigests::default();
        assert_eq!(digests.digest(&tool)?, digests.digest(&tool)?);
        digests.check_identity(&tool)?;
        assert_eq!(telemetry()["stats"]["tool_digest_reads"], 1);
        assert_eq!(telemetry()["stats"]["tool_digest_hits"], 1);
        let replacement = temporary.path().join("new");
        fs::write(&replacement, b"other")?;
        fs::rename(replacement, &tool)?;
        assert!(digests.digest(&tool).is_err());
        assert!(digests.check_identity(&tool).is_err());
        drop(guard);
        let _guard = activate()?;
        let next = ToolDigests::default();
        assert_eq!(next.digest(&tool)?, sha256_file(&tool)?);
        assert_eq!(telemetry()["stats"]["tool_digest_reads"], 1);
        Ok(())
    }

    #[test]
    fn guard_clears_after_unwind_and_does_not_cross_threads() {
        assert!(std::panic::catch_unwind(|| {
            let _guard = activate().unwrap();
            panic!("test");
        })
        .is_err());
        assert!(!enabled());
        let _guard = activate().unwrap();
        assert!(activate().is_err());
        std::thread::spawn(|| assert!(!enabled())).join().unwrap();
    }

    #[test]
    fn dynamic_plans_and_edited_bytes_match_for_nested_array_and_anonymous_instances() -> Result<()>
    {
        let _guard = activate()?;
        let file = PathBuf::from("synthetic.circom");
        let source = "template Leaf() { signal input x; signal output y[2]; for(var i=0;i<2;i++) { y[i] <-- x+i; } }";
        let sources = BTreeMap::from([(file.clone(), source.to_owned())]);
        let templates = super::super::parse_templates(&file, source)?;
        let names = [
            "main.outer[1].Leaf_1_20.x",
            "main.outer[1].Leaf_1_20.y[0]",
            "main.outer[1].Leaf_1_20.y[1]",
        ];
        let sym = symbols(&names);
        let cache = RewriteStructure::new(&sym, &templates, &sources);
        for (value, aborted) in [(7u32, false), (11, true), (23, false)] {
            let candidate = BTreeMap::from([
                (names[0].to_owned(), BigUint::from(3u32)),
                (names[1].to_owned(), BigUint::from(value)),
                (names[2].to_owned(), BigUint::from(value + 1)),
            ]);
            let deviated = BTreeSet::from([names[1].to_owned(), names[2].to_owned()]);
            let plan = |cache| {
                super::super::plan_rewrites(
                    &candidate, &sym, &deviated, aborted, &templates, &sources, None, cache,
                )
                .map_err(|failure| anyhow::anyhow!("{}: {}", failure.reason, failure.detail))
            };
            let legacy = plan(None)?;
            let cached = plan(Some(&cache))?;
            assert_eq!(legacy, cached);
            let apply = |plan: &super::super::RewritePlan| {
                let mut result = source.to_owned();
                let mut edits = plan.edits[&file].clone();
                edits.sort_by_key(|entry| entry.0);
                for (start, end, replacement) in edits.into_iter().rev() {
                    result.replace_range(start..end, &replacement);
                }
                result
            };
            assert_eq!(apply(&legacy), apply(&cached));
            assert!(apply(&cached).contains(&format!("? {value}")));
        }
        assert_eq!(telemetry()["stats"]["rewrite_structure_builds"], 1);
        assert_eq!(telemetry()["stats"]["rewrite_structure_hits"], 2);
        assert_eq!(telemetry()["stats"]["hint_parse_calls"], 1);
        assert!(telemetry()["stats"]["hint_parse_hits"].as_u64().unwrap() >= 5);
        Ok(())
    }

    #[test]
    fn lazy_parse_preserves_first_failure_and_distinct_contexts() -> Result<()> {
        let _guard = activate()?;
        for (body, names) in [
            (
                "signal input x; signal output y; x --> y;",
                vec!["main.x", "main.y"],
            ),
            (
                "signal input x; signal output y; y <-- x",
                vec!["main.x", "main.y"],
            ),
            (
                "signal input x; signal output y[2]; y[0] <-- x;",
                vec!["main.x", "main.y"],
            ),
        ] {
            let file = PathBuf::from("error.circom");
            let source =
                format!("template T() {{ {body} }} template Unused() {{ signal x; x <-- ; }}");
            let sources = BTreeMap::from([(file.clone(), source.clone())]);
            let templates = super::super::parse_templates(&file, &source)?;
            let sym = symbols(&names);
            let cache = RewriteStructure::new(&sym, &templates, &sources);
            let candidate = BTreeMap::from([
                ("main.x".into(), BigUint::from(1u32)),
                ("main.y".into(), BigUint::from(2u32)),
            ]);
            let deviated = BTreeSet::from(["main.y".into()]);
            let run = |cache| {
                super::super::plan_rewrites(
                    &candidate,
                    &sym,
                    &deviated,
                    false,
                    &templates,
                    &sources,
                    Some("T"),
                    cache,
                )
                .map_err(|failure| (failure.status, failure.reason, failure.detail))
            };
            assert_eq!(run(None), run(Some(&cache)));
            assert_eq!(run(None), run(Some(&cache)));
            let other = sym.clone();
            assert!(!cache.matches(&other, &templates, &sources));
        }
        Ok(())
    }
}
