import { apiFetch, buildQueryString } from "./client";
import type {
  UnifiedEventListResponse,
  SelectionDetailResponse,
} from "./types";

export interface EventListParams {
  category?: string;
  resource_id?: string;
  start_ms?: number;
  end_ms?: number;
  limit?: number;
  offset?: number;
  [key: string]: unknown;
}

export interface ExperimentActivityParams {
  category?: string;
  since_ms?: number;
  /** exclusive upper bound. offset paging is only stable under one — the feed
      grows at the head, so an unbounded window shifts under every page. */
  until_ms?: number;
  limit?: number;
  offset?: number;
  [key: string]: unknown;
}

export const events = {
  list: (params?: EventListParams) =>
    apiFetch<UnifiedEventListResponse>(
      `/v1/event${buildQueryString(params)}`
    ),

  experimentActivity: (experimentId: string, params?: ExperimentActivityParams) =>
    apiFetch<UnifiedEventListResponse>(
      `/v1/event/experiment/${experimentId}/activity${buildQueryString(params)}`
    ),

  getSelectionDetail: (requestId: string) =>
    apiFetch<SelectionDetailResponse>(
      `/v1/event/selection/${requestId}`
    ),
};
