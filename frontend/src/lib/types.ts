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
  /** Usable rectangle of a non-square design (null/undefined = square, size x size). */
  width?: number | null;
  height?: number | null;
  model?: string;
  sprite_type?: string;
  reference_id?: string;
  pixel_data?: number[][];
  /** The design's own palette (stored per generation). */
  colors?: string[] | null;
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

export interface AgentInfo {
  cli_version: string | null;
  cli_command: string;
  project_dir: string;
  data_dir: string;
  source_label: string;
}

export interface SSEEvent {
  type: "log" | "pixels" | "complete" | "error";
  data: any;
}
