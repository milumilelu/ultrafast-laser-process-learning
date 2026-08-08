import type { ChainNodeView } from '../../domain/capability'
import { StatusBadge } from '../ui/StatusBadge'

const NODE_TONE: Record<ChainNodeView['status'], 'ok' | 'warn' | 'neutral' | 'err'> = {
  READY: 'ok',
  UNVERIFIED: 'warn',
  BLOCKED: 'err',
  NOT_RUN: 'neutral',
}

const NODE_LABEL: Record<ChainNodeView['status'], string> = {
  READY: '就绪',
  UNVERIFIED: '待验证',
  BLOCKED: '受阻',
  NOT_RUN: '未运行',
}

/** Execution capability graph (spec §七): why the pipeline cannot run yet. */
export function DependencyChain({ nodes }: { nodes: ChainNodeView[] }) {
  if (nodes.length === 0) return null
  return (
    <ol className="chain">
      {nodes.map((item, index) => (
        <li key={item.node.id} className="chain-node">
          <div className="chain-row">
            <span className="chain-index">{index + 1}</span>
            <span className="chain-label">{item.node.label}</span>
            <StatusBadge tone={NODE_TONE[item.status]} label={NODE_LABEL[item.status]} />
          </div>
          {item.blockingInputs.length > 0 && (
            <div className="chain-blockers">
              缺少: {item.blockingInputs.join(', ')}
            </div>
          )}
          {item.node.downstream.length > 0 && <div className="chain-arrow" aria-hidden="true" />}
        </li>
      ))}
    </ol>
  )
}
