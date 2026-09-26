"""Build the metadata-only candidate list for T6 and injection evaluation (B).

Inputs are raw GitHub search responses under runs/b-candidates-2026-09-27/raw/ (ignored).
No repository is cloned and no file content is read: only repository names from search
results and repository metadata from the GitHub API are used.

Outputs (tracked): candidates.json with every candidate, its metadata and the filter verdict.
The T6/B split is computed only with --finalize, after the teammate recommendation deadline,
because the order depends on the hash of the complete candidate list.
"""

import hashlib
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
RAW = ROOT / "runs" / "b-candidates-2026-09-27" / "raw"
META = ROOT / "runs" / "b-candidates-2026-09-27" / "metadata"
OUT = pathlib.Path(__file__).resolve().parent / "candidates.json"
TEAM = pathlib.Path(__file__).resolve().parent / "team_recommendations.json"
EXCLUSIONS = ROOT / "datasets" / "exclusions.injection-eval.draft.json"

MIN_STARS = 10
PUSHED_AFTER = "2023-01-01"
T6_FRACTION_DENOMINATOR = 3  # first 1/3 of the ordered list goes to T6, the rest to B


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def search_sources():
    names = {}
    for path in sorted(RAW.glob("page-*.json")):
        for item in json.loads(path.read_text())["items"]:
            names.setdefault(item["full_name"], set()).add("repository-search")
    for path in sorted(list(RAW.glob("code-page-*.json")) + list((RAW / "sized").glob("*.json"))):
        for item in json.loads(path.read_text()).get("items", []):
            names.setdefault(item["repository"]["full_name"], set()).add("code-search")
    if TEAM.exists():
        # A list of {"full_name": "org/repo", ...}; only the repository name is used here.
        for item in json.loads(TEAM.read_text()):
            names.setdefault(item["full_name"], set()).add("team-recommendation")
    return names


def cache_path(full_name):
    return META / (full_name.replace("/", "__") + ".json")


def prefetch(names, batch=100):
    """Fill the metadata cache with GraphQL, 100 repositories per request.

    The cached fields use the REST names read by metadata(); a repository that cannot be
    resolved is cached as an error entry, exactly like a failed REST lookup.
    """
    META.mkdir(parents=True, exist_ok=True)
    missing = [name for name in names if not cache_path(name).exists()]
    for start in range(0, len(missing), batch):
        chunk = missing[start:start + batch]
        fields = ("nameWithOwner stargazerCount pushedAt isFork isArchived "
                  "defaultBranchRef { name } primaryLanguage { name }")
        query = "query {" + " ".join(
            f'r{i}: repository(owner: "{name.split("/")[0]}", name: "{name.split("/")[1]}") {{ {fields} }}'
            for i, name in enumerate(chunk)) + "}"
        result = subprocess.run(["gh", "api", "graphql", "-f", f"query={query}"],
                                capture_output=True, text=True)
        try:
            data = json.loads(result.stdout).get("data") or {}
        except json.JSONDecodeError:
            raise SystemExit(f"GraphQL batch failed: {result.stderr[:300]}")
        for i, name in enumerate(chunk):
            repo = data.get(f"r{i}")
            if repo is None:
                cache_path(name).write_text(json.dumps({"error": "repository not resolvable via GraphQL"}))
                continue
            cache_path(name).write_text(json.dumps({
                "full_name": repo["nameWithOwner"],
                "stargazers_count": repo["stargazerCount"],
                "pushed_at": repo["pushedAt"] or "",
                "fork": repo["isFork"],
                "archived": repo["isArchived"],
                "default_branch": (repo["defaultBranchRef"] or {}).get("name"),
                "language": (repo["primaryLanguage"] or {}).get("name"),
                "source": "graphql",
            }))
        time.sleep(1)


def metadata(full_name):
    META.mkdir(parents=True, exist_ok=True)
    cache = cache_path(full_name)
    if not cache.exists():
        result = subprocess.run(["gh", "api", f"repos/{full_name}"], capture_output=True, text=True)
        time.sleep(0.2)
        cache.write_text(result.stdout if result.returncode == 0 else json.dumps({"error": result.stderr[:300]}))
    return json.loads(cache.read_text())


def main():
    finalize = "--finalize" in sys.argv[1:]
    snapshot = json.loads(EXCLUSIONS.read_text())
    excluded = {name.lower() for group in snapshot["projects"].values() for name in group}
    sources = search_sources()
    prefetch(sorted(sources, key=str.lower))
    rows = []
    for name in sorted(sources, key=str.lower):
        meta = metadata(name)
        row = {"full_name": meta.get("full_name", name), "found_by": sorted(sources[name])}
        if "error" in meta:
            row.update(verdict="unavailable", reason=meta["error"].strip()[:120])
            rows.append(row)
            continue
        row.update(
            stars=meta["stargazers_count"],
            pushed_at=meta["pushed_at"],
            fork=meta["fork"],
            archived=meta["archived"],
            default_branch=meta["default_branch"],
            primary_language=meta["language"],
        )
        if row["full_name"].lower() in excluded or name.lower() in excluded:
            row.update(verdict="excluded", reason="in injection-evaluation exclusion snapshot")
        elif meta["fork"]:
            row.update(verdict="excluded", reason="fork")
        elif meta["archived"]:
            row.update(verdict="excluded", reason="archived")
        elif meta["stargazers_count"] < MIN_STARS:
            row.update(verdict="excluded", reason=f"fewer than {MIN_STARS} stars")
        elif meta["pushed_at"] < PUSHED_AFTER:
            row.update(verdict="excluded", reason=f"no push since {PUSHED_AFTER}")
        else:
            row.update(verdict="candidate")
        rows.append(row)

    candidates = [row["full_name"] for row in rows if row["verdict"] == "candidate"]
    list_digest = sha256("\n".join(candidates).encode())
    t6_count = len(candidates) // T6_FRACTION_DENOMINATOR
    if finalize:
        # Deterministic, choice-free order: hash of (list digest, repository name).
        ordered = sorted(candidates, key=lambda name: sha256(f"{list_digest}\n{name}".encode()))
        position = {name: index for index, name in enumerate(ordered)}
        for row in rows:
            if row["verdict"] == "candidate":
                index = position[row["full_name"]]
                row.update(order=index + 1, pool="T6" if index < t6_count else "B")

    OUT.write_text(json.dumps({
        "schema_version": 1,
        "status": ("final" if finalize else "provisional: split not computed until the recommendation deadline")
        + "; metadata only; no repository was cloned or opened",
        "criteria": {"min_stars": MIN_STARS, "pushed_after": PUSHED_AFTER, "fork": False, "archived": False},
        "exclusion_snapshot": {"path": str(EXCLUSIONS.relative_to(ROOT)), "sha256": sha256(EXCLUSIONS.read_bytes())},
        "candidate_list_sha256": list_digest,
        "split": {"order": "ascending sha256(candidate_list_sha256 + newline + full_name)", "t6": f"first floor(n/{T6_FRACTION_DENOMINATOR})", "b": "remaining"},
        "counts": {"found": len(rows), "candidates": len(candidates)}
        | ({"t6_pool": t6_count, "b_pool": len(candidates) - t6_count} if finalize else {}),
        "repositories": rows,
    }, indent=2) + "\n")
    print(json.dumps(json.loads(OUT.read_text())["counts"]))


if __name__ == "__main__":
    sys.exit(main())
