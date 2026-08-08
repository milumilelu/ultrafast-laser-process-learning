/** Global Context Bar (UI-1/5.2): always-visible canonical task summary.
 *  Refreshes automatically on every Task Context update. */

import { objectiveToTarget, processTaskLabel } from '../../lib/canonical'
import { useScienceStore } from '../../stores/science'
import { useTaskContextStore } from '../../stores/taskContext'
import { StatusBadge } from '../StatusBadge'

export function GlobalContextBar() {
  const context = useTaskContextStore((state) => state.context)
  const dataProfile = useScienceStore((state) => state.dataProfile)
  const selectedModelId = useScienceStore((state) => state.selectedModelId)
  const training = useScienceStore((state) => state.training)
  const target = objectiveToTarget(context.objective)

  return (
    <div className="global-context-bar" data-testid="global-context-bar">
      <span className="gc-item">
        <span className="gc-key">材料</span>
        <b>{context.materialId ?? '—'}</b>
      </span>
      <span className="gc-item">
        <span className="gc-key">激光</span>
        <b>{context.laserType ?? '—'}</b>
      </span>
      <span className="gc-item">
        <span className="gc-key">工艺</span>
        <b>{context.processType ? processTaskLabel(context.processType) : '—'}</b>
      </span>
      <span className="gc-item">
        <span className="gc-key">目标</span>
        <b>
          {target ?? '—'} {target === 'depth_um' ? '↑' : target === 'roughness_um' ? '↓' : ''}
        </b>
      </span>
      <span className="gc-item">
        <span className="gc-key">设备</span>
        <b>{context.datasetEquipmentId ?? context.equipmentId ?? '—'}</b>
      </span>
      <span className="gc-item">
        <span className="gc-key">数据</span>
        <b>{dataProfile ? `${dataProfile.n_samples} 样本` : '—'}</b>
      </span>
      <span className="gc-item">
        <span className="gc-key">模型</span>
        <b>{training?.selected_model ?? selectedModelId ?? '未选择'}</b>
      </span>
      <span className="gc-item" style={{ marginLeft: 'auto' }}>
        <StatusBadge tone="neutral">
          Task {context.taskContextId}:v{context.version}
        </StatusBadge>
        {context.objective && (
          <StatusBadge tone="info">
            {context.objective === 'quality_first' ? '质量优先' : '效率优先'}
          </StatusBadge>
        )}
      </span>
    </div>
  )
}
