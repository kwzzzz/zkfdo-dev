#!/usr/bin/env python3
"""Record purpose-based metadata review before C-03 preparation begins.

The first census and transport failures remain immutable. Decisions below use
introductory repository statements, not build results. Production denotes a
reported application/protocol purpose and never certifies deployment or every
subdirectory. Unclear, mixed, or merely functional descriptions remain unknown.
"""

import copy
import json
from pathlib import Path
import re

import c03_curation as curation
import collect_c03_corpus as collection


# Role, source-evidence index, and scope of the manual interpretation.
# No row is selected or removed by this table; unlisted rows retain their status.
DECISIONS = {
    "0xPolygon/zkevm-proverjs": ("tool_benchmark", 0, "proof generator reference implementation"),
    "alejandro99so/eerc-backend-converter": ("production", 0, "private token application/system purpose"),
    "anon-aadhaar/anon-aadhaar": ("production", 0, "identity protocol purpose"),
    "aptos-labs/keyless-zk-proofs": ("production", 0, "Aptos Keyless protocol component purpose"),
    "Arianee/arianee-sdk": ("library", 0, "SDK collection of reusable ecosystem packages"),
    "ArmanKolozyan/CCC-Check": ("tool_benchmark", 0, "analysis tool purpose"),
    "ava-labs/EncryptedERC": ("production", 0, "confidential token protocol purpose"),
    "celo-org/self": ("production", 0, "identity wallet application purpose"),
    "dangduongminhnhat/Circheck": ("tool_benchmark", 0, "analysis research tool and evaluation framework"),
    "DoraFactory/Vota-Circuits": ("production", 0, "named voting protocol component purpose"),
    "EkuboProtocol/privacy-pools": ("production", 0, "privacy pool protocol implementation purpose"),
    "erhant/circom101": ("education_example", 0, "explicit circuit and concept explanation purpose"),
    "Galactica-corp/galactica-monorepo": ("production", 0, "network certificate and wallet application purpose; examples remain path-tagged"),
    "Galxe/identity-protocol": ("production", 0, "named identity protocol monorepo"),
    "Hinkal-Protocol/Hinkal-Contracts-Circuits": ("production", 0, "named DeFi protocol component purpose"),
    "holyaustin/Filecoin-Forge": ("education_example", 1, "explicit tutorials, case studies and guides"),
    "invisibook-lab/invisibook": ("production", 0, "order book application purpose"),
    "jose-compu/opencircom": ("library", 0, "explicit reusable circuit template collection"),
    "Miny-Labs/benzo": ("production", 0, "private token balance application purpose"),
    "pantherfoundation/panther-core": ("production", 0, "named protocol implementation purpose"),
    "privacy-ethereum/maci": ("production", 0, "on-chain voting protocol purpose"),
    "proofcarryingdata/zupass": ("production", 1, "proof-carrying data application purpose"),
    "rarimo/passport-zk-circuits": ("production", 0, "named biometric-passport voting system component purpose"),
    "selfxyz/self": ("production", 0, "identity wallet application purpose"),
    "semaphore-protocol/semaphore": ("production", 1, "named protocol circuit logic purpose"),
    "stealthdrop/stealthdrop": ("production", 0, "named application site and airdrop utility purpose"),
    "stellar/soroban-examples": ("education_example", 0, "explicit example contracts"),
    "tanctl/zylith-old": ("production", 0, "shielded market maker protocol purpose"),
    "tangle-network/protocol-solidity": ("production", 0, "named bridging and shielded pool protocol contracts"),
    "vacp2p/research": ("education_example", 1, "explicit experimental proof-of-concept repository"),
    "Zellic/zkerc20": ("production", 1, "privacy-preserving transfer/bridge application purpose"),
    "zkemail/email-tx-builder": ("library", 1, "SDK for email-authorized application transactions"),
    "zkemail/zk-email-verify": ("production", 0, "email verification application purpose"),
    "zkemail/zk-regex": ("tool_benchmark", 1, "regex-to-circuit compiler purpose"),
    "zkp2p/zkp2p-v1-monorepo": ("production", 0, "named fiat-to-crypto onramp application purpose"),
}

