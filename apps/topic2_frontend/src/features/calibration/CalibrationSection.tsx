/** Calibration section (spec §十二-§十三): dynamic parameter registry + fit + identifiability. */

import { useMemo, useState } from 'react'
import type { ArtifactSnapshot } from '../../domain/artifact'
import { buildCapabilityView } from '../../domain/capability'
import {
  buildCalibrationView,
  buildParameterRegistry,
  type Identifiability,
  type RegistryRow,
} from '../../domain/calibration'
import { buildPriors } from '../../domain/knowledge'
import { parameterLabel, parameterTone } from '../../domain/status'
import { Card, EmptyState } from '../../components/ui/Card'
import { StatusBadge } from '../../components/ui/StatusBadge'
import { Tabs, DataTable } from '../../components/ui/Tabs'
import { RefList, SnapshotMeta, DeveloperPayload } from '../../components/scientific/Artifact'

const TABS = [
  { id: 'parameters', label: 'Parameters' },
  { id: 'fit', label: 'Fit' },
  { id: 'identifiability', label: 'Identifiability' },
]

interface CalibrationSectionProps {
  capability?: ArtifactSnapshot
  calibration?: ArtifactSnapshot
  identifiability?: ArtifactSnapshot
  priors?: ArtifactSnapshot
  model?: ArtifactSnapshot
  developerMode: boolean
}

export function CalibrationSection({
  capability,
  calibration,
  identifiability,
  priors,
  model,
  developerMode,
}: CalibrationSectionProps) {
  const [tab, setTab] = useState('parameters')

  const capabilityView = useMemo(
    () => buildCapabilityView(capability?.content as Record<string, unknown>),
    [capability],
  )
  const calibrationView = useMemo(
    () => buildCalibrationView(calibration?.content as Record<string, unknown>),
    [calibration],
  )
  const priorsView = useMemo(
    () => buildPriors(priors?.content as Record<string, unknown>),
    [priors],
  )

  const registry = useMemo(
    () =>
      buildParameterRegistry({
        capability: capabilityView,
        calibration: calibrationView,
        identifiabilityReport: identifiability?.content as Record<string, unknown>,
        priors: priorsView,
      }),
    [capabilityView, calibrationView, identifiability, priorsView],
  )

  const identifiabilityRows = useMemo(() => {
    const content = identifiability?.content as Record<string, unknown> | undefined
    return (content?.parameters as Array<{ parameter?: string; status?: string; reason_codes?: string[]; required_observations?: string[] }>) ?? []
  }, [identifiability])

  const hasAny = registry.length > 0 || Boolean(calibrationView)

  if (!hasAny) {
    return (
      <div className="section">
        <h1>Calibration 物理标定</h1>
        <EmptyState
          message="尚未生成标定产物"
          hint="返回总览点击「继续」，运行 calibrate_physics 后生成动态参数 Registry。"
        />
      </div>
    )
  }

  return (
    <div className="section">
      <div className="section-head">
        <h1>Calibration 物理标定</h1>
        {calibrationView && (
          <StatusBadge
            tone={calibrationView.status === 'CALIBRATED' ? 'ok' : 'neutral'}
            label={calibrationView.status === 'CALIBRATED' ? '已标定' : '未标定'}
          />
        )}
      </div>

      <Tabs tabs={TABS} active={tab} onChange={setTab} />

      {tab === 'parameters' && (
        <Card
          title={`动态参数 Registry（${registry.length}）`}
          actions={<span className="card-hint">参数集合由后端产物决定，非固定列表</span>}
          className="registry-card"
        >
          <DataTable<RegistryRow>
            columns={[
              { key: 'parameter', label: 'Parameter', width: '140px' },
              { key: 'role', label: 'Role', width: '90px' },
              {
                key: 'requiredBy',
                label: 'Required By',
                render: (row) => (row.requiredBy.length > 0 ? row.requiredBy.join(', ') : '—'),
              },
              {
                key: 'value',
                label: 'Value',
                render: (row) => (row.value === null ? '—' : `${row.value}${row.unit ? ' ' + row.unit : ''}`),
              },
              {
                key: 'range',
                label: '区间',
                render: (row) =>
                  row.lower === null || row.upper === null ? '—' : `[${row.lower}, ${row.upper}]`,
              },
              {
                key: 'source',
                label: 'Source',
                render: (row) => (
                  <StatusBadge tone={parameterTone(row.source)} label={parameterLabel(row.source)} />
                ),
              },
              {
                key: 'identifiability',
                label: 'Identifiability',
                render: (row) =>
                  row.identifiability ? (
                    <StatusBadge
                      tone={row.identifiability === 'IDENTIFIABLE' ? 'ok' : row.identifiability === 'WEAKLY_IDENTIFIABLE' ? 'warn' : 'neutral'}
                      label={row.identifiability === 'IDENTIFIABLE' ? '可辨识' : row.identifiability === 'WEAKLY_IDENTIFIABLE' ? '弱可辨识' : '不可辨识'}
                    />
                  ) : (
                    '—'
                  ),
              },
              {
                key: 'semantics',
                label: '语义',
                render: (row) =>
                  row.semantics ? (
                    <StatusBadge
                      tone={row.semantics === 'PHYSICAL' ? 'ok' : 'warn'}
                      label={row.semantics === 'PHYSICAL' ? '物理' : row.semantics === 'EFFECTIVE' ? '有效参数' : '临时推算'}
                    />
                  ) : (
                    '—'
                  ),
              },
            ]}
            rows={registry}
            keyOf={(row) => row.parameter}
          />
        </Card>
      )}

      {tab === 'fit' && (
        <FitView calibration={calibrationView} model={model} developerMode={developerMode} />
      )}

      {tab === 'identifiability' && (
        <IdentifiabilityView
          rows={identifiabilityRows}
          capabilityIdentifiability={capabilityView?.identifiability ?? []}
          calibrationParameters={calibrationView?.parameters ?? []}
        />
      )}
    </div>
  )
}

