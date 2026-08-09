import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { NavLink, useSearchParams } from 'react-router-dom'
import { datasetsApi, type EquipmentProfileEntry } from '../api/datasets'
import { Card, EmptyState, ErrorBanner, Spinner } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { EquipmentProfileForm } from '../features/equipment/EquipmentProfileForm'

export function ResourcesPage({ kind }: { kind: 'materials' | 'machines' | 'literature' }) {
  return (
    <>
      <nav className="resource-tabs" aria-label="资源分类">
        <NavLink to="/resources/materials">材料</NavLink>
        <NavLink to="/resources/equipment">设备</NavLink>
        <NavLink to="/resources/literature">文献</NavLink>
      </nav>
      {kind === 'materials'
        ? <MaterialResources />
        : kind === 'machines'
          ? <MachineResources />
          : <LiteratureResources />}
    </>
  )
}

function MaterialResources() {
  const materials = useQuery({ queryKey: ['materials'], queryFn: () => datasetsApi.materials() })
  return (
    <div className="section">
      <h1>材料档案</h1>
      <Card>
        {materials.isLoading && <Spinner />}
        {materials.isError && <ErrorBanner message={(materials.error as Error).message} />}
        {materials.data?.length === 0 && <EmptyState message="暂无材料档案" />}
        {materials.data && (
          <ul className="plain-list">
            {materials.data.map((entry) => (
              <li key={entry.material}>
                <strong>{entry.material}</strong>
                {entry.data_origin ? ` · ${entry.data_origin}` : ''}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}

function MachineResources() {
  const researchProfiles = useQuery({
    queryKey: ['equipment-profiles', 'RESEARCH'],
    queryFn: () => datasetsApi.equipmentProfiles(),
  })
  const [showCreate, setShowCreate] = useState(false)
  const [editing, setEditing] = useState<EquipmentProfileEntry | null>(null)

  return (
    <div className="section">
      <h1>设备档案</h1>
      <p className="section-sub">
        这里只管理实际执行设备。历史实验的设备来源由后端从真实数据记录自动解析，不作为用户输入展示。
      </p>
      <div className="cards-grid">
        <Card
          title="执行设备（可创建、版本化）"
          className="equipment-management-card"
          actions={(
            <Button
              variant="ghost"
              onClick={() => {
                setEditing(null)
                setShowCreate((value) => !value)
              }}
            >
              {showCreate && !editing ? '收起创建表单' : '新建设备档案'}
            </Button>
          )}
        >
          <p className="card-hint">
            研究任务只接受这里保存的设备 revision。设备 ID 和 revision 均由后台生成，用户不应手填。
          </p>
          {researchProfiles.isLoading && <Spinner />}
          {researchProfiles.isError && (
            <ErrorBanner message={`研究设备档案服务不可用：${(researchProfiles.error as Error).message}`} />
          )}
          {researchProfiles.data?.length === 0 && <EmptyState message="暂无研究执行设备档案" />}
          {researchProfiles.data && researchProfiles.data.length > 0 && (
            <EquipmentProfileList
              profiles={researchProfiles.data}
              editable
              onEdit={(profile) => {
                setEditing(profile)
                setShowCreate(true)
              }}
            />
          )}
          {showCreate && (
            <div className="equipment-editor">
              <h4>{editing ? `编辑 ${editing.profile_name}` : '新建设备档案'}</h4>
              <EquipmentProfileForm
                key={editing ? `${editing.equipment_profile_id}:${editing.revision_id}` : 'new-equipment'}
                profile={editing ?? undefined}
              />
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}

const PROFILE_FIELD_LABELS: Array<{
  section: 'laser_source' | 'optical_setup' | 'motion_system'
  key: string
  label: string
  unit: string
}> = [
  { section: 'laser_source', key: 'wavelength_nm', label: '波长', unit: 'nm' },
  { section: 'laser_source', key: 'pulse_width_min_fs', label: '可调脉宽下限', unit: 'fs' },
  { section: 'laser_source', key: 'pulse_width_max_fs', label: '可调脉宽上限', unit: 'fs' },
  { section: 'laser_source', key: 'workpiece_incident_power_min_W', label: '材料表面入射平均功率下限', unit: 'W' },
  { section: 'laser_source', key: 'workpiece_incident_power_max_W', label: '材料表面入射平均功率上限', unit: 'W' },
  { section: 'laser_source', key: 'rated_max_power_W', label: '激光器额定最大平均功率', unit: 'W' },
  { section: 'laser_source', key: 'frequency_min_kHz', label: '频率下限', unit: 'kHz' },
  { section: 'laser_source', key: 'frequency_max_kHz', label: '频率上限', unit: 'kHz' },
  { section: 'optical_setup', key: 'spot_diameter_um', label: '光斑直径', unit: 'μm' },
  { section: 'motion_system', key: 'scan_speed_min_mm_s', label: '速度下限', unit: 'mm/s' },
  { section: 'motion_system', key: 'scan_speed_max_mm_s', label: '速度上限', unit: 'mm/s' },
]

function EquipmentProfileList({
  profiles,
  editable = false,
  onEdit,
}: {
  profiles: EquipmentProfileEntry[]
  editable?: boolean
  onEdit?: (profile: EquipmentProfileEntry) => void
}) {
  return (
    <div className="equipment-profile-list">
      {profiles.map((profile) => (
        <details key={profile.equipment_profile_id} className="equipment-profile-detail">
          <summary>
            <strong>{profile.profile_name || profile.equipment_profile_id}</strong>
            <span>
              {profile.model ? ` · ${profile.model}` : ''}
              {' · '}revision {profile.revision_id ?? '缺失'}
            </span>
          </summary>
          <div className="equipment-profile-meta">
            <div>后台 ID：<span className="mono">{profile.equipment_profile_id}</span></div>
            <div>来源：研究设备档案库</div>
            <div>机器编号：{profile.machine_id || '未填写'}</div>
          </div>
          <table className="data-table equipment-profile-table">
            <thead>
              <tr><th>物理字段</th><th>值</th><th>核验状态</th></tr>
            </thead>
            <tbody>
              {PROFILE_FIELD_LABELS.map((field) => {
                const section = profile[field.section] as Record<string, unknown> | undefined
                const value = section?.[field.key]
                return (
                  <tr key={`${profile.equipment_profile_id}:${field.key}`}>
                    <td>{field.label}</td>
                    <td>{value === null || value === undefined ? '缺失' : `${String(value)} ${field.unit}`}</td>
                    <td>{profile.field_verification?.[field.key] ?? '未声明'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <div className="equipment-revisions">
            <strong>可绑定 revisions：</strong>{' '}
            {(profile.revisions ?? []).map((revision) => revision.revision_id).join(' · ') || profile.revision_id || '无'}
          </div>
          {editable && onEdit && (
            <div className="form-actions">
              <Button variant="ghost" onClick={() => onEdit(profile)}>编辑并生成新 revision</Button>
            </div>
          )}
        </details>
      ))}
    </div>
  )
}

function LiteratureResources() {
  const [searchParams] = useSearchParams()
  const selectedPaper = searchParams.get('paper')
  const literature = useQuery({ queryKey: ['literature'], queryFn: () => datasetsApi.literature() })
  return (
    <div className="section">
      <h1>文献库</h1>
      <p className="section-sub">仅展示具有原始 PDF 来源的真实文献及其 ScientificDocument 解析记录。</p>
      <Card title={`文献（${literature.data?.length ?? 0}）`}>
        {literature.isLoading && <Spinner />}
        {literature.isError && <ErrorBanner message={(literature.error as Error).message} />}
        {literature.data?.length === 0 && <EmptyState message="暂无已解析文献" />}
        {literature.data && literature.data.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th>paper_id</th>
                <th>题名</th>
                <th>材料</th>
                <th>年份</th>
                <th>来源与标识</th>
              </tr>
            </thead>
            <tbody>
              {literature.data.map((entry) => (
                <tr
                  id={`paper-${entry.paper_id}`}
                  key={entry.paper_id}
                  className={selectedPaper === entry.paper_id ? 'candidate-row-selected' : ''}
                >
                  <td className="mono">{entry.paper_id}</td>
                  <td>{entry.canonical_title}</td>
                  <td>{entry.material ?? '—'}</td>
                  <td>{entry.year ?? '—'}</td>
                  <td>
                    <div>{entry.source ?? '未标注'}</div>
                    {entry.pdf_ref && <div className="mono small">PDF: {entry.pdf_ref}</div>}
                    {entry.scientific_document_ref && (
                      <div className="mono small">Document: {entry.scientific_document_ref}</div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  )
}

export function SettingsPage() {
  return (
    <div className="section">
      <h1>系统</h1>
      <div className="cards-grid">
        <Card title="运行环境">
          <ul className="plain-list">
            <li>Frontend: Physics-to-Planning V3 workbench</li>
            <li>API: /api/v1（ApplicationRun gateway）</li>
            <li>Developer Mode 开关位于顶部 Global Context Bar</li>
          </ul>
        </Card>
        <Card title="关于">
          <EmptyState message="科学逻辑全部由后端执行" hint="前端只展示 artifact、触发操作、收集用户输入。" />
        </Card>
      </div>
    </div>
  )
}
