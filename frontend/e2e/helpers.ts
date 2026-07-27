// Credentials for the demo (full-access) account, seeded by the migrations.
// Documented in the README — not a real secret. Override via env if needed.
export const DEMO_EMAIL = process.env.E2E_EMAIL ?? "dev-test@local.dev";
export const DEMO_PASSWORD = process.env.E2E_PASSWORD ?? "dev-test-2026";
