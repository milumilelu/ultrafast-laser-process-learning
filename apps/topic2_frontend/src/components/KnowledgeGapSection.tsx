/** KnowledgeGapSection：展示 ApplicationRun 主链输出的知识需求与满足评估
 *  （analyze_knowledge_gaps / satisfy_requirements）。数据只读自应用运行结果，
 *  不单独启动任何科学分析任务。 */

import { useEffect, useState } from 'react'

import { applicationApi } from '../api/application'
import type { Topic2ApplicationResult } from '../api/types'
import { StatusBadge } from './StatusBadge'
import { useApplicationStore } from '../stores/application'

const REQUIREMENT_TYPE_LABELS: Record<string, string> = {
  experimental_condition: '实验条件',
  formula: '公式',
  material_property: '材料属性',
  threshold: '阈值',
  parameter_effect: '参数影响',
  parameter_range: '参数范围',
  reported_optimum: '报道最优',
  physics_dependency: '物理依赖',
  process_mechanism: '加工机理',
  data_quality: '数据质量',
}

const SATISFACTION_LABELS: Record<string, { label: string; tone: 'ok' | 'warn' | 'err' | 'neutral' }> = {
  SATISFIED: { label: '已满足', tone: 'ok' },
  PARTIALLY_SATISFIED: { label: '部分满足', tone: 'warn' },
  SATISFIED_WITH_CONFLICT: { label: '满足但有冲突', tone: 'warn' },
  UNSATISFIED: { label: '未满足', tone: 'err' },
}

interface KnowledgeStateShape {
  requirements?: {
    requirement_id: string
    type: string
    question: string
    required_for?: string
    priority?: string
    trigger_reasons?: string[]
  }[]
  satisfactions?: {
    requirement_id: string
    status: string
    assessment_method?: string
    unresolved_reasons?: string[]
  }[]
  missing_topics?: string[]
}

export function KnowledgeGapSection() {
  const activeApplicationRunId = useApplicationStore((state) => state.activeApplicationRunId)
  const [knowledgeState, setKnowledgeState] = useState<KnowledgeStateShape | null>(null)

  useEffect(() => {
    if (!activeApplicationRunId) {
      setKnowledgeState(null)
      return
    }
    let cancelled = false
    applicationApi
      .getResult(activeApplicationRunId)
      .then((result: Topic2ApplicationResult) => {
        if (cancelled) return
        setKnowledgeState((result as unknown as { knowledgeState?: KnowledgeStateShape }).knowledgeState ?? null)
      })
      .catch(() => {
        if (!cancelled) setKnowledgeState(null)
      })
    return () => {
      cancelled = true
    }
  }, [activeApplicationRunId])

  if (!knowledgeState) {
    return <div className="empty-state">尚未运行完整分析。知识需求将在应用运行后自动生成。</div>
  }

  const requirements = knowledgeState.requirements ?? []
  const satisfactions = knowledgeState.satisfactions ?? []
  const byRequirement = new Map(satisfactions.map((item) => [item.requirement_id, item]))

  if (requirements.length === 0) {
    return <div className="empty-state">知识需求清单为空。</div>
  }

  return (
    <div data-testid="knowledge-gap-section">
      <div className="row" style={{ marginBottom: 8 }}>
        <StatusBadge tone="neutral">需求 {requirements.length} 条</StatusBadge>
        <StatusBadge tone={knowledgeState.missing_topics?.length ? 'warn' : 'ok'}>
          未满足 {knowledgeState.missing_topics?.length ?? 0} 条
        </StatusBadge>
      </div>
      <table className="table">
        <thead>
          <tr>
            <th>需求</th>
            <th>类型</th>
            <th>问题</th>
            <th>触发依据</th>
            <th>满足状态</th>
          </tr>
        </thead>
        <tbody>
          {requirements.map((requirement) => {
            const satisfaction = byRequirement.get(requirement.requirement_id)
            const label = SATISFACTION_LABELS[satisfaction?.status ?? 'UNSATISFIED']
            return (
              <tr key={requirement.requirement_id}>
                <td className="mono">{requirement.requirement_id}</td>
                <td>{REQUIREMENT_TYPE_LABELS[requirement.type] ?? requirement.type}</td>
                <td>{requirement.question}</td>
                <td className="muted">
                  {(requirement.trigger_reasons ?? []).join('；') || '—'}
                </td>
                <td>
                  <StatusBadge tone={label.tone}>{label.label}</StatusBadge>
                  {(satisfaction?.unresolved_reasons ?? []).length > 0 && (
                    <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
                      {(satisfaction?.unresolved_reasons ?? []).join('；')}
                    </div>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
