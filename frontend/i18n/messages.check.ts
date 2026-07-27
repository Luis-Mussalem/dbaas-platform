import type { Messages } from "next-intl";
import pt from "../messages/pt.json";

// TYPE guard-rail, complementary to i18n/check-messages.mjs (which runs in CI).
// `Messages` is typed from en.json (see global.d.ts), so this assignment
// makes `tsc` fail if pt.json is missing a key that en.json has.
//
// It exists alongside the .mjs checker because it catches the error in the editor, the exact
// moment the key disappears — without waiting for CI. The .mjs covers what the type can't see: extra
// keys, ordering, and ICU structure.
//
// `satisfies` instead of `:` to check compatibility without widening the type.
export const ptMessages = pt satisfies Messages;
