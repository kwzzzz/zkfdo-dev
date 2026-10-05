"""Pure metadata curation for C-03; no repository access or preparation calls.

Callers supply CSV text and selected README/topic/CSV sentences with provenance.
Repository role is a reported role, not proof of deployment or eligibility.
Fork ancestry remains separate from identity and from direct exposure.
"""

import csv
import io
import re
from urllib.parse import urlsplit


_SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")
_REPO_PART = re.compile(r"[A-Za-z0-9_.-]+\Z")
_SHEET_FIELDS = {
    "저장소 URL": "repository_url_declared",
    "회로 폴더 위치": "circuit_folders_declared",
    "실제 쓰이는 근거 (있으면 링크)": "usage_evidence_declared",
    "circom 버전 (pragma 한 줄만 보면 됨)": "circom_version_declared",
    "찾은 곳": "discovery_source_declared",
}


def normalize_github_repo(value):
    """Normalize spelling only; do not infer redirects, parents, or subpaths."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("missing_github_repository")
    value = value.strip()
    if "://" in value:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"}
                or parsed.netloc.lower() not in {"github.com", "www.github.com"}
                or parsed.query or parsed.fragment):
            raise ValueError("not_a_github_repository_url")
        value = parsed.path.strip("/")
    else:
        value = value.strip("/")
    if value.endswith(".git"):
        value = value[:-4]
    parts = value.split("/")
    if (len(parts) != 2 or any(not _REPO_PART.fullmatch(p) for p in parts)
            or any(p in {".", ".."} for p in parts)):
        raise ValueError("expected_owner_and_repository_only")
    return value.casefold()


def _provenance(source_path, sha256):
    if not isinstance(source_path, str) or not source_path.strip():
        raise ValueError("missing_source_path")
    if not isinstance(sha256, str) or not _SHA256.fullmatch(sha256):
        raise ValueError("invalid_source_sha256")
    return {"path": source_path, "sha256": sha256.lower()}


def parse_team_sheet(text, source_path, sha256):
    """Parse numbered vertical blocks, retaining missing fields and duplicates.

    The unnumbered example block is excluded explicitly. CSV row positions are
    physical ending line numbers from csv.reader, not inferred collection dates.
    """
    source = _provenance(source_path, sha256)
    reader = csv.reader(io.StringIO(text.lstrip("\ufeff")))
    blocks = []
    current = None
    seen_items = set()
    for cells in reader:
        if not cells or not any(cell.strip() for cell in cells):
            continue
        if len(cells) != 2:
            raise ValueError(f"expected_two_csv_columns_at_line_{reader.line_num}")
        label, value = (cell.strip() for cell in cells)
        if label == "항목":
            if current is not None:
                blocks.append(current)
            current = None
            if value.isdecimal():
                number = int(value)
                if number in seen_items:
                    raise ValueError("duplicate_sheet_item_number")
                seen_items.add(number)
                current = {"sheet_item": number, "source_line": reader.line_num,
                           "field_source_lines": {}}
            continue
        if current is None:
            continue
        if label not in _SHEET_FIELDS:
            raise ValueError(f"unknown_sheet_field_at_line_{reader.line_num}")
        key = _SHEET_FIELDS[label]
        if key in current:
            raise ValueError(f"duplicate_sheet_field_{key}")
        current[key] = value or None
        current["field_source_lines"][key] = reader.line_num
        current["source_end_line"] = reader.line_num
    if current is not None:
        blocks.append(current)
    seen_repositories = {}
    for row in blocks:
        row["missing_fields"] = [key for key in _SHEET_FIELDS.values() if not row.get(key)]
        for key in _SHEET_FIELDS.values():
            row.setdefault(key, None)
        url = row["repository_url_declared"]
        row["repository_key"] = normalize_github_repo(url) if url else None
        row["collection_time_declared"] = None
        row["declarations_verified"] = False
        row["source"] = dict(source)
        key = row["repository_key"]
        row["duplicate_of_sheet_item"] = seen_repositories.get(key) if key else None
        if key:
            seen_repositories.setdefault(key, row["sheet_item"])
    return blocks


def _repo_name(value):
    if isinstance(value, dict):
        value = value.get("full_name") or value.get("html_url") or value.get("url")
    return normalize_github_repo(value) if value else None


def identity_links(metadata):
    """Keep verified name redirects, declared spellings, and fork ancestry apart."""
    declared = _repo_name(metadata.get("full_name") or metadata.get("url"))
    canonical = _repo_name(metadata.get("canonical_full_name"))
    resolution = metadata.get("canonical_resolution")
    verified = resolution in {"github_metadata", "github_api", "verified_redirect"}
    spellings = {_repo_name(name) for name in metadata.get("source_spellings", [])}
    spellings.discard(None)
    aliases = {declared} if declared else set()
    if verified and canonical:
        aliases.add(canonical)
        aliases.update(spellings)
    lineage = metadata.get("lineage") or {}
    return {
        "declared_repository": declared,
        "canonical_repository_declared": canonical,
        "canonical_resolution": resolution or "unknown",
        "identity_aliases": sorted(aliases),
        "unverified_spellings": sorted((spellings | ({canonical} if canonical else set())) - aliases),
        "fork_declared": lineage.get("fork"),
        "fork_parent": _repo_name(lineage.get("parent")),
        "fork_source": _repo_name(lineage.get("source")),
        "lineage_completeness": "reported" if lineage.get("fork") is not None else "unknown",
    }


def sheet_overlap(sheet_rows, repositories):
    """Compare all sheet rows; duplicate or ambiguous rows do not vanish."""
    identities = [(row, identity_links(row)) for row in repositories]
    results = []
    for row in sheet_rows:
        key = row["repository_key"]
        matched = [(metadata, links) for metadata, links in identities
                   if key and key in links["identity_aliases"]]
        parent_matches = [links["declared_repository"] for _, links in identities
                          if key and key in {links["fork_parent"], links["fork_source"]}]
        results.append({
            "sheet_item": row["sheet_item"], "repository_key": key,
            "status": "matched" if len(matched) == 1 else "ambiguous" if matched else "not_listed",
            "matches": [{"full_name": metadata.get("full_name"),
                         "canonical_full_name": metadata.get("canonical_full_name"),
                         "source_memberships": list(metadata.get("source_memberships", [])),
                         "github_ranks": list(metadata.get("github_ranks", [])),
                         "metadata_path": metadata.get("metadata_path"),
                         "started_at": metadata.get("started_at"),
                         "finished_at": metadata.get("finished_at")}
                        for metadata, _ in matched],
            "listed_forks_of_sheet_repository": sorted(set(parent_matches)),
        })
    return {"sheet_row_count": len(results),
            "matched_count": sum(row["status"] == "matched" for row in results),
            "ambiguous_count": sum(row["status"] == "ambiguous" for row in results),
            "not_listed_count": sum(row["status"] == "not_listed" for row in results),
            "rows": results}


def compare_exposure(metadata, catalog_projects, development_projects=()):
    """Report direct, verified-alias, and ancestry list matches independently.

    Unknown alias/family history prevents a never-exposed claim. Shared owner
    names are not identity evidence. Catalog labels describe lists, not findings.
    """
    links = identity_links(metadata)
    aliases = set(links["identity_aliases"])
    ancestors = {links["fork_parent"], links["fork_source"]} - {None}
    known = []
    development = []
    for kind, records, output in (("catalog", catalog_projects, known),
                                  ("development", development_projects, development)):
        for record in records:
            name = _repo_name(record)
            if not name:
                continue
            relation = ("direct" if name == links["declared_repository"] else
                        "verified_identity_alias" if name in aliases else
                        "fork_ancestry" if name in ancestors else None)
            if relation:
                output.append({"repository": name, "relation": relation, "list": kind,
                               "source_memberships": list(record.get("source_memberships", []))
                               if isinstance(record, dict) else []})
    return {"identity": links, "catalog_matches": known, "development_matches": development,
            "known_bug_listed_direct_or_alias": any(m["relation"] != "fork_ancestry" for m in known),
            "development_used_direct_or_alias": any(m["relation"] != "fork_ancestry" for m in development),
            "fork_family_exposure_match": any(m["relation"] == "fork_ancestry" for m in known + development),
            "independent_family_status": "unknown", "never_exposed_claim": False}


_ROLE_RULES = {
    "production": (
        r"\b(?:deployed|running|live)\b.{0,60}\b(?:mainnet|production)\b",
        r"\b(?:used by|used in|powers|powering)\b.{0,100}\b(?:protocol|application|service|platform|game)\b",
        r"\b(?:official|production)\b.{0,60}\b(?:protocol|application|service)\b",
        r"(?:프로토콜|서비스|시스템).{0,45}(?:공식|사용|검증용)",
        r"(?:공식|실사용).{0,45}(?:프로토콜|서비스|시스템)",
    ),
    "library": (r"\blibrar(?:y|ies)\b", r"라이브러리"),
    "tool_benchmark": (
        r"\b(?:compiler|fuzzer|analyzer|benchmark(?:ing)?|toolkit|toolchain)\b",
        r"\b(?:a|an|open.source)\s+(?:\w+\s+){0,3}tool\b", r"(?:벤치마크|컴파일러|오픈소스.{0,15}툴)",
    ),
    "education_example": (
        r"\b(?:tutorial|educational|proof.of.concept|learning project|demo(?:nstration)? project)\b",
        r"\b(?:this|an?)\s+(?:repository|project)?\s*(?:is\s+)?(?:an?\s+)?example\b",
        r"(?:교육용|학습용|예제|데모|Demo Day)",
    ),
}
_UNCERTAIN_PRODUCTION = re.compile(
    r"\b(?:not|never|not yet)\s+(?:been\s+)?deployed\b|\b(?:can|could|may|will)\s+be\s+(?:used|deployed)\b"
    r"|배포.{0,12}(?:안|않|미정)|(?:미배포|계획|예정)", re.I)
_ROLE_NEGATIONS = {
    "library": r"\bnot\s+(?:a\s+)?library\b|라이브러리.{0,8}(?:아님|아니)",
    "tool_benchmark": r"\bnot\s+(?:a\s+)?(?:benchmark|compiler|fuzzer|tool)\b",
    "education_example": r"\bnot\s+(?:an?\s+)?(?:tutorial|educational|example|demo)\b",
}


def make_evidence(text, kind, source_path, source_sha256, line=None):
    """Attach provenance to one selected metadata sentence, without reading it."""
    _provenance(source_path, source_sha256)
    if kind not in {"readme", "topics", "csv", "description"}:
        raise ValueError("unsupported_metadata_evidence_kind")
    if not isinstance(text, str) or not text.strip() or "\n" in text or "\r" in text:
        raise ValueError("expected_one_metadata_sentence")
    if line is not None and (not isinstance(line, int) or isinstance(line, bool) or line < 1):
        raise ValueError("invalid_source_line")
    return {"kind": kind, "text": text.strip(), "source_path": source_path,
            "source_sha256": source_sha256.lower(), "line": line}


def classify_repository(evidence):
    """Conservatively classify selected repository-role statements.

    Conflicting classes and topic-only hints stay unknown. A production role
    remains a metadata claim: this function never certifies actual deployment.
    CSV claims are retained with their lower evidence level.
    """
    checked = [make_evidence(item["text"], item["kind"], item["source_path"],
                             item["source_sha256"], item.get("line")) for item in evidence]
    matches = []
    for item in checked:
        if item["kind"] == "topics":
            continue
        for category, rules in _ROLE_RULES.items():
            if category == "production" and _UNCERTAIN_PRODUCTION.search(item["text"]):
                continue
            if re.search(_ROLE_NEGATIONS.get(category, r"(?!)"), item["text"], re.I):
                continue
            if any(re.search(rule, item["text"], re.I) for rule in rules):
                matches.append({"category": category, "evidence": item})
    categories = sorted({match["category"] for match in matches})
    classification = categories[0] if len(categories) == 1 else "unknown"
    reason = ("single_reported_role" if len(categories) == 1 else
              "conflicting_reported_roles" if categories else "insufficient_role_evidence")
    kinds = {match["evidence"]["kind"] for match in matches}
    return {"classification": classification, "status": "reported_metadata_only",
            "evidence_level": "csv_claim_only" if kinds == {"csv"} else
            "repository_statement" if kinds else "insufficient",
            "matched_categories": categories, "reason": reason,
            "evidence": checked, "matches": matches, "production_use_verified": False}
