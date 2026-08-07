import { beforeEach, describe, expect, it } from 'vitest'

import { migrateLegacyContext, useTaskContextStore } from '../taskContext'
import type { TaskContextState } from '../taskContext'

describe('task context store', () => {
  beforeEach(() => {
    useTaskContextStore.setState({ context: useTaskContextStore.getState().reset() })
  })

  it('starts with a unique id and version 1', () => {
    const first = useTaskContextStore.getState().context
    const second = useTaskContextStore.getState().reset()
    expect(first.taskContextId).toMatch(/^TASK-\d{4}$/)
    expect(first.version).toBe(1)
    expect(second.taskContextId).not.toBe(first.taskContextId)
  })

  it('increments version on every formal update', () => {
    const store = useTaskContextStore.getState()
    const v1 = store.context.version
    store.update({ materialId: 'SiC' })
    expect(useTaskContextStore.getState().context.version).toBe(v1 + 1)
    const v2 = useTaskContextStore.getState().context.version
    useTaskContextStore.getState().update({ objective: 'quality_first' })
    expect(useTaskContextStore.getState().context.version).toBe(v2 + 1)
  })

  it('persists updated fields and timestamps', () => {
    const store = useTaskContextStore.getState()
    store.update({
      materialId: 'SiC',
      laserType: 'fs',
      datasetEquipmentId: 'EQ-TEST-FS',
      processType: 'rectangular_groove',
      processParams: { groove_width_um: 200, groove_depth_um: 300 },
      objective: 'efficiency_first',
    })
    const context = useTaskContextStore.getState().context
    expect(context.materialId).toBe('SiC')
    expect(context.processType).toBe('rectangular_groove')
    expect(context.processParams.groove_width_um).toBe(200)
    expect(context.objective).toBe('efficiency_first')
    expect(context.updatedAt >= context.createdAt).toBe(true)
  })

  it('isComplete reflects a fully defined task', () => {
    const store = useTaskContextStore.getState()
    expect(store.isComplete()).toBe(false)
    store.update({
      materialId: 'SiC',
      laserType: 'fs',
      datasetEquipmentId: 'EQ-TEST-FS',
      processType: 'rectangular_groove',
      objective: 'efficiency_first',
    })
    expect(useTaskContextStore.getState().isComplete()).toBe(true)
  })

  it('migrates legacy persisted state (geometryType/targetMetrics/equipmentId)', () => {
    const legacy = {
      taskContextId: 'TASK-0099',
      version: 3,
      materialId: 'SiC',
      materialGrade: null,
      laserType: 'fs',
      equipmentId: 'EQ-TEST-FS',
      geometryType: 'rectangular_groove',
      targetMetrics: [{ target: 'roughness_um' }],
      datasetId: null,
      selectedModelId: null,
      createdAt: '2026-01-01T00:00:00.000Z',
      updatedAt: '2026-01-01T00:00:00.000Z',
    } as unknown as TaskContextState

    const migrated = migrateLegacyContext(legacy)
    expect(migrated.processType).toBe('rectangular_groove')
    expect(migrated.objective).toBe('quality_first')
    expect(migrated.processParams).toEqual({})
    // 旧 equipmentId 是 Topic2 设备 ID → 迁移为数据集设备；设备档案置空待用户选择
    expect(migrated.datasetEquipmentId).toBe('EQ-TEST-FS')
    expect(migrated.equipmentId).toBeNull()
  })
})

