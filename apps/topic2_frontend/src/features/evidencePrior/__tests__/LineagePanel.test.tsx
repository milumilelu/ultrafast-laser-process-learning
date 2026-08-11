import { render, screen } from '@testing-library/react'
import type { EvidencePriorResult } from '../../../api/evidencePrior'
import { LineagePanel } from '../LineagePanel'

const MINIMAL_RESULT: EvidencePriorResult = {
  analysis_run_id: 'run-min',
  task: {
    material: 'CFRP',
    material_grade: null,
    target_metric: 'depth_um',
    equipment: {
      equipment_profile_id: 'eq',
      equipment_revision_id: 'rev',
      profile_name: 'Test system',
      effective_max_power_W: null,
      effective_max_power_source: 'UNKNOWN',
      missing_fields: ['spot_diameter_um'],
    },
  },
  requirements: [
    {
      requirement_id: 'kreq-a',
      requirement_type: 'MATERIAL_IDENTITY',
      scientific_question: 'Is the material CFRP?',
      priority: 'high',
    },
  ],
  evidence: {
    evidence_set_id: 'es',
    items: [],
    misses: [],
    paper_candidates: {},
    knowledge_reused_count: 0,
    llm_call_count: 0,
  },
  beliefs: { belief_set_id: 'bs', beliefs: [] },
  priors: { prior_set_id: 'ps', priors: [], observations: [], conflicts: [], warnings: [] },
  warnings: [],
}

describe('LineagePanel', () => {
  it('shows an empty state before any analysis', () => {
    render(<LineagePanel />)
    expect(screen.getByText('尚未运行分析')).toBeInTheDocument()
  })

  it('renders the flow chain and requirement list from a result', () => {
    render(<LineagePanel result={MINIMAL_RESULT} />)
    expect(screen.getByText('任务')).toBeInTheDocument()
    expect(screen.getByText('双索引检索')).toBeInTheDocument()
    expect(screen.getByText('LLM 逐论文抽取')).toBeInTheDocument()
    expect(screen.getByText('E2P 先验')).toBeInTheDocument()
    expect(screen.getAllByText('MATERIAL_IDENTITY').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Is the material CFRP?').length).toBe(2)
    expect(screen.getByText(/1 个需求/)).toBeInTheDocument()
  })

  it('shows retrieval candidates and evidence state when present', () => {
    const result: EvidencePriorResult = {
      ...MINIMAL_RESULT,
      evidence: {
        ...MINIMAL_RESULT.evidence,
        paper_candidates: {
          'kreq-a': [
            {
              paper_id: 'paper-cfrp.pdf',
              document_version_id: 'doc-1',
              score: 0.05,
              matched_terms: [],
              paper_index_score: 0.8,
              global_block_score: 0.7,
              retrieval_routes: ['paper_index'],
            },
          ],
        },
        items: [
          {
            evidence_id: 'ev-1',
            requirement_id: 'kreq-a',
            paper_id: 'paper-cfrp.pdf',
            document_version_id: 'doc-1',
            paper_title: 'CFRP ablation',
            content: { evidence_type: 'MATERIAL_IDENTITY' },
            conditions: {},
            evidence_quote: 'CFRP laminates',
            source_block_refs: ['b1'],
            source_pages: [2],
            extraction_confidence: 0.9,
            validation_state: 'VALIDATED',
            validation_errors: [],
            governance_status: 'unreviewed',
            extraction_route: 'llm_extraction',
            extractor_model: 'deepseek-v4-flash',
          },
        ],
        llm_call_count: 1,
      },
    }
    render(<LineagePanel result={result} />)
    expect(screen.getByText('paper-cfrp.pdf')).toBeInTheDocument()
    expect(screen.getByText('已抽取')).toBeInTheDocument()
    expect(screen.getByText('VALIDATED')).toBeInTheDocument()
    expect(screen.getByText(/CFRP ablation/)).toBeInTheDocument()
    expect(screen.getByText(/1 次 LLM/)).toBeInTheDocument()
  })
})
