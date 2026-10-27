#!/usr/bin/env node
// Model an active Panther renewal with fresh test keys, KYC signature and zone path.
// Run the locked circomlibjs EdDSA helper inside networkless Docker.

import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const script = fileURLToPath(import.meta.url);
const scripts = dirname(script);
const root = dirname(scripts);
const revision = "4c221df7";
const lock = JSON.parse(readFileSync(join(scripts, `n6_b6_construct_input_${revision}.lock.json`), "utf8"));

if (!existsSync("/.dockerenv")) throw new Error("Docker execution required");

function digest(file) {
  return createHash("sha256").update(readFileSync(file)).digest("hex");
}

for (const label of ["test_source", "poseidon_constants", "eddsa_source", "panther_circom_constants"]) {
  if (digest(join(root, lock[`${label}_path`])) !== lock[`${label}_sha256`]) {
    throw new Error(`locked ${label} changed`);
  }
}
for (const [pathKey, versionKey] of [
  ["panther_circomlib_package_path", "panther_circomlib_version"],
  ["eddsa_package_path", "eddsa_package_version"],
]) {
  const packageJson = JSON.parse(readFileSync(join(root, lock[pathKey]), "utf8"));
  if (packageJson.version !== lock[versionKey]) throw new Error(`locked ${pathKey} version changed`);
}

let output;
let seed = `n6-b6-${revision}-2026-10-18`;
for (let i = 2; i < process.argv.length; i += 2) {
  const key = process.argv[i];
  const value = process.argv[i + 1];
  if (value === undefined) throw new Error(`missing value for ${key}`);
  if (key === "--output") output = value;
  else if (key === "--seed") seed = value;
  else throw new Error(`unknown option ${key}`);
}
if (!output || existsSync(output)) throw new Error("new output path required");

const child = spawnSync("python3", [join(scripts, `n6_b6_construct_input_${revision}.py`),
  "--seed", seed, "--output", output], { cwd: root, encoding: "utf8", maxBuffer: 1024 * 1024 });
if (child.error || child.status !== 0) {
  throw new Error(`locked Python generator failed: ${child.error?.code ?? child.status}`);
}
const actual = digest(output);
if (child.stdout.trim() !== actual) throw new Error("generator output hash mismatch");
process.stdout.write(`${actual}\n`);
