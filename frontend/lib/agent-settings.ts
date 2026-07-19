import { apiRequest } from "./api";

export interface AgentSetting {
  id: string;
  label: string;
  model_id: string | null;
  soft_prompt: string | null;
}

export interface AgentSettingsResponse {
  agents: AgentSetting[];
}

export interface AgentSettingUpdate {
  id: string;
  model_id?: string | null;
  soft_prompt?: string | null;
}

export function getAgentSettings(): Promise<AgentSettingsResponse> {
  return apiRequest<AgentSettingsResponse>("/agent-settings");
}

export function saveAgentSettings(
  agents: AgentSettingUpdate[],
): Promise<AgentSettingsResponse> {
  return apiRequest<AgentSettingsResponse>("/agent-settings", {
    method: "PUT",
    body: JSON.stringify({ agents }),
  });
}
