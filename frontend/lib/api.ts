import type {
  User,
  Company,
  TokenResponse,
  Instance,
  InstanceCreate,
  FleetSummary,
  Backup,
  BackupSchedule,
  MetricsSnapshot,
  MetricHistoryResponse,
  MetricWindow,
  Replica,
  HealthCheck,
  SlowQueriesResponse,
  ActiveConnectionsResponse,
  SchemaResponse,
  QueryResult,
  ExplainResponse,
  LocksResponse,
  MaintenanceTask,
  MaintenanceSchedule,
  AlertRule,
  AlertEvent,
  AuditLog,
  DashboardSummary,
  BackupStrategy,
  TaskType,
  AlertCondition,
  AlertSeverity,
  AlertMetricType,
  UserAdminCreate,
  UserAdminUpdate,
  SimulationStatus,
} from "@/lib/types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001/api/v1";

// Os tokens vivem em cookies HttpOnly gravados pelo backend (login/refresh) —
// JavaScript não lê nem escreve nada de sessão. Todo fetch vai com
// credentials: "include" e o navegador anexa os cookies sozinho.

// Empresa-ativa do superuser (Stage B). Gravada pelo WorkspaceSwitcher em
// "active_company_id"; enviada no header X-Company-Id para o backend filtrar.
// Ausente = superuser vê todas; para usuário comum o backend ignora o header.
// (Não é credencial — pode ficar em localStorage.)
function getActiveCompany(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("active_company_id");
}

// Dedupe: se várias requisições tomarem 401 ao mesmo tempo, todas reutilizam
// a MESMA promessa de refresh, em vez de dispararem N refreshes concorrentes.
// Análogo ao singleton get_provisioner() do backend (@lru_cache).
let refreshPromise: Promise<boolean> | null = null;

// Tenta renovar a sessão: o backend lê o refresh token do cookie HttpOnly e,
// se válido, devolve os novos tokens já gravados em cookies na resposta.
async function refreshAccessToken(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      credentials: "include",
    })
      .then((res) => res.ok)
      .catch(() => false)
      .finally(() => {
        // Libera o "lock" para futuras renovações depois que esta terminar.
        refreshPromise = null;
      });
  }

  return refreshPromise;
}

// Normaliza o corpo de erro do backend para UMA string legível.
// - HTTPException comum → `detail` é string (ex.: "User not found").
// - Erro de validação 422 → `detail` é uma LISTA de { loc, msg, type }; sem
//   isto, `new Error(lista)` viraria "[object Object]" na tela.
// O prefixo "Value error, " (que o Pydantic adiciona a ValueError) é removido.
function extractErrorMessage(body: unknown): string {
  if (typeof body === "string") return body;
  if (body && typeof body === "object") {
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((e) =>
          e && typeof e === "object" && "msg" in e
            ? String((e as { msg: unknown }).msg)
            : String(e)
        )
        .join("; ")
        .replace(/^Value error, /, "");
    }
    if (detail && typeof detail === "object") return JSON.stringify(detail);
  }
  return "Request failed";
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  retry = true
): Promise<T> {
  // Não fazemos refresh nos próprios endpoints de autenticação:
  // - /auth/login pode dar 401 por senha errada (não é token expirado)
  // - /auth/refresh é a própria renovação (evita recursão infinita)
  const isAuthEndpoint =
    path.startsWith("/auth/login") || path.startsWith("/auth/refresh");

  const activeCompany = getActiveCompany();

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(activeCompany ? { "X-Company-Id": activeCompany } : {}),
      ...options.headers,
    },
  });

  // Coração da correção: token expirou → tenta renovar uma vez e repete.
  if (response.status === 401 && retry && !isAuthEndpoint) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      // retry=false garante que repetimos a chamada UMA única vez.
      return request<T>(path, options, false);
    }
    // Refresh falhou → sessão morta: manda para o login. (Cookies HttpOnly
    // não podem ser apagados por JS; o próximo login os sobrescreve.)
    // Guard contra loop de reload quando o 401 acontece na própria /login.
    if (typeof window !== "undefined" && window.location.pathname !== "/login") {
      window.location.href = "/login";
    }
    throw new Error("Session expired");
  }

  if (!response.ok) {
    const body = await response
      .json()
      .catch(() => ({ detail: response.statusText }));
    throw new Error(extractErrorMessage(body));
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

// ─── Auth ─────────────────────────────────────────────────────────────────────

export async function login(
  username: string,
  password: string
): Promise<TokenResponse> {
  const body = new URLSearchParams({ username, password });
  return request<TokenResponse>("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString(),
  });
}

