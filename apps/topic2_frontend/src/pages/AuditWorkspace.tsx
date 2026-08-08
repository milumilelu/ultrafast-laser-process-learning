/** Scientific Run Inspector（P1 Observability）：/runs 核心开发工具。
 *
 *  四个 Tab 全部读取真实持久化数据，前端不硬编码任何执行链：
 *  - Flow：由 WorkflowEvent 重建的科学执行 DAG（stage → 子操作 → artifact）
 *  - Events：真实 persisted 事件流（含 trace details）
 *  - Artifacts：科学状态快照 JSON Inspector
 *  - State：关键状态快照摘要（TaskState → Requirements → KnowledgeState → Learning → Planning）
 *
 *  Developer Mode 开关控制 ID / raw payload / provenance / reason codes 显示。
 */

import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { applicationApi } from '../api/application'
import type { ApplicationRunSummary, WorkflowEvent } from '../api/types'
import { ErrorBanner, EmptyState } from '../components/Banners'
import { StatusBadge } from '../components/StatusBadge'
import { formatTimestamp } from '../lib/format'

interface ArtifactMeta {
  artifact_id: string
  artifact_type: string
  created_at: string
}

interface ArtifactSnapshot {
  id: string
  type: string
  schema_version: string
  input_refs: { type: string; id: string }[]
  content: Record<string, unknown>
  created_at: string
}

type InspectorTab = 'flow' | 'events' | 'artifacts' | 'state'

const EVENT_LABELS: Record<string, string> = {
  STAGE_STARTED: '阶段开始',
  STAGE_COMPLETED: '阶段完成',
  TOOL_STARTED: '操作开始',
  TOOL_COMPLETED: '操作完成',
  ENTITY_CREATED: '实体创建',
  ARTIFACT_CREATED: '产物生成',
  VALIDATION: '校验',
  WARNING: '警告',
  ERROR: '错误',
  RUN_STARTED: '运行开始',
  RUN_COMPLETED: '运行完成',
  RUN_FAILED: '运行失败',
}

const STATE_ARTIFACT_TYPES = [
  'TaskState',
  'ScientificCapabilityReport',
  'KnowledgeRequirementSet',
  'EvidenceIRSet',
  'PriorObjectSet',
  'CalibrationResult',
  'PhysicalModelState',
  'LocalRemovalModel',
  'MorphologySimulationResult',
  'ToolpathPlan',
  'KnowledgeState',
  'ProcessLearningResult',
]

