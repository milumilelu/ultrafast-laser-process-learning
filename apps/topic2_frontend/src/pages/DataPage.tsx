import { useQuery } from '@tanstack/react-query'
import { datasetsApi } from '../api/datasets'
import { Card, EmptyState, Spinner } from '../components/ui/Card'

const COLUMNS = [
  'experiment_id',
  'material',
  'laser_type',
  'pulse_width_ps',
  'frequency_kHz',
  'hatch_spacing_um',
  'passes',
  'scan_speed_mm_s',
  'depth_um',
  'roughness_um',
  'roughness_type',
  'source_file',
  'data_origin',
]

/** Experimental data browse (spec §三-3). Read-only; science stays on the backend. */
export function DataPage() {
  const rows = useQuery({
    queryKey: ['experiments', {}],
    queryFn: () => datasetsApi.experiments({ limit: 100 }),
  })
  const datasets = useQuery({ queryKey: ['datasets'], queryFn: () => datasetsApi.datasets() })
  return (
    <div className="section">
      <h1>实验数据</h1>
      <p className="section-sub">数据集 / Observation / 形貌文件。此处只浏览，不参与科学计算。</p>
      <div className="cards-grid">
        <Card title="版本化数据集">
          {datasets.isLoading && <Spinner />}
          {datasets.data?.length === 0 && <EmptyState message="暂无数据集版本" />}
          {datasets.data && (
            <ul className="plain-list">
              {datasets.data.map((dataset) => (
                <li key={dataset.dataset_version}>
                  <strong>{dataset.dataset_version}</strong> · {dataset.n_samples} samples · hash{' '}
                  <span className="mono">{dataset.dataset_hash.slice(0, 12)}…</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="实验记录（只读）">
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
        <Card title="形貌文件">
          <EmptyState message="单脉冲坑 / 形貌文件管理在下一迭代接入" />
        </Card>
      </div>
    </div>
  )
}
