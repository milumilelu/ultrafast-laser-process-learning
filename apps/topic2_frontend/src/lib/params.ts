/** The five parameters present in the repository's real source tables. */
export const CORE_PARAMETERS = [
  'pulse_width_ps',
  'frequency_kHz',
  'hatch_spacing_um',
  'passes',
  'scan_speed_mm_s',
] as const

export type CoreParameter = (typeof CORE_PARAMETERS)[number]

export interface ParameterBounds {
  lower: number
  upper: number
}

/** Suggested defaults derived live from real experiment rows; never hardcoded values.
 *  If a parameter is constant across the observed data, the editor gets a small
 *  widened range so the backend (which requires lower < upper) can still run. */
export function defaultBoundsFromRows(
  rows: ReadonlyArray<Record<string, unknown>>,
): Record<CoreParameter, ParameterBounds> {
  const result = {} as Record<CoreParameter, ParameterBounds>
  for (const name of CORE_PARAMETERS) {
    const values = rows
      .map((row) => row[name])
      .filter(
        (value): value is number =>
          typeof value === 'number' && Number.isFinite(value),
      )
      .sort((a, b) => a - b)
    const lower = values[0]
    const upper = values[values.length - 1]
    if (lower === undefined) {
      result[name] = { lower: 1, upper: 2 }
    } else if (lower === upper) {
      result[name] =
        name === 'passes'
          ? { lower: Math.max(1, lower - 1), upper: lower + 1 }
          : { lower: lower * 0.8, upper: lower * 1.2 }
    } else {
      result[name] = { lower, upper }
    }
  }
  return result
}
