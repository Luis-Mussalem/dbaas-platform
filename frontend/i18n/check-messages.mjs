// Guard-rail do i18n: falha o CI quando en.json e pt.json divergem.
//
// Mora aqui, e não em scripts/, porque o .gitignore da raiz ignora QUALQUER
// diretório chamado "scripts/" (regra de privacidade) — o arquivo sumiria do
// repo e o CI quebraria com "file not found".
//
// Checa três coisas, nesta ordem:
//   1. paridade  — as mesmas chaves nos dois arquivos, nos dois sentidos;
//   2. ordem     — mesma sequência de chaves (mantém os diffs legíveis);
//   3. ICU       — mesmos placeholders, ramos de plural/select e tags de rich
//                  text, via parser de verdade. Regex NÃO serve aqui: em
//                  "{count, plural, one {# alerta}}" ela captura "alerta"/"alert"
//                  como se fosse placeholder e acusa falso positivo.

import { parse, TYPE } from "@formatjs/icu-messageformat-parser";
import en from "./../messages/en.json" with { type: "json" };
import pt from "./../messages/pt.json" with { type: "json" };

// { "Ns": { "a": "x" } } → [["Ns.a", "x"], …], preservando a ordem de declaração.
function flatten(node, prefix = "") {
  return Object.entries(node).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return typeof value === "object" && value !== null
      ? flatten(value, path)
      : [[path, value]];
  });
}

// Assinatura ICU da mensagem: o que um tradutor NÃO pode mudar sem quebrar o
// código. Percorre a AST recursivamente porque plural/select aninham mensagens.
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
        // Os ramos de plural são regras do CLDR e VARIAM por idioma de propósito
        // (pt tem "one" para zero, en não) — só os de `select` são comparáveis.
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

// 1. paridade
for (const k of enKeys) if (!ptKeys.includes(k)) errors.push(`falta em pt.json: ${k}`);
for (const k of ptKeys) if (!enKeys.includes(k)) errors.push(`sobra em pt.json: ${k}`);

// 2. ordem (só quando a paridade passa — senão o ruído esconde a causa real)
if (errors.length === 0) {
  for (let i = 0; i < enKeys.length; i++) {
    if (enKeys[i] !== ptKeys[i]) {
      errors.push(`ordem divergente na posição ${i}: en="${enKeys[i]}" pt="${ptKeys[i]}"`);
      break;
    }
  }
}

// 3. estrutura ICU
if (errors.length === 0) {
  const ptMap = new Map(ptEntries);
  for (const [key, enMsg] of enEntries) {
    const ptMsg = ptMap.get(key);
    let a, b;
    try {
      a = signature(parse(enMsg));
    } catch (e) {
      errors.push(`ICU inválido em en.json → ${key}: ${e.message}`);
      continue;
    }
    try {
      b = signature(parse(ptMsg));
    } catch (e) {
      errors.push(`ICU inválido em pt.json → ${key}: ${e.message}`);
      continue;
    }
    for (const field of ["args", "tags", "branches"]) {
      if (show(a[field]) !== show(b[field])) {
        errors.push(`${field} divergem em ${key}: en={${show(a[field])}} pt={${show(b[field])}}`);
      }
    }
  }
}

if (errors.length > 0) {
  console.error(`✗ i18n:check — ${errors.length} problema(s):\n`);
  for (const e of errors) console.error(`  • ${e}`);
  console.error("\nen.json é a fonte da verdade: as chaves de pt.json devem espelhá-la.");
  process.exit(1);
}

console.log(`✓ i18n:check — ${enKeys.length} chaves, paridade/ordem/ICU conferem em en e pt.`);
