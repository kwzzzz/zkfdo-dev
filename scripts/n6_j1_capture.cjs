// Capture inputs passed by an unchanged project's witness tests or input tool.
// Captures stay in an ignored runs/ file; nothing is printed to stdout.
const Module = require('node:module');
const fs = require('node:fs');
const path = require('node:path');

const capturePath = process.env.N6_J1_CAPTURE_PATH;
if (!capturePath) throw new Error('N6_J1_CAPTURE_PATH is required');
const originalLoad = Module._load;
const originalWrite = fs.writeFileSync.bind(fs);
let sequence = 0;

function serializable(value) {
  return JSON.parse(JSON.stringify(value, (_key, item) => {
    if (typeof item === 'bigint') return item.toString();
    if (Buffer.isBuffer(item) || item instanceof Uint8Array) return Array.from(item);
    return item;
  }));
}

function capture(kind, source, input) {
  try {
    const record = { sequence: sequence++, kind, source: String(source || ''), input: serializable(input) };
    fs.appendFileSync(capturePath, `${JSON.stringify(record)}\n`, { mode: 0o600 });
  } catch (_) {
    // An unserializable argument cannot be used as a JSON base input.
  }
}

function wrapTester(tester, source) {
  if (!tester || typeof tester.calculateWitness !== 'function') return tester;
  return new Proxy(tester, {
    get(target, property, receiver) {
      if (property === 'calculateWitness') {
        return function (...args) {
          capture('calculateWitness', source, args[0]);
          return target.calculateWitness.apply(target, args);
        };
      }
      return Reflect.get(target, property, receiver);
    },
  });
}

function wrapTesterFactory(factory) {
  return new Proxy(factory, {
    apply(target, thisArg, args) {
      const source = args[0];
      const result = Reflect.apply(target, thisArg, args);
      return Promise.resolve(result).then((tester) => wrapTester(tester, source));
    },
  });
}

function copyWithReplacement(original, replacements) {
  const copy = Object.create(Object.getPrototypeOf(original));
  for (const key of Reflect.ownKeys(original)) {
    const descriptor = Object.getOwnPropertyDescriptor(original, key);
    if (Object.prototype.hasOwnProperty.call(replacements, key)) {
      Object.defineProperty(copy, key, {
        value: replacements[key], enumerable: descriptor.enumerable,
        writable: true, configurable: true,
      });
    } else {
      Object.defineProperty(copy, key, descriptor);
    }
  }
  return copy;
}

Module._load = function (request, parent, isMain) {
  const loaded = originalLoad.apply(this, arguments);
  if (request === 'circom_tester' && loaded && typeof loaded === 'object') {
    const replacements = {};
    for (const key of ['wasm', 'c']) {
      if (typeof loaded[key] === 'function') replacements[key] = wrapTesterFactory(loaded[key]);
    }
    return copyWithReplacement(loaded, replacements);
  }
  if (/^(?:\.\/|\.\.\/).*tester(?:\.js)?$/i.test(request) && typeof loaded === 'function') {
    return wrapTesterFactory(loaded);
  }
  if (request === 'snarkjs' && loaded && loaded.wtns) {
    const wtns = loaded.wtns;
    const wrapped = copyWithReplacement(wtns, {
      calculate: function (...args) {
        capture('wtns.calculate', args[1], args[0]);
        return wtns.calculate.apply(wtns, args);
      },
    });
    return copyWithReplacement(loaded, { wtns: wrapped });
  }
  return loaded;
};

if (process.env.N6_J1_CAPTURE_WRITES === '1') {
  fs.writeFileSync = function (file, data, ...rest) {
    if (typeof file === 'string' && file.endsWith('.json')) {
      try { capture('input-tool-output', path.resolve(file), JSON.parse(String(data))); } catch (_) { /* ignore */ }
    }
    return originalWrite(file, data, ...rest);
  };
}
