/** FE-2: the frontend must not implement scientific logic.
 * Static source scan for forbidden client-side science functions.
 */

const FORBIDDEN_IDENTIFIERS = [
  'calculateFluence',
  'computeFluence',
  'convertEvidenceToPrior',
  'calculateSatisfaction',
  'judgeSatisfaction',
  'deriveToolpath',
  'buildToolpath',
  'combineToolpath',
  'calculateApplicability',
  'calcPeakFluence',
  'calcPulseEnergy',
]

describe('FE-2: no scientific logic in frontend source', () => {
  const sources = import.meta.glob('../../**/*.{ts,tsx}', { as: 'raw', eager: true }) as Record<
    string,
    string
  >

  const sourceFiles = Object.entries(sources).filter(
    ([path]) => !path.includes('__tests__') && !path.endsWith('.d.ts'),
  )

  it('scans all frontend source files', () => {
    expect(sourceFiles.length).toBeGreaterThan(15)
  })

  it('never defines client-side science functions (FE-2)', () => {
    const violations: Array<[string, string]> = []
    for (const [path, content] of sourceFiles) {
      for (const identifier of FORBIDDEN_IDENTIFIERS) {
        if (content.includes(identifier)) violations.push([path, identifier])
      }
    }
    expect(violations).toEqual([])
  })

  it('does not import scipy/numpy (no client-side numerics)', () => {
    const violations = sourceFiles
      .filter(([, content]) => content.includes('scipy') || content.includes('numpy'))
      .map(([path]) => path)
    expect(violations).toEqual([])
  })
})
