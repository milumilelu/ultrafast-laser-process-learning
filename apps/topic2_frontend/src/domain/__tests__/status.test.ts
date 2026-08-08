import {
  executionLabel,
  executionStatusFrom,
  isExecutionStatus,
  isParameterStatus,
  isScientificStatus,
  parameterLabel,
  parameterTone,
  scientificLabel,
  scientificStatusFrom,
  scientificTone,
} from '../status'

describe('status namespaces (spec §二十四)', () => {
  it('execution status never contains UNKNOWN (spec §二十五)', () => {
    const executions = ['NOT_RUN', 'RUNNING', 'READY', 'BLOCKED', 'FAILED']
    expect(executions).not.toContain('UNKNOWN')
    for (const value of executions) expect(isExecutionStatus(value)).toBe(true)
  })

  it('UNKNOWN is a scientific status, not an execution status', () => {
    expect(isScientificStatus('UNKNOWN')).toBe(true)
    expect(isExecutionStatus('UNKNOWN')).toBe(false)
    expect(isParameterStatus('UNKNOWN')).toBe(false)
  })

  it('maps backend scientific strings into the ScientificStatus namespace', () => {
    expect(scientificStatusFrom('KNOWN')).toBe('KNOWN')
    expect(scientificStatusFrom('PARTIAL')).toBe('PARTIAL')
    expect(scientificStatusFrom('PARTIALLY_SATISFIED')).toBe('PARTIAL')
    expect(scientificStatusFrom(null)).toBe('UNKNOWN')
    expect(scientificStatusFrom('mismatch')).toBe('MISMATCH')
  })

  it('maps stage/run status into the ExecutionStatus namespace', () => {
    expect(executionStatusFrom('completed')).toBe('READY')
    expect(executionStatusFrom('running')).toBe('RUNNING')
    expect(executionStatusFrom('failed')).toBe('FAILED')
    expect(executionStatusFrom(undefined)).toBe('NOT_RUN')
  })

  it('tone semantics: UNKNOWN is neutral, MISMATCH is error', () => {
    expect(scientificTone('UNKNOWN')).toBe('neutral')
    expect(scientificTone('MISMATCH')).toBe('err')
    expect(scientificTone('KNOWN')).toBe('ok')
  })

  it('parameter namespace covers all seven sources', () => {
    const sources: Array<Parameters<typeof parameterLabel>[0]> = [
      'MEASURED',
      'DERIVED',
      'PRIOR_ONLY',
      'CALIBRATED',
      'PROVISIONAL',
      'NOT_IDENTIFIABLE',
      'MISSING',
    ]
    for (const source of sources) {
      expect(isParameterStatus(source)).toBe(true)
      expect(parameterLabel(source).length).toBeGreaterThan(0)
      expect(parameterTone(source)).toBeDefined()
    }
  })

  it('NOT_IDENTIFIABLE label makes the "no fitted value" semantics explicit', () => {
    expect(parameterLabel('NOT_IDENTIFIABLE')).toContain('不可辨识')
  })

  it('labels exist for all statuses', () => {
    expect(executionLabel('RUNNING')).toBe('运行中')
    expect(scientificLabel('UNKNOWN')).toBe('未知')
  })
})
