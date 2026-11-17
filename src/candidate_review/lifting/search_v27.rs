//! Request-scoped search diagnostics and byte-exact definition identity for v2.7.
use std::{
    cell::RefCell,
    collections::BTreeMap,
    marker::PhantomData,
    path::{Path, PathBuf},
    rc::Rc,
};

use anyhow::{ensure, Result};
use serde_json::{json, Value};

use super::{source, TemplateDef};

thread_local! {
    static STATE: RefCell<Option<State>> = const { RefCell::new(None) };
}

struct State {
    site: Option<String>,
    events: Vec<Value>,
    repair_iteration_limit: usize,
}

pub(super) struct Guard(PhantomData<Rc<()>>);

pub(super) fn activate() -> Result<Guard> {
    activate_with_limit(6)
}

pub(super) fn activate_with_limit(repair_iteration_limit: usize) -> Result<Guard> {
    ensure!(
        repair_iteration_limit > 0,
        "repair iteration limit must be positive"
    );
    STATE.with(|slot| {
        let mut state = slot.borrow_mut();
        ensure!(
            state.is_none(),
            "a J v2.7 request is already active on this thread"
        );
        *state = Some(State {
            site: None,
            events: Vec::new(),
            repair_iteration_limit,
        });
        Ok(Guard(PhantomData))
    })
}

pub(super) fn repair_iteration_limit() -> usize {
    STATE.with(|slot| {
        slot.borrow()
            .as_ref()
            .map_or(6, |state| state.repair_iteration_limit)
    })
}

pub(super) fn search_identity_suffix() -> String {
    if enabled() {
        format!(":j-v2.7:repair-limit:{}", repair_iteration_limit())
    } else {
        String::new()
    }
}

impl Drop for Guard {
    fn drop(&mut self) {
        STATE.with(|slot| *slot.borrow_mut() = None);
    }
}

pub(super) fn enabled() -> bool {
    STATE.with(|slot| slot.borrow().is_some())
}

pub(super) fn site(value: Option<&str>) {
    STATE.with(|slot| {
        if let Some(state) = slot.borrow_mut().as_mut() {
            state.site = value.map(str::to_owned);
        }
    });
}

pub(super) fn record(mut event: Value) {
    STATE.with(|slot| {
        if let Some(state) = slot.borrow_mut().as_mut() {
            if event.get("site").is_none() {
                event["site"] = json!(state.site);
            }
            state.events.push(event);
        }
    });
}

pub(super) fn write(output: &Path) -> Result<()> {
    STATE.with(|slot| {
        let state = slot.borrow();
        let state = state.as_ref().expect("active v2.7 request");
        super::write_json(
            &output.join("j-diagnostics.json"),
            &json!({
                "schema": "zkfdo-j-diagnostics-v2.7",
                "verdict_contract": "v2.5",
                "repair_iteration_limit": state.repair_iteration_limit,
                "independent_predicate_iteration_limit": 6,
                "events": state.events,
            }),
        )
    })
}

pub(super) fn branch_counts() -> BTreeMap<String, u64> {
    STATE.with(|slot| {
        let state = slot.borrow();
        let mut counts = BTreeMap::new();
        if let Some(state) = state.as_ref() {
            for event in &state.events {
                if event["site"].as_str() == state.site.as_deref() {
                    if let (Some(kind), Some(branches)) =
                        (event["kind"].as_str(), event["branches_tried"].as_u64())
                    {
                        *counts.entry(kind.to_owned()).or_default() += branches;
                    }
                }
            }
        }
        counts
    })
}

fn definition<'a>(template: &TemplateDef, sources: &'a BTreeMap<PathBuf, String>) -> &'a str {
    &sources[&template.file][template.definition_start..template.body_end + 1]
}

pub(super) fn unique_definitions<'a>(
    templates: &[&'a TemplateDef],
    sources: &BTreeMap<PathBuf, String>,
) -> Vec<&'a TemplateDef> {
    let mut seen = BTreeMap::new();
    for template in templates {
        seen.entry(definition(template, sources))
            .or_insert(*template);
    }
    seen.into_values().collect()
}

pub(super) fn view_definitions(
    templates: &[TemplateDef],
    sources: &BTreeMap<PathBuf, String>,
    target: &Path,
    name: &str,
) -> Vec<TemplateDef> {
    let matches = templates
        .iter()
        .filter(|template| template.name == name)
        .collect::<Vec<_>>();
    let unique = unique_definitions(&matches, sources);
    if matches.len() > 1 {
        resolution(
            "main",
            &matches,
            sources,
            Some(name),
            matches.len(),
            unique.len(),
            if unique.len() == 1 {
                "identical_definitions"
            } else {
                "ambiguous"
            },
        );
    }
    let selected = matches.iter().find(|template| template.file == target);
    templates
        .iter()
        .filter(|template| {
            selected.is_none_or(|selected| {
                template.file == target
                    || definition(template, sources) != definition(selected, sources)
            })
        })
        .cloned()
        .collect()
}

pub(super) fn resolution(
    instance: &str,
    matches: &[&TemplateDef],
    sources: &BTreeMap<PathBuf, String>,
    wanted: Option<&str>,
    named: usize,
    unique: usize,
    outcome: &str,
) {
    let definitions = matches
        .iter()
        .map(|template| {
            let text = &sources[&template.file];
            json!({
                "name": template.name, "file": template.file,
                "file_sha256": super::sha256_bytes(text.as_bytes()),
                "definition_sha256": super::sha256_bytes(definition(template, sources).as_bytes()),
                "start_byte": template.definition_start, "end_byte": template.body_end + 1,
                "line": text[..template.definition_start].matches('\n').count() + 1,
                "end_line": text[..template.body_end].matches('\n').count() + 1,
            })
        })
        .collect::<Vec<_>>();
    record(json!({"kind":"template_resolution", "instance":instance,
        "definitions":definitions, "main_narrowing_attempted":instance == "main" && wanted.is_some(),
        "wanted_name":wanted, "named_matches":named, "unique_definitions":unique,
        "outcome":outcome}));
}

