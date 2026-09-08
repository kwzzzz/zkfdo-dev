use std::path::{Path, PathBuf};

use anyhow::{bail, Result};
use serde::{Deserialize, Serialize};
use walkdir::{DirEntry, WalkDir};

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct CircomTarget {
    pub path: PathBuf,
}

pub fn scan_project(project: impl AsRef<Path>) -> Result<Vec<CircomTarget>> {
    let project = project.as_ref();

    if !project.exists() {
        bail!("project path does not exist: {}", project.display());
    }

    let mut targets = Vec::new();

    for entry in WalkDir::new(project)
        .follow_links(false)
        .into_iter()
        .filter_entry(should_visit)
    {
        let entry = entry?;

        if !entry.file_type().is_file() {
            continue;
        }

        if entry.path().extension().is_some_and(|ext| ext == "circom") {
            targets.push(CircomTarget {
                path: entry.path().to_path_buf(),
            });
        }
    }

    targets.sort_by(|left, right| left.path.cmp(&right.path));
    Ok(targets)
}

pub fn scan_placeholder() -> Vec<CircomTarget> {
    Vec::new()
}

fn should_visit(entry: &DirEntry) -> bool {
    let file_name = entry.file_name().to_string_lossy();

    !matches!(
        file_name.as_ref(),
        ".git" | ".zkfdo" | "node_modules" | "target"
    )
}

#[cfg(test)]
mod tests {
    use std::fs;

    use tempfile::tempdir;

    use super::*;

    #[test]
    fn scans_circom_files_recursively() {
        let temp = tempdir().expect("tempdir");
        let root = temp.path();
        let nested = root.join("circuits/nested");

        fs::create_dir_all(&nested).expect("nested dir");
        fs::write(root.join("main.circom"), "component main = Main();").expect("main");
        fs::write(nested.join("child.circom"), "template Child() {}").expect("child");
        fs::write(root.join("README.md"), "not a circuit").expect("readme");

        let targets = scan_project(root).expect("scan succeeds");

        assert_eq!(targets.len(), 2);
        assert!(targets
            .iter()
            .any(|target| target.path.ends_with("main.circom")));
        assert!(targets
            .iter()
            .any(|target| target.path.ends_with("circuits/nested/child.circom")));
    }

    #[test]
    fn ignores_common_generated_directories() {
        let temp = tempdir().expect("tempdir");
        let root = temp.path();

        fs::create_dir_all(root.join("target")).expect("target dir");
        fs::write(
            root.join("target/generated.circom"),
            "template Generated() {}",
        )
        .expect("generated");

        let targets = scan_project(root).expect("scan succeeds");

        assert!(targets.is_empty());
    }
}
