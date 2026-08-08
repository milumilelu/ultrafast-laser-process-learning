/** Run Inspector (spec §二十二): Flow / Artifacts / Events from real run data. */

import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { runsApi, type WorkflowEvent } from '../../api/runs'
import { useQuery } from '@tanstack/react-query'
import { CANONICAL_STAGES, STAGE_LABEL } from '../../domain/stages'
import { useUiStore } from '../../stores/ui'
import { Card, EmptyState, ErrorBanner, Spinner } from '../../components/ui/Card'
import { StatusBadge } from '../../components/ui/StatusBadge'
import { Tabs } from '../../components/ui/Tabs'
import { RefChip } from '../../components/scientific/Artifact'

const TABS = [
  { id: 'flow', label: 'Flow' },
  { id: 'artifacts', label: 'Artifacts' },
  { id: 'events', label: 'Events' },
  { id: 'compare', label: 'Compare' },
]

export function RunInspectorPage() {
  const { runId } = useParams()
  const [tab, setTab] = useState('flow')
  const developerMode = useUiStore((state) => state.developerMode)

  const runQuery = useQuery({
    queryKey: ['run-inspector', runId],
    queryFn: () => runsApi.getRun(runId as string),
    enabled: Boolean(runId),
    refetchInterval: (query) => (query.state.data?.status === 'running' ? 2000 : false),
  })
  const eventsQuery = useQuery({
    queryKey: ['run-inspector-events', runId],
    queryFn: () => runsApi.getEvents(runId as string),
    enabled: Boolean(runId),
    refetchInterval: (query) =>
      query.state.data && query.state.data.items.some((e) => e.type === 'RUN_COMPLETED' || e.type === 'RUN_FAILED')
        ? false
        : 2000,
  })
  const artifactsQuery = useQuery({
    queryKey: ['run-inspector-artifacts', runId],
    queryFn: () => runsApi.getArtifacts(runId as string),
    enabled: Boolean(runId),
  })

  const run = runQuery.data
  const events = eventsQuery.data?.items ?? []

  if (runQuery.isLoading) return <div className="section"><Spinner /> 加载运行记录…</div>
  if (runQuery.isError) {
    return (
      <div className="section">
        <h1>运行记录</h1>
        <ErrorBanner message={(runQuery.error as Error).message} />
      </div>
    )
  }

  return (
    <div className="section">
      <div className="section-head">
        <h1>Run {run?.application_run_id}</h1>
        <StatusBadge
          tone={run?.status === 'completed' ? 'ok' : run?.status === 'failed' ? 'err' : 'info'}
          label={String(run?.status ?? 'unknown')}
        />
      </div>

      <Tabs tabs={TABS} active={tab} onChange={setTab} />

      {tab === 'flow' && (
        <Card title="执行 DAG（真实 events 构造）">
          <FlowDag events={events} developerMode={developerMode} />
        </Card>
      )}

      {tab === 'artifacts' && (
        <Card title="Artifacts">
          {artifactsQuery.data?.items.length ? (
            <table className="data-table">
              <thead>
                <tr>
                  <th>artifact_id</th>
                  <th>artifact_type</th>
                  <th>created_at</th>
                </tr>
              </thead>
              <tbody>
                {artifactsQuery.data.items.map((item) => (
                  <tr key={item.artifact_id}>
                    <td className="mono">{item.artifact_id}</td>
                    <td>{item.artifact_type}</td>
                    <td>{item.created_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <EmptyState message="尚无 artifacts" />
          )}
        </Card>
      )}

      {tab === 'events' && (
        <Card title="Events">
          {events.length === 0 ? (
            <EmptyState message="尚无 events" />
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>seq</th>
                  <th>type</th>
                  <th>stage</th>
                  <th>summary</th>
                  {developerMode && <th>details</th>}
                </tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <tr key={event.event_id}>
                    <td className="mono">#{event.sequence}</td>
                    <td>{event.type}</td>
                    <td>{event.stage ?? '—'}</td>
                    <td>{event.summary}</td>
                    {developerMode && (
                      <td>
                        <details>
                          <summary>details</summary>
                          <pre className="mono small">{JSON.stringify(event.details, null, 2)}</pre>
                        </details>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}

      {tab === 'compare' && (
        <Card title="Compare">
          <EmptyState message="Run 对比在下一迭代实现（F6）" hint="将支持两个 Run 的参数 / 知识 / 模型 / 仿真 / 规划对比。" />
        </Card>
      )}
    </div>
  )
}

/** Flow DAG built exclusively from persisted WorkflowEvents (spec FE-9). */
export function FlowDag({ events, developerMode }: { events: WorkflowEvent[]; developerMode: boolean }) {
  const nodes = useMemo(() => {
    const stageEvents = new Map<string, { started: WorkflowEvent | null; completed: WorkflowEvent | null }>()
    for (const event of events) {
      if (!event.stage) continue
      const entry = stageEvents.get(event.stage) ?? { started: null, completed: null }
      if (event.type === 'STAGE_STARTED') entry.started = event
      if (event.type === 'STAGE_COMPLETED') entry.completed = event
      stageEvents.set(event.stage, entry)
    }
    const order = CANONICAL_STAGES
    return [...stageEvents.entries()]
      .map(([stage, entry]) => ({ stage, ...entry, order: order.indexOf(stage as (typeof order)[number]) }))
      .filter((node) => node.order >= 0)
      .sort((a, b) => a.order - b.order)
  }, [events])

  const artifactEvents = useMemo(() => events.filter((e) => e.type === 'ARTIFACT_CREATED'), [events])

  if (nodes.length === 0) {
    return <EmptyState message="暂无 stage events" hint="运行开始后由真实 STAGE_STARTED / STAGE_COMPLETED 事件构造。" />
  }

  return (
    <div className="flow-dag">
      <ol className="flow-list">
        {nodes.map((node, index) => (
          <li key={node.stage} className="flow-node">
            <div className="flow-node-head">
              <span className="flow-index">{index + 1}</span>
              <span className="flow-stage">{STAGE_LABEL[node.stage as keyof typeof STAGE_LABEL] ?? node.stage}</span>
              <span className="flow-key mono">{node.stage}</span>
              <StatusBadge
                tone={node.completed ? 'ok' : node.started ? 'info' : 'neutral'}
                label={node.completed ? 'completed' : node.started ? 'running' : 'not run'}
              />
            </div>
            {developerMode && node.completed && node.completed.artifactRefs.length > 0 && (
              <div className="flow-artifacts">
                {node.completed.artifactRefs.map((ref) => (
                  <RefChip key={`${ref.type}:${ref.id}`} ref={ref} />
                ))}
              </div>
            )}
            {index < nodes.length - 1 && <div className="flow-arrow" aria-hidden="true" />}
          </li>
        ))}
      </ol>
      {developerMode && artifactEvents.length > 0 && (
        <details className="dev-payload">
          <summary>ARTIFACT_CREATED events（{artifactEvents.length}）</summary>
          <pre className="mono small">{JSON.stringify(artifactEvents.map((e) => ({ seq: e.sequence, stage: e.stage, refs: e.artifactRefs })), null, 2)}</pre>
        </details>
      )}
    </div>
  )
}

export function RunsPage() {
  const query = useQuery({
    queryKey: ['runs-list'],
    queryFn: () => runsApi.listRuns(),
    refetchInterval: 5000,
  })
  return (
    <div className="section">
      <h1>运行记录</h1>
      {query.isLoading && <Spinner />}
      {query.data && query.data.items.length === 0 && <EmptyState message="暂无 ApplicationRun" hint="在「工作台」创建任务并运行后出现。" />}
      {query.data && query.data.items.length > 0 && (
        <Card title={`ApplicationRuns（${query.data.items.length}）`}>
          <table className="data-table">
            <thead>
              <tr>
                <th>run_id</th>
                <th>mode</th>
                <th>status</th>
                <th>workflow</th>
                <th>created_at</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {query.data.items.map((run) => (
                <tr key={run.application_run_id}>
                  <td className="mono">{run.application_run_id.slice(0, 20)}…</td>
                  <td>{run.mode}</td>
                  <td>
                    <StatusBadge
                      tone={run.status === 'completed' ? 'ok' : run.status === 'failed' ? 'err' : 'info'}
                      label={run.status}
                    />
                  </td>
                  <td>{run.workflow_version}</td>
                  <td>{run.created_at}</td>
                  <td>
                    <Link className="link" to={`/runs/${run.application_run_id}`}>
                      打开
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  )
}
