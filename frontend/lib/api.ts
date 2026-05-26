import type {
  User,
  TokenResponse,
  Instance,
  InstanceCreate,
  Backup,
  BackupSchedule,
  MetricsSnapshot,
  HealthCheck,
  SlowQueriesResponse,
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
} from "@/lib/types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001/api/v1";

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("access_token");
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getToken();

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail ?? "Request failed");
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

export async function logout(refreshToken: string | null = null): Promise<void> {
  return request<void>("/auth/logout", {
    method: "POST",
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
}

export async function getCurrentUser(): Promise<User> {
  return request<User>("/auth/me");
}

// ─── Instances ────────────────────────────────────────────────────────────────

export async function listInstances(): Promise<Instance[]> {
  return request<Instance[]>("/instances");
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

export async function getSlowQueries(
  instanceId: string
): Promise<SlowQueriesResponse> {
  return request<SlowQueriesResponse>(
    `/instances/${instanceId}/slow-queries`
  );
}

export async function getLocks(instanceId: string): Promise<LocksResponse> {
  return request<LocksResponse>(`/instances/${instanceId}/locks`);
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