/** 设备管理：数据集设备（Topic2 实验设备，决定科学查询数据）与
 *  设备档案（Agent 设备，提供机器边界/上下文）分开选择，杜绝混用。 */

import { useCallback, useEffect, useState } from 'react'

import { agentApi } from '../api/agent'
import type { EquipmentProfileBase } from '../api/types'
import { topic2Api } from '../api/topic2'
import { StatusBadge } from './StatusBadge'
import { NewEquipmentModal } from './NewEquipmentModal'

export interface ScopeCapability {
  n_samples: number
  n_unique_designs: number
  targets: {
    depth_um: { n_samples: number; n_unique_designs: number }
    roughness_um: { n_samples: number; n_unique_designs: number }
  }
  available_equipment: string[]
  equipment_samples: Record<string, number>
  available_geometries: string[]
  meets_identification: boolean
  meets_modeling: boolean
}

export function EquipmentManager({
  datasetEquipmentId,
  equipmentProfileId,
  onDatasetEquipmentChange,
  onEquipmentProfileChange,
  capability,
  capabilityLoading,
  onRefreshCapability,
}: {
  datasetEquipmentId: string | null
  equipmentProfileId: string | null
  onDatasetEquipmentChange: (id: string | null) => void
  onEquipmentProfileChange: (id: string | null) => void
  capability: ScopeCapability | null
  capabilityLoading: boolean
  onRefreshCapability: () => void
}) {
  const degraded = false
  const [agentProfiles, setAgentProfiles] = useState<EquipmentProfileBase[]>([])
  const [topic2Equipment, setTopic2Equipment] = useState<{ equipment_id: string; laser_id: string | null; machine_id: string | null }[]>([])
  const [error, setError] = useState<string | null>(null)
  const [showNew, setShowNew] = useState(false)

  const refresh = useCallback(async () => {
    setError(null)
    try {
      const profiles = await agentApi.listEquipmentProfiles()
      setAgentProfiles(profiles)
    } catch (err) {
      setError(err instanceof Error ? `设备档案读取失败：${err.message}` : '设备档案读取失败')
    }
    try {
      const result = await topic2Api.equipment()
      setTopic2Equipment(result.items)
    } catch (err) {
      setError(err instanceof Error ? `Topic2 设备读取失败：${err.message}` : 'Topic2 设备读取失败')
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const datasetOptions =
    capability && capability.available_equipment.length > 0
      ? topic2Equipment.filter((item) => capability.available_equipment.includes(item.equipment_id))
      : topic2Equipment

  return (
    <div>
      <div className="row" style={{ marginBottom: 12 }}>
        <div className="field" style={{ flex: 1, marginBottom: 0 }}>
          <label>数据集设备（Topic2 实验数据，用于科学计算 scope）</label>
          <select
            value={datasetEquipmentId ?? ''}
            onChange={(event) => onDatasetEquipmentChange(event.target.value || null)}
          >
            <option value="">— 选择数据集设备 —</option>
            {datasetOptions.map((item) => (
              <option key={item.equipment_id} value={item.equipment_id}>
                {item.equipment_id}（{item.laser_id ?? '—'}）
                {capability && capability.available_equipment.includes(item.equipment_id)
                  ? ` · ${capability.equipment_samples[item.equipment_id] ?? 0} 样本`
                  : ' · 当前组合无数据'}
              </option>
            ))}
          </select>
        </div>
        <div className="field" style={{ flex: 1, marginBottom: 0 }}>
          <label>设备档案（Agent 设备，提供机器边界 / 上下文）</label>
          <select
            value={equipmentProfileId ?? ''}
            onChange={(event) => onEquipmentProfileChange(event.target.value || null)}
          >
            <option value="">— 选择设备档案 —</option>
            {agentProfiles.map((profile) => (
              <option key={profile.equipment_profile_id} value={profile.equipment_profile_id}>
                {profile.profile_name ?? profile.equipment_profile_id}
                {profile.is_active ? '（当前激活）' : ''}
              </option>
            ))}
          </select>
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8 }}>
          <button className="btn" onClick={() => { void refresh(); onRefreshCapability() }} disabled={capabilityLoading}>
            刷新
          </button>
          {!degraded && (
            <button className="btn primary" onClick={() => setShowNew(true)}>
              + 新建设备档案
            </button>
          )}
        </div>
      </div>

      {capability && (
        <div className="row" style={{ marginBottom: 12 }}>
          <StatusBadge tone={capability.n_samples > 0 ? 'ok' : 'err'}>
            当前组合数据：{capability.n_samples} 样本 / {capability.n_unique_designs} 独立设计
          </StatusBadge>
          <StatusBadge tone={capability.meets_identification ? 'ok' : 'warn'}>
            参数辨识：{capability.meets_identification ? '可执行' : '数据不足（≥4 样本 / ≥2 设计）'}
          </StatusBadge>
          <StatusBadge tone={capability.meets_modeling ? 'ok' : 'warn'}>
            建模：{capability.meets_modeling ? '可执行' : '数据不足（≥2 独立设计）'}
          </StatusBadge>
        </div>
      )}

      {error && (
        <div className="error-banner" style={{ margin: 0, marginBottom: 12 }}>
          {error}
        </div>
      )}

      <div className="card-sub" style={{ marginBottom: 0 }}>
        两个"设备"概念不同：<b>数据集设备</b>是工艺数据库（Topic2）中实验记录的来源
        标识（如 EQ-REAL，120 条真实实验），决定参数辨识/建模/优化使用哪些观测数据；
        <b>设备档案</b>是 Agent 侧物理设备描述（激光/光学/运动参数，含光斑等物理特征
        输入），决定机器边界与工艺上下文。两者可不同：档案提供约束，数据集提供观测。
        热扩散系数 / 烧蚀阈值是<b>材料参数</b>，在任务定义的材料中设置（可选）。
      </div>

      {showNew && (
        <NewEquipmentModal
          onClose={() => setShowNew(false)}
          onCreated={async (id) => {
            setShowNew(false)
            await refresh()
            onEquipmentProfileChange(id)
          }}
        />
      )}
    </div>
  )
}
