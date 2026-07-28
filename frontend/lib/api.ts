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
} from "@/lib/types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001/api/v1";

// The tokens live in HttpOnly cookies written by the backend (login/refresh) —
// JavaScript neither reads nor writes anything about the session. Every fetch goes with
// credentials: "include" and the browser attaches the cookies on its own.

// Superuser's active company (Stage B). Written by the WorkspaceSwitcher into
// "active_company_id"; sent in the X-Company-Id header for the backend to filter by.
// Absent = superuser sees all; for a regular user the backend ignores the header.
// (Not a credential — it can live in localStorage.)
function getActiveCompany(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("active_company_id");
}

// Dedupe: if several requests get a 401 at the same time, they all reuse
// the SAME refresh promise instead of firing N concurrent refreshes.
// Analogous to the backend's singleton get_provisioner() (@lru_cache).
let refreshPromise: Promise<boolean> | null = null;

// Tries to renew the session: the backend reads the refresh token from the HttpOnly
// cookie and, if valid, returns the new tokens already written to cookies in the response.
async function refreshAccessToken(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      credentials: "include",
    })
      .then((res) => res.ok)
      .catch(() => false)
      .finally(() => {
        // Releases the "lock" for future renewals once this one finishes.
        refreshPromise = null;
      });
  }

  return refreshPromise;
}

// Normalizes the backend's error body into ONE readable string.
// - Regular HTTPException → `detail` is a string (e.g.: "User not found").
// - 422 validation error → `detail` is a LIST of { loc, msg, type }; without
//   this, `new Error(list)` would show up as "[object Object]" on screen.
// The "Value error, " prefix (which Pydantic adds to ValueError) is stripped.
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
  // We don't refresh on the auth endpoints themselves:
  // - /auth/login can 401 for a wrong password (not an expired token)
  // - /auth/refresh is the renewal itself (avoids infinite recursion)
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

  // The heart of the fix: token expired → try to renew once and retry.
  if (response.status === 401 && retry && !isAuthEndpoint) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      // retry=false guarantees we repeat the call exactly ONCE.
      return request<T>(path, options, false);
    }
    // Refresh failed → session is dead: send to login. (HttpOnly cookies
    // can't be cleared by JS; the next login overwrites them.)
    // Guard against a reload loop when the 401 happens on /login itself.
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

// The backend reads the tokens from the HttpOnly cookies, blacklists both and clears
// the cookies in the response — no token travels through the body.
export async function logout(): Promise<void> {
  return request<void>("/auth/logout", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function getCurrentUser(): Promise<User> {
  return request<User>("/auth/me");
}

// Updates the current user (email and/or password). The backend only allows changing
// one's own account (PATCH /users/{id} returns 403 for another id) — an admin changing
// someone else's credentials goes through updateUserAdmin instead. Omitted fields are
// left unchanged.
//
// `current_password` is REQUIRED whenever email or password changes: both are account
// recovery handles, so the backend re-authenticates rather than trusting the session
// alone (400 without it, 403 if it's wrong).
export async function updateUser(
  userId: string,
  data: { email?: string; password?: string; current_password?: string }
): Promise<User> {
  return request<User>(`/users/${userId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

// ─── Companies (multi-tenant) ─────────────────────────────────────────────────

// Lists all companies. The backend restricts this to a superuser (403 for others),
// so only the superuser's switcher calls it. A regular user gets their own
// company via /auth/me (the `company` field), without needing this list.
export async function listCompanies(): Promise<Company[]> {
  return request<Company[]>("/companies");
}

// ─── Instances ────────────────────────────────────────────────────────────────

export async function listInstances(): Promise<Instance[]> {
  return request<Instance[]>("/instances");
}

// Aggregated state of ALL instances in scope in one call. Exists for
// the card grid: without it, each card would pull alerts, backups, uptime and
// metrics on its own (N instances × 4 requests on every poll).
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

// Time series for a metric (for sparklines/charts). Reads from the history
// already collected by the poller — works even while the instance is stopped.
export async function getMetricHistory(
  instanceId: string,
  metric: string,
  window: MetricWindow = "1h",
  // Resolution requested from the backend: the series comes back resampled into up to N buckets.
  // A card sparkline asks for fewer than a full page chart.
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

// Instance container logs (PostgreSQL stdout/stderr). tail = number of
// trailing lines. 409 if the container doesn't exist (instance never provisioned).
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

// Creates a streaming standby from the primary. Long-running backend operation
// (pg_basebackup + container boot) — the call only resolves at the end.
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

// Runs a read-only SELECT. The backend rejects `;`, DML and DDL with 422 and
// Postgres errors (missing table, syntax) with 400 — both arrive here
// as an Error with the message already extracted by extractErrorMessage.
export async function runQuery(
  instanceId: string,
  query: string
): Promise<QueryResult> {
  return request<QueryResult>(`/instances/${instanceId}/query`, {
    method: "POST",
    body: JSON.stringify({ query }), // "query" field mirrors the QueryRequest schema
  });
}

// Execution plan for the same SELECT (reuses the existing /explain endpoint).
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

// Uses the explicit company_id query param — independent of the WorkspaceSwitcher,
// since the admin wants to control the table's filter manually.
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
