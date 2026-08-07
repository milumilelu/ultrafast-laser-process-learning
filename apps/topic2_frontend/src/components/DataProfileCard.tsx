/** DataProfile card: descriptive counts computed from backend experiment rows.
 *  Maturity judgement stays backend-side (Model Policy). */

import type { DataProfile } from '../api/types'
import { formatNumber, formatPercent } from '../lib/format'

export function DataProfileCard({ profile }: { profile: DataProfile }) {
  return (
    <div className="grid grid-3">
      <div className="stat-card">
        <div className="stat-value">{profile.n_samples}</div>
        <div className="stat-label">样本数量</div>
      </div>
      <div className="stat-card">
        <div className="stat-value">{profile.n_unique_designs}</div>
        <div className="stat-label">独立参数组合</div>
      </div>
      <div className="stat-card">
        <div className="stat-value">{profile.n_features}</div>
        <div className="stat-label">输入参数数量</div>
      </div>
      <div className="stat-card">
        <div className="stat-value">{profile.batch_count}</div>
        <div className="stat-label">实验批次</div>
      </div>
      <div className="stat-card">
        <div className="stat-value">{profile.equipment_count}</div>
        <div className="stat-label">设备数量</div>
      </div>
      <div className="stat-card">
        <div className="stat-value">{formatPercent(profile.missing_rate)}</div>
        <div className="stat-label">缺失率</div>
      </div>
      <div className="stat-card">
        <div className="stat-value">{formatPercent(profile.replicate_ratio)}</div>
        <div className="stat-label">组合重复比</div>
      </div>
      <div className="stat-card">
        <div className="stat-value">{profile.coverage_score === null ? '—' : formatNumber(profile.coverage_score)}</div>
        <div className="stat-label">覆盖度（Backend 提供时显示）</div>
      </div>
      <div className="stat-card">
        <div className="stat-value">后端判定</div>
        <div className="stat-label">数据成熟度由 Model Policy 判定</div>
      </div>
    </div>
  )
}
