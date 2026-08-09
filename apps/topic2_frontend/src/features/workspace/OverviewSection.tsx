/** Overview: 科学决策首页 (spec §六). Four readiness cards + one next action. */

import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import type { ApplicationRunRecord, WorkflowEvent } from '../../api/runs'
import type { ArtifactSnapshot } from '../../domain/artifact'
import { buildCapabilityView } from '../../domain/capability'
import { buildRunControl, PHASE_LABEL, type RunControlContent } from '../../domain/control'
import { buildRequirements, summarizeRequirements } from '../../domain/knowledge'
import { buildCalibrationView } from '../../domain/calibration'
import { scientificLabel, scientificTone, scientificStatusFrom } from '../../domain/status'
import { isTaskDraftComplete, useTaskDraft } from '../../stores/taskDrafts'
import { Card, EmptyState, Spinner } from '../../components/ui/Card'
import { StatusBadge } from '../../components/ui/StatusBadge'
import { Button } from '../../components/ui/Button'
import { SnapshotMeta } from '../../components/scientific/Artifact'
import { EquipmentCard } from '../../components/scientific/EquipmentCard'
import { ControlStateCard } from '../../components/scientific/ControlStateCard'
import { TaskForm } from './TaskForm'

interface OverviewSectionProps {
  taskId: string
  runStatus: string | null
  artifacts?: Map<string, ArtifactSnapshot>
  run: ApplicationRunRecord | null | undefined
  events: WorkflowEvent[]
  busy: boolean
  onContinue: (stages?: string[]) => void
}

