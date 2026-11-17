//! Source-copy correspondence for the optional baseline-input probe.

use super::*;
use std::path::Component;

#[derive(Clone, Debug)]
struct Include {
    start: usize,
    end: usize,
    literal: String,
    target: PathBuf,
}

/// An original closure, checked before definition edits are translated.
pub(super) struct WorkspacePlan {
    entry: PathBuf,
    source_root: PathBuf,
    libraries: Vec<PathBuf>,
    originals: BTreeMap<PathBuf, String>,
    includes: BTreeMap<PathBuf, Vec<Include>>,
}

pub(super) struct PreparedWorkspace {
    pub root: PathBuf,
    pub libraries: Vec<PathBuf>,
    pub entry: PathBuf,
    pub edits: repair::Edits,
    workspace: PathBuf,
    original_entry: PathBuf,
    includes: BTreeMap<PathBuf, Vec<Include>>,
    expected: BTreeMap<PathBuf, BTreeMap<PathBuf, Vec<u8>>>,
}

impl WorkspacePlan {
    pub(super) fn new(
        entry: &Path,
        source_root: &Path,
        libraries: &[PathBuf],
        sources: &BTreeMap<PathBuf, String>,
    ) -> Result<Self> {
        site_signal_probe::checkpoint()?;
        let entry = fs::canonicalize(entry)?;
        let source_root = fs::canonicalize(source_root)?;
        let libraries = libraries
            .iter()
            .map(fs::canonicalize)
            .collect::<Result<Vec<_>, _>>()?;
        let closure = crate::targets::discovery_dependency_paths(&entry, &source_root, &libraries)?;
        let mut originals = BTreeMap::new();
        let mut includes = BTreeMap::new();
        for file in closure {
            site_signal_probe::checkpoint()?;
            ensure!(
                within_bases(&file, &source_root, &libraries),
                "include target outside every declared base: {}",
                file.display()
            );
            let text = sources.get(&file).with_context(|| {
                format!(
                    "original source is absent from the saved closure: {}",
                    file.display()
                )
            })?;
            ensure!(
                fs::read(&file)? == text.as_bytes(),
                "original source bytes changed: {}",
                file.display()
            );
            let mut directives = scan_includes(text)?;
            ensure!(
                directives
                    .iter()
                    .map(|item| item.literal.clone())
                    .collect::<Vec<_>>()
                    == crate::targets::circom_include_literals(&file)?,
                "include byte ranges do not match the source parser"
            );
            for directive in &mut directives {
                directive.target = resolve(&file, &directive.literal, &source_root, &libraries)?;
                ensure!(
                    within_bases(&directive.target, &source_root, &libraries),
                    "include target outside every declared base: {}",
                    directive.target.display()
                );
                ensure!(
                    file == entry || !Path::new(&directive.literal).is_absolute(),
                    "intermediate source contains an absolute include: {}",
                    file.display()
                );
            }
            originals.insert(file.clone(), text.clone());
            includes.insert(file, directives);
        }
        Ok(Self {
            entry,
            source_root,
            libraries,
            originals,
            includes,
        })
    }

    /// Writes per-copy include edits while keeping the selected entry copy in the key.
    pub(super) fn write(
        self,
        workspace: &Path,
        mapped_edits: &repair::Edits,
    ) -> Result<PreparedWorkspace> {
        site_signal_probe::checkpoint()?;
        let entry_relative = self.entry.strip_prefix(&self.source_root)?;
        let selected_entry = Path::new("root").join(entry_relative);
        let mut edits = mapped_edits.clone();
        for file in edits.keys() {
            ensure!(
                self.originals.contains_key(file),
                "edited source is outside the original closure"
            );
        }
        self.add_entry_includes(&selected_entry, &mut edits)?;
        for (file, text) in &self.originals {
            apply(text, edits.get(file))?;
        }
        let (root, libraries) = write_edits_workspace(
            workspace,
            &self.source_root,
            &self.libraries,
            &self.originals,
            &edits,
        )?;
        for base in std::iter::once(&root).chain(&libraries) {
            fs::create_dir_all(base)?;
        }
        let workspace = fs::canonicalize(workspace)?;
        let root = fs::canonicalize(root)?;
        let libraries = libraries
            .iter()
            .map(fs::canonicalize)
            .collect::<Result<Vec<_>, _>>()?;
        let entry = root.join(entry_relative);
        let mut expected = BTreeMap::new();
        let mut copies = Vec::new();
        for (original, text) in &self.originals {
            site_signal_probe::checkpoint()?;
            let mut expected_copies = BTreeMap::new();
            for relative in self.copy_locations(original) {
                let copy = workspace.join(&relative);
                let mut copy_edits = mapped_edits.clone();
                if original == &self.entry {
                    self.add_entry_includes(&relative, &mut copy_edits)?;
                }
                let contents = apply(text, copy_edits.get(original))?;
                if original == &self.entry {
                    let parent = fs::canonicalize(copy.parent().context("copy has no parent")?)?;
                    ensure!(
                        parent.starts_with(&workspace)
                            && !fs::symlink_metadata(&copy)?.file_type().is_symlink(),
                        "rewritten entry would leave the probe workspace"
                    );
                    fs::write(&copy, &contents)?;
                }
                copies.push(serde_json::json!({
                    "original": original,
                    "copy": relative,
                    "expected_sha256": sha256_bytes(contents.as_bytes()),
                    "edits": copy_edits.get(original).cloned().unwrap_or_default(),
                }));
                expected_copies.insert(copy, contents.into_bytes());
            }
            expected.insert(original.clone(), expected_copies);
        }
        write_json(
            &workspace.join("source-copy-map.json"),
            &serde_json::json!({
                "entrypoint": selected_entry,
                "edits": edits,
                "copies": copies,
            }),
        )?;
        Ok(PreparedWorkspace {
            root,
            libraries,
            entry,
            edits,
            workspace,
            original_entry: self.entry,
            includes: self.includes,
            expected,
        })
    }