export function AuditWorkspace() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [runs, setRuns] = useState<ApplicationRunSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<ApplicationRunSummary | null>(null)
  const [events, setEvents] = useState<WorkflowEvent[]>([])
  const [artifacts, setArtifacts] = useState<ArtifactMeta[]>([])
  const [snapshots, setSnapshots] = useState<Record<string, ArtifactSnapshot>>({})
  const [selectedArtifact, setSelectedArtifact] = useState<ArtifactSnapshot | null>(null)
  const [tab, setTab] = useState<InspectorTab>('flow')
  const [developerMode, setDeveloperMode] = useState(false)

  const openRun = useCallback((runId: string) => {
    setSelectedArtifact(null)
    applicationApi
      .getRun(runId)
      .then((run) => setSelected(run))
      .catch((err) => setError(err instanceof Error ? err.message : '读取应用运行失败'))
    applicationApi
      .getEvents(runId)
      .then((result) => setEvents(result.items))
      .catch(() => setEvents([]))
    applicationApi
      .getArtifacts(runId)
      .then((result) => setArtifacts(result.items))
      .catch(() => setArtifacts([]))
  }, [])

  useEffect(() => {
    const queryRun = searchParams.get('run')
    if (queryRun) openRun(queryRun)
  }, [searchParams, openRun])

  const loadRuns = useCallback(() => {
    setLoading(true)
    applicationApi
      .listRuns()
      .then((result) => setRuns(result.items))
      .catch((err) => setError(err instanceof Error ? err.message : '读取运行记录失败'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    loadRuns()
  }, [loadRuns])

  const inspectArtifact = useCallback(
    (artifactId: string) => {
      const cached = snapshots[artifactId]
      if (cached) {
        setSelectedArtifact(cached)
        return
      }
      applicationApi
        .getArtifact(artifactId)
        .then((payload) => {
          const snapshot = payload.content as unknown as ArtifactSnapshot
          setSnapshots((current) => ({ ...current, [artifactId]: snapshot }))
          setSelectedArtifact(snapshot)
        })
        .catch(() => undefined)
    },
    [snapshots],
  )

  return (
    <div>
      <h1>运行与审计 · Scientific Run Inspector</h1>
      <p className="card-sub">
        科学运行检查器：Flow / Events / Artifacts / State 全部来自真实持久化数据，
        可逐级追溯「输入了什么 → 调用了什么 → 产出了什么 → 为什么接受/拒绝」。
      </p>

      <ErrorBanner message={error} />

      <div className="row" style={{ marginBottom: 10, alignItems: 'center' }}>
        <label className="dev-mode-toggle" style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
          <input
            type="checkbox"
            checked={developerMode}
            onChange={(event) => setDeveloperMode(event.target.checked)}
          />
          <b>Developer Mode</b>
          <span className="muted">（显示 ID / 原始数据 / 来源 / 原因码）</span>
        </label>
      </div>

      <div className="grid grid-2">
        <div className="card">
          <div className="card-title">Application Runs</div>
          {loading ? (
            <div className="empty-state">
              <span className="spinner" /> 读取中…
            </div>
          ) : runs.length === 0 ? (
            <EmptyState message="暂无 Application Run。运行完整分析后自动生成。" />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Run ID</th>
                  <th>模式</th>
                  <th>状态</th>
                  <th>时间</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr
                    key={run.application_run_id}
                    className={selected?.application_run_id === run.application_run_id ? 'row-selected' : ''}
                    onClick={() => {
                      setSearchParams({ run: run.application_run_id })
                      openRun(run.application_run_id)
                    }}
                  >
                    <td className="mono">{run.application_run_id}</td>
                    <td>{run.mode === 'demo' ? '演示' : '研究'}</td>
                    <td>
                      <StatusBadge tone={run.status === 'completed' ? 'ok' : run.status === 'failed' ? 'err' : 'warn'}>
                        {run.status}
                      </StatusBadge>
                    </td>
                    <td>{formatTimestamp(run.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {selected && (
          <div className="card">
            <div className="card-title">
              {selected.application_run_id}
              <span className="badge neutral">{selected.workflow_version}</span>
              <span className="badge neutral">{selected.mode}</span>
            </div>
            <div className="row" style={{ marginBottom: 6 }}>
              <StatusBadge tone="neutral">事件 {events.length}</StatusBadge>
              <StatusBadge tone="neutral">产物 {artifacts.length}</StatusBadge>
              <StatusBadge tone="neutral">Task {selected.task_context_ref}</StatusBadge>
            </div>
            <div className="card-sub">
              完成时间：{selected.completed_at ? formatTimestamp(selected.completed_at) : '—'}
            </div>
            <div className="row">
              {Object.keys(selected.stage_status ?? {}).map((stage) => (
                <span className="badge neutral" key={stage}>
                  {stage}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {selected && (
        <>
          <div className="app-tabs" data-testid="inspector-tabs">
            {(
              [
                ['flow', 'Flow 科学数据流'],
                ['events', 'Events 真实事件'],
                ['artifacts', 'Artifacts 产物'],
                ['state', 'State 状态'],
              ] as [InspectorTab, string][]
            ).map(([key, label]) => (
              <button key={key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>
                {label}
              </button>
            ))}
          </div>

          {tab === 'flow' && <FlowTab events={events} developerMode={developerMode} />}
          {tab === 'events' && <EventsTab events={events} developerMode={developerMode} />}
          {tab === 'artifacts' && (
            <ArtifactsTab
              artifacts={artifacts}
              selectedArtifact={selectedArtifact}
              onInspect={inspectArtifact}
              developerMode={developerMode}
            />
          )}
          {tab === 'state' && (
            <StateTab artifacts={artifacts} onInspect={inspectArtifact} developerMode={developerMode} />
          )}
        </>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ Flow */

export function FlowTab({ events, developerMode }: { events: WorkflowEvent[]; developerMode: boolean }) {
  if (events.length === 0) {
    return <EmptyState message="无事件数据（该 Run 未记录事件）。" />
  }
  // 按 stage 分组：STAGE_STARTED → 子事件 → STAGE_COMPLETED
  const stages: { stage: string; children: WorkflowEvent[] }[] = []
  let current: { stage: string; children: WorkflowEvent[] } | null = null
  for (const event of events) {
    if (event.type === 'STAGE_STARTED') {
      current = { stage: event.stage ?? 'application', children: [] }
      stages.push(current)
      continue
    }
    if (event.type === 'STAGE_COMPLETED') {
      current = null
      continue
    }
    if (event.type === 'RUN_STARTED' || event.type === 'RUN_COMPLETED' || event.type === 'RUN_FAILED') {
      continue
    }
    if (current) current.children.push(event)
  }

  return (
    <div className="flow-tab" data-testid="flow-tab">
      {stages.map(({ stage, children }) => (
        <div key={stage} className="flow-stage">
          <div className="flow-stage-title">
            <span className="badge info">{stage}</span>
            <span className="muted">
              {children.filter((event) => event.type === 'TOOL_STARTED').length} 个操作 ·{' '}
              {children.filter((event) => event.type === 'ARTIFACT_CREATED').length} 个产物
            </span>
          </div>
          <div className="flow-children">
            {children.map((event) => (
              <div key={event.event_id} className="flow-child">
                <span className={`badge ${toneOf(event.type)}`}>{EVENT_LABELS[event.type] ?? event.type}</span>
                <span className="flow-summary">{event.summary}</span>
                {developerMode && (
                  <div className="flow-details mono muted">
                    {event.details && Object.keys(event.details).length > 0 && (
                      <pre className="flow-json">{JSON.stringify(event.details, null, 1)}</pre>
                    )}
                    {event.artifactRefs && event.artifactRefs.length > 0 && (
                      <div>→ {event.artifactRefs.map((ref) => `${ref.type}:${ref.id}`).join(', ')}</div>
                    )}
                    {event.entityRefs && event.entityRefs.length > 0 && (
                      <div>实体 {event.entityRefs.map((ref) => `${ref.type}:${ref.id}`).join(', ')}</div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function toneOf(type: string): 'ok' | 'warn' | 'err' | 'neutral' | 'info' {
  if (type === 'TOOL_COMPLETED' || type === 'ARTIFACT_CREATED' || type === 'ENTITY_CREATED') return 'ok'
  if (type === 'WARNING' || type === 'VALIDATION') return 'warn'
  if (type === 'ERROR') return 'err'
  return 'info'
}

/* ---------------------------------------------------------------- Events */

function EventsTab({ events, developerMode }: { events: WorkflowEvent[]; developerMode: boolean }) {
  if (events.length === 0) {
    return <EmptyState message="无事件数据。" />
  }
  return (
    <div className="card" data-testid="events-tab">
      <div className="card-title">真实执行事件（{events.length}）</div>
      <table className="table">
        <thead>
          <tr>
            <th>#</th>
            <th>时间</th>
            <th>类型</th>
            <th>阶段</th>
            <th>摘要</th>
          </tr>
        </thead>
        <tbody>
          {events.map((event) => (
            <tr key={event.event_id}>
              <td className="mono">{event.sequence}</td>
              <td className="mono">{formatTimestamp(event.timestamp).slice(11)}</td>
              <td>
                <span className={`badge ${toneOf(event.type)}`}>{EVENT_LABELS[event.type] ?? event.type}</span>
              </td>
              <td className="mono">{event.stage ?? '—'}</td>
              <td>
                {event.summary}
                {developerMode && event.details && Object.keys(event.details).length > 0 && (
                  <details>
                    <summary className="muted">trace details</summary>
                    <pre className="artifact-json mono">{JSON.stringify(event.details, null, 2)}</pre>
                  </details>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ------------------------------------------------------------- Artifacts */

function ArtifactsTab({
  artifacts,
  selectedArtifact,
  onInspect,
  developerMode,
}: {
  artifacts: ArtifactMeta[]
  selectedArtifact: ArtifactSnapshot | null
  onInspect: (artifactId: string) => void
  developerMode: boolean
}) {
  return (
    <div className="card" data-testid="artifacts-tab">
      <div className="card-title">科学产物（Artifacts · {artifacts.length}）</div>
      <div className="row" style={{ marginBottom: 8 }}>
        {artifacts.map((artifact) => (
          <button key={artifact.artifact_id} className="btn small" onClick={() => onInspect(artifact.artifact_id)}>
            {artifact.artifact_type}
          </button>
        ))}
      </div>
      {selectedArtifact && (
        <div>
          <div className="card-sub">
            类型 <b>{selectedArtifact.type}</b> · schema {selectedArtifact.schema_version} ·{' '}
            {developerMode && <span className="mono">{selectedArtifact.id}</span>}
          </div>
          {developerMode && selectedArtifact.input_refs.length > 0 && (
            <div className="muted" style={{ marginBottom: 6 }}>
              来源（input_refs）：{selectedArtifact.input_refs.map((ref) => `${ref.type}:${ref.id}`).join(', ')}
            </div>
          )}
          {developerMode ? (
            <>
              {'provenance' in selectedArtifact.content && (
                <pre className="artifact-json mono">
                  provenance: {JSON.stringify(selectedArtifact.content.provenance, null, 2)}
                </pre>
              )}
              {'reason_codes' in selectedArtifact.content && (
                <div className="muted">
                  reason codes: {JSON.stringify(selectedArtifact.content.reason_codes)}
                </div>
              )}
              <pre className="artifact-json mono">{JSON.stringify(selectedArtifact.content, null, 2)}</pre>
            </>
          ) : (
            <div className="empty-state">开启 Developer Mode 查看 raw payload、provenance 与 reason codes。</div>
          )}
        </div>
      )}
    </div>
  )
}

/* ----------------------------------------------------------------- State */

function StateTab({
  artifacts,
  onInspect,
  developerMode,
}: {
  artifacts: ArtifactMeta[]
  onInspect: (artifactId: string) => void
  developerMode: boolean
}) {
  const stateArtifacts = artifacts.filter((artifact) => STATE_ARTIFACT_TYPES.includes(artifact.artifact_type))
  if (stateArtifacts.length === 0) {
    return <EmptyState message="该 Run 暂无状态快照产物。" />
  }
  return (
    <div className="state-tab" data-testid="state-tab">
      <div className="card-sub">关键状态快照（点击查看原始内容）</div>
      {stateArtifacts.map((artifact) => (
        <div key={artifact.artifact_id} className="state-card">
          <button className="btn small" onClick={() => onInspect(artifact.artifact_id)}>
            {artifact.artifact_type}
          </button>
          {developerMode && <span className="id-chip muted">{artifact.artifact_id}</span>}
        </div>
      ))}
      <div className="card-sub" style={{ marginTop: 12 }}>
        所有节点均来自当前 Run 的真实 artifact metadata；点击后读取对应 schema、input refs 与原始 payload。
      </div>
    </div>
  )
}