export function OverviewSection({
  taskId,
  runStatus,
  artifacts,
  run,
  events,
  busy,
  onContinue,
}: OverviewSectionProps) {
  const draft = useTaskDraft(taskId)
  const [editing, setEditing] = useState(false)
  const [hint, setHint] = useState<string | null>(null)

  const capability = useMemo(() => {
    const snapshot = artifacts?.get('ScientificCapabilityReport')
    return buildCapabilityView(snapshot?.content as Record<string, unknown>)
  }, [artifacts])

  const control = useMemo(
    () => buildRunControl(run?.result?.runControlState as RunControlContent | undefined),
    [run],
  )

  const knowledge = useMemo(() => {
    const snapshot = artifacts?.get('KnowledgeState') ?? artifacts?.get('KnowledgeRequirementSet')
    const requirements = buildRequirements(snapshot?.content as Record<string, unknown>)
    return summarizeRequirements(requirements)
  }, [artifacts])

  const calibration = useMemo(() => {
    const snapshot = artifacts?.get('CalibrationResult')
    const view = buildCalibrationView(snapshot?.content as Record<string, unknown>)
    if (!view) return { estimated: 0, priorOnly: 0, notIdentifiable: 0, hasRun: false }
    const estimated = view.parameters.filter((p) => p.estimate !== null).length
    const notIdentifiable = view.parameters.filter((p) => p.identifiability === 'NOT_IDENTIFIABLE').length
    return { estimated, priorOnly: view.parameters.length - estimated, notIdentifiable, hasRun: true }
  }, [artifacts])

  const planningPhase = control.phases.PLANNING ?? { status: 'NOT_RUN' as const, blockingReasons: [] }
  const nextAction = control.nextActions[0]

  const capabilityStatus = capability ? capability.status : 'UNKNOWN'
  const stageCount = control.completedStages.length

  const draftComplete = Boolean(draft && isTaskDraftComplete(draft))
  const handleStart = () => {
    if (!draftComplete) {
      setEditing(true)
      setHint('请先完成材料 / 激光 / 几何 / 目标 / 设备的选择，并填写目标几何（Gate A 必填）。')
      return
    }
    setHint(null)
    onContinue()
  }

  if (!draft) return <EmptyState message="任务不存在" />

  return (
    <div className="overview">
      <div className="overview-head">
        <div>
          <h1>任务总览</h1>
          <p className="overview-sub">
            {draft.material} · {draft.geometryType} · {draft.objectiveMetric}
          </p>
        </div>
        <div className="overview-actions">
          {!draft.runId && (
            <Button variant="ghost" onClick={() => setEditing((v) => !v)}>
              {editing ? '收起' : '编辑任务'}
            </Button>
          )}
          {!draft.runId && <Button onClick={handleStart}>开始运行</Button>}
          {draft.runId && (
            <Button busy={busy} onClick={() => onContinue()}>
              继续
            </Button>
          )}
        </div>
      </div>

      {hint && <div className="warning-note">任务未完成：{hint}</div>}

      {editing && !draft.runId && <TaskForm taskId={taskId} onSaved={() => setEditing(false)} />}

      {draft.runId && (
        <div className="overview-runline">
          后端确认 {stageCount} 个 stage 完成 · Run 状态:{' '}
          <strong>{runStatus ?? '…'}</strong>
          {busy && <Spinner />}
        </div>
      )}

      <ControlStateCard control={run?.result?.runControlState as Record<string, unknown> | undefined} />
      <EquipmentCard artifact={artifacts?.get('MachineProfileSnapshot')} />

      <div className="cards-grid">
        <Card title="Scientific Capability" actions={<StatusBadge tone={scientificTone(scientificStatusFrom(capabilityStatus))} label={scientificLabel(scientificStatusFrom(capabilityStatus))} />}>
          {capability ? (
            <>
              <div className="card-stat">
                {capability.inputs.filter((i) => i.status === 'AVAILABLE').length}/
                {capability.inputs.length} 物理输入可解析
              </div>
              <div className="card-stat">Simulator {capability.supportedFidelity.join(', ') || '未声明'}</div>
            </>
          ) : (
            <EmptyState message="尚未生成 ScientificCapabilityReport" hint="点击「开始运行」执行能力预检。" />
          )}
          <SnapshotMeta snapshot={artifacts?.get('ScientificCapabilityReport')} />
        </Card>

        <Card title="Knowledge" actions={<StatusBadge tone={knowledge.total === 0 ? 'neutral' : knowledge.unresolved > 0 || knowledge.partial > 0 ? 'warn' : 'ok'} label={`${knowledge.total === 0 ? '未生成' : knowledge.unresolved > 0 || knowledge.partial > 0 ? '部分' : '就绪'}`} />}>
          {knowledge.total > 0 ? (
            <>
              <div className="card-stat">{knowledge.total} 个需求</div>
              <div className="card-stat">{knowledge.satisfied} 已满足 · {knowledge.partial} 部分 · {knowledge.unresolved} 未解决</div>
              <div className="card-links">
                <Link to={`/workspace/${taskId}/knowledge`}>查看需求详情 →</Link>
              </div>
            </>
          ) : (
            <EmptyState message="尚未分析知识需求" hint="运行 analyze_knowledge_requirements 后生成。" />
          )}
        </Card>

        <Card title="Physical Model" actions={<StatusBadge tone={calibration.hasRun ? (calibration.notIdentifiable > 0 ? 'warn' : 'ok') : 'neutral'} label={calibration.hasRun ? (calibration.estimated > 0 ? '已标定' : '未标定') : '未运行'} />}>
          {calibration.hasRun ? (
            <>
              <div className="card-stat">{calibration.estimated} 已拟合</div>
              <div className="card-stat">{calibration.priorOnly} 仅先验 · {calibration.notIdentifiable} 不可辨识</div>
              <div className="card-links">
                <Link to={`/workspace/${taskId}/calibration`}>查看参数 Registry →</Link>
              </div>
            </>
          ) : (
            <EmptyState message="尚未建立物理模型" hint="先完成 Capability 与 Knowledge，再运行 calibrate_physics。" />
          )}
        </Card>

        <Card title="Planning" actions={<StatusBadge tone={planningPhase.status === 'COMPLETED' || planningPhase.status === 'READY' ? 'ok' : planningPhase.status === 'PARTIAL' ? 'warn' : planningPhase.status === 'BLOCKED' ? 'err' : 'neutral'} label={PHASE_LABEL[planningPhase.status]} />}>
          <div className="card-stat">后端阶段状态：{PHASE_LABEL[planningPhase.status]}</div>
          {planningPhase.blockingReasons.map((reason) => <div key={reason} className="warning-note">{reason}</div>)}
        </Card>
      </div>

      <Card title="Recommended Next Action" className="next-action-card">
        <div className="next-action">
          <div className="next-action-message">{nextAction?.type ?? (control.phaseStatus === 'COMPLETED' ? 'RUN_COMPLETE' : 'START_RUN')}</div>
          <div className="next-action-detail">
            {nextAction ? '由后端 RunControlState 返回' : control.phaseStatus === 'COMPLETED' ? '主链已完成' : '创建 ApplicationRun 以获取后端下一步动作'}
          </div>
          {(nextAction?.missing?.length ?? 0) > 0 && (
            <div className="next-action-missing">
              缺少: {nextAction?.missing?.join(', ')}
            </div>
          )}
          {nextAction && ['CONTINUE_RUN', 'RESUME_RUN'].includes(nextAction.type) && (
            <div className="next-action-actions">
              <Button onClick={() => onContinue()}>{busy ? '运行中…' : '继续'}</Button>
            </div>
          )}
        </div>
      </Card>

      <Card title="事件流">
        {events.length === 0 ? (
          <EmptyState message="尚无事件" hint="运行开始后在此显示 STAGE / ARTIFACT 事件。" />
        ) : (
          <ol className="event-list">
            {events.slice(-8).map((event) => (
              <li key={event.event_id} className="event-item">
                <span className="event-seq">#{event.sequence}</span>
                <span className="event-type">{event.type}</span>
                {event.stage && <span className="event-stage">{event.stage}</span>}
                <span className="event-summary">{event.summary}</span>
              </li>
            ))}
          </ol>
        )}
      </Card>
    </div>
  )
}