# Exact root README selectors recover purpose statements omitted by the initial
# automatic introduction filter. Text is copied only from these metadata lines.
README_DECISIONS = {
    "iden3/circomlib": ("library", "This repository contains a library of circuit templates.",
                        "explicit circuit template library"),
    "zksecurity/zkbugs": ("tool_benchmark", "This repo includes 140 vulnerabilities in the following DSLs:",
                         "benchmark/reproduction dataset repository purpose; no candidate reproduction"),
    "FlynnSC/zk-hunt": ("education_example", "ZK Hunt is a prototype for an onchain game", "explicit game prototype"),
    "risc0/risc0": ("tool_benchmark", "RISC Zero is a zero-knowledge verifiable general computing platform",
                    "ZK computing platform/tool purpose"),
    "SURUJ404/Zero-proof": ("tool_benchmark", "A zero-knowledge verifiable general computing platform based on",
                           "computing platform/tool purpose inherited in repository description"),
    "tokamak-network/DEPRECATED-zvm": ("tool_benchmark", "Zero Knowledge based Ethereum Virtual Machine in Circom language",
                                     "virtual-machine implementation/tool purpose"),
}


def paragraph_sentence(path, line, kind="readme"):
    raw = path.read_bytes()
    lines = raw.decode("utf-8", errors="replace").splitlines()
    selected = []
    for value in lines[line - 1:]:
        if not value.strip() or (selected and value.lstrip().startswith(("#", "```", "~~~", "- ", "* ", "</"))):
            break
        selected.append(value.strip())
        if len(" ".join(selected)) > 2000:
            break
    text = " ".join(selected).strip("| ")
    if text.startswith("- "):
        text = text[2:]
    text = re.split(r"(?<=[.!?])\s+", text)[0]
    return curation.make_evidence(text, kind, collection.rel(path), collection.digest(raw), line)


def selected_evidence(row, index):
    evidence = row["classification"]["evidence"][index]
    if evidence["kind"] == "readme" and evidence.get("line"):
        path = collection.ROOT / evidence["source_path"]
        if collection.digest(path.read_bytes()) != evidence["source_sha256"]:
            raise ValueError("purpose_source_hash_changed")
        # Preserve a second sentence selected from the same source line instead
        # of replacing it with that line's first sentence.
        first = paragraph_sentence(path, evidence["line"])
        if evidence["text"] in first["text"] or first["text"].startswith(evidence["text"]):
            return first
    return copy.deepcopy(evidence)


def readme_evidence(row, prefix):
    clone = collection.ROOT / row["clone_path"]
    for path in sorted(clone.iterdir()):
        if path.is_file() and not path.is_symlink() and path.name.lower().startswith("readme"):
            for line, value in enumerate(path.read_text(errors="replace").splitlines(), 1):
                if prefix in value:
                    return paragraph_sentence(path, line)
    raise ValueError("reviewed_purpose_statement_missing: " + row["full_name"])


def apply_review(row, role, evidence, reason):
    if role not in {"production", "library", "tool_benchmark", "education_example", "unknown"}:
        raise ValueError("invalid_reviewed_role")
    prior = row["classification"]
    row["classification"] = {
        "classification": role, "status": "metadata_purpose_reviewed_before_preparation",
        "evidence_level": "repository_statement" if evidence["kind"] != "csv" else "csv_claim_only",
        "matched_categories": [role] if role != "unknown" else [], "evidence": [evidence], "reason": reason,
        "production_use_verified": False,
        "production_label_scope": "reported_application_or_protocol_purpose; deployment_and_subdirectory_roles_not_certified",
        "topics_declared": prior.get("topics_declared", []), "topics_source": prior.get("topics_source"),
        "prior_automatic_role": prior["classification"], "preparation_results_accessed": False}


