/** Workspace page: current ApplicationRun's real execution state machine.
 * Left rail is not a menu — it is the run's execution state (spec §四).
 */

import { useCallback, useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, Navigate, NavLink, useParams } from 'react-router-dom'
import { CANONICAL_STAGES, CHECKPOINT_STAGES, WORKSPACE_SECTIONS } from '../../domain/stages'
import { executionLabel, executionStatusFrom, executionTone } from '../../domain/status'
import { getTaskDraft, listTaskDrafts, saveTaskDraft, emptyTaskDraft } from '../../stores/taskDrafts'
import { useUiStore } from '../../stores/ui'
import { StatusBadge } from '../../components/ui/StatusBadge'
import { Button } from '../../components/ui/Button'
import { useApplicationRun, useRunEvents, useRunArtifacts } from './useRunState'
import { OverviewSection } from './OverviewSection'
import { CapabilitySection } from '../capability/CapabilitySection'
import { KnowledgeSection } from '../knowledge/KnowledgeSection'
import { CalibrationSection } from '../calibration/CalibrationSection'
import { EmptyState, ErrorBanner } from '../../components/ui/Card'
import { createOrContinueRun } from './runFlow'

const VALID_SECTIONS = new Set(['overview', 'capability', 'knowledge', 'calibration', 'simulation', 'planning'])

export function WorkspacePage() {
  const { taskId, section = 'overview' } = useParams()
  if (!taskId) return <Navigate to="/workspace" replace />
  if (!VALID_SECTIONS.has(section)) return <Navigate to={`/workspace/${taskId}`} replace />
  return <WorkspaceInner taskId={taskId} section={section} />
}

function WorkspaceInner({ taskId, section }: { taskId: string; section: string }) {
  const draft = getTaskDraft(taskId)
  const developerMode = useUiStore((state) => state.developerMode)
  const runId = draft?.runId ?? null
  const run = useApplicationRun(runId)
  const eventsQuery = useRunEvents(runId)
  const artifacts = useRunArtifacts(runId)
  const queryClient = useQueryClient()

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const createOrContinue = useCallback(
    async (stages?: string[]) => {
      setError(null)
      if (!draft) return
      try {
        setBusy(true)
        await createOrContinueRun(taskId, stages)
        await queryClient.invalidateQueries({ queryKey: ['application-run'] })
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : '运行失败')
      } finally {
        setBusy(false)
      }
    },
    [taskId, queryClient],
  )

  const continueMutation = useMutation({
    mutationFn: (stages?: string[]) => createOrContinue(stages),
  })

  const stageRows = useMemo(() => {
    const status = run.data?.stage_status ?? {}
    return CANONICAL_STAGES.map((stage, index) => {
      const raw = status[stage]?.status
      const exec = executionStatusFrom(raw)
      return { stage, index, exec }
    })
  }, [run.data?.stage_status])

  const nextCheckpoint = useMemo(() => {
    const completed = new Set(
      CANONICAL_STAGES.filter((stage) => {
        const raw = run.data?.stage_status?.[stage]?.status
        return raw === 'completed' || raw === 'COMPLETED'
      }),
    )
    return CHECKPOINT_STAGES.find((stage) => !completed.has(stage)) ?? null
  }, [run.data?.stage_status])

  const runStatus = run.data?.status ?? null

  if (!draft) {
    return (
      <EmptyState
        message="任务不存在"
        hint={
          <Link to="/workspace" className="link">
            返回任务列表
          </Link>
        }
      />
    )
  }
  return (
    <div className="workspace">
      <aside className="workflow-rail">
        <div className="workflow-rail-title">Scientific Workflow</div>
        <ol className="workflow-list">
          {WORKSPACE_SECTIONS.map((ws) => {
            const exec = ws.unlockStage
              ? stageRows.find((row) => row.stage === ws.unlockStage)?.exec ?? 'NOT_RUN'
              : 'READY'
            const to = ws.id === 'overview' ? `/workspace/${taskId}` : `/workspace/${taskId}/${ws.id}`
            return (
              <li key={ws.id}>
                <NavLink
                  to={to}
                  className={({ isActive }) =>
                    `workflow-item ${isActive ? 'workflow-item-active' : ''}`
                  }
                >
                  <StatusBadge tone={executionTone(exec)} label={executionLabel(exec)} />
                  <span className="workflow-label">{ws.label}</span>
                  {ws.pending && <span className="workflow-pending">下一迭代</span>}
                </NavLink>
              </li>
            )
          })}
        </ol>
      </aside>

      <section className="workspace-main">
        <ErrorBanner message={error} />
        {section === 'overview' && (
          <OverviewSection
            taskId={taskId}
            runStatus={runStatus}
            artifacts={artifacts.data}
            run={run.data}
            events={eventsQuery.data?.items ?? []}
            busy={busy || continueMutation.isPending}
            onContinue={(stages) => createOrContinue(stages)}
            nextCheckpoint={nextCheckpoint}
          />
        )}
        {section === 'capability' && (
          <CapabilitySection artifact={artifacts.data?.get('ScientificCapabilityReport')} />
        )}
        {section === 'knowledge' && (
          <KnowledgeSection
            taskId={taskId}
            requirements={artifacts.data?.get('KnowledgeRequirementSet')}
            queryPlans={artifacts.data?.get('LiteratureRetrievalQueryPlan')}
            evidence={artifacts.data?.get('EvidenceIRSet')}
            priors={artifacts.data?.get('PriorObjectSet')}
            knowledgeState={artifacts.data?.get('KnowledgeState')}
            developerMode={developerMode}
          />
        )}
        {section === 'calibration' && (
          <CalibrationSection
            capability={artifacts.data?.get('ScientificCapabilityReport')}
            calibration={artifacts.data?.get('CalibrationResult')}
            identifiability={artifacts.data?.get('IdentifiabilityReport')}
            priors={artifacts.data?.get('PriorObjectSet')}
            model={artifacts.data?.get('LocalRemovalModel')}
            developerMode={developerMode}
          />
        )}
        {(section === 'simulation' || section === 'planning') && (
          <EmptyState
            message={`「${section === 'simulation' ? '仿真' : '规划'}」在下一迭代实现（F4/F5）`}
            hint="后端已产出 MorphologySimulationResult / ToolpathPlan artifact，本工作台下一迭代将直接消费展示。"
          />
        )}
      </section>
    </div>
  )
}

