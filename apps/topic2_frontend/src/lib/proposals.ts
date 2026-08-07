/** Apply accepted Agent proposals to the real stores. Proposals are the only
 *  way the Agent may change structured state — always via Human confirmation. */

import type { AgentProposal } from '../stores/agent'
import { useScienceStore } from '../stores/science'
import { useTaskContextStore } from '../stores/taskContext'
import type { TaskContextPatch } from '../stores/taskContext'

export function applyProposalChanges(proposal: AgentProposal): boolean {
  const changes = proposal.changes
  switch (proposal.type) {
    case 'update_task': {
      const patch: TaskContextPatch = {}
      if (typeof changes.materialId === 'string') patch.materialId = changes.materialId
      if (changes.laserType === 'fs' || changes.laserType === 'ps') patch.laserType = changes.laserType
      if (typeof changes.equipmentId === 'string') patch.equipmentId = changes.equipmentId
      if (typeof changes.processType === 'string') patch.processType = changes.processType as 'rectangular_groove' | 'circular_hole' | 'single_line' | 'custom'
      if (changes.objective === 'quality_first' || changes.objective === 'efficiency_first') {
        patch.objective = changes.objective
      }
      if (typeof changes.processParams === 'object' && changes.processParams !== null) {
        patch.processParams = changes.processParams as Record<string, string | number>
      }
      if (Object.keys(patch).length === 0) return false
      useTaskContextStore.getState().update(patch)
      return true
    }
    case 'select_model': {
      const modelName = typeof changes.model_name === 'string' ? changes.model_name : null
      if (modelName) {
        useScienceStore.getState().setSelection(modelName, 'manual')
      }
      if (typeof changes.selectedModelId === 'string') {
        useTaskContextStore
          .getState()
          .update({ selectedModelId: changes.selectedModelId })
      }
      return modelName !== null || typeof changes.selectedModelId === 'string'
    }
    case 'run_modeling':
    case 'run_optimization':
    case 'use_evidence':
      // Level-3 actions stay Human-triggered from the UI; acceptance only records the decision.
      return false
    default:
      return false
  }
}
