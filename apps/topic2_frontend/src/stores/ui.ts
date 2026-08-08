/** Pure UI state (spec §26.2). No scientific data lives here. */

import { create } from 'zustand'

interface UiState {
  developerMode: boolean
  toggleDeveloperMode: () => void
}

export const useUiStore = create<UiState>()((set) => ({
  developerMode: false,
  toggleDeveloperMode: () => set((state) => ({ developerMode: !state.developerMode })),
}))
