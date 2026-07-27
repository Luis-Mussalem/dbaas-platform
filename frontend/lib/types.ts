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

// Logical environment of the instance (mirrors the backend's Environment enum).
export type Environment = "production" | "staging" | "development";

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

export type UserRole = "admin" | "member";

// Company (tenant). Multi-tenant: a regular user belongs to one company;
// the superuser has no single company (company = null) and sees all of them.
export interface Company {
  id: string;
  name: string;
  created_at: string;
}

export interface User {
  id: string;
  email: string;
  is_active: boolean;
  is_superuser: boolean;
  role: UserRole;
  company_id: string | null;
  company: Company | null;
  created_at: string;
  updated_at: string;
  // Only populated by the admin listing (GET /users) — MAX(timestamp) in audit_logs.
  last_activity?: string | null;
}

export interface UserAdminCreate {
  email: string;
  password: string;
  company_id?: string;
  is_superuser?: boolean;
  role?: UserRole;
}

export interface UserAdminUpdate {
  email?: string;
  is_active?: boolean;
  is_superuser?: boolean;
  company_id?: string | null;
  role?: UserRole;
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
  region: string | null;
  environment: Environment | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

// Aggregated per-instance state, for the fleet cards. Every field is optional:
// a new or stopped instance doesn't yet have collection/alerts/backup, and the card shows
// "—" instead of zero (which would be a false statement).
export interface InstanceSummary {
  instance_id: string;
  connections_active: number | null;
  connections_max: number | null;
  queries_per_second: number | null;
  p95_latency_ms: number | null;
  db_size_bytes: number | null;
  size_delta_24h_bytes: number | null;
  open_alerts: number;
  max_alert_severity: AlertSeverity | null;
  last_backup_at: string | null;
  last_backup_status: BackupStatus | null;
  uptime_30d_pct: number | null;
}

export interface FleetSummary {
  instances: InstanceSummary[];
}

export interface InstanceCreate {
  name: string;
  engine_version?: "14" | "15" | "16" | "17";
  cpu?: number;
  memory_mb?: number;
  storage_gb?: number;
  region?: string;
  environment?: Environment;
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

export type MetricWindow = "15m" | "1h" | "6h" | "24h";

export interface MetricHistoryPoint {
  collected_at: string;
  value: number;
}

export interface MetricHistoryResponse {
  instance_id: string;
  metric_name: string;
  window: MetricWindow;
  points: MetricHistoryPoint[];
}

export interface ActiveConnection {
  pid: number;
  user: string | null;
  state: string | null;
  wait_event: string | null;
  duration_seconds: number | null;
  query: string | null;
}

export interface ActiveConnectionsResponse {
  instance_id: string;
  connections: ActiveConnection[];
}

export interface SchemaTable {
  table: string;
  estimated_rows: number;
}

export interface SchemaGroup {
  name: string;
  tables: SchemaTable[];
}

export interface SchemaResponse {
  instance_id: string;
  schemas: SchemaGroup[];
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

// ─── SQL Console ───────────────────────────────────────────────────────────────

// Result of a read-only SELECT (POST /instances/{id}/query).
// Cells arrive as string | null: the backend converts every value to text
// (None preserved) to avoid serialization pitfalls — a console displays text anyway.
export interface QueryResult {
  instance_id: string;
  columns: string[];
  rows: (string | null)[][];
  row_count: number;
  truncated: boolean;
}

// Execution plan (POST /instances/{id}/explain). `plan` is the raw JSON from
// EXPLAIN (FORMAT JSON); we display it formatted, without typing it node by node.
export interface ExplainResponse {
  instance_id: string;
  plan: unknown[];
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
  user_email: string | null;
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
  // Fleet performance KPIs (derived from real data; p95/uptime can be
  // null while there aren't samples yet — the UI shows "—").
  queries_per_second: number;
  p95_latency_ms: number | null;
  fleet_uptime_pct: number | null;
}

// ─── Replication (PHASE 9) ────────────────────────────────────────────────────

export type ReplicationState =
  | "pending"
  | "provisioning"
  | "streaming"
  | "catchup"
  | "disconnected"
  | "promoted"
  | "failed";

// Summary of the standby embedded in the Replica (name/status/port in the fleet).
export interface ReplicaInstanceInfo {
  id: string;
  name: string;
  status: InstanceStatus;
  host: string | null;
  port: number | null;
}

export interface Replica {
  id: string;
  primary_instance_id: string;
  replica_instance_id: string;
  replication_state: ReplicationState;
  lag_bytes: number | null;
  lag_seconds: number | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  replica_instance: ReplicaInstanceInfo | null;
}
