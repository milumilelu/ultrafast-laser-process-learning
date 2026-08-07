/** Number / status formatters. */

export function formatNumber(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  if (!Number.isFinite(value)) return '—'
  return value.toLocaleString('en-US', {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  })
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${(value * 100).toFixed(digits)}%`
}

export const RUN_TYPE_LABELS: Record<string, string> = {
  parameter_identification: '参数辨识',
  model_policy: '模型策略',
  model_training: '模型训练',
  optimization: '工艺优化',
  e2p: 'E2P',
}

export function runTypeLabel(runType: string): string {
  return RUN_TYPE_LABELS[runType] ?? runType
}

export const TRANSFER_LABELS: Record<string, { label: string; cls: string }> = {
  strong: { label: '强适用', cls: 'transfer-strong' },
  medium: { label: '中适用', cls: 'transfer-medium' },
  weak: { label: '弱适用', cls: 'transfer-weak' },
  none: { label: '不适用', cls: 'transfer-none' },
}

export function transferLabel(level: string): string {
  return TRANSFER_LABELS[level]?.label ?? level
}

export function transferClass(level: string): string {
  return TRANSFER_LABELS[level]?.cls ?? ''
}

export const EFFECT_LABELS: Record<string, { label: string; cls: string }> = {
  positive: { label: '正向', cls: 'effect-positive' },
  negative: { label: '负向', cls: 'effect-negative' },
  undetermined: { label: '未确定', cls: 'effect-neutral' },
}

export function effectLabel(direction: string): string {
  return EFFECT_LABELS[direction]?.label ?? direction
}

export function effectClass(direction: string): string {
  return EFFECT_LABELS[direction]?.cls ?? ''
}

export const AGENT_STATUS_LABELS: Record<string, string> = {
  idle: '空闲',
  thinking: '思考中',
  calling_tool: '调用工具',
  waiting_backend: '等待科学计算',
  completed: '已完成',
  needs_confirmation: '等待确认',
  degraded: '降级模式',
  error: '异常',
}

export function agentStatusLabel(status: string): string {
  return AGENT_STATUS_LABELS[status] ?? status
}

export function formatTimestamp(timestamp: string | null | undefined): string {
  if (!timestamp) return '—'
  return timestamp.replace('T', ' ').replace('Z', '').slice(0, 19)
}
