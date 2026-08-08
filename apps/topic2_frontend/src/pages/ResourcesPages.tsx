import { useQuery } from '@tanstack/react-query'
import { datasetsApi } from '../api/datasets'
import { Card, EmptyState, Spinner } from '../components/ui/Card'
import { PlaceholderPage } from '../components/ui/Placeholder'

export function ResourcesPage({ kind }: { kind: 'materials' | 'machines' | 'literature' }) {
  if (kind === 'materials') {
    const materials = useQuery({ queryKey: ['materials'], queryFn: () => datasetsApi.materials() })
    return (
      <div className="section">
        <h1>材料档案</h1>
        <Card>
          {materials.isLoading && <Spinner />}
          {materials.data && materials.data.length === 0 && <EmptyState message="暂无材料档案" />}
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
  if (kind === 'machines') {
    const equipment = useQuery({ queryKey: ['equipment'], queryFn: () => datasetsApi.equipment() })
    return (
      <div className="section">
        <h1>设备档案</h1>
        <Card>
          {equipment.isLoading && <Spinner />}
          {equipment.data && equipment.data.length === 0 && <EmptyState message="暂无设备档案" />}
          {equipment.data && (
            <ul className="plain-list">
              {equipment.data.map((entry) => (
                <li key={entry.equipment_id}>
                  <strong>{entry.equipment_id}</strong> · {entry.samples} samples
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    )
  }
  return <PlaceholderPage title="文献库" message="文献库管理在下一迭代接入" hint="将展示 ScientificDocument 与检索资产。" />
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
