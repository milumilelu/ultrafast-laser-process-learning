import { useEffect, useMemo, useState, type Dispatch, type SetStateAction } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  evidencePriorApi,
  type EvidenceBelief,
  type EvidenceItem,
  type EvidencePriorRequest,
  type EvidencePriorResult,
  type PriorObject,
  type TargetMetric,
} from '../../api/evidencePrior'
import { datasetsApi, type EquipmentProfileEntry } from '../../api/datasets'
import { Button } from '../../components/ui/Button'
import { Card, EmptyState, ErrorBanner, Spinner } from '../../components/ui/Card'
import { EquipmentProfileForm } from '../equipment/EquipmentProfileForm'

export function EvidencePriorPage() {
  const profiles = useQuery({
    queryKey: ['equipment-profiles', 'EVIDENCE_PRIOR_V1'],
    queryFn: () => datasetsApi.equipmentProfiles(),
  })
  const [showEquipmentForm, setShowEquipmentForm] = useState(false)
  const [task, setTask] = useState<EvidencePriorRequest>({
    material: '',
    equipment_profile_id: '',
    equipment_revision_id: '',
    target_metric: 'depth_um',
  })
  const selectedProfile = useMemo(
    () => profiles.data?.find((profile) => profile.equipment_profile_id === task.equipment_profile_id),
    [profiles.data, task.equipment_profile_id],
  )

  useEffect(() => {
    if (task.equipment_profile_id || !profiles.data?.length) return
    const profile = profiles.data[0]
    setTask((previous) => ({
      ...previous,
      equipment_profile_id: profile.equipment_profile_id,
      equipment_revision_id: profile.revision_id ?? profile.revisions?.[0]?.revision_id ?? '',
    }))
  }, [profiles.data, task.equipment_profile_id])

  const analysis = useMutation({ mutationFn: evidencePriorApi.analyze })
  const submit = () => {
    if (!task.material.trim() || !task.equipment_profile_id || !task.equipment_revision_id) return
    analysis.mutate({
      ...task,
      material: task.material.trim(),
      material_grade: task.material_grade?.trim() || undefined,
    })
  }

  return (
    <div className="evidence-prior-page">
      <div className="evidence-prior-heading">
        <div>
          <h1>文献证据 → E2P 先验</h1>
          <p>设备 revision 与任务共同定义检索语境；每篇论文独立抽取，证据经适用性评估后形成软先验。</p>
        </div>
        {analysis.isPending && <div className="analysis-running"><Spinner /> 正在调用真实 LLM 逐论文抽取…</div>}
      </div>

      <div className="evidence-prior-inputs">
        <Card title="1. 设备档案构建 / 选择">
          {profiles.isLoading && <Spinner />}
          {profiles.isError && <ErrorBanner message={(profiles.error as Error).message} />}
          <label className="field">
            <span>设备档案</span>
            <select
              value={task.equipment_profile_id}
              onChange={(event) => selectProfile(event.target.value, profiles.data ?? [], setTask)}
            >
              <option value="">选择设备…</option>
              {(profiles.data ?? []).map((profile) => (
                <option key={profile.equipment_profile_id} value={profile.equipment_profile_id}>
                  {profile.profile_name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>锁定 revision</span>
            <select
              value={task.equipment_revision_id}
              onChange={(event) => setTask((previous) => ({ ...previous, equipment_revision_id: event.target.value }))}
              disabled={!selectedProfile}
            >
              <option value="">选择 revision…</option>
              {revisionOptions(selectedProfile).map((revision) => (
                <option key={revision.revision_id} value={revision.revision_id}>
                  {revision.revision_number ? `v${revision.revision_number} · ` : ''}{revision.revision_id}
                </option>
              ))}
            </select>
          </label>
          {selectedProfile && <EquipmentSummary profile={selectedProfile} />}
          <Button variant="ghost" onClick={() => setShowEquipmentForm((value) => !value)}>
            {showEquipmentForm ? '收起设备表单' : '新建设备档案'}
          </Button>
          {showEquipmentForm && (
            <EquipmentProfileForm
              onCompleted={(result) => {
                setTask((previous) => ({
                  ...previous,
                  equipment_profile_id: result.equipment_profile_id,
                  equipment_revision_id: result.revision_id,
                }))
                setShowEquipmentForm(false)
              }}
            />
          )}
        </Card>

        <Card title="2. 用户需求输入">
          <div className="form-grid evidence-task-grid">
            <label className="field">
              <span>材料 *</span>
              <input
                value={task.material}
                onChange={(event) => setTask((previous) => ({ ...previous, material: event.target.value }))}
                placeholder="例如：4H-SiC、diamond、Ti6Al4V"
              />
            </label>
            <label className="field">
              <span>材料牌号（可选）</span>
              <input
                value={task.material_grade ?? ''}
                onChange={(event) => setTask((previous) => ({ ...previous, material_grade: event.target.value }))}
                placeholder="例如：4H、航空级"
              />
            </label>
            <label className="field">
              <span>目标指标 *</span>
              <select
                value={task.target_metric}
                onChange={(event) => setTask((previous) => ({
                  ...previous,
                  target_metric: event.target.value as TargetMetric,
                }))}
              >
                <option value="depth_um">加工深度 depth_um</option>
                <option value="roughness_um">表面粗糙度 roughness_um</option>
              </select>
            </label>
          </div>
          <p className="card-hint">不要求 dataset、几何、当前功率设定或 Planning 参数。</p>
          <ErrorBanner message={(analysis.error as Error | null)?.message ?? null} />
          <Button
            onClick={submit}
            busy={analysis.isPending}
            disabled={!task.material.trim() || !task.equipment_revision_id}
          >
            开始文献检索、抽取与 E2P
          </Button>
        </Card>
      </div>

      <div className="evidence-prior-outputs">
        <EvidencePanel result={analysis.data} />
        <PriorPanel result={analysis.data} />
      </div>
    </div>
  )
}

function selectProfile(
  id: string,
  profiles: EquipmentProfileEntry[],
  setTask: Dispatch<SetStateAction<EvidencePriorRequest>>,
) {
  const profile = profiles.find((item) => item.equipment_profile_id === id)
  const revision = profile?.revision_id ?? profile?.revisions?.[0]?.revision_id ?? ''
  setTask((previous) => ({
    ...previous,
    equipment_profile_id: id,
    equipment_revision_id: revision,
  }))
}

function revisionOptions(profile?: EquipmentProfileEntry) {
  if (!profile) return []
  const revisions = [...(profile.revisions ?? [])]
  if (profile.revision_id && !revisions.some((item) => item.revision_id === profile.revision_id)) {
    revisions.unshift({ revision_id: profile.revision_id })
  }
  return revisions
}

function EquipmentSummary({ profile }: { profile: EquipmentProfileEntry }) {
  const laser = profile.laser_source ?? {}
  const measured = numberValue(laser.measured_max_power_W)
  const rated = numberValue(laser.rated_max_power_W)
  const ratio = numberValue(laser.power_transmission_ratio)
  const effective = measured ?? (rated !== null && ratio !== null ? rated * ratio : rated)
  const source = measured !== null
    ? 'MEASURED'
    : rated !== null && ratio !== null
      ? 'DERIVED_FROM_ATTENUATION'
      : rated !== null
        ? 'MANUFACTURER_SPEC'
        : 'UNKNOWN'
  return (
    <dl className="equipment-summary">
      <div><dt>脉宽</dt><dd>{rangeText(laser.pulse_width_min_fs, laser.pulse_width_max_fs, 'fs')}</dd></div>
      <div><dt>频率</dt><dd>{rangeText(laser.frequency_min_kHz, laser.frequency_max_kHz, 'kHz')}</dd></div>
      <div><dt>有效最大功率</dt><dd>{effective === null ? '缺失' : `${effective} W`} · {source}</dd></div>
    </dl>
  )
}

function EvidencePanel({ result }: { result?: EvidencePriorResult }) {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const selected = result?.evidence.items.find((item) => item.evidence_id === selectedId)
    ?? result?.evidence.items[0]
  return (
    <Card title="3. 文献知识抽取结果">
      {!result && <EmptyState message="尚未运行分析" hint="提交设备 revision 与任务后展示逐论文 EvidenceIR。" />}
      {result && (
        <>
          <div className="result-stats">
            <span>{result.requirements.length} 个精确需求</span>
            <span>{result.evidence.items.length} 条 EvidenceIR</span>
            <span>{result.evidence.llm_call_count} 次 LLM</span>
            <span>{result.evidence.knowledge_reused_count} 条知识复用</span>
          </div>
          <div className="evidence-browser">
            <ol className="evidence-result-list">
              {result.evidence.items.map((item) => (
                <li key={item.evidence_id}>
                  <button
                    className={selected?.evidence_id === item.evidence_id ? 'evidence-result-active' : ''}
                    onClick={() => setSelectedId(item.evidence_id)}
                  >
                    <strong>{item.content.evidence_type}</strong>
                    <span>{item.paper_title || item.paper_id}</span>
                    <small>p.{item.source_pages.join(', ') || '—'} · {item.validation_state}</small>
                  </button>
                </li>
              ))}
            </ol>
            {selected ? <EvidenceDetail evidence={selected} /> : <EmptyState message="未抽取到证据" />}
          </div>
        </>
      )}
    </Card>
  )
}

function EvidenceDetail({ evidence }: { evidence: EvidenceItem }) {
  return (
    <div className="evidence-detail">
      <h3>{evidence.paper_title || evidence.paper_id}</h3>
      <blockquote>{evidence.evidence_quote || '无有效原文引文'}</blockquote>
      <dl className="kv-list">
        <Kv label="evidence_id" value={evidence.evidence_id} />
        <Kv label="content" value={evidence.content} />
        <Kv label="conditions" value={evidence.conditions} />
        <Kv label="blocks" value={evidence.source_block_refs} />
        <Kv label="extractor" value={`${evidence.extractor_model} · ${evidence.extraction_route}`} />
        <Kv label="confidence" value={evidence.extraction_confidence} />
        {evidence.validation_errors.length > 0 && <Kv label="validation errors" value={evidence.validation_errors} />}
      </dl>
    </div>
  )
}

function PriorPanel({ result }: { result?: EvidencePriorResult }) {
  const beliefs = new Map(result?.beliefs.beliefs.map((belief) => [belief.belief_id, belief]))
  return (
    <Card title="4. E2P 先验结果">
      {!result && <EmptyState message="尚无 E2P 输出" hint="EvidenceIR 经逐维适用性评估后形成 belief 与软先验。" />}
      {result && (
        <>
          <div className="result-stats">
            <span>{result.beliefs.beliefs.length} 个 EvidenceBelief</span>
            <span>{result.priors.priors.length} 个 PriorObject</span>
            <span>{result.priors.conflicts.length} 个冲突组</span>
          </div>
          <div className="prior-list">
            {result.priors.priors.map((prior) => (
              <PriorCard key={prior.prior_id} prior={prior} belief={beliefs.get(prior.belief_refs[0])} />
            ))}
          </div>
          {result.priors.priors.length === 0 && <EmptyState message="没有形成软先验" />}
          {result.warnings.length > 0 && (
            <div className="governance-reminders">
              <h3>结果提醒</h3>
              <ul>{result.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>
            </div>
          )}
        </>
      )}
    </Card>
  )
}

function PriorCard({ prior, belief }: { prior: PriorObject; belief?: EvidenceBelief }) {
  return (
    <article className="prior-card-v1">
      <header>
        <strong>{prior.prior_type}</strong>
        <span>{prior.status} · uncertainty {prior.uncertainty}</span>
      </header>
      <div className="prior-main">{priorSummary(prior)}</div>
      <div className="prior-score">applicability {prior.applicability_score.toFixed(3)} · weight {prior.weight.toFixed(3)}</div>
      {prior.conflict_group_id && <div className="prior-conflict">冲突组：{prior.conflict_group_id}</div>}
      {belief && (
        <details>
          <summary>适用性分解（{belief.transfer_level}）</summary>
          <table className="data-table">
            <tbody>
              {belief.facets.map((facet) => (
                <tr key={facet.facet}>
                  <td>{facet.facet}</td><td>{facet.status}</td><td>{facet.score.toFixed(3)}</td><td>{facet.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
      <div className="mono small">evidence: {prior.evidence_refs.join(', ')}</div>
    </article>
  )
}

function priorSummary(prior: PriorObject): string {
  if (prior.prior_type === 'ParameterPrior') {
    if (prior.value !== null && prior.value !== undefined) return `${prior.parameter} = ${prior.value} ${prior.unit ?? ''}`
    return `${prior.parameter}: [${prior.lower ?? '—'}, ${prior.upper ?? '—'}] ${prior.unit ?? ''}`
  }
  if (prior.prior_type === 'RegionPrior') return `${prior.target_metric}: ${JSON.stringify(prior.parameters ?? [])}`
  if (prior.prior_type === 'ModelStructurePrior') return `${prior.mechanism}: ${prior.statement ?? ''}`
  return `${prior.parameter ? `${prior.parameter} · ` : ''}${prior.direction ?? ''} ${prior.statement ?? ''}`
}

function Kv({ label, value }: { label: string; value: unknown }) {
  return <div className="kv-row"><dt>{label}</dt><dd>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>
}

function rangeText(lower: unknown, upper: unknown, unit: string) {
  return lower === undefined || upper === undefined ? '缺失' : `${String(lower)}–${String(upper)} ${unit}`
}

function numberValue(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  return null
}
