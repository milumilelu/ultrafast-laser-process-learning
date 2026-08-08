/** Topic2DemoWorkspace (UI-9): DEMO_SCENARIO_01 只读演示。
 *  复用 IntelligentProcessApplication 的正式结果组件，注入 demo 模式 +
 *  固定场景（SiC / fs / rectangular_groove / depth_um / EQ-DEMO-FS / seed 42）。 */

import { useCallback, useState } from 'react'
import { Link } from 'react-router-dom'

import { applicationApi } from '../api/application'
import type { Topic2ApplicationResult } from '../api/types'
import { ErrorBanner } from '../components/Banners'
import { StatusBadge } from '../components/StatusBadge'

const DEMO_NARRATIVE = [
  '① Target（SiC · fs · rectangular groove · depth_um）',
  '② Parameter Identification',
  '③ Process Modeling',
  '④ Scientific Evidence（固定 5-paper pilot set）',
  '⑤ CFA Applicability（UNCALIBRATED，audit only）',
  '⑥ E2P Governed Prior',
  '⑦ Vanilla vs Assisted BO',
  '⑧ Recommended Next Experiment',
  '⑨ Audit / Replay',
]

export function Topic2DemoWorkspace() {
  const [demoResult, setDemoResult] = useState<Topic2ApplicationResult | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [replay, setReplay] = useState<Record<string, unknown> | null>(null)

  const runDemo = useCallback(async () => {
    setError(null)
    setDemoResult(null)
    setReplay(null)
    setRunning(true)
    try {
      const summary = await applicationApi.createRun({
        mode: 'demo',
        random_seed: 42,
        client_request_id: crypto.randomUUID(),
      })
      if (summary.status === 'failed') {
        setError('演示运行失败（fails closed，未伪造结果）。')
        setRunning(false)
        return
      }
      const result = await applicationApi.getResult(summary.application_run_id)
      setDemoResult(result)
      setRunning(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : '演示运行失败')
      setRunning(false)
    }
  }, [])

  const runReplay = useCallback(async () => {
    if (!demoResult) return
    setReplay(null)
    try {
      const result = await applicationApi.replay(demoResult.runId)
      setReplay(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Replay 失败')
    }
  }, [demoResult])

  return (
    <div className="demo-workspace">
      <h1>Topic 2 演示（Demo Scenario 01）</h1>
      <p className="card-sub">
        绑定冻结场景：SiC · fs · rectangular_groove · depth_um · EQ-DEMO-FS · 固定数据集 ·
        固定 5-paper pilot 文献 · seed 42 · CFA 未校准。任务配置只读，结果可一键运行与重放。
      </p>

      <div className="row" style={{ marginBottom: 12 }}>
        <button className="btn primary" onClick={runDemo} disabled={running}>
          {running ? (
            <>
              <span className="spinner" /> 运行 Topic 2 演示中…
            </>
          ) : (
            '运行 Topic 2 演示'
          )}
        </button>
        {demoResult && (
          <button className="btn" onClick={runReplay}>
            Replay
          </button>
        )}
        {demoResult && (
          <StatusBadge tone="ok">演示完成：{demoResult.runId}</StatusBadge>
        )}
      </div>

      <ErrorBanner message={error} />

      <div className="grid grid-2" style={{ marginBottom: 16 }}>
        <div className="card">
          <div className="card-title">演示流程</div>
          <ol className="detail-list">
            {DEMO_NARRATIVE.map((step) => (
              <li key={step} className="dl-value">
                {step}
              </li>
            ))}
          </ol>
        </div>
        {demoResult && (
          <div className="card">
            <div className="card-title">Why should I trust this recommendation?</div>
            <ul className="detail-list">
              <li>
                <span className="dl-key">DATA</span>
                <span className="dl-value">{demoResult.targetTask.sampleCount ?? '—'} experimental samples</span>
              </li>
              <li>
                <span className="dl-key">MODEL</span>
                <span className="dl-value">Group-CV selected model: {demoResult.processLearning.selectedModel ?? '—'}</span>
              </li>
              <li>
                <span className="dl-key">EVIDENCE</span>
                <span className="dl-value">
                  {demoResult.scientificBasis.governedEvidenceCount ?? 0} governed literature claims
                </span>
              </li>
              <li>
                <span className="dl-key">APPLICABILITY</span>
                <span className="dl-value">
                  Uncalibrated CFA（{demoResult.cfa.calibrationStatus}）· Unknown preserved
                </span>
              </li>
              <li>
                <span className="dl-key">OPTIMIZATION</span>
                <span className="dl-value">GP-UCB + audited soft prior</span>
              </li>
              <li>
                <span className="dl-key">TRACEABILITY</span>
                <span className="dl-value">Every result links to source artifacts</span>
              </li>
            </ul>
            {replay && (
              <div className="warn-banner" style={{ marginTop: 12 }}>
                Scientific payload identical:{' '}
                {replay.scientific_payload_identical ? '✓' : '✗'} · Runtime IDs changed:
                {replay.runtime_ids_changed ? ' expected ✓' : ' —'}（新 Run {String(replay.replay_run_id)}）
              </div>
            )}
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-title">演示工作区（只读，复用正式结果组件）</div>
        <p className="card-sub">
          演示模式锁定科学输入；结果组件与研究模式完全一致。可在页顶切换模式后进入应用工作区查看完整辨识 / 建模 / 优化结果。
        </p>
        <Link className="btn" to="/application">
          进入工艺智能应用
        </Link>
      </div>

      {demoResult && (
        <div className="card">
          <div className="card-title">演示结果摘要</div>
          <div className="grid grid-2">
            <div>
              <div className="card-sub">推荐下一实验点（Evidence-assisted）</div>
              <table className="table">
                <thead>
                  <tr>
                    <th>参数</th>
                    <th>Assisted</th>
                    <th>Vanilla</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.keys(demoResult.optimization.evidenceAssisted.recommended_parameters ?? {}).map((name) => (
                    <tr key={name}>
                      <td>{name}</td>
                      <td className="mono">
                        {String(demoResult.optimization.evidenceAssisted.recommended_parameters?.[name] ?? '—')}
                      </td>
                      <td className="mono">
                        {String(demoResult.optimization.vanilla.recommended_parameters?.[name] ?? '—')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div>
              <div className="card-sub">治理与审计</div>
              <ul className="detail-list">
                <li>
                  <span className="dl-key">选中模型</span>
                  <span className="dl-value">{demoResult.processLearning.selectedModel ?? '—'}</span>
                </li>
                <li>
                  <span className="dl-key">prior applied</span>
                  <span className="dl-value">
                    vanilla={String(demoResult.optimization.priorAppliedEvidence.vanilla_search_prior_applied)} · assisted=
                    {String(demoResult.optimization.priorAppliedEvidence.assisted_search_prior_applied)}
                  </span>
                </li>
                <li>
                  <span className="dl-key">prior hash</span>
                  <span className="dl-value mono">
                    {demoResult.optimization.priorAppliedEvidence.governed_prior_hash ?? '—'}
                  </span>
                </li>
                <li>
                  <span className="dl-key">evidence ids</span>
                  <span className="dl-value mono">
                    {(demoResult.optimization.priorAppliedEvidence.assisted_prior_evidence_ids ?? []).join(', ') || '—'}
                  </span>
                </li>
                <li>
                  <span className="dl-key">CFA</span>
                  <span className="dl-value">{demoResult.cfa.calibrationStatus} · facets:{' '}
                    {Object.entries(demoResult.cfa.facetSummary ?? {})
                      .map(([facet, status]) => `${facet}=${status}`)
                      .join(' ')}
                  </span>
                </li>
              </ul>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
