/** Capability section (spec §七-§九): execution graph → input resolver → derived state. */

import { useMemo } from 'react'
import type { ArtifactSnapshot } from '../../domain/artifact'
import {
  buildCapabilityView,
  buildChainStatus,
  type CapabilityInputRow,
} from '../../domain/capability'
import { scientificLabel, scientificTone } from '../../domain/status'
import { Card, EmptyState } from '../../components/ui/Card'
import { StatusBadge } from '../../components/ui/StatusBadge'
import { DependencyChain } from '../../components/scientific/DependencyChain'
import { DeveloperPayload, SnapshotMeta } from '../../components/scientific/Artifact'
import { DataTable } from '../../components/ui/Tabs'

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
  const chain = useMemo(() => buildChainStatus(view), [view])

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

      <Card title="执行能力依赖图" className="capability-graph">
        <p className="card-hint">
          每个节点由后端可解析的物理输入决定；红色为阻塞链（spec §七）。
        </p>
        <DependencyChain nodes={chain.nodes} />
        <DeveloperPayload payload={artifact?.content} />
        <SnapshotMeta snapshot={artifact} />
      </Card>

      <Card title="输入解析器" className="capability-resolver">
        <p className="card-hint">来源语义由后端 artifact 决定，前端不做科学判断（spec §八）。</p>
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
