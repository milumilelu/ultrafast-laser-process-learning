/** applicationStore (UI-2): Application Result references only (UI-P6).
 *  Full scientific payloads stay in the backend artifacts; this store keeps
 *  IDs + the selected tab so pages never re-aggregate the same object. */

import { create } from 'zustand'

export type ApplicationTab = 'summary' | 'identification' | 'modeling' | 'optimization'

interface ApplicationStore {
  activeApplicationRunId: string | null
  processLearningArtifactId: string | null
  evidenceArtifactId: string | null
  cfaArtifactId: string | null
  governedPriorArtifactId: string | null
  vanillaBoRunId: string | null
  assistedBoRunId: string | null
  selectedTab: ApplicationTab
  runMode: 'demo' | 'research' | null
  setRunRefs: (refs: {
    runId: string
    processLearningArtifactId?: string | null
    evidenceArtifactId?: string | null
    cfaArtifactId?: string | null
    governedPriorArtifactId?: string | null
    vanillaBoRunId?: string | null
    assistedBoRunId?: string | null
    mode?: 'demo' | 'research' | null
  }) => void
  setSelectedTab: (tab: ApplicationTab) => void
  clear: () => void
}

export const useApplicationStore = create<ApplicationStore>()((set) => ({
  activeApplicationRunId: null,
  processLearningArtifactId: null,
  evidenceArtifactId: null,
  cfaArtifactId: null,
  governedPriorArtifactId: null,
  vanillaBoRunId: null,
  assistedBoRunId: null,
  selectedTab: 'summary',
  runMode: null,
  setRunRefs: (refs) =>
    set({
      activeApplicationRunId: refs.runId,
      processLearningArtifactId: refs.processLearningArtifactId ?? null,
      evidenceArtifactId: refs.evidenceArtifactId ?? null,
      cfaArtifactId: refs.cfaArtifactId ?? null,
      governedPriorArtifactId: refs.governedPriorArtifactId ?? null,
      vanillaBoRunId: refs.vanillaBoRunId ?? null,
      assistedBoRunId: refs.assistedBoRunId ?? null,
      runMode: refs.mode ?? null,
    }),
  setSelectedTab: (selectedTab) => set({ selectedTab }),
  clear: () =>
    set({
      activeApplicationRunId: null,
      processLearningArtifactId: null,
      evidenceArtifactId: null,
      cfaArtifactId: null,
      governedPriorArtifactId: null,
      vanillaBoRunId: null,
      assistedBoRunId: null,
      selectedTab: 'summary',
      runMode: null,
    }),
}))
