/** TaskAndDataWorkspace (7.x): 三阶段 - 研究任务 / 数据与设备 / Physics Readiness。
 *  Task 编辑复用 TaskPage；Readiness 状态来自后端报告（Application Run 结果），
 *  前端禁止自行判定 dependency。 */

import { useEffect, useState } from 'react'

import { applicationApi } from '../api/application'
import { StatusBadge } from '../components/StatusBadge'
import { PhysicsReadinessMatrix } from '../components/learning/PhysicsReadinessMatrix'
import type { PhysicsCoordinateStatus } from '../api/types'
import { scientificLabel, scientificTone, type StatusTone } from '../lib/status'
import { useApplicationStore } from '../stores/application'
import { useModeStore } from '../stores/mode'
import { TaskPage } from './TaskPage'

export function TaskAndDataWorkspace() {
  const mode = useModeStore((state) => state.mode)
  const activeApplicationRunId = useApplicationStore((state) => state.activeApplicationRunId)
  const [coordinates, setCoordinates] = useState<PhysicsCoordinateStatus[]>([])
  const [readinessMeta, setReadinessMeta] = useState<{ status: string; sampleCount?: number } | null>(null)
  const [readinessError, setReadinessError] = useState<string | null>(null)

  useEffect(() => {
    if (!activeApplicationRunId) {
      setCoordinates([])
      setReadinessMeta(null)
      return
    }
    let cancelled = false
    applicationApi
      .getResult(activeApplicationRunId)
      .then((result) => {
        if (cancelled) return
        // 统一坐标矩阵来自后端报告投影（processLearning.physicsReadiness），
        // 状态/依赖全部由后端给出，前端不自行判定。
        const raw = result.processLearning.physicsReadiness ?? []
        setCoordinates(raw)
        const physics = (result.cfa.targetPhysicsReadiness as Record<string, unknown> | null) ?? null
        setReadinessMeta({
          status: String(physics?.status ?? (raw.length > 0 ? 'AVAILABLE' : 'UNKNOWN')),
          sampleCount: result.targetTask.sampleCount ?? undefined,
        })
      })
      .catch(() => {
        if (!cancelled) {
          setCoordinates([])
          setReadinessError('读取 Physics Readiness 报告失败')
        }
      })
    return () => {
      cancelled = true
    }
  }, [activeApplicationRunId])

  return (
    <div>
      <h1>任务与数据</h1>
      <div className="row" style={{ marginBottom: 12 }}>
        <StatusBadge tone="info">Step 1 研究任务</StatusBadge>
        <StatusBadge tone="info">Step 2 数据与设备</StatusBadge>
        <StatusBadge tone="info">Step 3 Readiness Check</StatusBadge>
        {mode === 'demo' && <StatusBadge tone="warn">展示模式：任务配置只读</StatusBadge>}
      </div>
      <TaskPage />

      <div className="card">
        <div className="card-title">Physics Readiness（来自后端 TargetPhysicsReadinessReport）</div>
        {readinessMeta && (
          <div className="row" style={{ marginBottom: 8 }}>
            <StatusBadge tone={scientificTone(readinessMeta.status) as StatusTone}>
              {scientificLabel(readinessMeta.status)}
            </StatusBadge>
            {readinessMeta.sampleCount != null && (
              <StatusBadge tone="neutral">{readinessMeta.sampleCount} samples</StatusBadge>
            )}
          </div>
        )}
        {readinessError && <StatusBadge tone="err">{readinessError}</StatusBadge>}
        {activeApplicationRunId ? (
          <PhysicsReadinessMatrix coordinates={coordinates} />
        ) : (
          <div className="empty-state">
            运行完整分析后，此矩阵将展示目标侧物理坐标状态（pulse_interval / pulse_spacing /
            pulse_overlap / peak_fluence / normalized_fluence 等）。状态全部来自后端报告。
          </div>
        )}
      </div>
    </div>
  )
}