export function WorkspaceLanding() {
  const [drafts, setDrafts] = useState(() => listTaskDrafts())
  const [error, setError] = useState<string | null>(null)
  const [createdId, setCreatedId] = useState<string | null>(null)

  const handleCreate = () => {
    try {
      const draft = saveTaskDraft(emptyTaskDraft())
      setDrafts(listTaskDrafts())
      setError(null)
      setCreatedId(draft.taskId)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '创建任务失败')
    }
  }

  if (createdId) return <Navigate to={`/workspace/${createdId}`} replace />

  return (
    <div className="landing">
      <h1>Scientific Workbench</h1>
      <p className="landing-sub">
        一个 Scientific Task → 一个 ApplicationRun → 一组不断演进的 Scientific State
      </p>
      <ErrorBanner message={error} />
      <div className="landing-actions">
        <Button onClick={handleCreate}>新建任务</Button>
      </div>
      {drafts.length > 0 ? (
        <table className="data-table task-table">
          <thead>
            <tr>
              <th>Task</th>
              <th>Material</th>
              <th>Process</th>
              <th>Geometry</th>
              <th>Target</th>
              <th>Machine</th>
              <th>Run</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {drafts.map((draft) => (
              <tr key={draft.taskId}>
                <td>{draft.taskId}</td>
                <td>{draft.material || '—'}</td>
                <td>{draft.laserType || '—'}</td>
                <td>{draft.geometryType || '—'}</td>
                <td>{draft.objectiveMetric || '—'}</td>
                <td>{draft.equipmentProfileId || '—'}</td>
                <td>{draft.runId ? draft.runId.slice(0, 12) + '…' : '—'}</td>
                <td>
                  <Link className="link" to={`/workspace/${draft.taskId}`}>
                    打开
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <EmptyState message="还没有任务" hint="点击「新建任务」开始第一个 Scientific Task。" />
      )}
    </div>
  )
}