def main():
    base = collection.ROOT / "runs/c03-corpus-2026-10-02"
    census_path = base / "census.json"
    original = json.loads(census_path.read_text())
    retries_path = base / "collection-retries-v2.json"
    retries = json.loads(retries_path.read_text())
    census = copy.deepcopy(original)
    retry_map = {row["full_name"]: row for row in retries["repositories"]}
    decisions = []
    catalog = json.loads((collection.ROOT / "runs/c02-corpus-2026-10-02/catalog_sources.json").read_text())
    for index, original_row in enumerate(census["repositories"]):
        name = original_row["full_name"]
        row = copy.deepcopy(retry_map.get(name, original_row))
        if name in retry_map:
            row["prior_collection_attempt"] = collection.ref(collection.ROOT / original_row["metadata_path"])
            row["collection_retry_reason"] = "same_pinned_SHA_public_transport_after_partial_local_clone_failure"
            row["manual_collection_transport_interventions"] = 1
        else:
            row["manual_collection_transport_interventions"] = 0
        if name in DECISIONS:
            role, evidence_index, reason = DECISIONS[name]
            evidence = selected_evidence(row, evidence_index)
            apply_review(row, role, evidence, reason)
        elif name in README_DECISIONS:
            role, prefix, reason = README_DECISIONS[name]
            evidence = readme_evidence(row, prefix)
            apply_review(row, role, evidence, reason)
        else:
            row["classification"]["review_status"] = "automatic_purpose_evidence_checked; ambiguous_or_insufficient_stays_unknown"
        row["prior_exposure_list_matches_c03"] = curation.compare_exposure(
            row, catalog["development_exposure"]["prior_exposure_metadata"])["catalog_matches"]
        row["metadata_reviewed_at"] = collection.now()
        row["supersedes"] = collection.ref(collection.ROOT / row["metadata_path"])
        target = collection.ROOT / row["metadata_path"]
        target = target.with_name("curation.v2.json")
        row["metadata_path"] = collection.rel(target)
        collection.write_new(target, row)
        census["repositories"][index] = row
        decisions.append({"full_name": name, "classification": row["classification"],
                          "metadata": collection.ref(target), "setup_or_preparation_observed": False})
    census["schema_version"] = 2
    census["supersedes"] = collection.ref(census_path)
    census["transport_retries"] = collection.ref(retries_path)
    census["manual_collection_transport_retry_count"] = len(retry_map)
    census["curation_reviewed_at"] = collection.now()
    census["classification_label_scope"] = "metadata_reported_repository_purpose_not_verified_production_deployment"
    review_path = base / "classification-review.v2.json"
    collection.write_new(review_path, {"schema_version": 1, "recorded_at": collection.now(),
        "procedure_sha256": collection.PROCEDURE_SHA, "prior_census": collection.ref(census_path),
        "review_code": collection.ref(Path(__file__)), "decision_count": len(decisions),
        "setup_started": False, "compilation_started": False, "decisions": decisions})
    census["classification_review"] = collection.ref(review_path)
    target = base / "census.v2.json"
    collection.write_new(target, census)
    collection.write_new(base / "curation-lock.v2.json", {"schema_version": 2,
        "frozen_at": collection.now(), "procedure_sha256": collection.PROCEDURE_SHA,
        "supersedes": collection.ref(base / "curation-lock.json"), "census": collection.ref(target),
        "review": collection.ref(review_path), "collector": collection.ref(Path(collection.__file__)),
        "review_code": collection.ref(Path(__file__)), "repository_count": len(census["repositories"]),
        "setup_started": False, "compilation_started": False})
    print(json.dumps({"census": collection.rel(target), "repositories": len(census["repositories"]),
                      "transport_retries": len(retry_map), "frozen": True}))


if __name__ == "__main__":
    main()