    fn copy_locations(&self, original: &Path) -> Vec<PathBuf> {
        std::iter::once((&self.source_root, PathBuf::from("root")))
            .chain(
                self.libraries
                    .iter()
                    .enumerate()
                    .map(|(index, base)| (base, PathBuf::from(format!("lib{index}")))),
            )
            .filter_map(|(base, copy)| {
                original
                    .strip_prefix(base)
                    .ok()
                    .map(|relative| copy.join(relative))
            })
            .collect()
    }

    fn add_entry_includes(&self, entry_copy: &Path, edits: &mut repair::Edits) -> Result<()> {
        for include in &self.includes[&self.entry] {
            if !Path::new(&include.literal).is_absolute() {
                continue;
            }
            let target = self
                .copy_locations(&include.target)
                .into_iter()
                .next()
                .context("include target outside every declared base")?;
            let relative = relative_path(
                entry_copy.parent().context("entry copy has no parent")?,
                &target,
            )?;
            let replacement = relative
                .to_str()
                .context("include path is not UTF-8")?
                .replace('\\', "\\\\")
                .replace('"', "\\\"");
            edits.entry(self.entry.clone()).or_default().push((
                include.start,
                include.end,
                replacement,
            ));
        }
        Ok(())
    }
}

impl PreparedWorkspace {
    /// Must run immediately before compilation, including when artifacts are cached.
    pub(super) fn verify(&self) -> Result<()> {
        site_signal_probe::checkpoint()?;
        let closure =
            crate::targets::discovery_dependency_paths(&self.entry, &self.root, &self.libraries)?;
        let actual = closure.into_iter().collect::<BTreeSet<_>>();
        ensure!(
            actual.iter().all(|file| file.starts_with(&self.workspace)),
            "workspace dependency leaves the probe workspace"
        );
        let mut selected = BTreeMap::<PathBuf, PathBuf>::new();
        let mut visited = BTreeSet::new();
        let mut pending = vec![(self.original_entry.clone(), fs::canonicalize(&self.entry)?)];
        while let Some((original, copy)) = pending.pop() {
            site_signal_probe::checkpoint()?;
            ensure!(
                copy.starts_with(&self.workspace),
                "workspace dependency leaves the probe workspace"
            );
            let expected = self
                .expected
                .get(&original)
                .and_then(|copies| copies.get(&copy))
                .with_context(|| {
                    format!(
                        "workspace dependency does not follow original-to-copy correspondence: {}",
                        copy.display()
                    )
                })?;
            if let Some(previous) = selected.insert(original.clone(), copy.clone()) {
                ensure!(
                    previous == copy,
                    "original dependency uses multiple workspace copies"
                );
            }
            if !visited.insert(copy.clone()) {
                continue;
            }
            let bytes = fs::read(&copy)?;
            ensure!(
                &bytes == expected,
                "workspace dependency bytes differ from the planned edits: {}",
                copy.display()
            );
            let text = std::str::from_utf8(&bytes)?;
            let directives = scan_includes(text)?;
            let original_directives = &self.includes[&original];
            ensure!(
                directives.len() == original_directives.len(),
                "workspace include count changed"
            );
            ensure!(
                directives
                    .iter()
                    .map(|item| item.literal.clone())
                    .collect::<Vec<_>>()
                    == crate::targets::circom_include_literals(&copy)?,
                "workspace include byte ranges do not match the source parser"
            );
            for (directive, original_directive) in directives.iter().zip(original_directives) {
                ensure!(
                    !Path::new(&directive.literal).is_absolute(),
                    "workspace retains an absolute include"
                );
                let target = resolve(&copy, &directive.literal, &self.root, &self.libraries)?;
                pending.push((original_directive.target.clone(), target));
            }
        }
        ensure!(
            visited == actual,
            "workspace dependency closure differs from the planned correspondence"
        );
        ensure!(
            selected.len() == self.expected.len(),
            "workspace dependency closure omits an original source"
        );
        write_json(
            &self.workspace.join("verified-source-copy-map.json"),
            &serde_json::json!({
                "original_to_copy": selected,
                "files_verified": visited.len(),
            }),
        )?;
        site_signal_probe::checkpoint()
    }
}

