// Shared classes for the "raw" controls (button/input/select) used across
// pages and tabs. Each file used to redeclare its own — centralizing them avoids
// visual drift between screens. Truly unique variants stay local to their file.

// Primary button (h-9) — submit/creation in forms.
export const BTN_PRIMARY =
  "inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50";

// Secondary button (h-9, with border) — pairs with the primary one in forms.
export const BTN_DEFAULT =
  "inline-flex h-9 items-center gap-1.5 rounded-md border border-border px-4 text-sm font-medium text-fg-2 transition hover:bg-surface-2 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50";

// Compact button (h-8, with border) — toolbars and table/card actions.
export const BTN =
  "inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-3 text-[13px] font-medium text-fg-2 transition hover:bg-surface-2 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50";

// Ghost button (h-7, no border) — discreet actions inside cards.
export const BTN_GHOST =
  "inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[12.5px] font-medium text-fg-2 transition hover:bg-surface-2 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50";

// Destructive action button (h-8).
export const BTN_DANGER =
  "inline-flex h-8 items-center gap-1.5 rounded-md border border-danger/30 px-3 text-[13px] font-medium text-danger transition hover:bg-danger/10 disabled:cursor-not-allowed disabled:opacity-50";

// Compact input/select (h-8) — filter bars.
export const INPUT =
  "h-8 rounded-md border border-border bg-background px-2 text-[13px] text-foreground outline-none transition focus:border-brand";

// Form input (h-9, full width) — settings pages.
export const INPUT_LG =
  "h-9 w-full rounded-md border border-border bg-background px-3 text-sm text-foreground outline-none transition focus:border-brand";