/// Rewrite every byte-identical copy, including copies in the entrypoint closure.
/// Offsets are translated relative to the full declaration, including its parameters.
pub(super) fn expand_identical_edits(
    edits: &mut BTreeMap<PathBuf, Vec<(usize, usize, String)>>,
    templates: &[TemplateDef],
    sources: &BTreeMap<PathBuf, String>,
) -> Result<()> {
    let original = edits.clone();
    for (file, replacements) in &original {
        for (start, end, value) in replacements {
            let Some(origin) = templates.iter().find(|template| {
                &template.file == file && *start >= template.body_start && *end <= template.body_end
            }) else {
                continue;
            };
            for target in templates
                .iter()
                .filter(|target| definition(target, sources) == definition(origin, sources))
            {
                let mapped_start = target.definition_start + start - origin.definition_start;
                let mapped_end = target.definition_start + end - origin.definition_start;
                let list = edits.entry(target.file.clone()).or_default();
                if let Some(existing) = list
                    .iter()
                    .find(|(left, right, _)| *left == mapped_start && *right == mapped_end)
                {
                    ensure!(
                        &existing.2 == value,
                        "conflicting rewrites for identical definitions"
                    );
                } else {
                    list.push((mapped_start, mapped_end, value.clone()));
                }
            }
        }
    }
    for replacements in edits.values_mut() {
        replacements.sort_by_key(|(start, end, _)| (*start, *end));
    }
    Ok(())
}

pub(super) fn assignment_operators(
    targets: &std::collections::BTreeSet<String>,
    templates: &[TemplateDef],
    sources: &BTreeMap<PathBuf, String>,
) -> Vec<Value> {
    let mut found = Vec::new();
    for signal in targets {
        let leaf = super::leaf_base(super::split_instance(signal).1);
        let pattern = format!(
            r"(?:^|[^\w$]){}\s*(?:\[[^\]]*\]\s*)*(<--|<==|=)",
            regex::escape(leaf)
        );
        let regex = regex::Regex::new(&pattern).expect("escaped signal pattern");
        for template in templates {
            let text = &sources[&template.file];
            let masked = source::mask(text);
            for captures in regex.captures_iter(&masked[template.body_start..template.body_end]) {
                let operator = captures.get(1).expect("assignment operator");
                let offset = template.body_start + operator.start();
                found.push(json!({"signal":signal, "operator":operator.as_str(),
                    "template":template.name, "file":template.file,
                    "line":text[..offset].matches('\n').count()+1,
                    "scope":"matching_leaf_declarations"}));
            }
        }
    }
    found
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn repair_cap_is_request_scoped_and_part_of_search_identity() {
        assert_eq!(repair_iteration_limit(), 6);
        assert_eq!(search_identity_suffix(), "");
        assert!(activate_with_limit(0).is_err());
        let default_identity = {
            let _guard = activate().unwrap();
            assert_eq!(repair_iteration_limit(), 6);
            search_identity_suffix()
        };
        {
            let _guard = activate_with_limit(9).unwrap();
            assert_eq!(repair_iteration_limit(), 9);
            assert_ne!(search_identity_suffix(), default_identity);
            let directory = tempfile::tempdir().unwrap();
            write(directory.path()).unwrap();
            let diagnostics: Value = serde_json::from_slice(
                &std::fs::read(directory.path().join("j-diagnostics.json")).unwrap(),
            )
            .unwrap();
            assert_eq!(diagnostics["repair_iteration_limit"], 9);
            assert_eq!(diagnostics["independent_predicate_iteration_limit"], 6);
        }
        assert_eq!(repair_iteration_limit(), 6);
        assert_eq!(search_identity_suffix(), "");
    }

    #[test]
    fn activation_is_scoped_even_after_error() {
        assert!(!enabled());
        {
            let _guard = activate().unwrap();
            assert!(enabled());
        }
        assert!(!enabled());
    }

    #[test]
    fn duplicate_identity_includes_parameters_comments_and_body() {
        let source = "template T(n) { signal input a; signal output b; b <-- a; }";
        let sources = BTreeMap::from([
            (PathBuf::from("a"), source.to_owned()),
            (PathBuf::from("b"), format!("\n{source}")),
            (PathBuf::from("c"), source.replace("T(n)", "T(m)")),
            (PathBuf::from("d"), source.replace("b <-- a", "b <-- a+1")),
        ]);
        let templates = sources
            .iter()
            .flat_map(|(path, text)| source::parse_templates(path, text).unwrap())
            .collect::<Vec<_>>();
        assert_eq!(
            unique_definitions(&templates.iter().collect::<Vec<_>>(), &sources).len(),
            3
        );
        let start = sources[Path::new("a")].find(" a;").unwrap() + 1;
        let mut edits =
            BTreeMap::from([(PathBuf::from("a"), vec![(start, start + 1, "7".to_owned())])]);
        expand_identical_edits(&mut edits, &templates, &sources).unwrap();
        assert_eq!(edits.len(), 2);
        assert_eq!(edits[Path::new("b")][0].0, start + 1);
        assert!(!edits.contains_key(Path::new("c")));
    }
}
