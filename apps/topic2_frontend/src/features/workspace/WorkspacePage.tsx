/** Workspace page: current ApplicationRun's real execution state machine.
 * Left rail is not a menu — it is the run's execution state (spec §四).
 */

import { useCallback, useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, Navigate, NavLink, useParams } from 'react-router-dom'
import { WORKSPACE_SECTIONS } from '../../domain/stages'
import { buildRunControl } from '../../domain/control'
import { getTaskDraft, listTaskDrafts, saveTaskDraft, emptyTaskDraft } from '../../stores/taskDrafts'
import { useUiStore } from '../../stores/ui'
import { StatusBadge } from '../../components/ui/StatusBadge'
import { Button } from '../../components/ui/Button'
import { useApplicationRun, useRunEvents, useRunArtifacts } from './useRunState'
import { OverviewSection } from './OverviewSection'
import { CapabilitySection } from '../capability/CapabilitySection'
import { KnowledgeSection } from '../knowledge/KnowledgeSection'
import { NeedsPanel, ReadingPanel } from '../knowledge/NeedsPanel'
import { ConditionTracePanel } from '../knowledge/ConditionTracePanel'
import { CalibrationSection } from '../calibration/CalibrationSection'
import { SimulationSection } from '../simulation/SimulationSection'
import { PlanningSection } from '../planning/PlanningSection'
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

  // 阶段三 T1: frontend performs zero workflow transition logic.
  // Section status comes verbatim from the backend's RunControlState.phases;
  // stage_status is display-only (Inspector).
  const runControl = useMemo(
    () =>
      buildRunControl(
        (run.data?.result as { runControlState?: Record<string, unknown> | null })
          ?.runControlState ?? null,
      ),
    [run.data?.result],
  )

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
            const phase = ws.phase ? runControl.phases[ws.phase] : null
            const status = phase?.status ?? 'NOT_RUN'
            const tone =
              status === 'BLOCKED'
                ? 'warn'
                : status === 'PARTIAL'
                  ? 'warn'
                  : status === 'COMPLETED'
                    ? 'ok'
                    : status === 'READY'
                      ? 'ok'
                      : 'neutral'
            const label =
              status === 'COMPLETED'
                ? '完成'
                : status === 'BLOCKED'
                  ? '受阻'
                  : status === 'PARTIAL'
                    ? '部分'
                    : status === 'READY'
                      ? '就绪'
                      : '未运行'
            const to = ws.id === 'overview' ? `/workspace/${taskId}` : `/workspace/${taskId}/${ws.id}`
            return (
              <li key={ws.id}>
                <NavLink
                  to={to}
                  className={({ isActive }) =>
                    `workflow-item ${isActive ? 'workflow-item-active' : ''}`
                  }
                >
                  <StatusBadge tone={tone} label={label} />
                  <span className="workflow-label">{ws.label}</span>
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
          />
        )}
        {section === 'capability' && (
          <CapabilitySection artifact={artifacts.data?.get('ScientificCapabilityReport')} />
        )}
        {section === 'knowledge' && (
          <>
            <NeedsPanel artifact={artifacts.data?.get('ScientificNeedSet')} />
            <ReadingPanel
              artifact={artifacts.data?.get('ScientificCorpusPack')}
              events={eventsQuery.data?.items ?? []}
            />
            <ConditionTracePanel
              ledger={artifacts.data?.get('CandidateLedger')}
              conditions={artifacts.data?.get('SourceConditionSet')}
              reconstructibility={artifacts.data?.get('ReconstructibilityReportSet')}
            />
            <KnowledgeSection
              taskId={taskId}
              requirements={artifacts.data?.get('KnowledgeRequirementSet')}
              queryPlans={artifacts.data?.get('RequirementRetrievalPlan')}
              evidence={artifacts.data?.get('EvidenceIRSet')}
              priors={artifacts.data?.get('PriorObjectSet')}
              knowledgeState={artifacts.data?.get('KnowledgeState')}
              developerMode={developerMode}
            />
          </>
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
        {section === 'simulation' && (
          <SimulationSection
            simulation={artifacts.data?.get('MorphologySimulationResult')}
            model={artifacts.data?.get('LocalRemovalModel')}
          />
        )}
        {section === 'planning' && (
          <PlanningSection
            plan={artifacts.data?.get('ToolpathPlan')}
            simulation={artifacts.data?.get('MorphologySimulationResult')}
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
