export type Status = "Pending" | "Checking" | "Reject" | "Safety" | "Approve";
export type AgentState = "Idle" | "Thinking" | "Working" | "Completed";
export type AgentKey = "planner" | "transaction" | "report" | "kyc";

export const stats = [
  {key: "pending", value: 128, color: "yellow"},
  {key: "checking", value: 64, color: "blue"},
  {key: "reject", value: 21, color: "red"},
  {key: "approve", value: 312, color: "green"},
] as const;

export const flowData = [
  {day: "mon", volume: 12800, flagged: 420},
  {day: "tue", volume: 15200, flagged: 610},
  {day: "wed", volume: 14150, flagged: 520},
  {day: "thu", volume: 17800, flagged: 740},
  {day: "fri", volume: 16900, flagged: 690},
  {day: "sat", volume: 19400, flagged: 910},
  {day: "sun", volume: 21300, flagged: 860},
] as const;

export const investigations: Array<{
  id: string;
  status: Status;
  account: string;
  actionKey: string;
}> = [
  {id: "AML-2408-1182", status: "Pending", account: "US-4830-****-9921", actionKey: "awaitingPlanner"},
  {id: "AML-2408-1183", status: "Checking", account: "SG-1190-****-0384", actionKey: "tracingLayers"},
  {id: "AML-2408-1184", status: "Safety", account: "GB-7201-****-5509", actionKey: "releasedKyc"},
  {id: "AML-2408-1185", status: "Reject", account: "VN-8812-****-4402", actionKey: "manualReview"},
  {id: "AML-2408-1186", status: "Checking", account: "DE-4408-****-7102", actionKey: "fanIn"},
  {id: "AML-2408-1187", status: "Pending", account: "US-5510-****-2208", actionKey: "riskScoring"},
];

export const agents: Array<{
  key: AgentKey;
  status: AgentState;
  health: string;
  latency: string;
  tasks: number;
  utilization: number;
  data: Array<{v: number}>;
}> = [
  {key: "planner", status: "Thinking", health: "99.8%", latency: "112 ms", tasks: 1248, utilization: 62, data: [{v: 14}, {v: 18}, {v: 16}, {v: 24}, {v: 23}, {v: 30}, {v: 28}]},
  {key: "transaction", status: "Working", health: "98.6%", latency: "184 ms", tasks: 984, utilization: 78, data: [{v: 20}, {v: 22}, {v: 18}, {v: 27}, {v: 31}, {v: 29}, {v: 35}]},
  {key: "report", status: "Idle", health: "100%", latency: "88 ms", tasks: 602, utilization: 34, data: [{v: 8}, {v: 11}, {v: 9}, {v: 14}, {v: 12}, {v: 16}, {v: 15}]},
  {key: "kyc", status: "Completed", health: "99.1%", latency: "136 ms", tasks: 1096, utilization: 55, data: [{v: 12}, {v: 15}, {v: 18}, {v: 16}, {v: 21}, {v: 20}, {v: 24}]},
];

export const activityFeed: Record<AgentKey, Array<[string, string]>> = {
  planner: [["09:42", "fetchingHistory"], ["09:43", "prioritizingRisk"], ["09:44", "routingAccounts"]],
  transaction: [["09:41", "tracingFunds"], ["09:43", "detectingFanIn"], ["09:45", "calculatingMetrics"]],
  report: [["09:38", "reportOutline"], ["09:40", "evidenceSummary"], ["09:46", "plannerApproval"]],
  kyc: [["09:37", "matchingOwners"], ["09:39", "screeningAliases"], ["09:44", "identityScore"]],
};

export const models = ["AML-Core-v2.1", "Graph-Net-Alpha", "Velocity-Engine-X", "Reasoning-Pro"];

export const statusStyles: Record<Status, string> = {
  Pending: "bg-amber-50 text-amber-700 ring-amber-200",
  Checking: "bg-blue-50 text-blue-700 ring-blue-200",
  Reject: "bg-red-50 text-red-700 ring-red-200",
  Safety: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  Approve: "bg-emerald-50 text-emerald-700 ring-emerald-200",
};
