import { apiRequest } from "./api";

export interface ModelItem {
  id: string;
  model_name: string;
  base_url: string;
}

export interface ModelsResponse {
  items: ModelItem[];
  selected_id: string | null;
}

export function listModels(): Promise<ModelsResponse> {
  return apiRequest<ModelsResponse>("/models");
}

export function selectModel(id: string): Promise<{ selected_id: string }> {
  return apiRequest<{ selected_id: string }>("/models/selected", {
    method: "PUT",
    body: JSON.stringify({ id }),
  });
}
