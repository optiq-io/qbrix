import { apiFetch, buildQueryString } from "./client";
import type {
  InsightParams,
  ExperimentStatsResponse,
  TimeseriesResponse,
  RewardTimeseriesResponse,
  ArmTimeseriesResponse,
  ArmAnalyticsResponse,
  WorkspaceArmStatsResponse,
  FeedbackFunnelResponse,
  CumulativeRewardResponse,
} from "./types";

export const insights = {
  getStats: (experimentId: string, params?: Partial<InsightParams>) =>
    apiFetch<ExperimentStatsResponse>(
      `/v1/insight/experiment/${experimentId}${buildQueryString(params)}`
    ),

  getTimeseries: (experimentId: string, params: InsightParams) =>
    apiFetch<TimeseriesResponse>(
      `/v1/insight/experiment/${experimentId}/timeseries${buildQueryString(params)}`
    ),

  getRewardTimeseries: (experimentId: string, params: InsightParams) =>
    apiFetch<RewardTimeseriesResponse>(
      `/v1/insight/experiment/${experimentId}/timeseries/rewards${buildQueryString(params)}`
    ),

  getArmTimeseries: (experimentId: string, params: InsightParams) =>
    apiFetch<ArmTimeseriesResponse>(
      `/v1/insight/experiment/${experimentId}/timeseries/arms${buildQueryString(params)}`
    ),

  getArmStats: (experimentId: string, params?: Partial<InsightParams>) =>
    apiFetch<ArmAnalyticsResponse>(
      `/v1/insight/experiment/${experimentId}/arms${buildQueryString(params)}`
    ),

  getFeedbackFunnel: (experimentId: string, params?: Partial<InsightParams>) =>
    apiFetch<FeedbackFunnelResponse>(
      `/v1/insight/experiment/${experimentId}/funnel${buildQueryString(params)}`
    ),

  getCumulativeReward: (experimentId: string, params: InsightParams) =>
    apiFetch<CumulativeRewardResponse>(
      `/v1/insight/experiment/${experimentId}/cumulative${buildQueryString(params)}`
    ),

  // every experiment's arms in one request. tenant-scoped, so it does not wait
  // on the experiment list the way `getArmStats` per id had to — the two go out
  // together and are joined here.
  getWorkspaceArmStats: (params?: Partial<InsightParams>) =>
    apiFetch<WorkspaceArmStatsResponse>(
      `/v1/insight/workspace/arms${buildQueryString(params)}`
    ),
};
