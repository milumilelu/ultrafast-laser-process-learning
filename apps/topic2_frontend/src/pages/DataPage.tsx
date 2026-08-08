import { useQuery } from '@tanstack/react-query'
import { datasetsApi } from '../api/datasets'
import { Card, EmptyState, Spinner } from '../components/ui/Card'

const COLUMNS = ['material', 'laser_type', 'pulse_width_ps', 'frequency_kHz', 'hatch_um', 'passes', 'scan_speed_mm_s', 'mean_depth_um', 'min_depth_um', 'max_depth_um', 'sa_um', 'sq_um', 'sz_um']

/** Experimental data browse (spec §三-3). Read-only; science stays on the backend. */
export function DataPage() {
  const rows = useQuery({
    queryKey: ['experiments', {}],
    queryFn: () => datasetsApi.experiments({ limit: 100 }),
  })

  return (
    <div className="section">
      <h1>实验数据</h1>
      <p className="section-sub">数据集 / Observation / 形貌文件。此处只浏览，不参与科学计算。</p>
      <div className="cards-grid">
        <Card title="数据集">
          {rows.isLoading && <Spinner />}
          {rows.data && rows.data.length === 0 && <EmptyState message="暂无实验数据" />}
          {rows.data && rows.data.length > 0 && (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    {COLUMNS.map((col) => (
                      <th key={col}>{col}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.data.slice(0, 50).map((row, index) => (
                    <tr key={index}>
                      {COLUMNS.map((col) => (
                        <td key={col}>{String(row[col] ?? '—')}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        <Card title="Observation">
          <EmptyState
            message="Observation 闭环在下一迭代接入"
            hint="将展示 ObservationResult 与 Data / Calibration / Process Model / E2P Trust 更新触发。"
          />
        </Card>
        <Card title="形貌文件">
          <EmptyState message="单脉冲坑 / 形貌文件管理在下一迭代接入" />
        </Card>
      </div>
    </div>
  )
}
