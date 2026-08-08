/** Software mode: Demo (frozen scenario, readonly) vs Research (full control). */

import { create } from 'zustand'

export type SoftwareMode = 'demo' | 'research'

interface ModeStore {
  mode: SoftwareMode
  setMode: (mode: SoftwareMode) => void
}

export const useModeStore = create<ModeStore>()((set) => ({
  mode: 'research',
  setMode: (mode) => set({ mode }),
}))
