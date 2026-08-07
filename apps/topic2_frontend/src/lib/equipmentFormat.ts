/** 设备参数展示辅助。 */

import { equipmentParamLabel } from './canonical'

export function formatNumberValue(value: number | string | null): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : value.toFixed(2)
  }
  return value
}

export function formatJsonValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

export { equipmentParamLabel }
