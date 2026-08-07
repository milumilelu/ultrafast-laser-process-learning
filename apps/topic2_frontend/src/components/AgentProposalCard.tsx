/** Level-2 "Propose" cards: the Agent proposes, the Human confirms or rejects.
 *  Only confirmation mutates the TaskContext (with a version bump). */

import { formatTargetGoal, targetLabel } from '../lib/canonical'
import type { AgentProposal } from '../stores/agent'

export const PROPOSAL_TYPE_LABELS: Record<AgentProposal['type'], string> = {
  update_task: '修改任务上下文',
  select_model: '选择模型',
  run_modeling: '启动建模',
  run_optimization: '启动优化',
  use_evidence: '使用证据',
}

function describeChanges(changes: Record<string, unknown>): string {
  const entries = Object.entries(changes)
  if (entries.length === 0) return '无内容变更'
  return entries
    .map(([key, value]) => {
      if (key === 'targetMetrics' && Array.isArray(value)) {
        return value
          .map(
            (item: { target: 'depth_um' | 'roughness_um' }) =>
              `${targetLabel(item.target)}（${formatTargetGoal(item.target)}）`,
          )
          .join(' + ')
      }
      return `${key} = ${JSON.stringify(value)}`
    })
    .join('；')
}

export function AgentProposalCard({
  proposal,
  onApply,
}: {
  proposal: AgentProposal
  onApply: (proposal: AgentProposal, accepted?: boolean) => void
}) {
  if (proposal.status !== 'pending') {
    return (
      <div className="proposal-card" data-testid="proposal-card">
        <div className="proposal-title">
          {PROPOSAL_TYPE_LABELS[proposal.type]} · {proposal.proposalId}
        </div>
        <div>
          状态：
          {proposal.status === 'accepted' ? '已采纳（Task Context 已升级）' : '已取消'}
        </div>
      </div>
    )
  }

  return (
    <div className="proposal-card" data-testid="proposal-card">
      <div className="proposal-title">
        Agent 建议 · {PROPOSAL_TYPE_LABELS[proposal.type]} · {proposal.proposalId}
      </div>
      <div>
        建议：{describeChanges(proposal.changes)}
      </div>
      {proposal.reasons.map((reason, index) => (
        <div className="reason" key={index}>
          原因：{reason}
        </div>
      ))}
      <div className="mono" style={{ color: 'var(--text-muted)', marginTop: 4 }}>
        绑定 Task Context v{proposal.taskContextVersion}
      </div>
      <div className="proposal-actions">
        <button className="btn primary small" onClick={() => onApply(proposal)}>
          应用修改
        </button>
        <button className="btn small" onClick={() => onApply(proposal, false)}>
          取消
        </button>
      </div>
    </div>
  )
}
