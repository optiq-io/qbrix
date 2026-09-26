export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
    public readonly code?: string,
    public readonly context?: Record<string, unknown>,
    /** seconds, from the Retry-After header on a 429 */
    public readonly retryAfter?: number,
  ) {
    super(`api error ${status}: ${detail}`);
    this.name = "ApiError";
  }
}

/** the tenant's own row from the backend's PLAN_LIMITS. -1 means unlimited. */
export interface PlanLimits {
  included_selections_per_month: number;
  max_api_keys: number;
  max_seats: number;
  max_active_experiments: number;
}

/** workspace-wide counts, not the caller's own */
export interface TenantUsage {
  api_keys: number;
  /** members + pending invites, which is what the seat cap counts */
  seats: number;
  active_experiments: number;
  selections_this_period?: number;
  period_start?: number;
  period_end?: number;
}

/** which build of the backend answered — `Entitlements.edition` */
export type Edition = "oss" | "cloud";

/** GET /auth/config — the only unauthenticated view of the deployment */
export type AuthConfig = {
  signup_open: boolean;
  edition: Edition;
  email_enabled: boolean;
};

// Authentication
export interface User {
  id: string;
  email: string;
  name?: string;
  /** null outside the cloud edition, where no tier is sold */
  plan_tier: "free" | "starter" | "growth" | "scale" | "enterprise" | null;
  role: "admin" | "member" | "viewer";
  created_at: number;
  is_active: boolean;
  email_verified: boolean;
  edition: Edition;
  // what this deployment grants and what it sells but withholds. bounded by
  // what the deployment actually runs, so a feature can be in neither.
  features?: string[];
  locked_features?: string[];
  limits?: PlanLimits;
  /** only on register/login/profile responses */
  usage?: TenantUsage;
}

