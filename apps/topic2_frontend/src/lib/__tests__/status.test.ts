/** UI-P3 状态语义测试：Unknown 从不渲染为 Mismatch；CFA 无概率字段。 */

import { describe, expect, it } from 'vitest'

import { scientificTone, scientificLabel } from '../status'

describe('scientific status semantics (UI-P3)', () => {
  it('known/verified/available render green', () => {
    for (const status of ['AVAILABLE', 'VERIFIED', 'KNOWN', 'READY']) {
      expect(scientificTone(status)).toBe('ok')
    }
  })

  it('partial/unverified render yellow', () => {
    expect(scientificTone('PARTIAL')).toBe('warn')
    expect(scientificTone('UNVERIFIED')).toBe('warn')
    expect(scientificTone('PENDING')).toBe('warn')
  })

  it('unknown/blocked render gray, never red', () => {
    for (const status of ['UNKNOWN', 'NOT_REPORTED', 'BLOCKED', 'NOT_YET_CALIBRATED']) {
      expect(scientificTone(status)).toBe('neutral')
    }
  })

  it('explicit mismatch/error render red only', () => {
    for (const status of ['MISMATCH', 'ERROR', 'CONTRADICTED']) {
      expect(scientificTone(status)).toBe('err')
    }
  })

  it('unknown is not labeled as mismatch', () => {
    expect(scientificLabel('UNKNOWN')).not.toContain('不匹配')
    expect(scientificLabel('MISMATCH')).toBe('不匹配')
  })

  it('uncertain statuses stay in the unknown family', () => {
    expect(scientificTone('UNKNOWNISH')).toBe('neutral')
  })
})
