// i18n guard-rail: fails CI when en.json and pt.json diverge.
//
// Lives here, not in scripts/, because the root .gitignore ignores ANY
// directory called "scripts/" (privacy rule) — the file would disappear from
// the repo and CI would break with "file not found".
//
// Checks three things, in this order:
//   1. parity — the same keys in both files, in both directions;
//   2. order  — same key sequence (keeps diffs readable);
//   3. ICU    — same placeholders, plural/select branches and rich-text tags,
//               via a real parser. Regex does NOT work here: in
//               "{count, plural, one {# alerta}}" it would capture "alerta"/"alert"
//               as if it were a placeholder and raise a false positive.

import { parse, TYPE } from "@formatjs/icu-messageformat-parser";
import en from "./../messages/en.json" with { type: "json" };
import pt from "./../messages/pt.json" with { type: "json" };

// { "Ns": { "a": "x" } } → [["Ns.a", "x"], …], preserving declaration order.
function flatten(node, prefix = "") {
  return Object.entries(node).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return typeof value === "object" && value !== null
      ? flatten(value, path)
      : [[path, value]];
  });
}

// A message's ICU signature: what a translator CANNOT change without breaking the
// code. Walks the AST recursively because plural/select nest messages.
function signature(ast, acc = { args: new Set(), tags: new Set(), branches: new Set() }) {
  for (const node of ast) {
    if (node.type === TYPE.argument) acc.args.add(node.value);
    if (node.type === TYPE.tag) {
      acc.tags.add(node.value);
      signature(node.children, acc);
    }
    if (node.type === TYPE.plural || node.type === TYPE.select) {
      acc.args.add(node.value);
      for (const [name, branch] of Object.entries(node.options)) {
        // Plural branches are CLDR rules and VARY by language on purpose
        // (pt has "one" for zero, en doesn't) — only `select` branches are comparable.
        if (node.type === TYPE.select) acc.branches.add(name);
        signature(branch.value, acc);
      }
    }
  }
  return acc;
}

const show = (set) => [...set].sort().join(", ") || "∅";
const errors = [];

const enEntries = flatten(en);
const ptEntries = flatten(pt);
const enKeys = enEntries.map(([k]) => k);
const ptKeys = ptEntries.map(([k]) => k);

// 1. parity
for (const k of enKeys) if (!ptKeys.includes(k)) errors.push(`missing in pt.json: ${k}`);
for (const k of ptKeys) if (!enKeys.includes(k)) errors.push(`extra in pt.json: ${k}`);

// 2. order (only once parity passes — otherwise the noise hides the real cause)
if (errors.length === 0) {
  for (let i = 0; i < enKeys.length; i++) {
    if (enKeys[i] !== ptKeys[i]) {
      errors.push(`order diverges at position ${i}: en="${enKeys[i]}" pt="${ptKeys[i]}"`);
      break;
    }
  }
}

// 3. ICU structure
if (errors.length === 0) {
  const ptMap = new Map(ptEntries);
  for (const [key, enMsg] of enEntries) {
    const ptMsg = ptMap.get(key);
    let a, b;
    try {
      a = signature(parse(enMsg));
    } catch (e) {
      errors.push(`invalid ICU in en.json → ${key}: ${e.message}`);
      continue;
    }
    try {
      b = signature(parse(ptMsg));
    } catch (e) {
      errors.push(`invalid ICU in pt.json → ${key}: ${e.message}`);
      continue;
    }
    for (const field of ["args", "tags", "branches"]) {
      if (show(a[field]) !== show(b[field])) {
        errors.push(`${field} diverge in ${key}: en={${show(a[field])}} pt={${show(b[field])}}`);
      }
    }
  }
}

if (errors.length > 0) {
  console.error(`✗ i18n:check — ${errors.length} problem(s):\n`);
  for (const e of errors) console.error(`  • ${e}`);
  console.error("\nen.json is the source of truth: pt.json's keys must mirror it.");
  process.exit(1);
}

console.log(`✓ i18n:check — ${enKeys.length} keys, parity/order/ICU match across en and pt.`);
