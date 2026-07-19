export type WorkflowNodeKind = "agent";
export type WorkflowNodeIcon =
  | "planner"
  | "transaction"
  | "kyc"
  | "screening"
  | "behavior"
  | "report";

export interface WorkflowNodeDefinition {
  [key: string]: unknown;
  id: string;
  name: string;
  kind: WorkflowNodeKind;
  role: string;
  stage: string;
  icon: WorkflowNodeIcon;
  position: { x: number; y: number };
}

export interface WorkflowEdgeDefinition {
  id: string;
  source: string;
  target: string;
  label?: string;
}

/** Top-to-bottom layout: planner → (TX | KYC) → screening → behavior → report */
export const WORKFLOW_NODES: readonly WorkflowNodeDefinition[] = [
  {
    id: "planner",
    name: "Planner Agent",
    kind: "agent",
    role: "Lập kế hoạch điều tra bắt buộc và xác định các nhánh bằng chứng cần thu thập.",
    stage: "Planning",
    icon: "planner",
    position: { x: 180, y: 0 },
  },
  {
    id: "transaction_agent",
    name: "Transaction Agent",
    kind: "agent",
    role: "Truy vết dòng tiền, cấu trúc giao dịch và các mẫu hành vi đáng ngờ.",
    stage: "Parallel investigation",
    icon: "transaction",
    position: { x: 0, y: 160 },
  },
  {
    id: "kyc_agent",
    name: "KYC Agent",
    kind: "agent",
    role: "Điều tra hồ sơ khách hàng, thực thể và quan hệ sở hữu liên quan.",
    stage: "Parallel investigation",
    icon: "kyc",
    position: { x: 360, y: 160 },
  },
  {
    id: "screening_agent",
    name: "Screening Agent",
    kind: "agent",
    role: "Kiểm tra watchlist và phân loại kết quả screening theo bằng chứng công cụ.",
    stage: "Screening",
    icon: "screening",
    position: { x: 180, y: 320 },
  },
  {
    id: "behavior_mapper",
    name: "Behavior Mapper Agent",
    kind: "agent",
    role: "Chuyển findings đã có thành hành vi và truy vấn pháp lý có liên kết bằng chứng.",
    stage: "Legal enrichment",
    icon: "behavior",
    position: { x: 180, y: 480 },
  },
  {
    id: "report_agent",
    name: "Report Agent",
    kind: "agent",
    role: "Tổng hợp hồ sơ rủi ro cuối cùng từ case file và evidence đã được kiểm định.",
    stage: "Reporting",
    icon: "report",
    position: { x: 180, y: 640 },
  },
] as const;

export const LLM_AGENTS = WORKFLOW_NODES.filter(
  (node) => node.kind === "agent",
);

export const WORKFLOW_EDGES: readonly WorkflowEdgeDefinition[] = [
  { id: "planner-transaction", source: "planner", target: "transaction_agent" },
  { id: "planner-kyc", source: "planner", target: "kyc_agent" },
  { id: "transaction-screening", source: "transaction_agent", target: "screening_agent" },
  { id: "kyc-screening", source: "kyc_agent", target: "screening_agent" },
  { id: "screening-behavior", source: "screening_agent", target: "behavior_mapper" },
  { id: "behavior-report", source: "behavior_mapper", target: "report_agent" },
] as const;