// O backend lê os tokens dos cookies HttpOnly, blacklista os dois e limpa os
// cookies na resposta — nenhum token transita pelo corpo.
export async function logout(): Promise<void> {
  return request<void>("/auth/logout", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function getCurrentUser(): Promise<User> {
  return request<User>("/auth/me");
}

// Atualiza o próprio usuário (email e/ou senha). O backend só permite alterar a
// própria conta (PATCH /users/{id} retorna 403 para outro id) — coerente com o
// modelo single-operator. Campos omitidos não são alterados.
export async function updateUser(
  userId: string,
  data: { email?: string; password?: string }
): Promise<User> {
  return request<User>(`/users/${userId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

// ─── Companies (multi-tenant) ─────────────────────────────────────────────────

// Lista todas as empresas. O backend restringe a superuser (403 para os demais),
// então só o switcher do superuser chama isto. O usuário comum recebe a própria
// empresa via /auth/me (campo `company`), sem precisar desta lista.
export async function listCompanies(): Promise<Company[]> {
  return request<Company[]>("/companies");
}

// ─── Instances ────────────────────────────────────────────────────────────────

export async function listInstances(): Promise<Instance[]> {
  return request<Instance[]>("/instances");
}

// Estado agregado de TODAS as instâncias do escopo numa chamada. Existe para
// o grid de cards: sem ela, cada card puxaria alertas, backups, uptime e
// métricas por conta própria (N instâncias × 4 requests a cada poll).
export async function getFleetSummary(): Promise<FleetSummary> {
  return request<FleetSummary>("/instances/fleet-summary");
}

export async function getInstance(id: string): Promise<Instance> {
  return request<Instance>(`/instances/${id}`);
}

export async function createInstance(data: InstanceCreate): Promise<Instance> {
  return request<Instance>("/instances", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function updateInstanceStatus(
  id: string,
  action: "start" | "stop"
): Promise<Instance> {
  return request<Instance>(`/instances/${id}/status`, {
    method: "PATCH",
    body: JSON.stringify({ action }),
  });
}

export async function deleteInstance(id: string): Promise<void> {
  return request<void>(`/instances/${id}`, { method: "DELETE" });
}

// ─── Backups ──────────────────────────────────────────────────────────────────

export async function listBackups(instanceId: string): Promise<Backup[]> {
  return request<Backup[]>(`/instances/${instanceId}/backups`);
}

export async function createBackup(
  instanceId: string,
  strategy: BackupStrategy
): Promise<Backup> {
  return request<Backup>(`/instances/${instanceId}/backups`, {
    method: "POST",
    body: JSON.stringify({ strategy }),
  });
}

export async function restoreBackup(backupId: string): Promise<void> {
  return request<void>(`/backups/${backupId}/restore`, { method: "POST" });
}

export async function listBackupSchedules(
  instanceId: string
): Promise<BackupSchedule[]> {
  return request<BackupSchedule[]>(`/instances/${instanceId}/schedules`);
}

export async function createBackupSchedule(
  instanceId: string,
  data: {
    strategy: BackupStrategy;
    cron_expression: string;
    retention_days?: number;
  }
): Promise<BackupSchedule> {
  return request<BackupSchedule>(`/instances/${instanceId}/schedules`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function deleteBackupSchedule(
  instanceId: string,
  scheduleId: string
): Promise<void> {
  return request<void>(
    `/instances/${instanceId}/schedules/${scheduleId}`,
    { method: "DELETE" }
  );
}

// ─── Metrics ──────────────────────────────────────────────────────────────────

export async function getMetrics(instanceId: string): Promise<MetricsSnapshot> {
  return request<MetricsSnapshot>(`/instances/${instanceId}/metrics`);
}

export async function getHealth(instanceId: string): Promise<HealthCheck> {
  return request<HealthCheck>(`/instances/${instanceId}/health`);
}

// Série temporal de uma métrica (para sparklines/gráficos). Lê do histórico
// já coletado pelo poller — funciona mesmo com a instância parada.
export async function getMetricHistory(
  instanceId: string,
  metric: string,
  window: MetricWindow = "1h",
  // Resolução pedida ao backend: a série vem reamostrada em até N baldes.
  // Um sparkline de card pede menos que um gráfico de página inteira.
  points?: number
): Promise<MetricHistoryResponse> {
  const qs = new URLSearchParams({ metric, window });
  if (points) qs.set("points", String(points));
  return request<MetricHistoryResponse>(
    `/instances/${instanceId}/metrics/history?${qs.toString()}`
  );
}

export async function getSlowQueries(
  instanceId: string
): Promise<SlowQueriesResponse> {
  return request<SlowQueriesResponse>(
    `/instances/${instanceId}/slow-queries`
  );
}

export async function getConnections(
  instanceId: string
): Promise<ActiveConnectionsResponse> {
  return request<ActiveConnectionsResponse>(
    `/instances/${instanceId}/connections`
  );
}

export async function getSchema(instanceId: string): Promise<SchemaResponse> {
  return request<SchemaResponse>(`/instances/${instanceId}/schema`);
}

export async function getLocks(instanceId: string): Promise<LocksResponse> {
  return request<LocksResponse>(`/instances/${instanceId}/locks`);
}

// Logs do container da instância (stdout/stderr do PostgreSQL). tail = nº de
// linhas finais. 409 se o container não existir (instância nunca provisionada).
export async function getInstanceLogs(
  instanceId: string,
  tail = 200
): Promise<{ logs: string }> {
  return request<{ logs: string }>(
    `/instances/${instanceId}/logs?tail=${tail}`
  );
}

// ─── Replication (PHASE 9) ────────────────────────────────────────────────────

export async function listReplicas(instanceId: string): Promise<Replica[]> {
  return request<Replica[]>(`/instances/${instanceId}/replicas`);
}

// Cria um standby em streaming a partir do primário. Operação longa no backend
// (pg_basebackup + boot do container) — a chamada só resolve ao final.
export async function createReplica(instanceId: string): Promise<Replica> {
  return request<Replica>(`/instances/${instanceId}/replicas`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function promoteReplica(replicaId: string): Promise<Replica> {
  return request<Replica>(`/replicas/${replicaId}/promote`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

// ─── SQL Console ────────────────────────────────────────────────────────────

// Executa um SELECT read-only. O backend rejeita `;`, DML e DDL com 422 e
// erros do Postgres (tabela inexistente, sintaxe) com 400 — ambos chegam aqui
// como Error com a mensagem já extraída por extractErrorMessage.
export async function runQuery(
  instanceId: string,
  query: string
): Promise<QueryResult> {
  return request<QueryResult>(`/instances/${instanceId}/query`, {
    method: "POST",
    body: JSON.stringify({ query }), // campo "query" espelha o schema QueryRequest
  });
}

// Plano de execução do mesmo SELECT (reusa o endpoint /explain já existente).
export async function explainQuery(
  instanceId: string,
  query: string
): Promise<ExplainResponse> {
  return request<ExplainResponse>(`/instances/${instanceId}/explain`, {
    method: "POST",
    body: JSON.stringify({ query }),
  });
}

// ─── Maintenance ─────────────────────────────────────────────────────────────

export async function listMaintenanceTasks(
  instanceId: string
): Promise<MaintenanceTask[]> {
  return request<MaintenanceTask[]>(`/instances/${instanceId}/maintenance`);
}

export async function runMaintenance(
  instanceId: string,
  data: { task_type: TaskType; target_table?: string }
): Promise<MaintenanceTask> {
  return request<MaintenanceTask>(
    `/instances/${instanceId}/maintenance/run`,
    { method: "POST", body: JSON.stringify(data) }
  );
}

export async function listMaintenanceSchedules(
  instanceId: string
): Promise<MaintenanceSchedule[]> {
  return request<MaintenanceSchedule[]>(
    `/instances/${instanceId}/maintenance/schedules`
  );
}

export async function createMaintenanceSchedule(
  instanceId: string,
  data: { task_type: TaskType; cron_expression: string }
): Promise<MaintenanceSchedule> {
  return request<MaintenanceSchedule>(
    `/instances/${instanceId}/maintenance/schedules`,
    { method: "POST", body: JSON.stringify(data) }
  );
}

export async function deleteMaintenanceSchedule(
  instanceId: string,
  scheduleId: string
): Promise<void> {
  return request<void>(
    `/instances/${instanceId}/maintenance/schedules/${scheduleId}`,
    { method: "DELETE" }
  );
}

// ─── Alerts ───────────────────────────────────────────────────────────────────

export async function listAlertRules(instanceId: string): Promise<AlertRule[]> {
  return request<AlertRule[]>(`/instances/${instanceId}/alerts/rules`);
}

export async function createAlertRule(
  instanceId: string,
  data: {
    name: string;
    metric_type: AlertMetricType;
    condition: AlertCondition;
    threshold: number;
    severity?: AlertSeverity;
  }
): Promise<AlertRule> {
  return request<AlertRule>(`/instances/${instanceId}/alerts/rules`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function updateAlertRule(
  ruleId: string,
  data: {
    condition?: AlertCondition;
    threshold?: number;
    severity?: AlertSeverity;
    is_active?: boolean;
  }
): Promise<AlertRule> {
  return request<AlertRule>(`/alerts/rules/${ruleId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export async function deleteAlertRule(ruleId: string): Promise<void> {
  return request<void>(`/alerts/rules/${ruleId}`, { method: "DELETE" });
}

export async function seedDefaultAlertRules(
  instanceId: string
): Promise<AlertRule[]> {
  return request<AlertRule[]>(
    `/instances/${instanceId}/alerts/seed-defaults`,
    { method: "POST" }
  );
}

export async function listAlertEvents(
  instanceId: string,
  onlyOpen = false
): Promise<AlertEvent[]> {
  const qs = onlyOpen ? "?only_open=true" : "";
  return request<AlertEvent[]>(
    `/instances/${instanceId}/alerts/events${qs}`
  );
}

export async function listAllAlertEvents(
  onlyOpen = false
): Promise<AlertEvent[]> {
  const qs = onlyOpen ? "?only_open=true" : "";
  return request<AlertEvent[]>(`/alerts/events${qs}`);
}

export async function resolveAlertEvent(eventId: string): Promise<AlertEvent> {
  return request<AlertEvent>(`/alerts/events/${eventId}/resolve`, {
    method: "POST",
  });
}

// ─── Users (admin) ────────────────────────────────────────────────────────────

// Usa o query param company_id explícito — independente do WorkspaceSwitcher,
// pois o admin quer controlar o filtro da tabela manualmente.
export async function listUsers(companyId?: string): Promise<User[]> {
  const qs = companyId ? `?company_id=${companyId}` : "";
  return request<User[]>(`/users${qs}`);
}

export async function createUserAdmin(data: UserAdminCreate): Promise<User> {
  return request<User>("/users", { method: "POST", body: JSON.stringify(data) });
}

export async function updateUserAdmin(
  userId: string,
  data: UserAdminUpdate
): Promise<User> {
  return request<User>(`/users/${userId}/admin`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export async function deactivateUser(userId: string): Promise<User> {
  return updateUserAdmin(userId, { is_active: false });
}

// ─── Admin ────────────────────────────────────────────────────────────────────

export async function getDashboard(): Promise<DashboardSummary> {
  return request<DashboardSummary>("/admin/dashboard");
}

export async function getAuditLogs(params?: {
  limit?: number;
  offset?: number;
  action?: string;
  resource_type?: string;
  user_id?: string;
}): Promise<AuditLog[]> {
  const qs = new URLSearchParams();
  if (params?.limit !== undefined) qs.set("limit", String(params.limit));
  if (params?.offset !== undefined) qs.set("offset", String(params.offset));
  if (params?.action) qs.set("action", params.action);
  if (params?.resource_type) qs.set("resource_type", params.resource_type);
  if (params?.user_id) qs.set("user_id", params.user_id);
  const query = qs.toString() ? `?${qs}` : "";
  return request<AuditLog[]>(`/admin/audit-log${query}`);
}
// ─── Demo simulation ──────────────────────────────────────────────────────────

export async function getSimulation(): Promise<SimulationStatus> {
  return request<SimulationStatus>("/demo/simulation");
}

export async function startSimulation(): Promise<SimulationStatus> {
  return request<SimulationStatus>("/demo/simulation/start", { method: "POST" });
}

export async function stopSimulation(): Promise<SimulationStatus> {
  return request<SimulationStatus>("/demo/simulation/stop", { method: "POST" });
}

// Apaga tudo o que a simulação produziu e devolve a frota ao estado real.
export async function resetSimulation(): Promise<SimulationStatus> {
  return request<SimulationStatus>("/demo/simulation/reset", { method: "POST" });
}
