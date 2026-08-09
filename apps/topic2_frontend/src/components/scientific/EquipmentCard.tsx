/** Equipment snapshot card (M6): canonical equipment resource identity. */

import { useMemo } from 'react'
import type { ArtifactSnapshot } from '../../domain/artifact'
import {
  buildEquipmentView,
  EQUIPMENT_FIELD_LABEL,
  SOURCE_QUALITY_LABEL,
} from '../../domain/equipment'
import { Card, EmptyState } from '../ui/Card'
import { StatusBadge } from '../ui/StatusBadge'

export function EquipmentCard({ artifact }: { artifact?: ArtifactSnapshot }) {
  const view = useMemo(
    () => buildEquipmentView(artifact?.content as Record<string, unknown>),
    [artifact],
  )
  if (!artifact) return null

  return (
    <Card
      title={`Equipment ${view.equipmentProfileId}`}
      actions={
        <StatusBadge
          tone={
            view.resourceStatus === 'READY'
              ? 'ok'
              : view.resourceStatus === 'PARTIAL'
                ? 'warn'
                : 'err'
          }
          label={
            view.resourceStatus === 'READY'
              ? '资源就绪'
              : view.resourceStatus === 'PARTIAL'
                ? '部分就绪'
                : '资源受阻'
          }
        />
      }
    >
      <div className="equipment-card">
        <div className="control-meta">
          <span className="control-chip">{SOURCE_QUALITY_LABEL[view.sourceQuality]}</span>
          {view.revisionId && <span className="control-chip">rev {view.revisionId}</span>}
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>字段</th>
              <th>值</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {view.fields.map((field) => (
              <tr key={field.parameter}>
                <td>{EQUIPMENT_FIELD_LABEL[field.parameter] ?? field.parameter}</td>
                <td>
                  {field.value !== null ? `${field.value} ${field.unit ?? ''}`.trim() : '—'}
                </td>
                <td>
                  <StatusBadge
                    tone={field.status === 'VERIFIED' ? 'ok' : field.status === 'DERIVED' ? 'info' : 'neutral'}
                    label={field.status === 'VERIFIED' ? '已验证' : field.status === 'DERIVED' ? '派生' : '缺失'}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {view.machineBounds.length > 0 && (
          <div className="card-hint" style={{ marginTop: 8 }}>
            机器边界: {view.machineBounds.map((bound) => `${bound.name} ${bound.lower ?? '?'}–${bound.upper ?? '?'}`).join(' · ')}
          </div>
        )}
        {view.warnings.length > 0 && (
          <ul className="gate-reasons">
            {view.warnings.map((warning, index) => (
              <li key={index}>{warning}</li>
            ))}
          </ul>
        )}
        {view.fields.length === 0 && <EmptyState message="尚无设备快照" />}
      </div>
    </Card>
  )
}
