/** EquipmentResourcePage (/resources/equipment): 设备档案资源页。
 *  Agent 设备档案（机器边界/光学设置/工艺能力）+ Topic2 实验设备清单。 */

import { useEffect, useState } from 'react'

import { agentApi } from '../api/agent'
import { topic2Api } from '../api/topic2'
import type { EquipmentProfile, EquipmentProfileBase } from '../api/types'
import { EmptyState } from '../components/Banners'
import { StatusBadge } from '../components/StatusBadge'
import { equipmentParamLabel } from '../lib/canonical'
import { formatNumber } from '../lib/format'
import { useTaskContextStore } from '../stores/taskContext'

export function EquipmentResourcePage() {
  const [profiles, setProfiles] = useState<EquipmentProfileBase[]>([])
  const [selected, setSelected] = useState<EquipmentProfile | null>(null)
  const [topic2Equipment, setTopic2Equipment] = useState<{ equipment_id: string; laser_id: string | null }[]>([])
  const [loading, setLoading] = useState(true)
  const context = useTaskContextStore((state) => state.context)

  useEffect(() => {
    let cancelled = false
    agentApi
      .listEquipmentProfiles()
      .then((items) => {
        if (!cancelled) setProfiles(items)
      })
      .catch(() => undefined)
    topic2Api
      .equipment()
      .then((result) => {
        if (!cancelled) setTopic2Equipment(result.items.map((item) => ({ equipment_id: item.equipment_id, laser_id: item.laser_id })))
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const openProfile = (id: string) => {
    setSelected(null)
    agentApi
      .getEquipmentProfile(id)
      .then(setSelected)
      .catch(() => undefined)
  }

  const selectedOptical = (selected?.optical_setup ?? {}) as Record<string, number | string | null>
  const selectedLaser = (selected?.laser_source ?? {}) as Record<string, number | string | null>
  const selectedCapability = Object.fromEntries(
    Object.entries(selected?.process_capability ?? {}).filter(
      // 热扩散系数/烧蚀阈值是材料参数（任务定义中设置），不再展示为设备能力
      ([key]) => key !== 'thermal_diffusivity_m2_s' && key !== 'ablation_threshold_J_cm2',
    ),
  ) as Record<string, number | string | null>

  return (
    <div>
      <h1>设备档案</h1>
      <p className="card-sub">
        设备档案（Agent 侧）提供机器边界与光学/材料属性；数据集设备（Topic2 侧）提供科学查询 scope。
        物理输入只来自已持久化设备档案，前端不把科学候选直接提升为设备参数。
      </p>

      <StatusBadge tone="neutral">
        当前任务档案：{context.equipmentId ?? '未选择'} · 数据集设备：
        {context.datasetEquipmentId ?? '未选择'}
      </StatusBadge>

      <div className="grid grid-2" style={{ marginTop: 16 }}>
        <div className="card">
          <div className="card-title">Agent 设备档案</div>
          {loading ? (
            <div className="empty-state">
              <span className="spinner" /> 读取中…
            </div>
          ) : profiles.length === 0 ? (
            <EmptyState message="暂无设备档案（Agent 离线或未创建）。" />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>档案</th>
                  <th>状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {profiles.map((profile) => (
                  <tr key={profile.equipment_profile_id}>
                    <td>
                      <b>{profile.profile_name}</b>
                      <div className="mono muted">{profile.equipment_profile_id}</div>
                    </td>
                    <td>
                      <StatusBadge tone={profile.is_active ? 'ok' : 'neutral'}>
                        {profile.is_active ? '激活' : '未激活'}
                      </StatusBadge>
                    </td>
                    <td>
                      <button className="btn small" onClick={() => openProfile(profile.equipment_profile_id)}>
                        查看
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card">
          <div className="card-title">Topic2 实验设备</div>
          <table className="table">
            <thead>
              <tr>
                <th>设备 ID</th>
                <th>激光</th>
              </tr>
            </thead>
            <tbody>
              {topic2Equipment.map((item) => (
                <tr key={item.equipment_id}>
                  <td className="mono">{item.equipment_id}</td>
                  <td className="mono">{item.laser_id ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {selected && (
        <div className="card">
          <div className="card-title">
            档案详情：{selected.profile_name}
            <span className="id-chip muted">{selected.equipment_profile_id}</span>
            <span className="badge neutral">rev {selected.revision_id ?? '—'}</span>
          </div>
          <div className="grid grid-2">
            <div>
              <div className="card-sub">激光源</div>
              <ul className="detail-list">
                {Object.entries(selectedLaser).map(([key, value]) => (
                  <li key={key}>
                    <span className="dl-key">{equipmentParamLabel(key)}</span>
                    <span className="dl-value mono">{value === null ? '—' : String(value)}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <div className="card-sub">光学设置</div>
              <ul className="detail-list">
                {Object.entries(selectedOptical).map(([key, value]) => (
                  <li key={key}>
                    <span className="dl-key">{equipmentParamLabel(key)}</span>
                    <span className="dl-value mono">{value === null ? '—' : String(value)}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
          <div className="card-sub" style={{ marginTop: 8 }}>工艺能力</div>
          <ul className="detail-list">
            {Object.entries(selectedCapability).map(([key, value]) => (
              <li key={key}>
                <span className="dl-key">{equipmentParamLabel(key)}</span>
                <span className="dl-value mono">
                  {typeof value === 'number' ? formatNumber(value) : value === null ? '—' : String(value)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
