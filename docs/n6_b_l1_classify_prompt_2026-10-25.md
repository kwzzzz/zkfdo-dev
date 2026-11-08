Task (approved by repo owner miiz): create scripts/n6_b_l1_classify.py in this repository. Work only by reading source and A results and writing that one script (plus a short record file, see end).

HARD RULES (violating any is a failure):
- Do NOT open, read, list, grep or print anything belonging to B judging results: nothing under runs/n6-b6g-2026-10-23.noindex/, runs/n6-b6h-2026-10-24.noindex/, runs/n6-b6e-*, runs/n6-b6f-*, /Volumes/zkfdo-jcache/n6-b6g-batch1x, /Volumes/zkfdo-jcache/n6-b6h*, no B candidates, witnesses, engine stdout, result verdict fields. Do not run the new script on B data.
- Do not touch running processes (a judging runner is running), do not run builds, cargo, J engine, Docker, zkFuzz, installs. No git write operations. Do not modify any existing file.
- Do not run recursive listings (ls -R, find, du) under runs/.
- No AI attribution anywhere in files.

Spec: docs/n5_amendment_b_judging_2026-10-17.md section 4 item 1 and 2. For each L1 result (verdict reachable; check src/candidate_review/lifting/mod.rs ClassResult and how v2.2 / v1 engines write per-request results — see scripts/n6_b6h_j_runner.py, scripts/n6_b6g_j_runner.py, scripts/n6_b6h_result_gate.py for the result file layout and which verdict strings mean L1) classify:
- public input: public_inputs_equal true -> "private_reach" (사설 도달); false -> "public_input_change_reach"; missing/None -> "unknown" (treated like public_input_change_reach).
- public output: alternative witness public outputs differ from honest -> "output_change"; same -> "internal_only"; missing -> "unknown". Verify from Rust source whether outputs_differing counts only public outputs of main; if it counts something else, say so in the record and implement the closest faithful rule, flagging it.
- entrypoint: look up revision_id/main in the classification table runs/n6-b5-2026-10-17.noindex/batch1-prep.noindex/entrypoint-classification.json (verify SHA-256 126745ca432de49f4ee7bdf901d8f4eb81082b96eb11b4b623c29f61057bd660 before use, refuse on mismatch) -> "deployed" / "harness"; not found -> harness.
- real_vulnerability_candidate = private_reach AND output_change AND deployed. Others are "constraint_defect_confirmed".
Output: JSON with per-request id/revision/class fields only and counts. NEVER output values (inputs, witnesses, signal values, candidate contents). Take result paths/index and required SHA-256 arguments explicitly; refuse on mismatch.
Test: run it only on A calibration results under runs/n6-b6-2026-10-18.noindex/a-calibration.noindex/ (A may be opened; for A use a mode where the entrypoint table lookup falls back to harness or accepts a provided A table; document it). Report the A counts. Then run python3 -m py_compile on the script.
Finally write docs/n6_b_l1_classify_2026-10-25.md (Korean, short): what the script does, field mapping with source file:line evidence, A test command and counts, script SHA-256 (shasum -a 256). Print a short summary at the end.
