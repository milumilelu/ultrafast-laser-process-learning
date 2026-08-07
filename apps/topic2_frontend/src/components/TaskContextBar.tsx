/** Fixed strip showing the global Task Context on every page. */

import { useNavigate } from 'react-router-dom'

import {
  laserTypeLabel,
  materialLabel,
  objectiveLabel,
  processTaskLabel,
} from '../lib/canonical'
import { useTaskContextStore } from '../stores/taskContext'

export function TaskContextBar() {
  const context = useTaskContextStore((state) => state.context)
  const navigate = useNavigate()

  return (
    <div className="task-context-bar">
      <span className="tc-item">
        <span className="tc-key">任务</span>
        <span className="mono">{context.taskContextId}</span>
        <span className="tc-version">v{context.version}</span>
      </span>
      <span className="tc-item">
        <span className="tc-key">材料</span>
        <span>{context.materialId ? materialLabel(context.materialId) : '未定义'}</span>
      </span>
      <span className="tc-item">
        <span className="tc-key">激光</span>
        <span>{context.laserType ? laserTypeLabel(context.laserType) : '—'}</span>
      </span>
      <span className="tc-item">
        <span className="tc-key">数据集设备</span>
        <span>{context.datasetEquipmentId ?? '—'}</span>
      </span>
      <span className="tc-item">
        <span className="tc-key">设备档案</span>
        <span>{context.equipmentId ?? '—'}</span>
      </span>
      <span className="tc-item">
        <span className="tc-key">加工任务</span>
        <span>{context.processType ? processTaskLabel(context.processType) : '—'}</span>
      </span>
      <span className="tc-item">
        <span className="tc-key">加工目标</span>
        <span>{context.objective ? objectiveLabel(context.objective) : '—'}</span>
      </span>
      <span className="tc-item">
        <span className="tc-key">数据集</span>
        <span>{context.datasetId ?? '—'}</span>
      </span>
      <span className="tc-item">
        <span className="tc-key">模型</span>
        <span>{context.selectedModelId ?? '—'}</span>
      </span>
      <span className="tc-item tc-link" onClick={() => navigate('/task')}>
        修改任务 →
      </span>
    </div>
  )
}
