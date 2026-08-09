/** ScientificCorpusPack view model (阶段一) — corpus + reading mapping report. */

export interface ResolutionSourceView {
  sourceId: string
  paperId: string
  title: string
  sectionTypes: string[]
}

export interface ResolutionMappingView {
  sources: number
  completed: number
  partial: number
  failed: number
  fromCache: number
}

export interface ResolutionView {
  sources: ResolutionSourceView[]
  mapping: ResolutionMappingView
  candidates: number
  corpusPackId: string
}

export interface CorpusPackContent {
  schema_version?: string
  corpus_pack?: {
    corpus_pack_id?: string
    sources?: Array<{
      source_id?: string
      paper_id?: string
      title?: string
      sections?: Array<{ section_type?: string }>
    }>
  }
  analysis_mapping?: {
    sources?: number
    completed?: number
    partial?: number
    failed?: number
    from_cache?: number
  }
}

export function buildResolutionView(content: CorpusPackContent | null | undefined): ResolutionView {
  const raw = content ?? {}
  const corpus = raw.corpus_pack ?? {}
  const mapping = raw.analysis_mapping ?? {}
  return {
    sources: (corpus.sources ?? []).map((source) => ({
      sourceId: String(source.source_id ?? ''),
      paperId: String(source.paper_id ?? ''),
      title: String(source.title ?? ''),
      sectionTypes: (source.sections ?? [])
        .map((section) => String(section.section_type ?? ''))
        .filter(Boolean),
    })),
    mapping: {
      sources: Number(mapping.sources ?? corpus.sources?.length ?? 0),
      completed: Number(mapping.completed ?? 0),
      partial: Number(mapping.partial ?? 0),
      failed: Number(mapping.failed ?? 0),
      fromCache: Number(mapping.from_cache ?? 0),
    },
    candidates: 0,
    corpusPackId: String(corpus.corpus_pack_id ?? ''),
  }
}
