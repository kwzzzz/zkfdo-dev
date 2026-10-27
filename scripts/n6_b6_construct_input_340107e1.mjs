#!/usr/bin/env node
// Model an active first MACI tally batch with seed-derived voter test keys.
// Run the locked Poseidon data and Python calculation inside networkless Docker.

import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const script = fileURLToPath(import.meta.url);
const scripts = dirname(script);
const root = dirname(scripts);
const revision = "340107e1";
const lock = JSON.parse(readFileSync(join(scripts, `n6_b6_construct_input_${revision}.lock.json`), "utf8"));

if (!existsSync("/.dockerenv")) throw new Error("Docker execution required");

function digest(file) {
  return createHash("sha256").update(readFileSync(file)).digest("hex");
}

for (const label of ["poseidon_constants", "vota_circom_constants"]) {
  if (digest(join(root, lock[`${label}_path`])) !== lock[`${label}_sha256`]) {
    throw new Error(`locked ${label} changed`);
  }
}
const packageJson = JSON.parse(readFileSync(join(root, lock.vota_circomlib_package_path), "utf8"));
if (packageJson.version !== lock.vota_circomlib_version) {
  throw new Error("locked circomlib package version changed");
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
