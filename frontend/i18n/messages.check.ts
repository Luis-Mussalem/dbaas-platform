import type { Messages } from "next-intl";
import pt from "../messages/pt.json";

// Guard-rail de TIPO, complementar ao i18n/check-messages.mjs (que roda no CI).
// `Messages` é tipado a partir de en.json (ver global.d.ts), então esta atribuição
// faz o `tsc` falhar se pt.json perder uma chave que en.json tem.
//
// Existe além do checker .mjs porque pega o erro no editor, no exato momento em
// que a chave some — sem esperar o CI. O .mjs cobre o que o tipo não vê: chaves
// a mais, ordem e a estrutura ICU.
//
// `satisfies` em vez de `:` para checar a compatibilidade sem alargar o tipo.
export const ptMessages = pt satisfies Messages;
