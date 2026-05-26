// ─── Status types ─────────────────────────────────────────────────────────────

export type InstanceStatus =
  | "pending"
  | "provisioning"
  | "running"
  | "stopped"
  | "deleting"
  | "deleted"
  | "failed";

export type BackupStatus = "pending" | "running" | "completed" | "failed" | "deleted";
export type BackupType = "manual" | "scheduled";
export type BackupStrategy = "logical" | "physical";

export type TaskType =
  | "vacuum"
  | "vacuum_full"
  | "analyze"
  | "reindex"
  | "kill_idle"
  | "kill_long";

export type TaskStatus = "pending" | "running" | "completed" | "failed";

export type AlertMetricType =
  | "connections_ratio"
  | "cache_hit_ratio"
  | "db_usage_percent"
  | "long_query_seconds"
  | "backup_age_hours";

export type AlertCondition = "gt" | "gte" | "lt" | "lte" | "eq";
export type AlertSeverity = "info" | "warning" | "critical";

// ─── Auth ─────────────────────────────────────────────────────────────────────

export interface LoginRequest {
  username: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

// ─── User ─────────────────────────────────────────────────────────────────────

export interface User {
  id: string;
  email: string;
  is_active: boolean;
  is_superuser: boolean;
  created_at: string;
  updated_at: string;
}

// ─── Database Instance ────────────────────────────────────────────────────────

export interface Instance {
  id: string;
  name: string;
  engine_version: "14" | "15" | "16" | "17";
  status: InstanceStatus;
  host: string | null;
  port: number | null;
  db_name: string | null;
  db_user: string | null;
  cpu: number | null;
  memory_mb: number | null;
  storage_gb: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface InstanceCreate {
  name: string;
  engine_version?: "14" | "15" | "16" | "17";
  cpu?: number;
  memory_mb?: number;
  storage_gb?: number;
  notes?: string;
}

export interface InstanceStatusUpdate {
  action: "start" | "stop";
}

// ─── Backup ───────────────────────────────────────────────────────────────────

export interface Backup {
  id: string;
  instance_id: string;
  backup_type: BackupType;
  strategy: BackupStrategy;
  status: BackupStatus;
  file_path: string | null;
  size_bytes: number | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  expires_at: string | null;
}

export interface BackupSchedule {
  id: string;
  instance_id: string;
  strategy: BackupStrategy;
  cron_expression: string;
  retention_days: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  last_run_at: string | null;
  next_run_at: string | null;
}

// ─── Metrics ──────────────────────────────────────────────────────────────────

export interface MetricsSnapshot {
  instance_id: string;
  metrics: Record<string, number>;
  collected_at: string | null;
}

export interface HealthCheck {
  instance_id: string;
  status: "healthy" | "unhealthy";
  response_time_ms: number;
  checked_at: string;
}

export interface SlowQuery {
  query: string;
  calls: number;
  total_exec_time_ms: number;
  mean_exec_time_ms: number;
  rows: number;
  cache_hit_ratio: number;
}

export interface SlowQueriesResponse {
  instance_id: string;
  queries: SlowQuery[];
}

export interface LockInfo {
  pid: number;
  table: string | null;
  mode: string;
  granted: boolean;
  locktype: string;
}

export interface LocksResponse {
  instance_id: string;
  locks: LockInfo[];
  has_blocked_queries: boolean;
}

// ─── Maintenance ─────────────────────────────────────────────────────────────

export interface MaintenanceTask {
  id: string;
  instance_id: string;
  task_type: TaskType;
  status: TaskStatus;
  target_table: string | null;
  scheduled_at: string;
  started_at: string | null;
  completed_at: string | null;
  result_summary: string | null;
}

export interface MaintenanceSchedule {
  id: string;
  instance_id: string;
  task_type: TaskType;
  cron_expression: string;
  is_active: boolean;
  next_run_at: string | null;
  created_at: string;
}

// ─── Alerts ───────────────────────────────────────────────────────────────────

export interface AlertRule {
  id: string;
  instance_id: string;
  name: string;
  metric_type: AlertMetricType;
  condition: AlertCondition;
  threshold: number;
  severity: AlertSeverity;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface AlertEvent {
  id: string;
  rule_id: string;
  instance_id: string;
  triggered_at: string;
  resolved_at: string | null;
  current_value: number;
  message: string;
}

// ─── Admin ────────────────────────────────────────────────────────────────────

export interface AuditLog {
  id: string;
  user_id: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  details: Record<string, unknown> | null;
  ip_address: string | null;
  timestamp: string;
}

export interface DashboardSummary {
  total_instances: number;
  instances_by_status: Partial<Record<InstanceStatus, number>>;
  active_alerts: number;
  backups_last_24h: number;
  failed_backups_last_24h: number;
  pending_maintenance_tasks: number;
}
