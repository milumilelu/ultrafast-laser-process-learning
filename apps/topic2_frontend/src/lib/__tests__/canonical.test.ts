import { describe, expect, it } from 'vitest'

import { formatTargetGoal, isCanonicalId, targetDirection } from '../canonical'

describe('canonical ids', () => {
  it('accepts known material canonical ids', () => {
    expect(isCanonicalId('material', 'SiC')).toBe(true)
    expect(isCanonicalId('material', 'CFRP')).toBe(true)
  })

  it('rejects free text as material id', () => {
    expect(isCanonicalId('material', '碳化硅陶瓷材料')).toBe(false)
    expect(isCanonicalId('material', '')).toBe(false)
    expect(isCanonicalId('material', null)).toBe(false)
  })

  it('accepts only fs/ps as laser type', () => {
    expect(isCanonicalId('laser_type', 'fs')).toBe(true)
    expect(isCanonicalId('laser_type', 'ps')).toBe(true)
    expect(isCanonicalId('laser_type', 'picosecond')).toBe(false)
  })

  it('rejects ids with spaces for generic entities', () => {
    expect(isCanonicalId('equipment', 'EQ TEST A')).toBe(false)
    expect(isCanonicalId('equipment', 'EQ-TEST-FS')).toBe(true)
  })
})

describe('target direction', () => {
  it('derives maximize/minimize from backend BO convention', () => {
    expect(targetDirection('depth_um')).toBe('maximize')
    expect(targetDirection('roughness_um')).toBe('minimize')
  })

  it('formats goals in Chinese', () => {
    expect(formatTargetGoal('depth_um')).toBe('深度最大化')
    expect(formatTargetGoal('roughness_um')).toBe('粗糙度最小化')
  })
})
