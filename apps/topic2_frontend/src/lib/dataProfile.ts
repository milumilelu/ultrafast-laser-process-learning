/** Descriptive DataProfile computed by direct counting over backend experiment rows.
 *  The frontend never decides "maturity" — policy decisions remain backend-side. */

import type { DataProfile, ExperimentRow } from '../api/types'
import { CORE_PARAMETERS } from './params'

export function computeDataProfile(rows: ExperimentRow[]): DataProfile {
  const valid = rows.filter((row) => row.valid_flag === 1)
  const designs = new Set(valid.map((row) => row.parameter_combination_id)).size
  const batches = new Set(valid.map((row) => row.experiment_batch_id)).size
  const equipment = new Set(valid.map((row) => row.equipment_id)).size

  const present: Record<string, number> = {}
  for (const name of CORE_PARAMETERS) {
    present[name] = valid.filter((row) => row[name] != null).length
  }
  const cells = valid.length * CORE_PARAMETERS.length
  const filled = Object.values(present).reduce((sum, count) => sum + count, 0)
  const missingRate = cells === 0 ? 0 : 1 - filled / cells

  return {
    n_samples: valid.length,
    n_unique_designs: designs,
    n_features: CORE_PARAMETERS.length,
    replicate_ratio: valid.length === 0 ? 0 : designs / valid.length,
    missing_rate: missingRate,
    batch_count: batches,
    equipment_count: equipment,
    coverage_score: null,
  }
}
