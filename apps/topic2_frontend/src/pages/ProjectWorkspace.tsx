/** ProjectWorkspace (6.x): 项目概览 - 当前研究任务状态 + 下一步可做什么。
 *  Stepper / Readiness 状态来自正式结果（scienceStore + taskContext）。 */

import { Link } from 'react-router-dom'

import { StatusBadge } from '../components/StatusBadge'
import { ResearchReadiness, type ReadinessRow } from '../components/workflow/ResearchReadiness'
import { WorkflowStepper, type StepperStage } from '../components/workflow/WorkflowStepper'
import { formatTimestamp, runTypeLabel } from '../lib/format'
import { objectiveToTarget, processTaskLabel } from '../lib/canonical'
import { useModeStore } from '../stores/mode'
import { useScienceStore } from '../stores/science'
import { useTaskContextStore } from '../stores/taskContext'
import { useWorkflowStore } from '../stores/workflow'

export function ProjectWorkspace() {
  const context = useTaskContextStore((state) => state.context)
  const {
    evidence,
    training,
    optimization,
    dataProfile,
    recentRuns,
    ragEvidence,
  } = useScienceStore()
  const mode = useModeStore((state) => state.mode)
  const workflowEvents = useWorkflowStore((state) => state.events)

  const target = objectiveToTarget(context.objective)
  const complete = useTaskContextStore((state) => state.isComplete())
  const sampleCount = dataProfile?.n_samples ?? 0

  const stages: StepperStage[] = [
    {
      key: 'task',
      label: '任务定义',
      state: complete ? 'done' : 'current',
      detail: context.taskContextId,
      to: '/task',
    },
    {
      key: 'data',
      label: '数据准备',
      state: dataProfile ? 'done' : 'pending',
      detail: dataProfile ? `${sampleCount} samples` : null,
      to: '/task',
    },
    {
      key: 'learning',
      label: '过程学习',
      state: training ? 'done' : 'pending',
      detail: training ? `${training.selected_model}` : null,
      to: '/application?tab=modeling',
    },
    {
      key: 'evidence',
      label: '科学证据',
      state: evidence || ragEvidence.length > 0 ? 'done' : 'pending',
      detail: evidence ? `${evidence.accepted.length} accepted` : null,
      to: '/evidence',
    },
    {
      key: 'cfa',
      label: 'CFA',
      state: 'warn',
      detail: 'UNCALIBRATED',
      to: '/evidence',
    },
    {
      key: 'optimization',
      label: '优化',
      state: optimization ? 'done' : 'pending',
      detail: optimization ? 'Vanilla + Assisted' : null,
      to: '/application?tab=optimization',
    },
    {
      key: 'decision',
      label: '实验决策',
      state: workflowEvents.length > 0 || optimization ? 'current' : 'pending',
      to: '/application?tab=optimization',
    },
  ]

  const readiness: ReadinessRow[] = [
    { layer: 'Target Data', status: dataProfile ? 'READY' : 'UNKNOWN', summary: dataProfile ? `${sampleCount} samples` : '未加载' },
    { layer: 'Process Learning', status: training ? 'READY' : 'UNKNOWN', summary: training ? `${training.selected_model}（Group-CV）` : '未训练' },
    { layer: 'Equipment', status: context.equipmentId ? 'PARTIAL' : 'UNKNOWN', summary: context.equipmentId ? 'profile selected' : '未选择' },
    { layer: 'Source Evidence', status: ragEvidence.length > 0 || evidence ? 'READY' : 'UNKNOWN', summary: `${ragEvidence.length} candidates` },
    { layer: 'Physics', status: 'PARTIAL', summary: 'power 相关坐标不可用（如实报告）' },
    { layer: 'CFA', status: 'NOT_YET_CALIBRATED', summary: '5 facets · audit only' },
    { layer: 'E2P Prior', status: 'UNKNOWN', summary: '证据审核通过后签发（fails closed）' },
    { layer: 'BO', status: optimization ? 'READY' : 'UNKNOWN', summary: optimization ? 'Vanilla / Assisted' : '未运行' },
  ]

  return (
    <div>
      <h1>项目概览</h1>
      <p className="card-sub">
        当前研究任务：{context.taskContextId}:v{context.version} ·{' '}
        {mode === 'demo' ? '展示模式（冻结场景）' : '研究模式'}
      </p>

      <div className="row" style={{ marginBottom: 16 }}>
        <StatusBadge tone={complete ? 'ok' : 'warn'}>
          任务定义：{complete ? '完成' : '未完成'}
        </StatusBadge>
        <StatusBadge tone="neutral">
          {context.materialId ?? '材料未定义'} · {context.laserType ?? '激光未定义'} ·{' '}
          {context.processType ? processTaskLabel(context.processType) : '工艺未定义'} ·{' '}
          {target ?? '目标未定义'}
        </StatusBadge>
        {recentRuns[0] && (
          <StatusBadge tone="neutral">
            最近 Run：{runTypeLabel(recentRuns[0].run_type)}（{formatTimestamp(recentRuns[0].created_at)}）
          </StatusBadge>
        )}
      </div>

      <div className="grid grid-2">
        <div className="card">
          <div className="card-title">工作流进度</div>
          <WorkflowStepper stages={stages} />
        </div>
        <div className="card">
          <div className="card-title">研究就绪矩阵</div>
          <ResearchReadiness rows={readiness} />
        </div>
      </div>

      <div className="card">
        <div className="card-title">快捷入口</div>
        <div className="row">
          <Link className="btn primary" to="/application">
            查看工艺智能应用
          </Link>
          <Link className="btn" to="/demo">
            运行固定 Demo
          </Link>
          <Link className="btn" to="/runs">
            查看最近 Run
          </Link>
          <Link className="btn" to="/task">
            继续研究
          </Link>
        </div>
      </div>
    </div>
  )
}