export interface LoginResponse {
  user: User;
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export type LoginRequest =
  | { email: string; password: string }
  | { api_key: string };

export interface RegisterRequest {
  name: string;
  email: string;
  password: string;
  workspace_name?: string;
  workspace_slug?: string;
}

// Invites
export interface Invite {
  id: string;
  email: string;
  role: string;
  status: string;
  token?: string;
  invite_url?: string;
  invited_by: string;
  expires_at: number;
  created_at: number;
}

export interface InviteCreateRequest {
  email: string;
  role?: "admin" | "member" | "viewer";
}

export interface InviteListResponse {
  invites: Invite[];
  limit: number;
  offset: number;
}

export interface InviteAcceptRequest {
  name: string;
  password: string;
}

export interface InviteValidationResponse {
  email: string;
  role: string;
  workspace_name: string;
  expires_at: number;
}

// Context schema — mirrors lib/core/qbrixcore/context_schema.py. the shape an
// experiment declares once at creation; the API derives `dim` from it and
// refuses to change it afterwards.
export type ContextProperty =
  | { type: "categorical"; name: string; values: string[] }
  | { type: "numeric"; name: string; min: number; max: number }
  | { type: "boolean"; name: string };

export type ContextSchema = ContextProperty[];

export const MAX_CONTEXT_DIM = 64;

// every encoding opens with one constant slot, and each categorical carries a
// trailing `other` for values the schema has not seen. both cost width and
// neither is authored, so the arithmetic only adds up if they are counted here.
export const BASELINE_WIDTH = 1;

export function propertyWidth(p: ContextProperty): number {
  return p.type === "categorical" ? p.values.length + 1 : 1;
}

export function schemaWidth(schema: ContextSchema): number {
  return BASELINE_WIDTH + schema.reduce((sum, p) => sum + propertyWidth(p), 0);
}

// Experiments
export interface Experiment {
  id: string;
  name: string;
  pool_id: string;
  policy: string;
  policy_params: Record<string, unknown>;
  enabled: boolean;
  created_at?: string;
  updated_at?: string;
  pool?: Pool;
  feature_gate?: GateConfigResponse | null;
  meta_experiment_id?: string | null;
}

export interface ExperimentCreateRequest {
  name: string;
  pool_id: string;
  policy: string;
  policy_params?: Record<string, unknown>;
  enabled?: boolean;
  feature_gate?: {
    enabled?: boolean;
    rollout_percentage?: number;
    default_arm_id?: string | null;
    timezone?: string;
    schedule_start?: string | null;
    schedule_end?: string | null;
    active_hours_start?: string | null;
    active_hours_end?: string | null;
    rules?: { key: string; operator: string; value: unknown; arm_id?: string | null }[];
  };
}

export interface ExperimentUpdateRequest {
  enabled?: boolean;
  policy_params?: Record<string, unknown>;
}

export interface ExperimentListResponse {
  experiments: Experiment[];
  limit: number;
  offset: number;
}

// Pools and Arms
export interface Arm {
  id: string;
  name: string;
  index: number;
  is_active: boolean;
  metadata: Record<string, unknown>;
}

export interface Pool {
  id: string;
  name: string;
  arms: Arm[];
  created_at?: string;
  updated_at?: string;
}

export interface PoolCreateRequest {
  name: string;
  arms: { name: string; metadata?: Record<string, unknown> }[];
}

export interface PoolUpdateRequest {
  name?: string;
}

export interface PoolListResponse {
  pools: Pool[];
  limit: number;
  offset: number;
}

// Feature Gates
export interface GateRule {
  id?: string;
  key: string;
  operator: "eq" | "neq" | "gt" | "gte" | "lt" | "lte" | "in" | "not_in" | "contains" | "not_contains";
  value: unknown;
  arm_id: string | null;
  priority?: number;
}

export interface GateRuleResponse {
  key: string;
  operator: string;
  value: unknown;
  arm_id: string | null;
  arm_name: string | null;
}

export interface GateConfigResponse {
  experiment_id: string;
  enabled: boolean;
  rollout_percentage: number;
  default_arm_id: string | null;
  default_arm_name: string | null;
  schedule_start: string | null;
  schedule_end: string | null;
  active_hours_start: string | null;
  active_hours_end: string | null;
  timezone: string;
  rules: GateRuleResponse[];
  updated_at?: string;
  version: number;
}

// a field present here is written; a field absent is left as stored, since
// updateConfig PATCHes. createConfig still needs the full picture.
export interface GateUpdateRequest {
  enabled?: boolean;
  rollout_percentage?: number;
  default_arm_id?: string | null;
  schedule_start?: string | null;
  schedule_end?: string | null;
  active_hours_start?: string | null;
  active_hours_end?: string | null;
  timezone?: string;
  rules?: {
    key: string;
    operator: string;
    value: unknown;
    arm_id?: string | null;
    arm_name?: string | null;
  }[];
}

export interface GateEvaluateRequest {
  context_id: string;
  context_metadata: Record<string, unknown>;
}

export interface GateRuleEvaluation {
  key: string;
  operator: string;
  value: unknown;
  matched: boolean;
  /** the rule that actually decided the outcome, when one did */
  decisive: boolean;
}

export interface GateEvaluateResponse {
  /** true when the bandit would select — not a synonym for "rules passed" */
  eligible: boolean;
  reason: "disabled" | "blackout" | "rollout" | "rule" | "bandit";
  arm_id: string | null;
  arm_name: string | null;
  enabled: boolean;
  in_schedule: boolean;
  in_rollout: boolean;
  rollout_percentage: number;
  rules: GateRuleEvaluation[];
}

// Policies
export interface PolicyParam {
  name: string;
  type: "number" | "integer";
  required: boolean;
  default: number | null;
  description: string;
  constraints: Record<string, number>;
}

export interface Policy {
  name: string;
  category: "stochastic" | "contextual" | "adversarial" | "meta";
  reward_types: string[];
  description: string;
  user_params: PolicyParam[];
}

export interface PoliciesListResponse {
  policies: Policy[];
}

// Settings
export interface UpdateProfileRequest {
  name?: string;
  email?: string;
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}

export interface DeleteAccountRequest {
  password: string;
}

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  created_at: number;
  member_count: number;
}

export interface UpdateWorkspaceRequest {
  name?: string;
  slug?: string;
}

