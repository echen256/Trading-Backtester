export interface DatasetMetadata {
  schema_version: 'trading-market-dataset/v1'
  id: string
  asset_class: string
  symbol: string
  base_asset: string | null
  quote_asset: string | null
  venue: string | null
  interval_seconds: number
  timezone: string
  calendar: string | null
  adjustment: string | null
  source: { provider: string; path: string; fingerprint: string }
  quality: {
    row_count: number
    first_timestamp: string | null
    last_timestamp: string | null
    duplicates_removed: number
    missing_intervals: number
    gap_ranges: Array<Record<string, unknown>>
    warnings: string[]
  }
}

export interface Bar {
  time: string
  open: number
  high: number
  low: number
  close: number
  volume: number | null
}

export interface BarsResponse {
  dataset_id: string
  symbol: string
  native_interval_seconds: number
  response_interval_seconds: number
  aggregated: boolean
  count: number
  bars: {
    time: string[]
    open: number[]
    high: number[]
    low: number[]
    close: number[]
    volume: Array<number | null>
  }
}

export interface TpoLevel {
  price: number
  count: number
  letters: string[]
  in_value_area: boolean
  is_poc: boolean
}

export type TpoProfileResponse = {
  available: false
  dataset_id: string
  symbol: string
  asset_class: string
  reason: string
} | {
  available: true
  dataset_id: string
  symbol: string
  asset_class: string
  session_date: string
  session_label: string
  session_timezone: string
  session_start: string
  session_end: string
  profile_through: string
  complete: boolean
  period_minutes: number
  native_interval_seconds: number
  bar_count: number
  bracket_size: number
  total_tpos: number
  poc: number
  vah: number
  val: number
  ib_high: number
  ib_low: number
  session_high: number
  session_low: number
  levels: TpoLevel[]
}

export interface StudyGroup {
  id: string
  label: string
  color?: string
  visible?: boolean
}

export interface StudyPoint {
  id: string
  group: string
  pane?: string
  time: string
  value: number
  label?: string
  role?: string
  marker?: string
  color?: string
  metadata?: Record<string, unknown>
}

export interface StudyLink {
  id: string
  group: string
  pane?: string
  start_time: string
  end_time: string
  start_value: number
  end_value: number
  label?: string
  color?: string
  dash?: string
  metadata?: Record<string, unknown>
}

export interface StudySpan {
  id: string
  group: string
  pane?: string
  start_time: string
  end_time: string
  lower?: number | null
  upper?: number | null
  label?: string
  color?: string
  opacity?: number
  metadata?: Record<string, unknown>
}

export interface StudyLevel {
  id: string
  group: string
  pane?: string
  value: number
  label?: string
  color?: string
}

export interface PanelPoint { time: string; value: number | null; color?: string }

export interface StudyPanel {
  id: string
  label: string
  height?: number
  visible?: boolean
  zero_line?: boolean
  series: Array<{
    id: string
    name: string
    type: 'line' | 'histogram' | 'area'
    color?: string
    line_width?: number
    points: PanelPoint[]
  }>
}

export interface ChartStudy {
  schema_version: 'trading-chart-study/v2'
  groups: StudyGroup[]
  panels: StudyPanel[]
  points: StudyPoint[]
  links: StudyLink[]
  spans: StudySpan[]
  levels: StudyLevel[]
}

export interface StudyView {
  id: string
  label: string
  dataset_id: string
  symbol?: string
  timeframe?: string
  default_start?: string | null
  default_end?: string | null
  chart: ChartStudy
}

export interface StudyManifest {
  schema_version: 'trading-study-run/v1'
  study: { id: string; name: string; version: string; description?: string; generator?: string }
  run: { id: string; generated_at: string; status: string; parameters: Record<string, unknown> }
  inputs: Array<{ dataset_id: string; fingerprint?: string }>
  views: StudyView[]
  metrics: Array<Record<string, unknown>>
  tables: Array<{ id?: string; label?: string; columns?: string[]; rows?: Array<Record<string, unknown>> }>
  resources: Record<string, unknown>
  methodology?: string | null
}

export interface StudySummary {
  id: string
  study_id: string
  study_name: string
  generated_at: string
  status: string
  view_count: number
  symbols: string[]
}
