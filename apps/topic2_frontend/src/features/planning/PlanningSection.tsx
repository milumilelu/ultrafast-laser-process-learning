/** Planning section (M6): Raster vs Cross Hatch comparison and the
 * recommended ToolpathPlan with full lineage. */

import { useMemo } from 'react'
import type { ArtifactSnapshot } from '../../domain/artifact'
import { buildPlanView, PATH_FAMILY_LABEL, PLAN_STATUS_LABEL } from '../../domain/planning'
import { Card, EmptyState } from '../../components/ui/Card'
import { StatusBadge } from '../../components/ui/StatusBadge'

export function PlanningSection({
  plan,
  simulation,
}: {
  plan?: ArtifactSnapshot
  simulation?: ArtifactSnapshot
}) {
  const view = useMemo(
    () => buildPlanView(plan?.content as Record<string, unknown>),
    [plan],
  )
  if (!plan) {
    return (
      <div className="section">
        <h1>Planning 规划</h1>
        <EmptyState
          message="尚无路径规划产物"
          hint="运行 plan_process 后生成 ToolpathPlan。"
        />
      </div>
    )
  }
  const bestRmse = Math.min(
    ...view.candidates.map((candidate) => candidate.morphologyRmseUm ?? Infinity),
  )

  return (
    <div className="section">
      <div className="section-head">
        <h1>Planning 规划</h1>
        <StatusBadge
          tone={
            view.status === 'BLOCKED'
              ? 'err'
              : view.status === 'PROVISIONAL_SIMULATION_ONLY'
                ? 'warn'
                : 'ok'
          }
          label={PLAN_STATUS_LABEL[view.status] ?? view.status}
        />
      </div>

      <div className="cards-grid">
        <Card title="推荐路径">
          <div className="recommended-plan">
            <div className="metric"><span className="metric-label">路径族</span><span className="metric-value">{PATH_FAMILY_LABEL[view.pathFamily] ?? view.pathFamily}</span></div>
            <div className="metric"><span className="metric-label">形貌 RMSE</span><span className="metric-value">{view.predictedRmseUm?.toFixed(2) ?? '—'} µm</span></div>
            <div className="metric"><span className="metric-label">目标函数</span><span className="metric-value">{view.objectiveValue?.toFixed(3) ?? '—'}</span></div>
            <div className="metric"><span className="metric-label">加工时间</span><span className="metric-value">{view.predictedTimeS?.toFixed(4) ?? '—'} s</span></div>
          </div>
          {view.pathParameters && Object.keys(view.pathParameters).length > 0 && (
            <div className="card-hint">
              参数: {Object.entries(view.pathParameters).map(([key, value]) => `${key}=${String(value)}`).join(' · ')}
            </div>
          )}
        </Card>

        <Card title="候选对比">
          <table className="data-table">
            <thead>
              <tr>
                <th>路径族</th>
                <th>形貌 RMSE</th>
                <th>加工时间</th>
                <th>目标值</th>
              </tr>
            </thead>
            <tbody>
              {view.candidates.map((candidate) => (
                <tr
                  key={candidate.planId}
                  className={candidate.pathFamily === view.pathFamily ? 'candidate-row-selected' : ''}
                >
                  <td>{PATH_FAMILY_LABEL[candidate.pathFamily] ?? candidate.pathFamily}</td>
                  <td>
                    {candidate.morphologyRmseUm !== null ? (
                      <>
                        {candidate.morphologyRmseUm.toFixed(2)} µm
                        {candidate.morphologyRmseUm === bestRmse && (
                          <span className="candidate-best"> 最优</span>
                        )}
                      </>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td>{candidate.machiningTimeS !== null ? `${candidate.machiningTimeS.toFixed(4)} s` : '—'}</td>
                  <td>{candidate.objectiveValue?.toFixed(3) ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>

      <Card title="机器约束">
        <div className="card-hint">
          {view.machineConstraints.length === 0
            ? '无可用机器约束'
            : view.machineConstraints
                .map((constraint) => `${constraint.name} ${constraint.lower ?? '?'}–${constraint.upper ?? '?'} ${constraint.unit}`)
                .join(' · ')}
        </div>
      </Card>

      <Card title="推荐依据（可追溯）">
        <ol className="lineage">
          <li className="lineage-node">
            <span className="lineage-label">ToolpathPlan</span>
            <span className="lineage-meta">{view.planId} · simulation_ref: {view.simulationRef ? `${view.simulationRef.type}/${view.simulationRef.id}` : '—'}</span>
          </li>
          <li className="lineage-node">
            <span className="lineage-label">MorphologySimulationResult</span>
            <span className="lineage-meta">{simulation ? String((simulation.content as Record<string, unknown>).simulation_id) : '—'}</span>
          </li>
          {view.planningPriorRefs.length > 0 && (
            <li className="lineage-node">
              <span className="lineage-label">PlanningPreferencePrior</span>
              <span className="lineage-meta">{view.planningPriorRefs.map((ref) => ref.id).join(', ')}</span>
            </li>
          )}
        </ol>
      </Card>
    </div>
  )
}
