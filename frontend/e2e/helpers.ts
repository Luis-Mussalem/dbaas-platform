// Credenciais da conta de demonstração (full-access), semeada pelas migrations.
// Documentadas no README — não são segredo real. Sobrescreva por env se preciso.
export const DEMO_EMAIL = process.env.E2E_EMAIL ?? "dev-test@local.dev";
export const DEMO_PASSWORD = process.env.E2E_PASSWORD ?? "dev-test-2026";
