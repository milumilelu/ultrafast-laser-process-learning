/** Simulation section (M6): MorphologySimulationResult metrics +
 * height-field heatmap + center cross-section profile (pure SVG/CSS). */

import { useMemo } from 'react'
import type { ArtifactSnapshot } from '../../domain/artifact'
import { buildSimulationView, FIDELITY_LABEL } from '../../domain/simulation'
import { Card, EmptyState } from '../../components/ui/Card'
import { StatusBadge } from '../../components/ui/StatusBadge'

export function SimulationSection({
  simulation,
  model,
}: {
  simulation?: ArtifactSnapshot
  model?: ArtifactSnapshot
}) {
  const view = useMemo(
    () => buildSimulationView(simulation?.content as Record<string, unknown>),
    [simulation],
  )
  if (!simulation) {
    return (
      <div className="section">
        <h1>Simulation 仿真</h1>
        <EmptyState
          message="尚无仿真产物"
          hint="运行 establish_process_model / plan_process 后生成 MorphologySimulationResult。"
        />
      </div>
    )
  }
  const modelMode = ((model?.content as Record<string, unknown>)?.mode as string) ?? ''

  return (
    <div className="section">
      <div className="section-head">
        <h1>Simulation 仿真</h1>
        <StatusBadge
          tone={view.status === 'KNOWN' ? 'ok' : view.status === 'PARTIAL' ? 'warn' : 'neutral'}
          label={`${FIDELITY_LABEL[view.fidelity] ?? view.fidelity} · ${view.status}`}
        />
      </div>

      <div className="cards-grid">
        <Card title="预测指标">
          <div className="metric-list">
            <div className="metric"><span className="metric-label">平均深度</span><span className="metric-value">{view.meanDepthUm?.toFixed(2) ?? '—'} µm</span></div>
            <div className="metric"><span className="metric-label">最大深度</span><span className="metric-value">{view.maxDepthUm?.toFixed(2) ?? '—'} µm</span></div>
            <div className="metric"><span className="metric-label">形貌 RMSE</span><span className="metric-value">{view.morphologyRmseUm?.toFixed(2) ?? '—'} µm</span></div>
            <div className="metric"><span className="metric-label">脉冲数</span><span className="metric-value">{view.pulseCount}</span></div>
            <div className="metric"><span className="metric-label">加工时间</span><span className="metric-value">{view.machiningTimeS?.toFixed(4) ?? '—'} s</span></div>
          </div>
          {view.targetDepthUm !== null && (
            <div className="card-hint">
              目标平均深度 {view.targetDepthUm.toFixed(2)} µm vs 预测 {view.predictedDepthUm?.toFixed(2) ?? '—'} µm
            </div>
          )}
        </Card>

        <Card title="模型与保真度">
          <div className="metric-list">
            <div className="metric"><span className="metric-label">LocalRemovalModel</span><span className="metric-value">{modelMode || '—'}</span></div>
            <div className="metric"><span className="metric-label">仿真 ID</span><span className="metric-value">{view.simulationId}</span></div>
            <div className="metric"><span className="metric-label">网格间距</span><span className="metric-value">{view.gridSpacingUm ?? '—'} µm</span></div>
          </div>
        </Card>
      </div>

      <div className="cards-grid">
        <Card title="预测形貌（俯视热图）">
          <HeightFieldHeatmap grid={view.heightField} />
        </Card>
        <Card title="中心截面轮廓">
          <ProfileChart section={view.crossSection} />
        </Card>
      </div>
      {view.warnings.length > 0 && (
        <Card title="警告">
          <ul className="gate-reasons">
            {view.warnings.map((warning, index) => (
              <li key={index}>{warning}</li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}

function HeightFieldHeatmap({ grid }: { grid: number[][] }) {
  if (grid.length === 0) {
    return <EmptyState message="无高度场数据" />
  }
  const cols = grid[0]?.length ?? 0
  if (cols === 0) return <EmptyState message="无高度场数据" />
  const all = grid.flat().filter((value) => Number.isFinite(value))
  const max = Math.max(...all, 0.0001)
  const cellSize = 6
  return (
    <div className="heatmap-wrap" role="img" aria-label="predicted morphology heatmap">
      <div
        className="heatmap"
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${cols}, ${cellSize}px)`,
          gridAutoRows: `${cellSize}px`,
        }}
      >
        {grid.flatMap((row, y) =>
          row.map((depth, x) => {
            const ratio = Math.min(1, Math.max(0, depth / max))
            const lightness = 12 + ratio * 60
            return (
              <div
                key={`${x}-${y}`}
                className="heatmap-cell"
                style={{ backgroundColor: `hsl(210 70% ${lightness}%)` }}
                title={`(${x}, ${y}) ${depth.toFixed(2)} µm`}
              />
            )
          }),
        )}
      </div>
      <div className="card-hint">深度 µm · 每格 {grid.length} 行 × {cols} 列</div>
    </div>
  )
}

function ProfileChart({ section }: { section: { x: number; depth: number }[] }) {
  if (section.length === 0) {
    return <EmptyState message="无截面数据" />
  }
  const width = 300
  const height = 120
  const padding = 8
  const maxDepth = Math.max(...section.map((point) => point.depth), 0.0001)
  const points = section
    .map((point, index) => {
      const x = padding + (index / Math.max(1, section.length - 1)) * (width - 2 * padding)
      const y = height - padding - (point.depth / maxDepth) * (height - 2 * padding)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
  return (
    <svg className="profile-chart" width={width} height={height} role="img" aria-label="cross-section profile">
      <polyline points={points} fill="none" stroke="var(--accent)" strokeWidth="1.5" />
      <line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} stroke="var(--border)" />
      <text x={padding} y={height - 2} fontSize="9" fill="var(--text-dim)">0</text>
      <text x={width - 2 * padding} y={height - 2} fontSize="9" fill="var(--text-dim)">
        {((section.length - 1) * (section[1]?.x - section[0]?.x || 0)).toFixed(0)} µm
      </text>
      <text x={padding} y={height - padding - (height - 2 * padding)} fontSize="9" fill="var(--text-dim)">
        {maxDepth.toFixed(1)} µm
      </text>
    </svg>
  )
}