function FitView({
  calibration,
  model,
  developerMode,
}: {
  calibration: ReturnType<typeof buildCalibrationView>
  model?: ArtifactSnapshot
  developerMode: boolean
}) {
  if (!calibration) {
    return <Card title="Fit"><EmptyState message="尚无 CalibrationResult" hint="运行 calibrate_physics 后生成。" /></Card>
  }
  const fitted = calibration.parameters.filter((p) => p.estimate !== null).length
  const fixed = calibration.parameters.length - fitted
  return (
    <Card title="Fit">
      <div className="fit-stats">
        <div className="fit-stat">
          <div className="fit-stat-value">{calibration.fitMetrics.nObservations}</div>
          <div className="fit-stat-label">Observations</div>
        </div>
        <div className="fit-stat">
          <div className="fit-stat-value">{fitted}</div>
          <div className="fit-stat-label">Parameters fitted</div>
        </div>
        <div className="fit-stat">
          <div className="fit-stat-value">{fixed}</div>
          <div className="fit-stat-label">Parameters fixed / prior-only</div>
        </div>
        <div className="fit-stat">
          <div className="fit-stat-value">{calibration.parameters.filter((p) => p.priorRefs.length > 0).length}</div>
          <div className="fit-stat-label">Priors used</div>
        </div>
      </div>
      <div className="fit-metrics">
        <span>RMSE: <strong>{calibration.fitMetrics.rmse.toFixed(4)}</strong> {calibration.fitMetrics.targetUnit}</span>
        <span>MAE: <strong>{calibration.fitMetrics.mae.toFixed(4)}</strong></span>
        <span>R²: <strong>{calibration.fitMetrics.r2 === null ? '—' : calibration.fitMetrics.r2.toFixed(4)}</strong></span>
      </div>
      {calibration.assumptions.length > 0 && (
        <ul className="assumption-list">
          {calibration.assumptions.map((assumption, index) => (
            <li key={index}>{assumption}</li>
          ))}
        </ul>
      )}
      {calibration.validationDataRefs.length === 0 && (
        <div className="warning-note">validation_data_refs 为空：拟合指标为 in-sample 标定指标，不代表独立验证。</div>
      )}
      <DataTable
        columns={[
          { key: 'parameter', label: '参数' },
          {
            key: 'estimate',
            label: '估计值',
            render: (row) => (row.estimate === null ? '—' : `${row.estimate} ${row.unit}`),
          },
          {
            key: 'interval',
            label: '区间',
            render: (row) => (row.lower === null ? '—' : `[${row.lower}, ${row.upper}]`),
          },
          {
            key: 'identifiability',
            label: '可辨识性',
            render: (row) => (
              <StatusBadge
                tone={row.identifiability === 'IDENTIFIABLE' ? 'ok' : row.identifiability === 'WEAKLY_IDENTIFIABLE' ? 'warn' : 'neutral'}
                label={row.identifiability}
              />
            ),
          },
          {
            key: 'priorRefs',
            label: 'Prior',
            render: (row) => <RefList refs={row.priorRefs} />,
          },
        ]}
        rows={calibration.parameters}
        keyOf={(row) => row.parameter}
      />
      {model && (
        <Card title="LocalRemovalModel" className="model-card">
          <div className="kv-row">
            <dt>mode</dt>
            <dd>{String(model.content.mode ?? '—')}</dd>
          </div>
          <div className="kv-row">
            <dt>threshold</dt>
            <dd>{String(model.content.threshold_J_cm2 ?? '—')} J/cm²</dd>
          </div>
          <div className="kv-row">
            <dt>incubation S</dt>
            <dd>{String(model.content.incubation_S ?? '—')}</dd>
          </div>
          <div className="kv-row">
            <dt>status</dt>
            <dd>{String(model.content.status ?? '—')}</dd>
          </div>
          <SnapshotMeta snapshot={model} />
        </Card>
      )}
      {developerMode && <DeveloperPayload payload={model?.content} label="LocalRemovalModel raw" />}
    </Card>
  )
}

