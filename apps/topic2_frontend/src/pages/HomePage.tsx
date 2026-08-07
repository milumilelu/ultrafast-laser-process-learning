/** 首页：真实后端统计数据 + 当前任务 + 服务状态 + 近期运行。无任何硬编码数值。 */

import { useEffect } from 'react'
import { Link } from 'react-router-dom'

import { topic2Api } from '../api/topic2'
import { DataProfileCard } from '../components/DataProfileCard'
import { EmptyState, ErrorBanner } from '../components/Banners'
import { StatCard } from '../components/StatCard'
import { StatusBadge } from '../components/StatusBadge'
import { formatTimestamp, runTypeLabel } from '../lib/format'
import {
  laserTypeLabel,
  materialLabel,
  objectiveLabel,
  processTaskLabel,
} from '../lib/canonical'
import { useScienceStore } from '../stores/science'
import { useTaskContextStore } from '../stores/taskContext'

export function HomePage() {
  const context = useTaskContextStore((state) => state.context)
  const {
    experiments,
    experimentsLoading,
    experimentsError,
    dataProfile,
    recentRuns,
    recentRunsError,
    setExperiments,
    setRecentRuns,
  } = useScienceStore()

  useEffect(() => {
    setExperiments([], null, true)
    topic2Api
      .experiments()
      .then((result) => setExperiments(result.items))
      .catch((error) => setExperiments([], error instanceof Error ? error.message : '获取实验数据失败'))
    topic2Api
      .listRuns()
      .then((result) => setRecentRuns(result.items.slice(0, 8)))
      .catch((error) =>
        setRecentRuns([], error instanceof Error ? error.message : '获取运行记录失败'),
      )
  }, [setExperiments, setRecentRuns])

  return (
    <div>
      <h1>首页</h1>
      <p className="card-sub">
        Human-Agent-Scientific Workflow：UI 定义任务 → Agent 理解与编排 → Topic2 Backend
        执行确定性科学计算 → 结果回到界面与 Agent → 人工决策。
      </p>

      <ErrorBanner message={experimentsError ?? recentRunsError} />

      <div className="card">
        <div className="card-title">当前任务上下文</div>
        <div className="row">
          <StatCard value={context.taskContextId} label="Task Context ID" />
          <StatCard value={`v${context.version}`} label="版本" />
          <StatCard value={context.materialId ? materialLabel(context.materialId) : '未定义'} label="材料" />
          <StatCard value={context.laserType ? laserTypeLabel(context.laserType) : '—'} label="激光" />
          <StatCard value={context.equipmentId ?? '—'} label="设备" />
          <StatCard value={context.processType ? processTaskLabel(context.processType) : '—'} label="加工任务" />
          <StatCard value={context.objective ? objectiveLabel(context.objective) : '—'} label="加工目标" />
        </div>
        {context.selectedModelId && (
          <div style={{ marginTop: 8 }}>
            <StatusBadge tone="info">当前模型：{context.selectedModelId}</StatusBadge>
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-title">数据状态（Topic2 Backend 实时统计）</div>
        {experimentsLoading ? (
          <div className="empty-state">
            <span className="spinner" /> 正在读取…
          </div>
        ) : (
          <>
            <div className="stat-grid" style={{ marginBottom: 16 }}>
              <StatCard value={new Set(experiments.map((row) => row.material)).size} label="已覆盖材料数" />
              <StatCard value={experiments.filter((row) => row.laser_type === 'fs').length} label="fs 记录数" />
              <StatCard value={experiments.filter((row) => row.laser_type === 'ps').length} label="ps 记录数" />
              <StatCard value={experiments.length} label="样本总数" />
            </div>
            {dataProfile && <DataProfileCard profile={dataProfile} />}
          </>
        )}
      </div>

      <div className="card">
        <div className="card-title">近期运行</div>
        {recentRuns.length === 0 ? (
          <EmptyState message="暂无运行记录。完成参数辨识 / 建模 / 优化后，运行记录会出现在这里。" />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Run ID</th>
                <th>类型</th>
                <th>任务</th>
                <th>时间</th>
              </tr>
            </thead>
            <tbody>
              {recentRuns.map((run) => (
                <tr key={run.run_id}>
                  <td>
                    <Link className="mono" to={`/runs?run=${encodeURIComponent(run.run_id)}`}>
                      {run.run_id}
                    </Link>
                  </td>
                  <td>{runTypeLabel(run.run_type)}</td>
                  <td className="mono">{run.task_id}</td>
                  <td>{formatTimestamp(run.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
