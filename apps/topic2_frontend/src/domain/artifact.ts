/** Artifact registry: which artifact kinds the workbench consumes (spec §19). */

export interface ArtifactRef {
  type: string
  id: string
}

export interface ArtifactMeta {
  artifact_id: string
  artifact_type: string
  created_at: string
}

export interface ArtifactSnapshot<T = Record<string, unknown>> {
  id: string
  type: string
  schema_version: string
  input_refs: ArtifactRef[]
  content: T
  created_at: string
}

export const PHYSICS_TO_PLANNING_ARTIFACT_TYPES = [
  'ScientificCapabilityReport',
  'KnowledgeRequirementSet',
  'KnowledgeState',
  'LiteratureRetrievalQueryPlan',
  'EvidenceIRSet',
  'PriorObjectSet',
  'CanonicalPhysicsState',
  'IdentifiabilityReport',
  'CalibrationResult',
  'PhysicalModelState',
  'LocalRemovalModel',
  'MorphologySimulationResult',
  'ToolpathPlan',
  'ProcessLearningResult',
  'ObservationResult',
] as const

export type PhysicsToPlanningArtifactType = (typeof PHYSICS_TO_PLANNING_ARTIFACT_TYPES)[number]

/** Latest artifact per kind (persisted artifacts are append-only per stage). */
export function selectLatestByType(
  items: ArtifactMeta[],
  wanted: readonly string[] = PHYSICS_TO_PLANNING_ARTIFACT_TYPES,
): Map<string, ArtifactMeta> {
  const wantedSet = new Set<string>(wanted)
  const latest = new Map<string, ArtifactMeta>()
  for (const item of items) {
    if (wantedSet.has(item.artifact_type)) latest.set(item.artifact_type, item)
  }
  return latest
}
