/** Capability section (spec §七-§九): execution graph → input resolver → derived state. */

import { useMemo } from 'react'
import type { ArtifactSnapshot } from '../../domain/artifact'
import {
  buildCapabilityView,
  type CapabilityInputRow,
} from '../../domain/capability'
import { scientificLabel, scientificTone } from '../../domain/status'
import { Card, EmptyState } from '../../components/ui/Card'
import { StatusBadge } from '../../components/ui/StatusBadge'
import { DeveloperPayload, SnapshotMeta } from '../../components/scientific/Artifact'
import { DataTable } from '../../components/ui/Tabs'
import { Link } from 'react-router-dom'

const SOURCE_LABEL: Record<CapabilityInputRow['source'], string> = {
  MEASURED: '实测',
  MACHINE_PROFILE: '设备档案',
  DERIVED: '派生',
  LITERATURE_PRIOR: '文献先验',
  CALIBRATED: '标定',
  MISSING: '缺失',
}

const SOURCE_TONE: Record<CapabilityInputRow['source'], 'ok' | 'info' | 'warn' | 'neutral'> = {
  MEASURED: 'ok',
  MACHINE_PROFILE: 'info',
  DERIVED: 'info',
  LITERATURE_PRIOR: 'warn',
  CALIBRATED: 'ok',
  MISSING: 'neutral',
}

export function CapabilitySection({
  artifact,
}: {
  artifact?: ArtifactSnapshot
}) {
  const view = useMemo(
    () => buildCapabilityView(artifact?.content as Record<string, unknown>),
    [artifact],
  )
  const equipmentNeedsAttention = view?.inputs.some(
    (input) => input.source === 'MACHINE_PROFILE' && input.status !== 'AVAILABLE',
  ) ?? false

  if (!view) {
    return (
      <div className="section">
        <h1>Capability 能力预检</h1>
        <EmptyState
          message="尚未生成 ScientificCapabilityReport"
          hint="返回总览点击「继续」，先运行 assess_capability 阶段。"
        />
      </div>
    )
  }

  return (
    <div className="section">
      <div className="section-head">
        <h1>Capability 能力预检</h1>
        <StatusBadge tone={scientificTone(view.status as never)} label={scientificLabel(view.status as never)} />
      </div>

      <Card title="后端能力状态" className="capability-graph">
        <p className="card-hint">状态、缺口与可辨识性均直接来自 ScientificCapabilityReport。</p>
        <div className="card-stat">interaction topology: {view.interactionTopology}</div>
        <div className="card-stat">supported fidelity: {view.supportedFidelity.join(', ') || '未声明'}</div>
        <DeveloperPayload payload={artifact?.content} />
        <SnapshotMeta snapshot={artifact} />
      </Card>

      <Card title="输入解析器" className="capability-resolver">
        <p className="card-hint">来源语义由后端 artifact 决定，前端不做科学判断（spec §八）。</p>
        {equipmentNeedsAttention && (
          <div className="next-actions">
            <div className="next-actions-title">设备输入缺失或未核验</div>
            <Link className="link" to="/resources/equipment">打开设备档案，补齐物理字段并生成新 revision</Link>
          </div>
        )}
        <DataTable<CapabilityInputRow>
          columns={[
            { key: 'name', label: '输入' },
            {
              key: 'value',
              label: '值',
              render: (row) =>
                row.value === null ? '—' : `${row.value} ${row.unit}`,
            },
            {
              key: 'status',
              label: '状态',
              render: (row) => (
                <StatusBadge
                  tone={row.status === 'AVAILABLE' ? 'ok' : row.status === 'UNVERIFIED' ? 'warn' : 'neutral'}
                  label={row.status === 'AVAILABLE' ? '可用' : row.status === 'UNVERIFIED' ? '待验证' : '缺失'}
                />
              ),
            },
            {
              key: 'source',
              label: '来源',
              render: (row) => (
                <StatusBadge tone={SOURCE_TONE[row.source]} label={SOURCE_LABEL[row.source]} />
              ),
            },
            {
              key: 'requiredBy',
              label: 'Required For',
              render: (row) =>
                row.requiredBy.length > 0 ? row.requiredBy.join(', ') : '—',
            },
          ]}
          rows={view.inputs}
          keyOf={(row) => row.name}
        />
      </Card>

      <Card title="Identifiability" className="capability-identifiability">
        <DataTable
          columns={[
            { key: 'parameter', label: '参数' },
            {
              key: 'status',
              label: '可辨识性',
              render: (row) => (
                <StatusBadge
                  tone={row.status === 'IDENTIFIABLE' ? 'ok' : row.status === 'WEAKLY_IDENTIFIABLE' ? 'warn' : 'neutral'}
                  label={row.status === 'IDENTIFIABLE' ? '可辨识' : row.status === 'WEAKLY_IDENTIFIABLE' ? '弱可辨识' : '不可辨识'}
                />
              ),
            },
            { key: 'reasonCodes', label: '原因', render: (row) => row.reasonCodes.join('; ') || '—' },
          ]}
          rows={view.identifiability}
          keyOf={(row) => row.parameter}
        />
      </Card>

      <Card title="Recommended Requirements" className="capability-requirements">
        <DataTable
          columns={[
            { key: 'requirementId', label: 'ID' },
            { key: 'type', label: '类型' },
            { key: 'scientificQuestion', label: '科学问题' },
            { key: 'requiredFor', label: 'Required For' },
            { key: 'priority', label: '优先级' },
          ]}
          rows={view.recommendedRequirements}
          keyOf={(row) => row.requirementId}
        />
      </Card>
    </div>
  )
}
