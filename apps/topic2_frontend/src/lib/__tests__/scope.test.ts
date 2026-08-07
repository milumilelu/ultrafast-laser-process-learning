import { beforeEach, describe, expect, it } from 'vitest'

import { taskContextToScope, IncompleteTaskContextError, scopeDataGates } from '../scope'
import { useTaskContextStore } from '../../stores/taskContext'

function completeContext() {
  const store = useTaskContextStore.getState()
  store.update({
    materialId: 'SiC',
    laserType: 'fs',
    datasetEquipmentId: 'EQ-REAL',
    equipmentId: 'eq-profile-1',
    processType: 'rectangular_groove',
    objective: 'efficiency_first',
  })
  return useTaskContextStore.getState().context
}

describe('task context to scope', () => {
  beforeEach(() => {
    useTaskContextStore.setState({ context: useTaskContextStore.getState().reset() })
  })

  it('maps efficiency-first to depth maximization scope using dataset equipment', () => {
    const context = completeContext()
    const scope = taskContextToScope(context)
    expect(scope).toMatchObject({
      task_context_id: context.taskContextId,
      task_context_version: context.version,
      material: 'SiC',
      laser_type: 'fs',
      equipment_id: 'EQ-REAL',
      geometry_type: 'rectangular_groove',
      target: 'depth_um',
      device_properties: { equipment_profile_id: 'eq-profile-1' },
    })
  })

  it('maps quality-first to roughness minimization scope', () => {
    completeContext()
    useTaskContextStore.getState().update({ objective: 'quality_first' })
    const scope = taskContextToScope(useTaskContextStore.getState().context)
    expect(scope.target).toBe('roughness_um')
  })

  it('maps custom process type to custom geometry canonical id', () => {
    completeContext()
    useTaskContextStore.getState().update({ processType: 'custom' })
    const scope = taskContextToScope(useTaskContextStore.getState().context)
    expect(scope.geometry_type).toBe('custom')
  })

  it('throws when the dataset equipment is missing even if a profile exists', () => {
    completeContext()
    useTaskContextStore.getState().update({ datasetEquipmentId: null })
    expect(() => taskContextToScope(useTaskContextStore.getState().context)).toThrow(
      IncompleteTaskContextError,
    )
  })

  it('scope gates match backend thresholds', () => {
    expect(scopeDataGates(3, 3, 3).identification).toBe(false)
    expect(scopeDataGates(4, 2, 4).identification).toBe(true)
    expect(scopeDataGates(10, 1, 10).modeling).toBe(false)
    expect(scopeDataGates(10, 2, 10).modeling).toBe(true)
    expect(scopeDataGates(5, 5, 4).optimization).toBe(false)
    expect(scopeDataGates(5, 5, 5).optimization).toBe(true)
  })
})