function IdentifiabilityView({
  rows,
  capabilityIdentifiability,
  calibrationParameters,
}: {
  rows: Array<{ parameter?: string; status?: string; reason_codes?: string[]; required_observations?: string[] }>
  capabilityIdentifiability: Array<{ parameter: string; status: string; reasonCodes: string[] }>
  calibrationParameters: Array<{ parameter: string; identifiability: Identifiability }>
}) {
  const merged = useMemo(() => {
    const map = new Map<string, { status: string; reasonCodes: string[] }>()
    for (const row of rows) {
      map.set(row.parameter ?? '', {
        status: row.status ?? 'NOT_IDENTIFIABLE',
        reasonCodes: row.reason_codes ?? [],
      })
    }
    for (const row of capabilityIdentifiability) {
      const existing = map.get(row.parameter)
      if (!existing) map.set(row.parameter, { status: row.status, reasonCodes: row.reasonCodes })
    }
    for (const estimate of calibrationParameters) {
      const existing = map.get(estimate.parameter)
      if (!existing) map.set(estimate.parameter, { status: estimate.identifiability, reasonCodes: [] })
    }
    return [...map.entries()].map(([parameter, value]) => ({ parameter, ...value }))
  }, [rows, capabilityIdentifiability, calibrationParameters])

  if (merged.length === 0) {
    return <Card title="Identifiability"><EmptyState message="尚无 IdentifiabilityReport" /></Card>
  }
  return (
    <Card title="Identifiability">
      <DataTable
        columns={[
          { key: 'parameter', label: '参数' },
          {
            key: 'status',
            label: '可辨识性',
            render: (row) => (
              <StatusBadge
                tone={row.status === 'IDENTIFIABLE' ? 'ok' : row.status === 'WEAKLY_IDENTIFIABLE' ? 'warn' : 'neutral'}
                label={row.status === 'IDENTIFIABLE' ? '可辨识' : row.status === 'WEAKLY_IDENTIFIABLE' ? '弱可辨识' : '当前数据不可辨识'}
              />
            ),
          },
          {
            key: 'reasonCodes',
            label: '原因',
            render: (row) => row.reasonCodes.join('; ') || '—',
          },
        ]}
        rows={merged}
        keyOf={(row) => row.parameter}
      />
    </Card>
  )
}
