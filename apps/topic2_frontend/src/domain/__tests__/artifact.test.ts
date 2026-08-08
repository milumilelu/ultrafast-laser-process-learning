import { selectLatestByType } from '../artifact'

describe('selectLatestByType (spec §19 snapshot contract)', () => {
  const items = [
    { artifact_id: 'a1', artifact_type: 'ScientificCapabilityReport', created_at: '2026-08-08T00:00:00Z' },
    { artifact_id: 'a2', artifact_type: 'KnowledgeRequirementSet', created_at: '2026-08-08T00:01:00Z' },
    { artifact_id: 'a3', artifact_type: 'ScientificCapabilityReport', created_at: '2026-08-08T00:02:00Z' },
    { artifact_id: 'a4', artifact_type: 'UnrelatedKind', created_at: '2026-08-08T00:03:00Z' },
  ]

  it('keeps only the latest artifact per physics-to-planning kind', () => {
    const latest = selectLatestByType(items)
    expect(latest.get('ScientificCapabilityReport')?.artifact_id).toBe('a3')
    expect(latest.get('KnowledgeRequirementSet')?.artifact_id).toBe('a2')
    expect(latest.has('UnrelatedKind')).toBe(false)
  })

  it('respects an explicit wanted list', () => {
    const latest = selectLatestByType(items, ['KnowledgeRequirementSet'])
    expect(latest.size).toBe(1)
    expect(latest.has('KnowledgeRequirementSet')).toBe(true)
  })

  it('empty input yields empty map', () => {
    expect(selectLatestByType([]).size).toBe(0)
  })
})
