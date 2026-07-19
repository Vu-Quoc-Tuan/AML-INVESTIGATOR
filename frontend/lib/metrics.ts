import { apiRequest } from "./api";

export interface FlowTrendPoint {
  date: string;
  day: string;
  queued: number;
  blocked: number;
  volume: number;
  flagged: number;
}

export interface FlowTrendsResponse {
  days: number;
  items: FlowTrendPoint[];
}

export function getFlowTrends(days = 7): Promise<FlowTrendsResponse> {
  return apiRequest<FlowTrendsResponse>(`/metrics/flow-trends?days=${days}`);
}
