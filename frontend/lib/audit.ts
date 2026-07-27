// Audited actions — mirrors the middleware's _AUDIT_ACTIONS table
// (backend/src/core/audit_middleware.py). The TEXT lives in the messages
// (Actions.phrase.* for the feed's verbal phrase, Actions.label.* for the
// audit table's label); here it's only what's presentation data.

export type Tone = "ok" | "info" | "warn" | "danger" | "muted";

export const AUDIT_ACTIONS = [
  "register",
  "login",
  "logout",
  "instance_created",
  "instance_status_changed",
  "instance_deleted",
  "backup_created",
  "restore_initiated",
  "schedule_created",
  "schedule_deleted",
  "maintenance_run",
] as const;

export type AuditAction = (typeof AUDIT_ACTIONS)[number];

// Single source of the tone. The ActivityFeed used to derive the color by substring
// (`action.includes("created")`) and the Audit screen had an explicit map:
// the two disagreed — `login` came out green in the feed and gray in the audit screen.
const ACTION_TONES: Record<AuditAction, Tone> = {
  register: "info",
  login: "muted",
  logout: "muted",
  instance_created: "ok",
  instance_status_changed: "info",
  instance_deleted: "danger",
  backup_created: "ok",
  restore_initiated: "warn",
  schedule_created: "ok",
  schedule_deleted: "danger",
  maintenance_run: "info",
};

export function isAuditAction(action: string): action is AuditAction {
  return (AUDIT_ACTIONS as readonly string[]).includes(action);
}

// Unknown action (new backend, old frontend) → neutral, never breaks.
export function toneFor(action: string): Tone {
  return isAuditAction(action) ? ACTION_TONES[action] : "muted";
}

export const RESOURCE_TYPES = [
  "user",
  "auth",
  "instance",
  "backup",
  "backup_schedule",
  "maintenance",
] as const;

export type ResourceType = (typeof RESOURCE_TYPES)[number];

export function isResourceType(value: string): value is ResourceType {
  return (RESOURCE_TYPES as readonly string[]).includes(value);
}

// Short actor label built from the email, in `name@company` format:
//   user1@jupiter.example -> user1@jupiter  (local part + 1st part of the domain)
//   admin@local.dev       -> admin@dev      (internal accounts: domain becomes "dev",
//   dev-test@local.dev    -> test@dev        and the "dev-" prefix on the name is dropped)
// Returns null when there's no email (a system action, or an already-deleted user) —
// the caller falls back to the generic label.
export function actorLabel(email: string | null | undefined): string | null {
  if (!email) return null;
  const [local, domain] = email.split("@");
  if (!domain) return email;
  if (domain === "local.dev") return `${local.replace(/^dev-/, "")}@dev`;
  return `${local}@${domain.split(".")[0]}`;
}
