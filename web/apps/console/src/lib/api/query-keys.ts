// typed query-key factory for @tanstack/react-query. each domain owns its own
// namespace so invalidations stay surgical (queryClient.invalidateQueries(
// {queryKey: queryKeys.experiments.all}) rebuilds every experiment query).

type ListParams = {
  limit?: number;
  offset?: number;
  search?: string;
  enabled?: boolean;
};

type WindowParams = {
  start_ms?: number;
  end_ms?: number;
};

type BucketParams = WindowParams & {
  interval_ms?: number;
};

export const queryKeys = {
  // resource: experiments
  experiments: {
    all: ["experiments"] as const,
    list: (params?: ListParams) => ["experiments", "list", params ?? {}] as const,
    detail: (id: string) => ["experiments", "detail", id] as const,
  },

  // resource: pools
  pools: {
    all: ["pools"] as const,
    list: (params?: { limit?: number; offset?: number }) =>
      ["pools", "list", params ?? {}] as const,
    detail: (id: string) => ["pools", "detail", id] as const,
    experiments: (id: string) => ["pools", id, "experiments"] as const,
  },

  // resource: gates (per experiment)
  gates: {
    all: ["gates"] as const,
    detail: (experimentId: string) => ["gates", experimentId] as const,
  },

  // resource: policies (introspection)
  policies: {
    all: ["policies"] as const,
    list: (rewardType?: string) => ["policies", "list", rewardType ?? null] as const,
  },

  // resource: runtime diagnostics
  runtime: {
    all: ["runtime"] as const,
    redisHealth: ["runtime", "health", "redis"] as const,
    motorHealth: ["runtime", "health", "motor"] as const,
    cortexHealth: ["runtime", "health", "cortex"] as const,
    streamSize: ["runtime", "stream", "size"] as const,
  },

  // resource: insights (EE)
  insights: {
    all: ["insights"] as const,
    experiment: (id: string, window?: WindowParams) =>
      ["insights", id, "stats", window ?? {}] as const,
    timeseries: (id: string, params: BucketParams) =>
      ["insights", id, "timeseries", params] as const,
    arms: (id: string, window?: WindowParams) =>
      ["insights", id, "arms", window ?? {}] as const,
    rewards: (id: string, params: BucketParams) =>
      ["insights", id, "rewards", params] as const,
    armSeries: (id: string, params: BucketParams) =>
      ["insights", id, "arm-series", params] as const,
    funnel: (id: string, window?: WindowParams) =>
      ["insights", id, "funnel", window ?? {}] as const,
    cumulative: (id: string, params: BucketParams) =>
      ["insights", id, "cumulative", params] as const,
    // workspace-wide, so it is not nested under an experiment id — and it is
    // deliberately not `insights.all`-invalidated any differently: a mutation
    // that dirties one experiment's arms dirties this too.
    workspaceArms: (window?: WindowParams) =>
      ["insights", "workspace", "arms", window ?? {}] as const,
  },

  // resource: events (EE)
  events: {
    all: ["events"] as const,
    list: (params?: {
      category?: string;
      resource_id?: string;
      start_ms?: number;
      end_ms?: number;
      limit?: number;
      offset?: number;
    }) => ["events", "list", params ?? {}] as const,
    selection: (id: string, params?: { limit?: number; offset?: number }) =>
      ["events", "selection", id, params ?? {}] as const,
    selectionDetail: (requestId: string) =>
      ["events", "selection-detail", requestId] as const,
    feedback: (id: string, params?: { limit?: number; offset?: number }) =>
      ["events", "feedback", id, params ?? {}] as const,
    audit: (params: {
      resource_id?: string;
      resource_type?: string;
      name?: string;
      limit?: number;
      offset?: number;
    }) => ["events", "audit", params] as const,
    experimentActivity: (
      id: string,
      params?: {
        category?: string;
        since_ms?: number;
        until_ms?: number | null;
        limit?: number;
        offset?: number;
      }
    ) => ["events", "experiment-activity", id, params ?? {}] as const,
  },

  // resource: the deployment itself, readable before anyone signs in
  deployment: {
    all: ["deployment"] as const,
    config: ["deployment", "config"] as const,
  },

  // resource: workspace + auth
  workspace: {
    all: ["workspace"] as const,
    current: ["workspace", "current"] as const,
    members: (params?: { limit?: number; offset?: number }) =>
      ["workspace", "members", params ?? {}] as const,
    invites: (params?: {
      limit?: number;
      offset?: number;
      invite_status?: string;
    }) => ["workspace", "invites", params ?? {}] as const,
  },

  apiKeys: {
    all: ["api-keys"] as const,
    list: ["api-keys", "list"] as const,
  },

  // resource: users (admin)
  users: {
    all: ["users"] as const,
    list: (params?: {
      limit?: number;
      offset?: number;
      search?: string;
      role?: string;
      status_filter?: string;
    }) => ["users", "list", params ?? {}] as const,
    stats: ["users", "stats"] as const,
  },

  // resource: billing (EE)
  billing: {
    all: ["billing"] as const,
    subscription: ["billing", "subscription"] as const,
    invoices: ["billing", "invoices"] as const,
  },
} as const;
