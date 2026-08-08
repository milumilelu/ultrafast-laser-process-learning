/** 友好错误映射：后端错误 → 中文可操作提示。
 *  所有科学执行入口的错误展示统一走这里，原始 detail 不再直接上屏。 */

export class ApiErrorLike extends Error {
  readonly status: number
  readonly detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

const ERROR_PATTERNS: { pattern: RegExp; hint: string }[] = [
  {
    pattern: /no comparable experiments found for the requested scope/i,
    hint: '当前任务组合在数据库中没有实验数据。请到「任务与数据」页更换材料 / 激光 / 数据集设备 / 加工任务组合（设备档案仅提供机器边界，不影响数据量）。',
  },
  {
    pattern: /model material does not match optimization scope/i,
    hint: '所选模型与当前任务材料不匹配。请重新训练或更换模型。',
  },
  {
    pattern: /optimization currently requires a persisted GPR/i,
    hint: '工艺优化需要带不确定性的 GPR 模型。当前模型不支持，请重新训练并选择 GPR。',
  },
  {
    pattern: /model policy scope does not match training scope/i,
    hint: '模型策略与当前训练任务范围不一致，请重新获取模型策略。',
  },
  {
    pattern: /governed prior.*(mismatch|not issued|fails closed|no longer approved)/i,
    hint: '受治理先验校验未通过（证据审核状态可能已变化），assisted 优化将回退为 Vanilla。',
  },
  {
    pattern: /missing machine bounds/i,
    hint: '优化参数范围不完整，请检查设备档案或数据范围。',
  },
  {
    pattern: /no governed prior|governed prior 不可签发/i,
    hint: '无已审核证据可签发受治理先验，assisted 优化将如实显示 prior_applied=false。',
  },
  {
    pattern: /application run not found/i,
    hint: '未找到该应用运行记录，可能已被清理。',
  },
  {
    pattern: /still running/i,
    hint: '该应用运行仍在执行中，请等待完成。',
  },
  {
    pattern: /already executed, refusing to re-run/i,
    hint: '该阶段已执行过，同一运行不允许重复执行。',
  },
]

export function friendlyApiError(error: unknown): string {
  if (error instanceof ApiErrorLike || (error instanceof Error && 'status' in error)) {
    const apiError = error as ApiErrorLike
    const detail = apiError.detail ?? String(error)
    const match = ERROR_PATTERNS.find((item) => item.pattern.test(detail))
    if (match) return match.hint
    // 后端 JSON detail（如 {"detail": "..."}）提取正文
    try {
      const parsed = JSON.parse(detail) as { detail?: unknown }
      if (typeof parsed.detail === 'string') return parsed.detail
    } catch {
      /* 非 JSON，保留原文 */
    }
    return detail
  }
  if (error instanceof Error) {
    const match = ERROR_PATTERNS.find((item) => item.pattern.test(error.message))
    if (match) return match.hint
    return error.message
  }
  return String(error)
}

/** 判断是否是"无数据"类错误（用于运行前预检与错误提示）。 */
export function isNoDataError(error: unknown): boolean {
  const text = error instanceof Error ? error.message : String(error)
  return /no comparable experiments|no rows for scope|当前任务组合在数据库中没有实验数据/.test(text)
}
