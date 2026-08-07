/** Optimization result: recommended vs vanilla parameters, prediction, acquisition
 *  breakdown, machine bounds and prior spec — all from the backend run. */

import type { OptimizationResult } from '../api/types'
import { formatNumber, formatPercent } from '../lib/format'
import { parameterLabel } from '../lib/canonical'

export function OptimizationResultPanel({ result }: { result: OptimizationResult }) {
  const parameters = Object.keys(result.recommended_parameters)

  return (
    <div>
      <div className="card-sub">
        优化方法：{result.optimization_method} · Run <span className="mono">{result.run_id}</span> ·
        推荐 ID <span className="mono">{result.recommendation_id}</span>
      </div>

      <div className="row">
        <div className="stat-card" style={{ flex: 1 }}>
          <div className="stat-value">{formatNumber(result.prediction.mean)}</div>
          <div className="stat-label">预测质量均值</div>
        </div>
        <div className="stat-card" style={{ flex: 1 }}>
          <div className="stat-value">±{formatNumber(result.prediction.std)}</div>
          <div className="stat-label">预测区间（std）</div>
        </div>
        <div className="stat-card" style={{ flex: 1 }}>
          <div className="stat-value">{formatPercent(result.acquisition.lambda_t)}</div>
          <div className="stat-label">证据权重 λ(t)</div>
        </div>
        <div className="stat-card" style={{ flex: 1 }}>
          <div className="stat-value">
            {result.recommendation_changed_by_evidence ? '是' : '否'}
          </div>
          <div className="stat-label">Evidence 改变推荐点</div>
        </div>
      </div>

      {result.recommendation_changed_by_evidence ? (
        <div className="warn-banner" style={{ marginTop: 12 }}>
          E2P 证据先验改变了推荐参数：Vanilla 与 E2P 结果不同，差异来自确定性 E2P Service 的
          PriorSpec，而非人为构造。
        </div>
      ) : (
        <div className="warn-banner" style={{ marginTop: 12 }}>
          当前 Evidence 未改变最优推荐点：Vanilla 与 E2P 推荐一致。
        </div>
      )}

      <table className="table" style={{ marginTop: 12 }}>
        <thead>
          <tr>
            <th>工艺参数</th>
            <th>E2P 推荐</th>
            <th>Vanilla 推荐</th>
            <th>允许范围</th>
            <th>约束状态</th>
          </tr>
        </thead>
        <tbody>
          {parameters.map((name) => {
            const bounds = result.machine_bounds[name]
            const recommended = result.recommended_parameters[name]
            const within =
              recommended >= bounds.lower && recommended <= bounds.upper
            return (
              <tr key={name}>
                <td>{parameterLabel(name)}</td>
                <td className="mono">{formatNumber(recommended)}</td>
                <td className="mono">{formatNumber(result.vanilla_recommended_parameters[name])}</td>
                <td className="mono">
                  [{formatNumber(bounds.lower)} , {formatNumber(bounds.upper)}]
                </td>
                <td>{within ? <span className="badge ok">满足</span> : <span className="badge err">越界</span>}</td>
              </tr>
            )
          })}
        </tbody>
      </table>

      <h3 style={{ marginTop: 16 }}>采集函数构成（Backend 输出）</h3>
      <ul className="detail-list">
        <li>
          <span className="dl-key">normalized UCB</span>
          <span className="dl-value mono">{formatNumber(result.acquisition.normalized_ucb, 6)}</span>
        </li>
        <li>
          <span className="dl-key">log prior score</span>
          <span className="dl-value mono">{formatNumber(result.acquisition.log_prior, 6)}</span>
        </li>
        <li>
          <span className="dl-key">综合 score</span>
          <span className="dl-value mono">{formatNumber(result.acquisition.score, 6)}</span>
        </li>
      </ul>

      <h3 style={{ marginTop: 16 }}>PriorSpec（E2P Service 确定性输出）</h3>
      {result.prior_spec.range_preferences.length === 0 ? (
        <div className="empty-state">无已接受的范围偏好证据，未生成 PriorSpec 偏好项。</div>
      ) : (
        <table className="table" style={{ marginTop: 8 }}>
          <thead>
            <tr>
              <th>Evidence</th>
              <th>参数</th>
              <th>范围</th>
              <th>强度</th>
              <th>固定权重</th>
            </tr>
          </thead>
          <tbody>
            {result.prior_spec.range_preferences.map((pref) => (
              <tr key={pref.evidence_id}>
                <td className="mono">{pref.evidence_id}</td>
                <td>{parameterLabel(pref.parameter)}</td>
                <td className="mono">
                  [{formatNumber(pref.lower)}, {formatNumber(pref.upper)}]
                </td>
                <td>{transferLabelOf(pref.strength)}</td>
                <td className="mono">{formatNumber(pref.fixed_weight, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function transferLabelOf(strength: string): string {
  const labels: Record<string, string> = {
    strong: '强适用',
    medium: '中适用',
    weak: '弱适用',
    none: '不适用',
  }
  return labels[strength] ?? strength
}
