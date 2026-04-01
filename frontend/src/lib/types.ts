export interface Palette {
  id: number;
  name: string;
  colors: string[];
  created_at?: number;
}

export interface Generation {
  id: number;
  prompt: string;
  system_prompt?: string;
  palette_id: number;
  palette_name?: string;
  size: number;
  model?: string;
  sprite_type?: string;
  reference_id?: string;
  pixel_data?: number[][];
  iterations?: number;
  status: string;
  image_path?: string;
  created_at?: number;
  palette?: string[];
  logs?: LogEntry[];
}

export interface LogEntry {
  id: number;
  generation_id: number;
  step: string;
  message: string;
  created_at?: number;
}

export interface Settings {
  system_prompt: string;
  models: string[];
  default_model: string;
  image_models: string[];
  default_image_model: string;
  sprite_types: Record<string, { label: string; has_tileset: boolean }>;
}

export interface SSEEvent {
  type: "log" | "pixels" | "complete" | "error";
  data: any;
}
