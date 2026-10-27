#!/usr/bin/env node
// Independent deterministic Split(30, 8) input from the recorded circuit source.
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const project = path.resolve(__dirname, '../runs/c03-corpus-2026-10-02/recovery-v3/repositories/Zellic__zkerc20/clone');
const { poseidon, mimcsponge } = require(path.join(project, 'node_modules/circomlibjs'));
const seed = 'n6-b6-76053f7f-constructed-v1';

function bounded(label, modulus) {
  const bytes = crypto.createHash('sha256').update(`${seed}:${label}`).digest('hex');
  return BigInt(`0x${bytes}`) % BigInt(modulus);
}

function two(left, right) {
  return BigInt(mimcsponge.multiHash([left, right], 0, 1));
}

function makeInput() {
  const sender = 1n + bounded('sender', 2n ** 80n);
  const asset = 1n + bounded('asset', 2n ** 80n);
  const amounts = Array.from({ length: 8 }, (_, i) => 13n + bounded(`amount:${i}`, 8000n));
  const salts = Array.from({ length: 8 }, (_, i) => 1n + bounded(`salt:${i}`, 2n ** 120n));
  const owners = Array(8).fill(sender);
  const nullifiers = amounts.map((amount, i) =>
    BigInt(poseidon([asset, amount, salts[i], owners[i]])));
  const leaves = nullifiers.map((nullifier, i) =>
    BigInt(poseidon([nullifier, salts[i]])));
  const levels = [leaves];
  for (let depth = 0; depth < 30; depth++) {
    const prior = levels[depth];
    const next = [];
    for (let i = 0; i < prior.length; i += 2) {
      next.push(two(prior[i], prior[i + 1] ?? 0n));
    }
    levels.push(next);
  }
  if (levels[30].length !== 1) throw new Error('Merkle tree root missing');
  const paths = [];
  const sides = [];
  for (let i = 0; i < 8; i++) {
    let index = i;
    let current = leaves[i];
    const pathValues = [];
    const sideValues = [];
    for (let depth = 0; depth < 30; depth++) {
      const sibling = levels[depth][index ^ 1] ?? 0n;
      const side = index & 1;
      pathValues.push(sibling.toString());
      sideValues.push(side);
      current = side ? two(sibling, current) : two(current, sibling);
      index = Math.floor(index / 2);
    }
    if (current !== levels[30][0]) throw new Error(`Merkle path ${i} invalid`);
    paths.push(pathValues);
    sides.push(sideValues);
  }
  const leftAmount = amounts.slice(0, 4).reduce((a, b) => a + b, 0n);
  const rightAmount = amounts.slice(4).reduce((a, b) => a + b, 0n);
  const leftSalt = 1n + bounded('leftSalt', 2n ** 120n);
  const rightSalt = 1n + bounded('rightSalt', 2n ** 120n);
  const leftCommitment = BigInt(poseidon([
    BigInt(poseidon([asset, leftAmount, leftSalt, sender])), leftSalt,
  ]));
  const rightCommitment = BigInt(poseidon([
    BigInt(poseidon([asset, rightAmount, rightSalt, sender])), rightSalt,
  ]));
  const scalar = value => value.toString();
  return {
    sender: scalar(sender), root: scalar(levels[30][0]), asset: scalar(asset),
    amounts: amounts.map(scalar), salts: salts.map(scalar), owners: owners.map(scalar),
    leftAmount: scalar(leftAmount), leftSalt: scalar(leftSalt), leftOwner: scalar(sender),
    leftCommitment: scalar(leftCommitment), rightAmount: scalar(rightAmount),
    rightSalt: scalar(rightSalt), rightOwner: scalar(sender),
    rightCommitment: scalar(rightCommitment), nullifiers: nullifiers.map(scalar),
    path: paths, sides,
  };
}

if (process.argv.length !== 3) throw new Error('usage: node script.js OUTPUT.json');
const destination = path.resolve(process.argv[2]);
fs.mkdirSync(path.dirname(destination), { recursive: true });
fs.writeFileSync(destination, `${JSON.stringify(makeInput(), null, 2)}\n`, { flag: 'wx' });
