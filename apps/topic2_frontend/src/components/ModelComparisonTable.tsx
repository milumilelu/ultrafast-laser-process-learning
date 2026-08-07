/** Model comparison table: all metrics come from the backend training run.
 *  The system recommends by Group-CV RMSE; the human may override (recorded). */

import { useScienceStore } from '../stores/science'
import type { ModelTrainingResult } from '../api/types'
import { formatNumber } from '../lib/format'

export function ModelComparisonTable({
  training,
  onSelect,
}: {
  training: ModelTrainingResult
  onSelect: (modelName: string) => void
}) {
  const selectedModelId = useScienceStore((state) => state.selectedModelId)
  const selectionMode = useScienceStore((state) => state.selectionMode)

  const models = Object.keys(training.validation_metrics)

  return (
    <div>
      <table className="table">
        <thead>
          <tr>
            <th>模型</th>
            <th>RMSE</th>
            <th>MAE</th>
            <th>R²</th>
            <th>不确定性</th>
            <th>系统推荐</th>
            <th>人工选择</th>
          </tr>
        </thead>
        <tbody>
          {models.map((model) => {
            const metrics = training.validation_metrics[model]
            const isRecommended = training.selected_model === model
            const isManual = selectedModelId === model && selectionMode === 'manual'
            return (
              <tr key={model} data-testid="model-row">
                <td>
                  {model}
                  {isManual && (
                    <span className="badge warn" style={{ marginLeft: 6 }}>
                      人工覆盖
                    </span>
                  )}
                </td>
                <td>{formatNumber(metrics.RMSE)}</td>
                <td>{formatNumber(metrics.MAE)}</td>
                <td>{formatNumber(metrics.R2)}</td>
                <td>{metrics.uncertainty_available ? '✓' : '—'}</td>
                <td>{isRecommended ? '★' : ''}</td>
                <td>
                  <button
                    className="btn small"
                    onClick={() => onSelect(model)}
                    disabled={isManual}
                    title={isManual ? '已人工选择，该操作将被记录' : '人工选择该模型（将被记录）'}
                  >
                    选择
                  </button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {selectionMode === 'manual' && (
        <div className="warn-banner" style={{ marginTop: 12 }}>
          已进行人工覆盖（系统推荐 {training.selected_model}，当前人工选择 {selectedModelId}）。该操作将被记录。
        </div>
      )}
      <div className="card-sub" style={{ marginTop: 8 }}>
        评价方式：{training.cv_strategy}；比较基准：{training.comparison.comparison_basis}
      </div>
    </div>
  )
}
