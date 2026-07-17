// Ações auditadas — espelha a tabela _AUDIT_ACTIONS do middleware
// (backend/src/core/audit_middleware.py). O TEXTO vive nas mensagens
// (Actions.phrase.* para a frase verbal do feed, Actions.label.* para o rótulo
// da tabela de auditoria); aqui fica só o que é dado de apresentação.

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

// Fonte única do tom. Antes o ActivityFeed derivava a cor por substring
// (`action.includes("created")`) e a tela de Auditoria tinha um mapa explícito:
// as duas discordavam — `login` saía verde no feed e cinza na auditoria.
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

// Ação desconhecida (backend novo, frontend antigo) → neutro, nunca quebra.
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

// Rótulo curto do ator a partir do email, no formato `nome@empresa`:
//   ana@jupiter.example  -> ana@jupiter   (local + 1ª parte do domínio)
//   admin@local.dev      -> admin@dev     (contas internas: domínio vira "dev",
//   dev-test@local.dev   -> test@dev       e o prefixo "dev-" do nome some)
// Retorna null quando não há email (ação de sistema ou usuário já deletado) —
// o chamador cai no rótulo genérico.
export function actorLabel(email: string | null | undefined): string | null {
  if (!email) return null;
  const [local, domain] = email.split("@");
  if (!domain) return email;
  if (domain === "local.dev") return `${local.replace(/^dev-/, "")}@dev`;
  return `${local}@${domain.split(".")[0]}`;
}
