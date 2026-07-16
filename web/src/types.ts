export type EffectMode =
  | "OFF"
  | "BLINK_RED"
  | "BLINK_GREEN"
  | "BLINK_BLUE"
  | "SOLID_BLUE";

export interface NodeView {
  node_id: string;
  mac: string;
  ip: string;
  port: number;
  rssi: number;
  firmware_version: string;
  uptime_ms: number;
  mode: EffectMode;
  period_ms: number;
  requested_brightness: number;
  actual_brightness: number;
  session_id: number;
  last_sequence: number;
  state: string;
  last_seen_ms: number;
  online: boolean;
  id_conflict: boolean;
}

export interface LayoutCell {
  row: number;
  column: number;
  node_id: string | null;
}

export interface Layout {
  rows: number;
  columns: number;
  cells: LayoutCell[];
}

export interface CommandResult {
  sequence: number;
  apply_at_ms: number;
  results: Record<string, string>;
}

export interface OtaJob {
  id: string;
  state: string;
  sha256: string;
  size: number;
  results: Record<string, string>;
}