fn within_bases(file: &Path, root: &Path, libraries: &[PathBuf]) -> bool {
    file.starts_with(root) || libraries.iter().any(|base| file.starts_with(base))
}

fn resolve(file: &Path, literal: &str, root: &Path, libraries: &[PathBuf]) -> Result<PathBuf> {
    file.parent()
        .map(|parent| parent.join(literal))
        .into_iter()
        .chain(std::iter::once(root.join(literal)))
        .chain(libraries.iter().map(|library| library.join(literal)))
        .find_map(|candidate| fs::canonicalize(candidate).ok())
        .with_context(|| format!("include could not be resolved: {literal}"))
}

fn relative_path(from: &Path, to: &Path) -> Result<PathBuf> {
    let from = from.components().collect::<Vec<_>>();
    let to = to.components().collect::<Vec<_>>();
    ensure!(
        from.iter()
            .chain(&to)
            .all(|part| matches!(part, Component::Normal(_))),
        "non-normal workspace copy path"
    );
    let common = from.iter().zip(&to).take_while(|(a, b)| a == b).count();
    let mut result = PathBuf::new();
    for _ in common..from.len() {
        result.push("..");
    }
    for part in &to[common..] {
        result.push(part.as_os_str());
    }
    Ok(result)
}

fn apply(text: &str, edits: Option<&Vec<(usize, usize, String)>>) -> Result<String> {
    let mut text = text.to_owned();
    let mut ordered = edits.cloned().unwrap_or_default();
    ordered.sort_by_key(|edit| (edit.0, edit.1));
    ensure!(
        ordered.windows(2).all(|pair| pair[0].1 <= pair[1].0),
        "overlapping probe workspace edits"
    );
    for (start, end, replacement) in ordered.into_iter().rev() {
        ensure!(
            start <= end && text.is_char_boundary(start) && text.is_char_boundary(end),
            "invalid probe workspace edit range"
        );
        text.replace_range(start..end, &replacement);
    }
    Ok(text)
}

