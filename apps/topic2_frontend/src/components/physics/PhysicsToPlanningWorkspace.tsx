/** Physics-to-Planning V1 views.
 *
 * Every scientific value is read from a persisted ApplicationRun artifact.
 * This module formats values and matrices for display; it does not compile
 * priors, calculate physics, judge satisfaction, simulate, or plan paths.
 */

import { useEffect, useMemo, useState } from 'react'

import { applicationApi } from '../../api/application'
import type {
  ApplicationArtifactSnapshot,
  CalibrationResultArtifact,
  EvidenceIRSetArtifact,
  KnowledgeRequirementSetArtifact,
  LocalRemovalModelArtifact,
  MorphologySimulationArtifact,
  PhysicsToPlanningArtifacts,
  PriorObjectSetArtifact,
  RetrievalQueryPlanArtifact,
  ScientificCapabilityArtifact,
  ToolpathPlanArtifact,
} from '../../api/types'
import { EmptyState, ErrorBanner } from '../Banners'
import { StatusBadge } from '../StatusBadge'
import { formatNumber } from '../../lib/format'
import { scientificLabel, scientificTone } from '../../lib/status'

export type PhysicsToPlanningView =
  | 'capability'
  | 'knowledge'
  | 'calibration'
  | 'simulation'
  | 'planning'

export const PHYSICS_TO_PLANNING_ARTIFACT_TYPES = [
  'ScientificCapabilityReport',
  'KnowledgeRequirementSet',
  'LiteratureRetrievalQueryPlan',
  'EvidenceIRSet',
  'PriorObjectSet',
  'CalibrationResult',
  'LocalRemovalModel',
  'MorphologySimulationResult',
  'ToolpathPlan',
] as const

export async function fetchPhysicsToPlanningArtifacts(
  runId: string,
): Promise<PhysicsToPlanningArtifacts> {
  const metadata = await applicationApi.getArtifacts(runId)
  const wanted = new Set<string>(PHYSICS_TO_PLANNING_ARTIFACT_TYPES)
  const latest = new Map<string, (typeof metadata.items)[number]>()
  for (const item of metadata.items) {
    if (wanted.has(item.artifact_type)) latest.set(item.artifact_type, item)
  }
  const snapshots = await Promise.all(
    [...latest.values()].map(async (item) => {
      const payload = await applicationApi.getArtifact(item.artifact_id)
      return [item.artifact_type, payload.content] as const
    }),
  )
  return Object.fromEntries(snapshots) as PhysicsToPlanningArtifacts
}

