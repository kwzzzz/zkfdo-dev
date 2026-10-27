#!/usr/bin/env node
// Model an active iden3 credential query with seed-derived test identities.
// Run the locked Poseidon data and Python calculation inside networkless Docker.

import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const script = fileURLToPath(import.meta.url);
const scripts = dirname(script);
const root = dirname(scripts);
const revision = "b5b5cf5d";
const lock = JSON.parse(readFileSync(join(scripts, `n6_b6_construct_input_${revision}.lock.json`), "utf8"));

if (!existsSync("/.dockerenv")) throw new Error("Docker execution required");

function digest(file) {
  return createHash("sha256").update(readFileSync(file)).digest("hex");
}

const constants = join(root, lock.poseidon_constants_path);
if (digest(constants) !== lock.poseidon_constants_sha256) {
  throw new Error("locked Poseidon constants changed");
}
const packageJson = JSON.parse(readFileSync(join(root, lock.package_json_path), "utf8"));
if (packageJson.version !== lock.package_version) {
  throw new Error("locked circomlibjs package version changed");
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
