#!/usr/bin/env node
// Create a 16-input, two-output VAnchor transfer with all inputs carrying funds.
// Prove all 16 note commitments in one 30-level Merkle tree and preserve balance.
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const project = path.resolve(here, '../runs/c03-corpus-2026-10-02/recovery-v3/repositories/tangle-network__protocol-solidity/clone');
const require = createRequire(path.join(project, 'package.json'));
const { poseidon } = require('circomlibjs');
const seed = 'n6-b6-e71f158d-constructed-v1';
const zero = 21663839004416932945382355908790599225266501822907911457504978515578255421292n;
const forbiddenZeroLeaf = 11850551329423159860688778991827824730037759162201783566284850822760196767874n;

function derive(label, modulus) {
  const hex = crypto.createHash('sha256').update(`${seed}:${label}`).digest('hex');
  return 1n + BigInt(`0x${hex}`) % BigInt(modulus);
}
function hash(...values) { return BigInt(poseidon(values)); }
function scalar(value) { return value.toString(); }

function makeInput() {
  const chainID = derive('chainID', 2n ** 32n);
  const inputNotes = Array.from({ length: 16 }, (_, i) => {
    const amount = 100n + derive(`amount:${i}`, 10000n);
    const privateKey = derive(`privateKey:${i}`, 2n ** 120n);
    const blinding = derive(`blinding:${i}`, 2n ** 120n);
    const publicKey = hash(privateKey);
    const commitment = hash(chainID, amount, publicKey, blinding);
    if (commitment === forbiddenZeroLeaf) throw new Error('zero leaf collision');
    return { amount, privateKey, blinding, commitment };
  });
  const leaves = inputNotes.map(note => note.commitment);
  const zeros = [zero];
  for (let depth = 1; depth <= 30; depth++) zeros.push(hash(zeros[depth - 1], zeros[depth - 1]));
  const levels = [leaves];
  for (let depth = 0; depth < 30; depth++) {
    const prior = levels[depth];
    const next = [];
    for (let i = 0; i < prior.length; i += 2) {
      next.push(hash(prior[i], prior[i + 1] ?? zeros[depth]));
    }
    levels.push(next);
  }
  if (levels[30].length !== 1) throw new Error('Merkle root missing');
  const root = levels[30][0];
  const inPathElements = [];
  const inputNullifier = [];
  for (let i = 0; i < 16; i++) {
    let position = i;
    let current = leaves[i];
    const siblings = [];
    for (let depth = 0; depth < 30; depth++) {
      const sibling = levels[depth][position ^ 1] ?? zeros[depth];
      siblings.push(scalar(sibling));
      current = position & 1 ? hash(sibling, current) : hash(current, sibling);
      position = Math.floor(position / 2);
    }
    if (current !== root) throw new Error(`Merkle path invalid: ${i}`);
    inPathElements.push(siblings);
    const signature = hash(inputNotes[i].privateKey, inputNotes[i].commitment, BigInt(i));
    inputNullifier.push(hash(inputNotes[i].commitment, BigInt(i), signature));
  }
  if (new Set(inputNullifier.map(scalar)).size !== 16) throw new Error('nullifier collision');
  const totalIn = inputNotes.reduce((sum, note) => sum + note.amount, 0n);
  const publicAmount = 13n;
  const totalOut = totalIn + publicAmount;
  const outAmount = [totalOut / 2n, totalOut - totalOut / 2n];
  const outBlinding = [derive('outBlinding:0', 2n ** 120n), derive('outBlinding:1', 2n ** 120n)];
  const outPubkey = [hash(derive('outPrivateKey:0', 2n ** 120n)),
    hash(derive('outPrivateKey:1', 2n ** 120n))];
  const outputCommitment = outAmount.map((amount, i) =>
    hash(chainID, amount, outPubkey[i], outBlinding[i]));
  const otherRoot = derive('otherRoot', 2n ** 120n);
  if (otherRoot === root) throw new Error('root collision');
  return {
    publicAmount: scalar(publicAmount), extDataHash: scalar(derive('extDataHash', 2n ** 120n)),
    inputNullifier: inputNullifier.map(scalar), inAmount: inputNotes.map(note => scalar(note.amount)),
    inPrivateKey: inputNotes.map(note => scalar(note.privateKey)),
    inBlinding: inputNotes.map(note => scalar(note.blinding)),
    inPathIndices: Array.from({ length: 16 }, (_, i) => i.toString()), inPathElements,
    outputCommitment: outputCommitment.map(scalar), outChainID: [scalar(chainID), scalar(chainID)],
    outAmount: outAmount.map(scalar), outPubkey: outPubkey.map(scalar),
    outBlinding: outBlinding.map(scalar), chainID: scalar(chainID),
    roots: [scalar(root), scalar(otherRoot)],
  };
}

if (process.argv.length !== 3) throw new Error('usage: node script.mjs OUTPUT.json');
const destination = path.resolve(process.argv[2]);
fs.mkdirSync(path.dirname(destination), { recursive: true });
fs.writeFileSync(destination, `${JSON.stringify(makeInput(), null, 2)}\n`, { flag: 'wx' });
