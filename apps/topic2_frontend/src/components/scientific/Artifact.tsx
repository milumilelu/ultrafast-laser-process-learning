import type { ArtifactRef } from '../../domain/artifact'
import { useUiStore } from '../../stores/ui'

/** Artifact ref display; raw ids only in Developer Mode (spec §二十三). */
export function RefChip({ ref }: { ref: ArtifactRef }) {
  const developerMode = useUiStore((state) => state.developerMode)
  if (!developerMode) return null
  return (
    <span className="ref-chip" title={`${ref.type}:${ref.id}`}>
      {ref.type}:{ref.id.slice(0, 12)}
    </span>
  )
}

export function RefList({ refs, label }: { refs: ArtifactRef[]; label?: string }) {
  const developerMode = useUiStore((state) => state.developerMode)
  if (!developerMode || refs.length === 0) return null
  return (
    <div className="ref-list">
      {label && <span className="ref-label">{label}</span>}
      {refs.map((ref) => (
        <RefChip key={`${ref.type}:${ref.id}`} ref={ref} />
      ))}
    </div>
  )
}

export function ProvenanceList({ records }: { records: Array<{ source_type: string; source_ref: string; role: string }> }) {
  const developerMode = useUiStore((state) => state.developerMode)
  if (!developerMode || records.length === 0) return null
  return (
    <div className="ref-list provenance">
      <span className="ref-label">provenance</span>
      {records.map((record, index) => (
        <span key={index} className="ref-chip">
          {record.role} ← {record.source_type}:{record.source_ref.slice(0, 12)}
        </span>
      ))}
    </div>
  )
}

export function DeveloperPayload({
  payload,
  label = 'raw payload',
}: {
  payload: unknown
  label?: string
}) {
  const developerMode = useUiStore((state) => state.developerMode)
  if (!developerMode) return null
  return (
    <details className="dev-payload">
      <summary>{label}</summary>
      <pre>{JSON.stringify(payload, null, 2)}</pre>
    </details>
  )
}

export function SnapshotMeta({ snapshot }: { snapshot: { id: string; schema_version?: string; input_refs?: ArtifactRef[] } | null | undefined }) {
  const developerMode = useUiStore((state) => state.developerMode)
  if (!developerMode || !snapshot) return null
  return (
    <div className="ref-list">
      <span className="ref-chip">id: {snapshot.id}</span>
      {snapshot.schema_version && <span className="ref-chip">schema: {snapshot.schema_version}</span>}
      {snapshot.input_refs?.map((ref) => (
        <RefChip key={`${ref.type}:${ref.id}`} ref={ref} />
      ))}
    </div>
  )
}
