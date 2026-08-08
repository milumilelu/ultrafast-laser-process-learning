/** Page Context: what the user is currently looking at. Provided to the Agent
 *  so it never has to guess structured UI state. Also carries contextual quick
 *  actions that surface inside the Agent sidebar. */

import { create } from 'zustand'

export type PageName =
  | 'home'
  | 'task'
  | 'identification'
  | 'modeling'
  | 'optimization'
  | 'application'
  | 'evidence'
  | 'database'
  | 'runs'
  | 'demo'
  | 'resources'

export interface PageQuickAction {
  label: string
  prompt: string
}

export interface PageContextState {
  page: PageName
  activeRunId: string | null
  activeModelId: string | null
  activeExperimentId: string | null
  quickActions: PageQuickAction[]
}

interface PageContextStore extends PageContextState {
  setPage: (page: PageName) => void
  setActiveRun: (runId: string | null) => void
  setActiveModel: (modelId: string | null) => void
  setQuickActions: (actions: PageQuickAction[]) => void
}

export const usePageContextStore = create<PageContextStore>()((set) => ({
  page: 'home',
  activeRunId: null,
  activeModelId: null,
  activeExperimentId: null,
  quickActions: [],
  setPage: (page) => set({ page }),
  setActiveRun: (activeRunId) => set({ activeRunId }),
  setActiveModel: (activeModelId) => set({ activeModelId }),
  setQuickActions: (quickActions) => set({ quickActions }),
}))
