/** Scientific audit trail: renders a run manifest payload (the backend's
 *  persisted run record) so every decision is traceable. */

import type { RunRecord } from '../api/types'
import { formatNumber, formatTimestamp, runTypeLabel } from '../lib/format'
import { parameterLabel } from '../lib/canonical'

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <h3>{title}</h3>
      {children}
    </div>
  )
}

export function RunTracePanel({ run }: { run: RunRecord }) {
  const payload = run.payload
  const recommended = payload.recommended_parameters as Record<string, number> | undefined
  const runtime = payload.runtime as Record<string, unknown> | undefined
  const scope = payload.scope as Record<string, unknown> | undefined

  return (
    <div data-testid="run-trace-panel">
      <div className="row" style={{ marginBottom: 12 }}>
        <div className="stat-card" style={{ flex: 1 }}>
          <div className="stat-value mono" style={{ fontSize: 15 }}>{run.run_id}</div>
          <div className="stat-label">Run ID</div>
        </div>
        <div className="stat-card" style={{ flex: 1 }}>
          <div className="stat-value">{runTypeLabel(run.run_type)}</div>
          <div className="stat-label">类型</div>
        </div>
        <div className="stat-card" style={{ flex: 1 }}>
          <div className="stat-value mono" style={{ fontSize: 15 }}>{run.task_id}</div>
          <div className="stat-label">任务</div>
        </div>
        <div className="stat-card" style={{ flex: 1 }}>
          <div className="stat-value" style={{ fontSize: 15 }}>{formatTimestamp(run.created_at)}</div>
          <div className="stat-label">时间</div>
        </div>
      </div>

      <ul className="detail-list">
        <li>
          <span className="dl-key">dataset_version</span>
          <span className="dl-value mono">{String(payload.dataset_version ?? '—')}</span>
        </li>
        <li>
          <span className="dl-key">dataset_hash</span>
          <span className="dl-value mono">{String(payload.dataset_hash ?? '—')}</span>
        </li>
        <li>
          <span className="dl-key">n_samples / n_unique_designs</span>
          <span className="dl-value mono">
            {String(payload.n_samples ?? '—')} / {String(payload.n_unique_designs ?? '—')}
          </span>
        </li>
        <li>
          <span className="dl-key">scope</span>
          <span className="dl-value mono">{JSON.stringify(scope ?? {})}</span>
        </li>
        <li>
          <span className="dl-key">candidate_models</span>
          <span className="dl-value mono">
            {Array.isArray(payload.candidate_models) ? payload.candidate_models.join(', ') : '—'}
          </span>
        </li>
        <li>
          <span className="dl-key">selected_model</span>
          <span className="dl-value mono">{String(payload.selected_model ?? '—')}</span>
        </li>
        <li>
          <span className="dl-key">model_version</span>
          <span className="dl-value mono">{String(payload.model_version ?? '—')}</span>
        </li>
        <li>
          <span className="dl-key">evidence_candidates</span>
          <span className="dl-value mono">
            {Array.isArray(payload.evidence_candidates) ? payload.evidence_candidates.join(', ') || '—' : '—'}
          </span>
        </li>
        <li>
          <span className="dl-key">evidence_accepted</span>
          <span className="dl-value mono">
            {Array.isArray(payload.evidence_accepted) ? payload.evidence_accepted.join(', ') || '—' : '—'}
          </span>
        </li>
        <li>
          <span className="dl-key">evidence_rejected</span>
          <span className="dl-value mono">
            {Array.isArray(payload.evidence_rejected)
              ? payload.evidence_rejected.map((item) => (typeof item === 'string' ? item : JSON.stringify(item))).join(', ') || '—'
              : '—'}
          </span>
        </li>
        <li>
          <span className="dl-key">prior_spec_version</span>
          <span className="dl-value mono">{String(payload.prior_spec_version ?? '—')}</span>
        </li>
        <li>
          <span className="dl-key">optimization_method</span>
          <span className="dl-value mono">{String(payload.optimization_method ?? '—')}</span>
        </li>
        <li>
          <span className="dl-key">optimization_config</span>
          <span className="dl-value mono">{JSON.stringify(payload.optimization_config ?? {})}</span>
        </li>
        <li>
          <span className="dl-key">random_seed / git_commit</span>
          <span className="dl-value mono">
            {String((runtime as { seed?: number } | undefined)?.seed ?? '—')} /{' '}
            {String((runtime as { git_commit?: string } | undefined)?.git_commit ?? '—')}
          </span>
        </li>
      </ul>

      {recommended && (
        <Section title="推荐参数">
          <table className="table">
            <thead>
              <tr>
                <th>参数</th>
                <th>值</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(recommended).map(([name, value]) => (
                <tr key={name}>
                  <td>{parameterLabel(name)}</td>
                  <td className="mono">{formatNumber(value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      {Boolean(payload.validation_metrics) && (
        <Section title="验证指标（Group-CV）">
          <pre className="mono" style={{ background: 'var(--bg)', padding: 10, borderRadius: 6 }}>
            {JSON.stringify(payload.validation_metrics, null, 2)}
          </pre>
        </Section>
      )}

      {Boolean(payload.parameter_identification) && (
        <Section title="参数辨识">
          <pre className="mono" style={{ background: 'var(--bg)', padding: 10, borderRadius: 6 }}>
            {JSON.stringify(payload.parameter_identification, null, 2)}
          </pre>
        </Section>
      )}

      {Boolean(payload.model_policy) && (
        <Section title="Model Policy">
          <pre className="mono" style={{ background: 'var(--bg)', padding: 10, borderRadius: 6 }}>
            {JSON.stringify(payload.model_policy, null, 2)}
          </pre>
        </Section>
      )}
    </div>
  )
}
