/** DataResourcePage（/resources/data）：实验数据资源页。
 *  只读浏览 Topic2 数据库实验记录（按材料/激光/设备/几何过滤），不做科学计算。 */

import { useEffect, useState } from 'react'

import { topic2Api } from '../api/topic2'
import { ErrorBanner, EmptyState } from '../components/Banners'
import { StatCard } from '../components/StatCard'
import { formatNumber } from '../lib/format'

const PAGE_SIZE = 25

export function DataResourcePage() {
  const [material, setMaterial] = useState('')
  const [laserType, setLaserType] = useState('')
  const [equipmentId, setEquipmentId] = useState('')
  const [materials, setMaterials] = useState<string[]>([])
  const [equipment, setEquipment] = useState<string[]>([])
  const [rows, setRows] = useState<Record<string, unknown>[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)

  useEffect(() => {
    let cancelled = false
    topic2Api
      .experiments()
      .then((result) => {
        if (cancelled) return
        setMaterials([...new Set(result.items.map((row) => row.material))])
        setEquipment([...new Set(result.items.map((row) => row.equipment_id))])
        setRows(result.items as unknown as Record<string, unknown>[])
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : '读取实验数据失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const applyFilter = () => {
    setVisibleCount(PAGE_SIZE)
    setLoading(true)
    setError(null)
    topic2Api
      .experiments({
        material: material || null,
        laser_type: laserType || null,
        equipment_id: equipmentId || null,
      })
      .then((result) => setRows(result.items as unknown as Record<string, unknown>[]))
      .catch((err) => setError(err instanceof Error ? err.message : '查询失败'))
      .finally(() => setLoading(false))
  }

  const visible = rows.slice(0, visibleCount)

  return (
    <div>
      <h1>实验数据</h1>
      <p className="card-sub">所有记录均来自 Topic2 Backend 数据库，前端不做任何加工。</p>

      <div className="card">
        <div className="card-title">查询条件</div>
        <div className="grid grid-3">
          <div className="field">
            <label>材料</label>
            <select value={material} onChange={(event) => setMaterial(event.target.value)}>
              <option value="">全部</option>
              {materials.map((item) => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>激光类型</label>
            <select value={laserType} onChange={(event) => setLaserType(event.target.value)}>
              <option value="">全部</option>
              <option value="fs">fs</option>
              <option value="ps">ps</option>
            </select>
          </div>
          <div className="field">
            <label>设备</label>
            <select value={equipmentId} onChange={(event) => setEquipmentId(event.target.value)}>
              <option value="">全部</option>
              {equipment.map((item) => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
          </div>
          <div className="field" style={{ display: 'flex', alignItems: 'flex-end' }}>
            <button className="btn primary" onClick={applyFilter}>查询</button>
          </div>
        </div>
      </div>

      <div className="stat-grid" style={{ marginBottom: 12 }}>
        <StatCard value={rows.length} label="命中记录" />
        <StatCard value={new Set(rows.map((row) => row.parameter_combination_id)).size} label="独立参数组合" />
        <StatCard value={new Set(rows.map((row) => row.experiment_batch_id)).size} label="实验批次" />
        <StatCard value={rows.filter((row) => row.valid_flag === 1).length} label="有效记录" />
      </div>

      <ErrorBanner message={error} />

      <div className="card">
        <div className="card-title">实验记录</div>
        {loading ? (
          <div className="empty-state">
            <span className="spinner" /> 查询中…
          </div>
        ) : visible.length === 0 ? (
          <EmptyState message="无匹配记录。" />
        ) : (
          <>
            <table className="table">
              <thead>
                <tr>
                  <th>实验 ID</th>
                  <th>材料</th>
                  <th>激光</th>
                  <th>设备</th>
                  <th>几何</th>
                  <th>目标</th>
                  <th>脉宽 ps</th>
                  <th>频率 kHz</th>
                  <th>填充间距 μm</th>
                  <th>遍数</th>
                  <th>速度 mm/s</th>
                  <th>深度 μm</th>
                  <th>粗糙度 μm</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((row) => (
                  <tr key={String(row.experiment_id)}>
                    <td className="mono">{String(row.experiment_id)}</td>
                    <td>{String(row.material)}</td>
                    <td>{String(row.laser_type)}</td>
                    <td className="mono">{String(row.equipment_id)}</td>
                    <td>{String(row.geometry_type)}</td>
                    <td>{String(row.target)}</td>
                    <td>{formatNumber(row.pulse_width_ps as number)}</td>
                    <td>{formatNumber(row.frequency_kHz as number)}</td>
                    <td>{formatNumber(row.hatch_spacing_um as number)}</td>
                    <td>{row.passes != null ? String(row.passes) : '—'}</td>
                    <td>{formatNumber(row.scan_speed_mm_s as number)}</td>
                    <td>{formatNumber(row.depth_um as number)}</td>
                    <td>{formatNumber(row.roughness_um as number)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {visibleCount < rows.length && (
              <div style={{ marginTop: 12 }}>
                <button className="btn small" onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}>
                  加载更多（{rows.length - visibleCount} 条剩余）
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
