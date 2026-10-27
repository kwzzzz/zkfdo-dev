#!/usr/bin/env node
// Extend the recorded LIQ_ADD vector with one active token1 note and its change note.
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const project = path.resolve(here, '../runs/n6-b2-2026-10-09.noindex/pragma-77e0f2db173d0c1812de503a/project/circuits');
const fixturePath = path.join(project, 'test/vectors/private_liquidity/add_liquidity_in_range.json');
const fixtureSha = '745a96006d1c479fa837a5b416dd95070f4f066576ec79f9bdd426a0eb2fe02d';
const packageLockSha = '6ef6186e9c0a96884bfa5bd47b495858b1d8215e868b24e18f04bce31224e427';
const packageJsonSha = '9c7e866ba70ada882020b7fd1d644a761149c50f59817f981d7bc347af1d30d7';
const seedDefault = 'n6-b6-77e0f2db-both-notes-v3';
const STARK_PRIME = (1n << 251n) + 17n * (1n << 192n) + 1n;
const ZERO_LEAF_HASH = 0x293d3e8a80f400daaaffdd5932e2bcc8814bab8f414a75dcacf87318f8b14c5n;
const DOMAIN = 0x5a594c495448n;
const NOTE_TYPE = 1n;

function sha(bytes) { return crypto.createHash('sha256').update(bytes).digest('hex'); }
function pinnedFile(filename, expected) {
  const bytes = fs.readFileSync(filename);
  if (sha(bytes) !== expected) throw new Error(`recorded source changed: ${filename}`);
  return bytes;
}
function derive(seed, label, index) {
  return 1n + BigInt(`0x${sha(`${seed}:${label}:${index}`)}`) % (1n << 120n);
}
function args() {
  let output;
  let seed = seedDefault;
  for (let i = 2; i < process.argv.length; i += 2) {
    if (process.argv[i] === '--output') output = process.argv[i + 1];
    else if (process.argv[i] === '--seed') seed = process.argv[i + 1];
    else throw new Error('usage: script.mjs --output OUTPUT.json [--seed SEED]');
  }
  if (!output || !seed) throw new Error('missing output or seed');
  return { output: path.resolve(output), seed };
}

async function main() {
  const { output, seed } = args();
  const source = JSON.parse(pinnedFile(fixturePath, fixtureSha).toString('utf8'));
  pinnedFile(path.join(project, 'package-lock.json'), packageLockSha);
  pinnedFile(path.join(project, 'node_modules/circomlibjs/package.json'), packageJsonSha);
  const require = createRequire(path.join(project, 'package.json'));
  const { buildPoseidon } = require('circomlibjs');
  const poseidon = await buildPoseidon();
  function hash(inputs) { return BigInt(poseidon.F.toObject(poseidon(inputs))); }
  function note(amount, label) {
    for (let i = 0; i < 10000; i++) {
      const secret = derive(seed, `${label}:secret`, i);
      const nullifierSeed = derive(seed, `${label}:nullifier-seed`, i);
      const nullifier = hash([DOMAIN, NOTE_TYPE, 1n, secret, nullifierSeed]);
      const commitment = hash([DOMAIN, NOTE_TYPE, 1n, amount, secret, nullifier]);
      if (nullifier > 0n && nullifier < STARK_PRIME && commitment > 0n &&
          commitment < STARK_PRIME && commitment !== ZERO_LEAF_HASH) {
        return { secret, nullifierSeed, nullifier, commitment };
      }
    }
    throw new Error(`no Stark-field ${label} note in 10000 deterministic trials`);
  }
  const values = source.input;
  if (values.tag !== String(0x4c49515f414444n) || values.token0_note_count !== '1' ||
      values.token1_note_count !== '0' || values.sqrt_price_start !== values.sqrt_ratio_lower ||
      values.token1_note_amount[0] !== '0' || values.output_commitment_token1 !== '0') {
    throw new Error('committed LIQ_ADD source shape changed');
  }
  // At the lower price boundary, amount1 required by this liquidity delta is zero.
  // A positive token1 input note is spent and returned as a positive change note.
  const amount1 = 2n;
  const input = note(amount1, 'input-token1');
  const change = note(amount1, 'change-token1');
  if (input.nullifier === BigInt(values.nullifier_token0) || input.nullifier === change.nullifier) {
    throw new Error('active nullifier collision');
  }
  values.token1_note_count = '1';
  values.token1_note_amount[0] = amount1.toString();
  values.token1_note_secret[0] = input.secret.toString();
  values.token1_note_nullifier_seed[0] = input.nullifierSeed.toString();
  values.input_commitment_token1 = input.commitment.toString();
  values.nullifier_token1 = input.nullifier.toString();
  values.out_token1_secret = change.secret.toString();
  values.out_token1_nullifier_seed = change.nullifierSeed.toString();
  values.output_commitment_token1 = change.commitment.toString();
  // The circuit publishes a root but has no Merkle path inputs or root/leaf equation.
  // The project's root routine accepts an empty path, for which root equals the leaf.
  values.merkle_root_token1 = input.commitment.toString();
  if (BigInt(values.token0_note_amount[0]) <= 0n || amount1 <= 0n) throw new Error('inactive note');
  const ordered = Object.fromEntries(Object.entries(values).sort(([a], [b]) => a.localeCompare(b)));
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, `${JSON.stringify(ordered, null, 2)}\n`, { flag: 'wx' });
}

await main();
