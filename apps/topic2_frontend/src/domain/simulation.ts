/** MorphologySimulationResult view model (M6) — F0/F1/F2 simulation output. */

export interface SimulationMetricsView {
  meanDepthUm: number | null
  maxDepthUm: number | null
  removedVolumeUm3: number | null
  morphologyRmseUm: number | null
  machiningTimeS: number | null
}

export interface SimulationView {
  simulationId: string
  fidelity: string
  pulseCount: number
  status: string
  targetDepthUm: number | null
  predictedDepthUm: number | null
  meanDepthUm: number | null
  maxDepthUm: number | null
  morphologyRmseUm: number | null
  machiningTimeS: number | null
  gridSpacingUm: number | null
  /** rows-major height field (um) with row count = y cells. */
  heightField: number[][]
  /** cross-section profile through the center row (x → depth). */
  crossSection: { x: number; depth: number }[]
  warnings: string[]
}

export interface SimulationContent {
  simulation_id?: string
  fidelity?: string
  pulse_count?: number
  status?: string
  metrics?: {
    mean_depth_um?: number
    max_depth_um?: number
    removed_volume_um3?: number
    morphology_rmse_um?: number | null
    machining_time_s?: number
  }
  predicted_depth_field_um?: number[][]
  target_depth_field_um?: number[][] | null
  state?: { grid_spacing_um?: number; height_field_um?: number[][] }
  warnings?: string[]
}

export const FIDELITY_LABEL: Record<string, string> = {
  F0_FIXED_KERNEL: 'F0 固定核',
  F1_INCUBATION: 'F1 孵化',
  F2_DEFOCUS_RECURSION: 'F2 离焦递归',
}

function meanOf(grid: number[][] | undefined): number | null {
  if (!grid || grid.length === 0) return null
  const values = grid.flat().filter((value) => Number.isFinite(value))
  if (values.length === 0) return null
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

function centerRowCrossSection(grid: number[][] | undefined, gridSpacing: number): { x: number; depth: number }[] {
  if (!grid || grid.length === 0) return []
  const row = grid[Math.floor(grid.length / 2)] ?? []
  return row.map((depth, index) => ({ x: index * gridSpacing, depth }))
}

export function buildSimulationView(content: SimulationContent | null | undefined): SimulationView {
  const raw = content ?? {}
  const metrics = raw.metrics ?? {}
  const predicted = raw.predicted_depth_field_um
  const gridSpacing = raw.state?.grid_spacing_um ?? null
  return {
    simulationId: String(raw.simulation_id ?? ''),
    fidelity: String(raw.fidelity ?? ''),
    pulseCount: Number(raw.pulse_count ?? 0),
    status: String(raw.status ?? ''),
    targetDepthUm: meanOf(raw.target_depth_field_um ?? undefined),
    predictedDepthUm: meanOf(predicted),
    meanDepthUm: metrics.mean_depth_um ?? null,
    maxDepthUm: metrics.max_depth_um ?? null,
    morphologyRmseUm: metrics.morphology_rmse_um ?? null,
    machiningTimeS: metrics.machining_time_s ?? null,
    gridSpacingUm: gridSpacing,
    heightField: predicted ?? [],
    crossSection: centerRowCrossSection(predicted, gridSpacing ?? 1),
    warnings: Array.isArray(raw.warnings) ? raw.warnings.map(String) : [],
  }
}
