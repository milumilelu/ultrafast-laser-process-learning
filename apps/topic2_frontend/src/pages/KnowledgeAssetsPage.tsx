import { useQuery } from '@tanstack/react-query'
import { datasetsApi } from '../api/datasets'
import { Card, EmptyState, Spinner } from '../components/ui/Card'

/** Global knowledge assets (spec §三-2): ScientificDocument / EvidenceIR / Prior. */
export function KnowledgeAssetsPage() {
  const materials = useQuery({ queryKey: ['materials'], queryFn: () => datasetsApi.materials() })

  return (
    <div className="section">
      <h1>科学知识</h1>
      <p className="section-sub">全局科学知识资产管理；任务级知识在「工作台 → Knowledge」查看。</p>
      <div className="cards-grid">
        <Card title="文献 / Evidence">
          <EmptyState
            message="全局文献知识库在下一迭代接入"
            hint="将展示 ScientificDocument / EvidenceIR / SourceCondition / Applicability 资产。"
          />
        </Card>
        <Card title="Prior 资产">
          <EmptyState
            message="Prior 由 ApplicationRun 生成并沉淀"
            hint="将展示 ParameterPrior / MechanismModelPrior / PlanningPreferencePrior 全局清单。"
          />
        </Card>
        <Card title="数据资产">
          {materials.isLoading && <Spinner />}
          {materials.data && (
            <ul className="plain-list">
              {materials.data.map((entry) => (
                <li key={entry.material}>
                  {entry.material}
                  {entry.data_origin ? ` · ${entry.data_origin}` : ''}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  )
}
