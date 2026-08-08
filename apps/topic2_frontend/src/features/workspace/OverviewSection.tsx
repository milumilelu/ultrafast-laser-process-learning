/** Overview: 科学决策首页 (spec §六). Four readiness cards + one next action. */

import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import type { ApplicationRunRecord, WorkflowEvent } from '../../api/runs'
import type { ArtifactSnapshot } from '../../domain/artifact'
import { buildCapabilityView, buildChainStatus, recommendNextAction } from '../../domain/capability'
import { buildRequirements } from '../../domain/knowledge'
import { buildCalibrationView } from '../../domain/calibration'
import { CANONICAL_STAGES } from '../../domain/stages'
import { scientificLabel, scientificTone, scientificStatusFrom } from '../../domain/status'
import { getTaskDraft } from '../../stores/taskDrafts'
import { Card, EmptyState, Spinner } from '../../components/ui/Card'
import { StatusBadge } from '../../components/ui/StatusBadge'
import { Button } from '../../components/ui/Button'
import { DependencyChain } from '../../components/scientific/DependencyChain'
import { SnapshotMeta } from '../../components/scientific/Artifact'
import { TaskForm } from './TaskForm'

interface OverviewSectionProps {
  taskId: string
  runStatus: string | null
  artifacts?: Map<string, ArtifactSnapshot>
  run: ApplicationRunRecord | null | undefined
  events: WorkflowEvent[]
  busy: boolean
  onContinue: (stages?: string[]) => void
  nextCheckpoint: string | null
}

export function OverviewSection({
  taskId,
  runStatus,
  artifacts,
  run,
  events,
  busy,
  onContinue,
  nextCheckpoint,
}: OverviewSectionProps) {
  const draft = getTaskDraft(taskId)
  const [editing, setEditing] = useState(false)
  const [hint, setHint] = useState<string | null>(null)

  const capability = useMemo(() => {
    const snapshot = artifacts?.get('ScientificCapabilityReport')
    return buildCapabilityView(snapshot?.content as Record<string, unknown>)
  }, [artifacts])

  const chain = useMemo(() => buildChainStatus(capability), [capability])

  const knowledge = useMemo(() => {
    const snapshot = artifacts?.get('KnowledgeRequirementSet')
    const requirements = buildRequirements(snapshot?.content as Record<string, unknown>)
    const satisfied = requirements.filter((r) => r.status === 'KNOWN' || r.status === 'PARTIAL').length
    const unresolved = requirements.length - satisfied
    return { total: requirements.length, satisfied, unresolved }
  }, [artifacts])

  const calibration = useMemo(() => {
    const snapshot = artifacts?.get('CalibrationResult')
    const view = buildCalibrationView(snapshot?.content as Record<string, unknown>)
    if (!view) return { estimated: 0, priorOnly: 0, notIdentifiable: 0, hasRun: false }
    const estimated = view.parameters.filter((p) => p.estimate !== null).length
    const notIdentifiable = view.parameters.filter((p) => p.identifiability === 'NOT_IDENTIFIABLE').length
    return { estimated, priorOnly: view.parameters.length - estimated, notIdentifiable, hasRun: true }
  }, [artifacts])

  const planning = useMemo(() => {
    const plan = artifacts?.get('ToolpathPlan')
    const model = artifacts?.get('LocalRemovalModel')
    if (plan) return { status: 'KNOWN', detail: '已生成 ToolpathPlan' }
    if (model) return { status: 'PARTIAL', detail: '已有 LocalRemovalModel，尚未规划路径' }
    return { status: 'UNKNOWN', detail: '尚未建立局部去除模型' }
  }, [artifacts])

  const nextAction = useMemo(() => recommendNextAction(capability, runStatus), [capability, runStatus])

  const capabilityStatus = capability ? capability.status : 'UNKNOWN'
  const stageCount = CANONICAL_STAGES.filter((stage) => run?.stage_status?.[stage]?.status === 'completed').length

  const draftComplete = Boolean(
    draft && draft.material && draft.laserType && draft.geometryType && draft.objectiveMetric && draft.equipmentProfileId,
  )
  const handleStart = () => {
    if (!draftComplete) {
      setEditing(true)
      setHint('请先完成材料 / 激光 / 几何 / 目标 / 设备的选择。')
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
              {nextCheckpoint ? '继续' : '重新推进'}
            </Button>
          )}
        </div>
      </div>

      {hint && <div className="warning-note">任务未完成：{hint}</div>}

      {editing && !draft.runId && <TaskForm taskId={taskId} onSaved={() => setEditing(false)} />}

      {draft.runId && (
        <div className="overview-runline">
          第 {stageCount}/{CANONICAL_STAGES.length} 阶段完成 · Run 状态:{' '}
          <strong>{runStatus ?? '…'}</strong>
          {busy && <Spinner />}
        </div>
      )}

      <div className="cards-grid">
        <Card title="Scientific Capability" actions={<StatusBadge tone={scientificTone(scientificStatusFrom(capabilityStatus))} label={scientificLabel(scientificStatusFrom(capabilityStatus))} />}>
          {capability ? (
            <>
              <div className="card-stat">
                {capability.inputs.filter((i) => i.status === 'AVAILABLE').length}/
                {capability.inputs.length} 物理输入可解析
              </div>
              <div className="card-stat">Simulator {capability.supportedFidelity.join(', ') || '未声明'}</div>
              {chain.nodes.length > 0 && (
                <details>
                  <summary>执行能力依赖</summary>
                  <DependencyChain nodes={chain.nodes} />
                </details>
              )}
            </>
          ) : (
            <EmptyState message="尚未生成 ScientificCapabilityReport" hint="点击「开始运行」执行能力预检。" />
          )}
          <SnapshotMeta snapshot={artifacts?.get('ScientificCapabilityReport')} />
        </Card>

        <Card title="Knowledge" actions={<StatusBadge tone={knowledge.total === 0 ? 'neutral' : knowledge.unresolved > 0 ? 'warn' : 'ok'} label={`${knowledge.total === 0 ? '未生成' : knowledge.unresolved > 0 ? '部分' : '就绪'}`} />}>
          {knowledge.total > 0 ? (
            <>
              <div className="card-stat">{knowledge.total} 个需求</div>
              <div className="card-stat">{knowledge.satisfied} 已满足 · {knowledge.unresolved} 未解决</div>
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

        <Card title="Planning" actions={<StatusBadge tone={planning.status === 'KNOWN' ? 'ok' : planning.status === 'PARTIAL' ? 'warn' : 'neutral'} label={planning.status === 'KNOWN' ? '就绪' : planning.status === 'PARTIAL' ? '部分' : '受阻'} />}>
          <div className="card-stat">{planning.detail}</div>
        </Card>
      </div>

      <Card title="Recommended Next Action" className="next-action-card">
        <div className="next-action">
          <div className="next-action-message">{nextAction.message}</div>
          <div className="next-action-detail">{nextAction.detail}</div>
          {nextAction.missingInputs.length > 0 && (
            <div className="next-action-missing">
              缺少: {nextAction.missingInputs.join(', ')}
            </div>
          )}
          {nextAction.kind === 'CONTINUE' && (
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
