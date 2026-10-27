#!/usr/bin/env node
// Create a synthetic, non-OFAC KYC credential with disclosure, age, and OFAC checks enabled.
// Insert it in a two-leaf credential tree and prove against the committed OFAC test trees.
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const project = path.resolve(here, '../runs/e01-setup-2026-10-03/recovery-v2/repositories/selfxyz__self/clone');
const require = createRequire(path.join(project, 'package.json'));
const { poseidon2, poseidon3, poseidon4, poseidon8, poseidon10 } = require('poseidon-lite');
const { SMT } = require('@openpassport/zk-kit-smt');
const { LeanIMT } = require('@openpassport/zk-kit-lean-imt');
const seed = 'n6-b6-83cc0060-constructed-v1';
const format = value => Array.isArray(value) ? value.map(x => BigInt(x).toString()) : [BigInt(value).toString()];

function sha(bytes) { return crypto.createHash('sha256').update(bytes).digest('hex'); }
function derive(label, modulus) {
  return 1n + BigInt(`0x${sha(`${seed}:${label}`)}`) % BigInt(modulus);
}
function pinnedJson(relative, expected) {
  const bytes = fs.readFileSync(path.join(project, relative));
  if (sha(bytes) !== expected) throw new Error(`recorded test tree changed: ${relative}`);
  return JSON.parse(bytes.toString('utf8'));
}
function packBytes(bytes) {
  const packed = [];
  for (let start = 0; start < bytes.length; start += 31) {
    let value = 0n;
    for (let i = 0; i < 31 && start + i < bytes.length; i++) {
      value += BigInt(bytes[start + i]) << BigInt(i * 8);
    }
    packed.push(value);
  }
  return packed;
}
function hashBytes(bytes) {
  const packed = packBytes(bytes);
  if (packed.length === 3) return BigInt(poseidon3(packed));
  if (packed.length === 10) return BigInt(poseidon10(packed));
  throw new Error(`unsupported committed KYC byte length: ${bytes.length}`);
}
function ascii(text) { return Array.from(text, char => char.charCodeAt(0)); }
function nameHash(name) { return hashBytes(ascii(name.padEnd(64, '\0'))); }
function smallKey(value) { return BigInt(value) % (1n << 64n); }
function ofacLeaf(name, date, yearOnly) {
  const dateHash = yearOnly ? poseidon4(ascii(date.slice(0, 4))) : poseidon8(ascii(date));
  return smallKey(poseidon2([dateHash, nameHash(name)]));
}
function ofacProof(tree, leaf) {
  const proof = tree.createProof(leaf);
  const closestLeaf = proof.matchingEntry ? proof.matchingEntry[0] :
    proof.entry[1] ? proof.entry[0] : 0;
  const siblings = [...proof.siblings].reverse();
  while (siblings.length < 64) siblings.push(0n);
  if (siblings.length !== 64) throw new Error('OFAC proof longer than circuit depth');
  return { root: format(proof.root), leafKey: format(closestLeaf), siblings: format(siblings) };
}

function makeInput() {
  const doc = {
    country: 'KEN', idType: 'NATIONAL ID', idNumber: '12345678901234567890123456789012',
    issuanceDate: '20200101', expiryDate: '20290101', fullName: 'John Doe', dob: '19900101',
    photoHash: '1234567890', phoneNumber: '1234567890', gender: 'M', address: '1234567890',
  };
  const fieldLengths = [
    ['country', 3], ['idType', 27], ['idNumber', 32], ['issuanceDate', 8], ['expiryDate', 8],
    ['fullName', 64], ['dob', 8], ['photoHash', 32], ['phoneNumber', 12], ['gender', 1], ['address', 100],
  ];
  const serialized = fieldLengths.map(([name, length]) => {
    if (doc[name].length > length) throw new Error(`KYC field too long: ${name}`);
    return doc[name].padEnd(length, '\0');
  }).join('');
  const data = ascii(serialized);
  if (data.length !== 295) throw new Error('KYC_MAX_LENGTH changed');
  const secret = derive('secret', 1n << 120n);
  const leaf = BigInt(poseidon2([secret, hashBytes(data)]));
  const tree = new LeanIMT((a, b) => poseidon2([a, b]), []);
  tree.insert(derive('other-credential', 1n << 120n));
  tree.insert(leaf);
  const proof = tree.generateProof(1);
  const merkleSiblings = [...proof.siblings];
  const leafDepth = merkleSiblings.length;
  const merklePath = Array.from({ length: 33 }, (_, i) => (proof.index >> i) & 1);
  while (merkleSiblings.length < 33) merkleSiblings.push(0n);
  if (leafDepth !== 1 || merkleSiblings.length !== 33) throw new Error('credential proof shape');

  const dobTree = new SMT(poseidon2, true);
  dobTree.import(pinnedJson('circuits/tests/consts/ofac/nameAndDobKycSMT.json',
    '048a0c5e549ab744f38fd18c2ad615df4c529eb2e84180656922e7cff67636dd'));
  const yobTree = new SMT(poseidon2, true);
  yobTree.import(pinnedJson('circuits/tests/consts/ofac/nameAndYobKycSMT.json',
    'a8047c229df50539cadb49c95c9921942164e19356366346c212d941214b2144'));
  const dobProof = ofacProof(dobTree, ofacLeaf(doc.fullName, doc.dob, false));
  const yobProof = ofacProof(yobTree, ofacLeaf(doc.fullName, doc.dob, true));
  const forbidden = [...ascii('USA'), ...Array(117).fill(0)];
  const split = Math.floor(data.length / 2);
  const low = (1n << BigInt(split)) - 1n;
  const high = (1n << BigInt(data.length - split)) - 1n;
  return {
    data_padded: format(data), compressed_disclose_sel: format([low, high]),
    scope: derive('scope', 1n << 120n).toString(), forbidden_countries_list: format(forbidden),
    merkle_root: format(tree.root), leaf_depth: format(leafDepth),
    path: format(merklePath), siblings: format(merkleSiblings),
    ofac_name_dob_smt_leaf_key: dobProof.leafKey, ofac_name_dob_smt_root: dobProof.root,
    ofac_name_dob_smt_siblings: dobProof.siblings,
    ofac_name_yob_smt_leaf_key: yobProof.leafKey, ofac_name_yob_smt_root: yobProof.root,
    ofac_name_yob_smt_siblings: yobProof.siblings,
    selector_ofac: ['1'], user_identifier: derive('user', 1n << 120n).toString(),
    current_date: '20261018'.split(''), majority_age_ASCII: ascii('018'), secret: secret.toString(),
  };
}

if (process.argv.length !== 3) throw new Error('usage: node script.mjs OUTPUT.json');
const destination = path.resolve(process.argv[2]);
fs.mkdirSync(path.dirname(destination), { recursive: true });
fs.writeFileSync(destination, `${JSON.stringify(makeInput(), null, 2)}\n`, { flag: 'wx' });