export interface UserStats {
  admin: number;
  member: number;
  viewer: number;
}

// API Keys
export interface APIKey {
  id: string;
  name: string;
  key?: string;
  rate_limit_per_minute: number;
  scopes: string[];
  is_active: boolean;
  created_at: number;
  last_used_at?: number;
}

export interface APIKeyCreateResponse {
  id: string;
  name: string;
  key: string;
  rate_limit_per_minute: number;
  scopes: string[];
  created_at: number;
  is_active: boolean;
}

export interface APIKeyCreateRequest {
  name: string;
}

export interface UpdateAPIKeyRequest {
  name: string;
}

export interface UpdateUserStatusRequest {
  is_active: boolean;
}

// User list responses (BE returns named keys, not generic items)
export interface UserListResponse {
  users: User[];
  limit: number;
  offset: number;
}

// Generic pagination (used for experiments/pools list wrappers)
export interface PaginatedList<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

// Runtime health
export interface ServiceHealthResponse {
  service: string;
  status: string;
}

export interface StreamLengthResponse {
  len: number;
}

// Insights
export type InsightParams = {
  interval_ms: number;
  start_ms?: number;
  end_ms?: number;
};

export interface ExperimentStatsResponse {
  experiment_id: string;
  total_selections: number;
  default_selections: number;
  unique_contexts: number;
  first_selection_ms: number | null;
  last_selection_ms: number | null;
  total_feedback: number;
  avg_reward: number | null;
  min_reward: number | null;
  max_reward: number | null;
}

export interface TimeseriesPoint {
  timestamp_ms: number;
  selections: number;
  default_selections: number;
}

export interface TimeseriesResponse {
  experiment_id: string;
  interval_ms: number;
  data: TimeseriesPoint[];
}

export interface RewardTimeseriesPoint {
  timestamp_ms: number;
  avg_reward: number;
  feedback_count: number;
}

export interface RewardTimeseriesResponse {
  data: RewardTimeseriesPoint[];
}

export interface ArmTimeseriesArm {
  arm_index: number;
  arm_name: string;
  selections: number;
}

export interface ArmTimeseriesPoint {
  timestamp_ms: number;
  arms: ArmTimeseriesArm[];
}

export interface ArmTimeseriesResponse {
  data: ArmTimeseriesPoint[];
}

export interface ArmStats {
  arm_index: number;
  arm_name: string;
  selections: number;
  feedback_count: number;
  avg_reward: number | null;
}

export interface ArmAnalyticsResponse {
  experiment_id: string;
  arms: ArmStats[];
}

export interface WorkspaceArmStatsResponse {
  experiments: ArmAnalyticsResponse[];
}

export interface FeedbackFunnelResponse {
  total_selections: number;
  total_feedback: number;
  feedback_rate: number;
}

export interface CumulativeRewardPoint {
  timestamp_ms: number;
  cumulative_reward: number;
  cumulative_count: number;
}

export interface CumulativeRewardResponse {
  data: CumulativeRewardPoint[];
}

// Events
export interface UnifiedEvent {
  name: string;
  tenant_id: string;
  resource_id: string;
  timestamp_ms: number;
  category: string;
  data: Record<string, unknown>;
}

export interface UnifiedEventListResponse {
  events: UnifiedEvent[];
  limit: number;
  offset: number;
}

export interface SelectionEvent {
  tenant_id: string;
  experiment_id: string;
  request_id: string;
  arm_id: string;
  arm_name: string;
  arm_index: number;
  is_default: boolean;
  context_id: string;
  timestamp_ms: number;
  policy: string;
}

export interface FeedbackEvent {
  tenant_id: string;
  experiment_id: string;
  request_id: string;
  arm_index: number;
  reward: number;
  context_id: string;
  timestamp_ms: number;
}

export interface SelectionDetailResponse {
  selection: SelectionEvent | null;
  feedback: FeedbackEvent | null;
}

export interface AuditEvent {
  name: string;
  tenant_id: string;
  actor_id: string;
  resource_type: string;
  resource_id: string;
  payload: string;
  timestamp_ms: number;
}
