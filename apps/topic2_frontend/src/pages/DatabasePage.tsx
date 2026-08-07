/** 工艺数据库：按材料 / 激光 / 设备 / 几何 / 目标查询真实实验记录。 */

import { useEffect, useState } from 'react'

import { topic2Api } from '../api/topic2'
import { ErrorBanner, EmptyState } from '../components/Banners'
import { StatCard } from '../components/StatCard'
import { formatNumber } from '../lib/format'
import { usePageContextStore } from '../stores/pageContext'
import { useScienceStore } from '../stores/science'

const PAGE_SIZE = 25

export function DatabasePage() {
  const [material, setMaterial] = useState('')
  const [laserType, setLaserType] = useState('')
  const [equipmentId, setEquipmentId] = useState('')
  const [geometryType, setGeometryType] = useState('')
  const [target, setTarget] = useState('')
  const [materials, setMaterials] = useState<string[]>([])
  const [equipment, setEquipment] = useState<string[]>([])
  const [geometries, setGeometries] = useState<string[]>([])
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)
  const setQuickActions = usePageContextStore((state) => state.setQuickActions)
  const {
    experiments,
    experimentsLoading,
    experimentsError,
    setExperiments,
  } = useScienceStore()

  useEffect(() => {
    topic2Api
      .experiments()
      .then((result) => {
        setMaterials([...new Set(result.items.map((row) => row.material))])
        setEquipment([...new Set(result.items.map((row) => row.equipment_id))])
        setGeometries([...new Set(result.items.map((row) => row.geometry_type))])
        setExperiments(result.items)
      })
      .catch((error) =>
        setExperiments([], error instanceof Error ? error.message : '读取实验数据失败'),
      )
    setQuickActions([
      { label: '数据状态如何？', prompt: '请根据工艺数据库页当前展示的真实实验数据，说明数据状态与可支持的分析范围。' },
    ])
    return () => setQuickActions([])
  }, [setExperiments, setQuickActions])

  const applyFilter = () => {
    setVisibleCount(PAGE_SIZE)
    setExperiments([], null, true)
    topic2Api
      .experiments({
        material: material || null,
        laser_type: laserType || null,
        equipment_id: equipmentId || null,
        geometry_type: geometryType || null,
        target: target || null,
      })
      .then((result) => setExperiments(result.items))
      .catch((error) =>
        setExperiments([], error instanceof Error ? error.message : '查询失败'),
      )
  }

  const visible = experiments.slice(0, visibleCount)

  return (
    <div>
      <h1>工艺数据库</h1>
      <p className="card-sub">所有记录均来自 Topic2 Backend SQLite 数据库，前端不做任何加工。</p>

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
          <div className="field">
            <label>加工几何</label>
            <select value={geometryType} onChange={(event) => setGeometryType(event.target.value)}>
              <option value="">全部</option>
              {geometries.map((item) => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>目标指标</label>
            <select value={target} onChange={(event) => setTarget(event.target.value)}>
              <option value="">全部</option>
              <option value="depth_um">depth_um</option>
              <option value="roughness_um">roughness_um</option>
            </select>
          </div>
          <div className="field" style={{ display: 'flex', alignItems: 'flex-end' }}>
            <button className="btn primary" onClick={applyFilter}>
              查询
            </button>
          </div>
        </div>
      </div>

      <div className="stat-grid" style={{ marginBottom: 16 }}>
        <StatCard value={experiments.length} label="命中记录" />
        <StatCard value={new Set(experiments.map((row) => row.parameter_combination_id)).size} label="独立参数组合" />
        <StatCard value={new Set(experiments.map((row) => row.experiment_batch_id)).size} label="实验批次" />
        <StatCard value={experiments.filter((row) => row.valid_flag === 1).length} label="有效记录" />
      </div>

      <ErrorBanner message={experimentsError} />

      <div className="card">
        <div className="card-title">实验记录（实验对象：Material / Equipment / Experiment / Measurement）</div>
        {experimentsLoading ? (
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
                  <th>批次</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((row) => (
                  <tr key={row.experiment_id}>
                    <td className="mono">{row.experiment_id}</td>
                    <td>{row.material}</td>
                    <td>{row.laser_type}</td>
                    <td className="mono">{row.equipment_id}</td>
                    <td>{row.geometry_type}</td>
                    <td>{row.target}</td>
                    <td>{formatNumber(row.pulse_width_ps)}</td>
                    <td>{formatNumber(row.frequency_kHz)}</td>
                    <td>{formatNumber(row.hatch_spacing_um)}</td>
                    <td>{row.passes ?? '—'}</td>
                    <td>{formatNumber(row.scan_speed_mm_s)}</td>
                    <td>{formatNumber(row.depth_um)}</td>
                    <td>{formatNumber(row.roughness_um)}</td>
                    <td className="mono">{row.experiment_batch_id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {visibleCount < experiments.length && (
              <div style={{ marginTop: 12 }}>
                <button className="btn small" onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}>
                  加载更多（{experiments.length - visibleCount} 条剩余）
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
