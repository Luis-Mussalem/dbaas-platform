// Classes compartilhadas dos controles "crus" (button/input/select) usados nas
// páginas e abas. Antes cada arquivo redeclarava as suas — centralizá-las evita
// deriva visual entre telas. Variantes realmente únicas ficam locais ao arquivo.

// Botão primário (h-9) — submit/criação em formulários.
export const BTN_PRIMARY =
  "inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50";

// Botão secundário (h-9, com borda) — par do primário em formulários.
export const BTN_DEFAULT =
  "inline-flex h-9 items-center gap-1.5 rounded-md border border-border px-4 text-sm font-medium text-fg-2 transition hover:bg-surface-2 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50";

// Botão compacto (h-8, com borda) — toolbars e ações de tabela/card.
export const BTN =
  "inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-3 text-[13px] font-medium text-fg-2 transition hover:bg-surface-2 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50";

// Botão fantasma (h-7, sem borda) — ações discretas dentro de cards.
export const BTN_GHOST =
  "inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[12.5px] font-medium text-fg-2 transition hover:bg-surface-2 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50";

// Botão de ação destrutiva (h-8).
export const BTN_DANGER =
  "inline-flex h-8 items-center gap-1.5 rounded-md border border-danger/30 px-3 text-[13px] font-medium text-danger transition hover:bg-danger/10 disabled:cursor-not-allowed disabled:opacity-50";

// Input/select compacto (h-8) — barras de filtro.
export const INPUT =
  "h-8 rounded-md border border-border bg-background px-2 text-[13px] text-foreground outline-none transition focus:border-brand";

// Input de formulário (h-9, largura total) — páginas de configuração.
export const INPUT_LG =
  "h-9 w-full rounded-md border border-border bg-background px-3 text-sm text-foreground outline-none transition focus:border-brand";