export function PhysicsToPlanningWorkspace({
  runId,
  view,
  developerMode,
  artifactRevision = 0,
}: {
  runId: string | null
  view: PhysicsToPlanningView
  developerMode: boolean
  artifactRevision?: number
}) {
  const [artifacts, setArtifacts] = useState<PhysicsToPlanningArtifacts>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    if (!runId) {
      setArtifacts({})
      return () => {
        cancelled = true
      }
    }
    setLoading(true)
    setError(null)
    fetchPhysicsToPlanningArtifacts(runId)
      .then((payload) => {
        if (!cancelled) setArtifacts(payload)
      })
      .catch((reason) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : '读取科学产物失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [runId, artifactRevision])

  if (!runId) return <EmptyState message="请先创建或选择一个 ApplicationRun。" />
  if (loading) return <div className="empty-state"><span className="spinner" /> 正在读取持久化 artifacts…</div>

  return (
    <>
      <ErrorBanner message={error} />
      {view === 'capability' && (
        <CapabilityArtifactView
          snapshot={artifacts.ScientificCapabilityReport}
          requirements={artifacts.KnowledgeRequirementSet}
          developerMode={developerMode}
        />
      )}
      {view === 'knowledge' && (
        <KnowledgeArtifactView
          requirements={artifacts.KnowledgeRequirementSet}
          queryPlans={artifacts.LiteratureRetrievalQueryPlan}
          evidence={artifacts.EvidenceIRSet}
          priors={artifacts.PriorObjectSet}
          developerMode={developerMode}
        />
      )}
      {view === 'calibration' && (
        <CalibrationArtifactView
          capability={artifacts.ScientificCapabilityReport}
          priors={artifacts.PriorObjectSet}
          calibration={artifacts.CalibrationResult}
          developerMode={developerMode}
        />
      )}
      {view === 'simulation' && (
        <SimulationArtifactView
          simulation={artifacts.MorphologySimulationResult}
          model={artifacts.LocalRemovalModel}
          developerMode={developerMode}
        />
      )}
      {view === 'planning' && (
        <PlanningArtifactView
          plan={artifacts.ToolpathPlan}
          simulation={artifacts.MorphologySimulationResult}
          developerMode={developerMode}
        />
      )}
    </>
  )
}

export function CapabilityArtifactView({
  snapshot,
  requirements,
  developerMode,
}: {
  snapshot?: ApplicationArtifactSnapshot<ScientificCapabilityArtifact>
  requirements?: ApplicationArtifactSnapshot<KnowledgeRequirementSetArtifact>
  developerMode: boolean
}) {
  if (!snapshot) return <EmptyState message="当前 checkpoint 尚无 ScientificCapabilityReport。" />
  const capability = snapshot.content
  const requirementItems = requirements?.content.requirements ?? capability.recommended_requirements
  return (
    <div data-testid="capability-view">
      <div className="card">
        <div className="card-title">Task / Scientific Capability</div>
        <div className="row">
          <StatusBadge tone={scientificTone(capability.status)}>{scientificLabel(capability.status)}</StatusBadge>
          <StatusBadge tone={capability.simulation_supported ? 'ok' : 'neutral'}>
            Simulator {capability.simulation_supported ? 'SUPPORTED' : 'NOT SUPPORTED'}
          </StatusBadge>
          <StatusBadge tone="info">Topology {capability.interaction_topology}</StatusBadge>
          {capability.supported_fidelity.map((fidelity) => <span className="badge neutral" key={fidelity}>{fidelity}</span>)}
        </div>
      </div>

      <div className="grid grid-2">
        <CapabilityInputs title="已有输入" items={capability.available} />
        <CapabilityInputs title="缺失输入" items={capability.missing} />
      </div>

      <div className="card">
        <div className="card-title">Identifiability</div>
        <table className="table">
          <thead><tr><th>参数</th><th>状态</th><th>原因</th><th>仍需观测</th></tr></thead>
          <tbody>
            {capability.identifiability.map((item) => (
              <tr key={item.parameter}>
                <td className="mono">{item.parameter}</td>
                <td><StatusBadge tone={scientificTone(item.status)}>{scientificLabel(item.status)}</StatusBadge></td>
                <td>{item.reason_codes.join(', ') || '—'}</td>
                <td>{item.required_observations.join(', ') || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <div className="card-title">Knowledge Requirements（由计算缺口驱动）</div>
        {requirementItems.map((item) => (
          <div className="requirement-card" key={item.requirement_id}>
            <div className="row">
              <b className="mono">{item.requirement_id}</b>
              <StatusBadge tone={scientificTone(item.status)}>{scientificLabel(item.status)}</StatusBadge>
              <span className={`badge ${item.priority === 'high' ? 'warn' : 'neutral'}`}>{item.priority}</span>
              <span className="badge info">{item.type}</span>
            </div>
            <div>{item.scientific_question ?? item.question}</div>
            <div className="muted">required_for: {item.required_for}</div>
          </div>
        ))}
      </div>
      <DeveloperDetails snapshot={snapshot} developerMode={developerMode} reasonCodes={capability.reason_codes} provenance={capability.provenance} />
    </div>
  )
}

function CapabilityInputs({
  title,
  items,
}: {
  title: string
  items: ScientificCapabilityArtifact['available']
}) {
  return (
    <div className="card">
      <div className="card-title">{title}</div>
      {items.length === 0 ? <div className="empty-state">无</div> : (
        <table className="table">
          <thead><tr><th>输入</th><th>值</th><th>状态</th></tr></thead>
          <tbody>{items.map((item) => (
            <tr key={item.name}>
              <td className="mono">{item.name}</td>
              <td>{item.value ?? '—'} {item.unit}</td>
              <td><StatusBadge tone={scientificTone(item.status)}>{scientificLabel(item.status)}</StatusBadge></td>
            </tr>
          ))}</tbody>
        </table>
      )}
    </div>
  )
}

export function KnowledgeArtifactView({
  requirements,
  queryPlans,
  evidence,
  priors,
  developerMode,
}: {
  requirements?: ApplicationArtifactSnapshot<KnowledgeRequirementSetArtifact>
  queryPlans?: ApplicationArtifactSnapshot<RetrievalQueryPlanArtifact>
  evidence?: ApplicationArtifactSnapshot<EvidenceIRSetArtifact>
  priors?: ApplicationArtifactSnapshot<PriorObjectSetArtifact>
  developerMode: boolean
}) {
  if (!requirements) return <EmptyState message="当前 checkpoint 尚无 KnowledgeRequirementSet。" />
  const plans = queryPlans?.content.plans ?? []
  const evidenceItems = evidence?.content.items ?? []
  const priorItems = priors?.content.priors ?? []
  return (
    <div data-testid="knowledge-view">
      <div className="card">
        <div className="card-title">Requirement → Retrieval → Evidence → PriorObject</div>
        <div className="knowledge-chain" aria-label="knowledge artifact chain">
          {['KnowledgeRequirementSet', 'LiteratureRetrievalQueryPlan', 'EvidenceIRSet', 'PriorObjectSet'].map((type, index) => (
            <span key={type}>{index > 0 && <span className="muted"> → </span>}<span className="badge info">{type}</span></span>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="card-title">为什么检索这些科学知识</div>
        {queryPlans && <StatusBadge tone="ok">Geometry policy: {queryPlans.content.geometry_policy}</StatusBadge>}
        {plans.map((plan) => (
          <div className="requirement-card" key={plan.query_plan_id}>
            <div className="row">
              <b className="mono">{plan.requirement_id}</b>
              <span className="badge info">{plan.requirement_type}</span>
              <StatusBadge tone={plan.geometry_is_hard_filter ? 'err' : 'ok'}>
                exact geometry hard filter = {String(plan.geometry_is_hard_filter)}
              </StatusBadge>
            </div>
            <div>{plan.scientific_question}</div>
            <div className="muted">检索词：{plan.query_terms.join(' · ')}</div>
            <div className="muted">Geometry 仅作 ranking/context hint；允许召回相同 interaction topology 的不同形状论文。</div>
          </div>
        ))}
      </div>

      <div className="grid grid-2">
        <div className="card">
          <div className="card-title">EvidenceIR（{evidenceItems.length}）</div>
          {evidenceItems.length === 0 ? <EmptyState message="尚无 EvidenceIR。" /> : evidenceItems.map((item, index) => (
            <div className="requirement-card" key={String(item.evidence_id ?? index)}>
              <b>{String(item.title ?? item.claim_type ?? item.evidence_id ?? `Evidence ${index + 1}`)}</b>
              <div className="muted">claim_type: {String(item.claim_type ?? 'UNKNOWN')}</div>
              {item.source_geometry != null && <div>Source geometry: {String(item.source_geometry)}</div>}
              {item.applicability_status != null && (
                <StatusBadge tone={scientificTone(String(item.applicability_status))}>
                  {scientificLabel(String(item.applicability_status))}
                </StatusBadge>
              )}
            </div>
          ))}
        </div>
        <div className="card">
          <div className="card-title">Typed PriorObject（{priorItems.length}）</div>
          {priorItems.length === 0 ? <EmptyState message="尚无 PriorObject。" /> : priorItems.map((prior) => (
            <div className="requirement-card" key={prior.prior_id}>
              <div className="row"><b>{prior.prior_type}</b><StatusBadge tone={scientificTone(prior.uncertainty)}>{prior.uncertainty}</StatusBadge></div>
              <div>{prior.parameter ?? prior.model_family ?? prior.preference ?? '—'}</div>
              {prior.lower != null && prior.upper != null && <div className="mono">[{prior.lower}, {prior.upper}] {prior.unit}</div>}
              <div className="muted">Evidence refs: {prior.evidence_refs.map((ref) => ref.id).join(', ')}</div>
            </div>
          ))}
        </div>
      </div>
      <DeveloperDetails snapshot={requirements} developerMode={developerMode} />
      <DeveloperDetails snapshot={queryPlans} developerMode={developerMode} />
      <DeveloperDetails snapshot={evidence} developerMode={developerMode} />
      <DeveloperDetails snapshot={priors} developerMode={developerMode} />
    </div>
  )
}

export function CalibrationArtifactView({
  capability,
  priors,
  calibration,
  developerMode,
}: {
  capability?: ApplicationArtifactSnapshot<ScientificCapabilityArtifact>
  priors?: ApplicationArtifactSnapshot<PriorObjectSetArtifact>
  calibration?: ApplicationArtifactSnapshot<CalibrationResultArtifact>
  developerMode: boolean
}) {
  if (!calibration) return <EmptyState message="当前 checkpoint 尚无 CalibrationResult。" />
  const parameterPriors = (priors?.content.priors ?? []).filter((item) => item.prior_type === 'ParameterPrior')
  return (
    <div data-testid="calibration-view">
      <div className="card">
        <div className="card-title">Physics / Calibration</div>
        <div className="row">
          <StatusBadge tone={scientificTone(calibration.content.status)}>{scientificLabel(calibration.content.status)}</StatusBadge>
          <span className="badge neutral">Target observations {calibration.content.fit_metrics.n_observations}</span>
          <span className="badge neutral">RMSE {formatNumber(calibration.content.fit_metrics.rmse)} {calibration.content.fit_metrics.target_unit}</span>
          <span className="badge neutral">Independent validation refs {calibration.content.validation_data_refs.length}</span>
        </div>
      </div>

      <div className="card">
        <div className="card-title">文献 Prior vs Target fitted result</div>
        <table className="table">
          <thead><tr><th>Parameter</th><th>Literature Prior</th><th>Target fitted result</th><th>Identifiability</th><th>Semantics</th></tr></thead>
          <tbody>{calibration.content.parameters.map((parameter) => {
            const matching = parameterPriors.filter((prior) => prior.parameter === parameter.parameter)
            return (
              <tr key={parameter.parameter}>
                <td className="mono">{parameter.parameter}</td>
                <td>{matching.length > 0 ? matching.map((prior) => `[${prior.lower}, ${prior.upper}] ${prior.unit}`).join(' / ') : '—'}</td>
                <td className="mono">
                  {parameter.identifiability === 'NOT_IDENTIFIABLE'
                    ? <span className="muted">—（当前数据不可辨识）</span>
                    : `${formatNumber(parameter.estimate)} [${formatNumber(parameter.lower)}, ${formatNumber(parameter.upper)}] ${parameter.unit}`}
                </td>
                <td><StatusBadge tone={scientificTone(parameter.identifiability)}>{scientificLabel(parameter.identifiability)}</StatusBadge></td>
                <td><span className="badge info">{parameter.parameter_semantics}</span></td>
              </tr>
            )
          })}</tbody>
        </table>
      </div>

      <div className="card">
        <div className="card-title">真实设备 / 数据输入（来自 Capability artifact）</div>
        <table className="table">
          <thead><tr><th>Input</th><th>Value</th><th>Verification state</th><th>Source refs</th></tr></thead>
          <tbody>{(capability?.content.available ?? []).map((item) => (
            <tr key={item.name}>
              <td className="mono">{item.name}</td><td>{item.value ?? '—'} {item.unit}</td>
              <td><StatusBadge tone={scientificTone(item.status)}>{scientificLabel(item.status)}</StatusBadge></td>
              <td className="mono">{item.source_refs.map((ref) => ref.id).join(', ') || '—'}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <DeveloperDetails snapshot={calibration} developerMode={developerMode} provenance={calibration.content.provenance} />
      <DeveloperDetails snapshot={priors} developerMode={developerMode} />
    </div>
  )
}

export function SimulationArtifactView({
  simulation,
  model,
  developerMode,
}: {
  simulation?: ApplicationArtifactSnapshot<MorphologySimulationArtifact>
  model?: ApplicationArtifactSnapshot<LocalRemovalModelArtifact>
  developerMode: boolean
}) {
  if (!simulation) return <EmptyState message="当前 checkpoint 尚无 MorphologySimulationResult。" />
  const result = simulation.content
  return (
    <div data-testid="simulation-view">
      <div className="card">
        <div className="card-title">Stateful 2.5D Morphology Simulator</div>
        <div className="row">
          <StatusBadge tone={scientificTone(result.status)}>{scientificLabel(result.status)}</StatusBadge>
          <span className="badge info">Fidelity {result.fidelity}</span>
          <span className="badge info">LocalRemovalModel {model?.content.mode ?? '—'}</span>
          <span className="badge neutral">Pulses {result.pulse_count}</span>
        </div>
      </div>
      <div className="surface-grid">
        <SurfaceField title="Target surface / depth" values={result.target_depth_field_um} />
        <SurfaceField title="Predicted surface / depth" values={result.predicted_depth_field_um} />
        <SurfaceField title="Difference / error" values={result.difference_field_um} diverging />
      </div>
      <div className="card">
        <div className="card-title">Backend morphology metrics</div>
        <MetricRows metrics={result.metrics} />
      </div>
      <DeveloperDetails snapshot={simulation} developerMode={developerMode} provenance={result.provenance} reasonCodes={result.warnings} />
      <DeveloperDetails snapshot={model} developerMode={developerMode} provenance={model?.content.provenance} />
    </div>
  )
}

function SurfaceField({ title, values, diverging = false }: { title: string; values: number[][] | null; diverging?: boolean }) {
  const flat = useMemo(() => values?.flat() ?? [], [values])
  const extent = useMemo(() => {
    if (flat.length === 0) return { min: 0, max: 1, absolute: 1 }
    const min = Math.min(...flat)
    const max = Math.max(...flat)
    return { min, max, absolute: Math.max(Math.abs(min), Math.abs(max), 1e-12) }
  }, [flat])
  if (!values || values.length === 0 || values[0].length === 0) {
    return <div className="card"><div className="card-title">{title}</div><EmptyState message="后端 artifact 未提供该场。" /></div>
  }
  const columns = values[0].length
  return (
    <div className="card surface-card">
      <div className="card-title">{title}</div>
      <div className="surface-field" style={{ gridTemplateColumns: `repeat(${columns}, minmax(5px, 1fr))` }}>
        {flat.map((value, index) => {
          const normalized = diverging
            ? (value / extent.absolute + 1) / 2
            : (value - extent.min) / Math.max(extent.max - extent.min, 1e-12)
          const hue = diverging ? 220 - normalized * 220 : 210 - normalized * 170
          return <span key={index} className="surface-cell" title={`${formatNumber(value, 5)} µm`} style={{ backgroundColor: `hsl(${hue} 72% 52%)` }} />
        })}
      </div>
      <div className="muted mono">min {formatNumber(extent.min, 4)} · max {formatNumber(extent.max, 4)} µm</div>
    </div>
  )
}

export function PlanningArtifactView({
  plan,
  simulation,
  developerMode,
}: {
  plan?: ApplicationArtifactSnapshot<ToolpathPlanArtifact>
  simulation?: ApplicationArtifactSnapshot<MorphologySimulationArtifact>
  developerMode: boolean
}) {
  if (!plan) return <EmptyState message="当前 checkpoint 尚无 ToolpathPlan。" />
  const item = plan.content
  return (
    <div data-testid="planning-view">
      <div className="card planning-hero">
        <div className="card-title">Recommended ToolpathPlan</div>
        <div className="row">
          <StatusBadge tone={scientificTone(item.status)}>{scientificLabel(item.status)}</StatusBadge>
          <span className="badge info">Path Family {item.path_family}</span>
          <span className="badge neutral">Simulation {item.simulation_ref.id}</span>
        </div>
      </div>
      <div className="grid grid-2">
        <KeyValueCard title="Path Parameters" values={item.path_parameters} />
        <KeyValueCard title="Laser Parameters" values={item.laser_parameters} />
      </div>
      <div className="card">
        <div className="card-title">Predicted Morphology / Expected Cost</div>
        <MetricRows metrics={item.predicted_metrics} />
        <div className="row">
          <span className="badge neutral">Objective {formatNumber(item.objective_value, 5)}</span>
          <span className="badge neutral">Candidates {item.candidate_summary.length}</span>
          <span className="badge neutral">Planning prior refs {item.planning_prior_refs.length}</span>
        </div>
      </div>
      <div className="card">
        <div className="card-title">Machine Constraints</div>
        <table className="table"><thead><tr><th>Parameter</th><th>Lower</th><th>Upper</th><th>Unit</th></tr></thead>
          <tbody>{item.machine_constraints.map((constraint) => (
            <tr key={constraint.name}><td>{constraint.name}</td><td>{constraint.lower ?? '—'}</td><td>{constraint.upper ?? '—'}</td><td>{constraint.unit}</td></tr>
          ))}</tbody>
        </table>
      </div>
      {simulation && <SurfaceField title="Predicted morphology（来自 simulation_ref）" values={simulation.content.predicted_depth_field_um} />}
      <DeveloperDetails snapshot={plan} developerMode={developerMode} provenance={item.provenance} />
      <DeveloperDetails snapshot={simulation} developerMode={developerMode} provenance={simulation?.content.provenance} />
    </div>
  )
}

function MetricRows({ metrics }: { metrics: MorphologySimulationArtifact['metrics'] }) {
  return (
    <div className="metric-strip">
      <div><span>Mean depth</span><b>{formatNumber(metrics.mean_depth_um)} µm</b></div>
      <div><span>Max depth</span><b>{formatNumber(metrics.max_depth_um)} µm</b></div>
      <div><span>Morphology RMSE</span><b>{formatNumber(metrics.morphology_rmse_um)} µm</b></div>
      <div><span>Machining time</span><b>{formatNumber(metrics.machining_time_s)} s</b></div>
    </div>
  )
}

function KeyValueCard({ title, values }: { title: string; values: Record<string, number | string> }) {
  return (
    <div className="card"><div className="card-title">{title}</div>
      <table className="table"><tbody>{Object.entries(values).map(([name, value]) => (
        <tr key={name}><td className="mono">{name}</td><td className="mono">{typeof value === 'number' ? formatNumber(value, 5) : value}</td></tr>
      ))}</tbody></table>
    </div>
  )
}

function DeveloperDetails<T>({
  snapshot,
  developerMode,
  provenance,
  reasonCodes,
}: {
  snapshot?: ApplicationArtifactSnapshot<T>
  developerMode: boolean
  provenance?: unknown
  reasonCodes?: string[]
}) {
  if (!developerMode || !snapshot) return null
  return (
    <details className="card developer-artifact" data-testid={`developer-${snapshot.type}`}>
      <summary><b>{snapshot.type}</b> · schema {snapshot.schema_version} · <span className="mono">{snapshot.id}</span></summary>
      <div className="muted">input_refs: {snapshot.input_refs.map((ref) => `${ref.type}:${ref.id}`).join(', ') || '[]'}</div>
      {reasonCodes && <div className="muted">reason codes: {reasonCodes.join(', ') || '[]'}</div>}
      {provenance != null && <pre className="artifact-json mono">provenance: {JSON.stringify(provenance, null, 2)}</pre>}
      <pre className="artifact-json mono">{JSON.stringify(snapshot.content, null, 2)}</pre>
    </details>
  )
}