fn scan_includes(text: &str) -> Result<Vec<Include>> {
    let bytes = text.as_bytes();
    let mut index = 0;
    let mut found = Vec::new();
    let mut expect_path = false;
    while index < bytes.len() {
        if bytes[index].is_ascii_whitespace() {
            index += 1;
            continue;
        }
        if bytes[index..].starts_with(b"//") {
            while index < bytes.len() && bytes[index] != b'\n' {
                index += 1;
            }
            continue;
        }
        if bytes[index..].starts_with(b"/*") {
            index += 2;
            while index < bytes.len() && !bytes[index..].starts_with(b"*/") {
                index += 1;
            }
            ensure!(index < bytes.len(), "unterminated source comment");
            index += 2;
            continue;
        }
        if bytes[index] == b'"' {
            index += 1;
            let start = index;
            while index < bytes.len() && bytes[index] != b'"' {
                if bytes[index] == b'\\' {
                    index += 1;
                }
                index += 1;
            }
            ensure!(index < bytes.len(), "unterminated include string");
            if expect_path {
                let mut literal = String::new();
                let mut chars = text[start..index].chars();
                while let Some(character) = chars.next() {
                    literal.push(if character == '\\' {
                        chars.next().context("unfinished include escape")?
                    } else {
                        character
                    });
                }
                found.push(Include {
                    start,
                    end: index,
                    literal,
                    target: PathBuf::new(),
                });
            }
            expect_path = false;
            index += 1;
            continue;
        }
        if bytes[index].is_ascii_alphabetic() || bytes[index] == b'_' {
            let start = index;
            index += 1;
            while index < bytes.len()
                && (bytes[index].is_ascii_alphanumeric() || bytes[index] == b'_')
            {
                index += 1;
            }
            expect_path = &text[start..index] == "include";
        } else {
            ensure!(!expect_path, "include path must be a string literal");
            index += 1;
        }
    }
    Ok(found)
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Fixture {
        temporary: tempfile::TempDir,
        root: PathBuf,
        entry: PathBuf,
        source: PathBuf,
        sources: BTreeMap<PathBuf, String>,
    }
    impl Fixture {
        fn new() -> Self {
            let temporary = tempfile::tempdir().unwrap();
            let root = temporary.path().join("original");
            fs::create_dir_all(root.join("src")).unwrap();
            fs::create_dir_all(root.join("wrappers")).unwrap();
            let root = fs::canonicalize(root).unwrap();
            let source = root.join("src/t.circom");
            let entry = root.join("wrappers/target.circom");
            fs::write(&source, "template T() { signal output out; out <-- 1; }\n").unwrap();
            fs::write(
                &entry,
                format!(
                    "pragma circom 2.2.3;\ninclude \"{}\";\ncomponent main = T();\n",
                    source.display()
                ),
            )
            .unwrap();
            let sources = [&entry, &source]
                .into_iter()
                .map(|file| (file.clone(), fs::read_to_string(file).unwrap()))
                .collect();
            Self {
                temporary,
                root,
                entry,
                source,
                sources,
            }
        }
        fn edits(&self, value: &str) -> repair::Edits {
            let text = &self.sources[&self.source];
            let start = text.find("<-- 1").unwrap() + 4;
            BTreeMap::from([(
                self.source.clone(),
                vec![(start, start + 1, value.to_owned())],
            )])
        }
        fn plan(&self, libraries: &[PathBuf]) -> WorkspacePlan {
            WorkspacePlan::new(&self.entry, &self.root, libraries, &self.sources).unwrap()
        }
        fn key(&self, prepared: &PreparedWorkspace) -> String {
            let tool = self.temporary.path().join("compiler");
            fs::write(&tool, "fixed compiler").unwrap();
            let tools = Tools {
                circom: tool.clone(),
                node: tool.clone(),
                snarkjs: tool,
                verified_digests: None,
            };
            edits_key(
                &tools,
                self.entry.strip_prefix(&self.root).unwrap(),
                &self.root,
                std::slice::from_ref(&self.root),
                &self.sources,
                &prepared.edits,
                false,
            )
            .unwrap()
        }
    }

    #[test]
    fn absolute_entry_uses_edited_copy_with_overlapping_bases() {
        let fixture = Fixture::new();
        let original = fs::read(&fixture.source).unwrap();
        let prepared = fixture
            .plan(std::slice::from_ref(&fixture.root))
            .write(
                &fixture.temporary.path().join("attempt-a"),
                &fixture.edits("0"),
            )
            .unwrap();
        prepared.verify().unwrap();
        let used = crate::targets::discovery_dependency_paths(
            &prepared.entry,
            &prepared.root,
            &prepared.libraries,
        )
        .unwrap();
        assert!(used.contains(&prepared.root.join("src/t.circom")));
        assert!(fs::read_to_string(prepared.root.join("src/t.circom"))
            .unwrap()
            .contains("out <-- 0"));
        assert_eq!(fs::read(&fixture.source).unwrap(), original);
        assert!(fs::read_to_string(&prepared.entry)
            .unwrap()
            .contains("include \"../src/t.circom\""));
        assert!(
            fs::read_to_string(prepared.libraries[0].join("wrappers/target.circom"))
                .unwrap()
                .contains("include \"../../root/src/t.circom\"")
        );
    }

    #[test]
    fn keys_ignore_attempt_directory_and_bind_value_and_include_edit() {
        let fixture = Fixture::new();
        let make = |name: &str, value: &str| {
            fixture
                .plan(std::slice::from_ref(&fixture.root))
                .write(&fixture.temporary.path().join(name), &fixture.edits(value))
                .unwrap()
        };
        let a = make("attempt-a", "0");
        let b = make("attempt-b", "0");
        let c = make("attempt-c", "2");
        assert_eq!(fixture.key(&a), fixture.key(&b));
        assert_ne!(fixture.key(&a), fixture.key(&c));
        let mut changed = b;
        changed.edits.get_mut(&fixture.entry).unwrap()[0]
            .2
            .push_str("/changed");
        assert_ne!(fixture.key(&a), fixture.key(&changed));
    }

    #[test]
    fn verification_rechecks_actual_bytes_even_with_a_complete_cache() {
        let fixture = Fixture::new();
        let prepared = fixture
            .plan(std::slice::from_ref(&fixture.root))
            .write(
                &fixture.temporary.path().join("attempt"),
                &fixture.edits("0"),
            )
            .unwrap();
        prepared.verify().unwrap();
        let cache = fixture
            .temporary
            .path()
            .join("cache/edits")
            .join(fixture.key(&prepared));
        fs::create_dir_all(&cache).unwrap();
        fs::write(cache.join("complete"), b"").unwrap();
        fs::write(
            prepared.root.join("src/t.circom"),
            &fixture.sources[&fixture.source],
        )
        .unwrap();
        assert!(prepared
            .verify()
            .unwrap_err()
            .to_string()
            .contains("bytes differ from the planned edits"));
        assert!(
            fs::read_to_string(prepared.libraries[0].join("src/t.circom"))
                .unwrap()
                .contains("out <-- 0")
        );
    }

    #[test]
    fn outside_absolute_include_is_rejected_without_substituting_equal_source() {
        let mut fixture = Fixture::new();
        let outside = fixture.temporary.path().join("outside.circom");
        fs::write(&outside, &fixture.sources[&fixture.source]).unwrap();
        let text = fixture.sources[&fixture.entry]
            .replace(fixture.source.to_str().unwrap(), outside.to_str().unwrap());
        fs::write(&fixture.entry, &text).unwrap();
        fixture.sources.insert(fixture.entry.clone(), text);
        fixture.sources.insert(
            fs::canonicalize(outside).unwrap(),
            fixture.sources[&fixture.source].clone(),
        );
        let error = WorkspacePlan::new(&fixture.entry, &fixture.root, &[], &fixture.sources)
            .err()
            .unwrap();
        assert!(error
            .to_string()
            .contains("include target outside every declared base"));
    }

    #[test]
    fn intermediate_absolute_include_is_rejected_without_rewriting() {
        let mut fixture = Fixture::new();
        let intermediate = fixture.root.join("middle.circom");
        let text = format!("include \"{}\";\n", fixture.source.display());
        fs::write(&intermediate, &text).unwrap();
        fixture.sources.insert(intermediate, text);
        let entry = "pragma circom 2.2.3;\ninclude \"../middle.circom\";\ncomponent main = T();\n";
        fs::write(&fixture.entry, entry).unwrap();
        fixture
            .sources
            .insert(fixture.entry.clone(), entry.to_owned());
        let error = WorkspacePlan::new(&fixture.entry, &fixture.root, &[], &fixture.sources)
            .err()
            .unwrap();
        assert!(error
            .to_string()
            .contains("intermediate source contains an absolute include"));
    }

    #[cfg(unix)]
    #[test]
    fn absolute_symlink_from_workspace_to_original_is_rejected() {
        let mut fixture = Fixture::new();
        std::os::unix::fs::symlink(&fixture.source, fixture.root.join("src/link.circom")).unwrap();
        let entry =
            "pragma circom 2.2.3;\ninclude \"../src/link.circom\";\ncomponent main = T();\n";
        fs::write(&fixture.entry, entry).unwrap();
        fixture
            .sources
            .insert(fixture.entry.clone(), entry.to_owned());
        let prepared = fixture
            .plan(&[])
            .write(
                &fixture.temporary.path().join("attempt"),
                &fixture.edits("0"),
            )
            .unwrap();
        assert!(prepared
            .verify()
            .unwrap_err()
            .to_string()
            .contains("leaves the probe workspace"));
    }

    #[cfg(unix)]
    #[test]
    fn equal_bytes_at_the_wrong_copy_do_not_satisfy_correspondence() {
        let fixture = Fixture::new();
        let prepared = fixture
            .plan(&[])
            .write(
                &fixture.temporary.path().join("attempt"),
                &fixture.edits("0"),
            )
            .unwrap();
        let used = prepared.root.join("src/t.circom");
        let different = prepared.root.join("src/different.circom");
        fs::rename(&used, &different).unwrap();
        std::os::unix::fs::symlink("different.circom", &used).unwrap();
        assert!(prepared
            .verify()
            .unwrap_err()
            .to_string()
            .contains("does not follow original-to-copy correspondence"));
    }

    #[test]
    fn include_scanner_preserves_comments_and_escaped_literal_ranges() {
        let text =
            "// include \"fake\";\ninclude /* gap */ \"a\\\"b.circom\"; /* include \"fake2\"; */";
        let includes = scan_includes(text).unwrap();
        assert_eq!(includes.len(), 1);
        assert_eq!(includes[0].literal, "a\"b.circom");
        assert_eq!(&text[includes[0].start..includes[0].end], "a\\\"b.circom");
    }
}
