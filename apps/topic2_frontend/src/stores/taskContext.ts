/** Global Task Context store with canonical IDs and mandatory version bumps.
 *  Every formal modification increments version; the Agent always binds to id + version. */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import type { LaserType } from '../api/types'

export type ProcessTaskType = 'rectangular_groove' | 'circular_hole' | 'single_line' | 'custom'
export type ObjectiveMode = 'quality_first' | 'efficiency_first'

export interface TargetMetric {
  target: 'depth_um' | 'roughness_um'
}

/** 设备光学属性（物理特征构建输入，随设备档案管理；在任务页展示读取） */
export interface DeviceProperties {
  /** 光斑半径（1/e²），与 spotDefinition 必须成对 */
  spotRadiusUm: string
  /** 光斑定义：如 "1/e2"、"full_width_half_maximum" */
  spotDefinition: string
}

/** 材料参数（可选，非必选）：随材料定义设置，与设备档案无关。
 *  用于物理特征构建（热扩散系数 → 热积累相关特征；烧蚀阈值 → 归一化通量等）。 */
export interface MaterialProperties {
  /** 热扩散系数 m²/s */
  thermalDiffusivityM2S: string
  /** 烧蚀阈值 J/cm² */
  ablationThresholdJcm2: string
}

export interface TaskContextState {
  taskContextId: string
  version: number
  materialId: string | null
  materialGrade: string | null
  laserType: LaserType | null
  /** 设备档案 ID（Agent 设备，提供机器边界与上下文） */
  equipmentId: string | null
  /** 数据集设备 ID（Topic2 实验设备，用于科学查询 scope） */
  datasetEquipmentId: string | null
  /** 加工任务：矩形槽 / 圆孔 / 单线 / 自定义（与后端 geometry_type 同构的 Canonical ID） */
  processType: ProcessTaskType | null
  /** 具体任务参数（矩形槽：槽宽/槽深；圆孔：孔径/孔深；单线：线宽/切深；自定义：描述） */
  processParams: Record<string, string | number>
  /** 加工目标：质量优先 / 效率优先（决定后端优化目标） */
  objective: ObjectiveMode | null
  targetMetrics: TargetMetric[]
  /** 设备光学属性（物理特征构建输入，随设备档案管理） */
  deviceProperties: DeviceProperties
  /** 材料参数（可选，非必选）：热扩散系数 / 烧蚀阈值 */
  materialProperties: MaterialProperties
  datasetId: string | null
  selectedModelId: string | null
  createdAt: string
  updatedAt: string
}

export interface TaskContextPatch {
  materialId?: string | null
  materialGrade?: string | null
  laserType?: LaserType | null
  equipmentId?: string | null
  datasetEquipmentId?: string | null
  processType?: ProcessTaskType | null
  processParams?: Record<string, string | number>
  objective?: ObjectiveMode | null
  targetMetrics?: TargetMetric[]
  deviceProperties?: DeviceProperties
  materialProperties?: MaterialProperties
  datasetId?: string | null
  selectedModelId?: string | null
}

let taskSequence = 0
let lastTaskId = ''

function nextTaskId(): string {
  if (lastTaskId) {
    const match = /^TASK-(\d+)$/.exec(lastTaskId)
    if (match) {
      taskSequence = Number(match[1])
      lastTaskId = ''
    }
  }
  taskSequence += 1
  return `TASK-${String(taskSequence).padStart(4, '0')}`
}

function createInitialContext(): TaskContextState {
  const now = new Date().toISOString()
  const initial: TaskContextState = {
    taskContextId: nextTaskId(),
    version: 1,
    materialId: null,
    materialGrade: null,
    laserType: null,
    equipmentId: null,
    datasetEquipmentId: null,
    processType: null,
    processParams: {},
    objective: null,
    targetMetrics: [],
    deviceProperties: {
      spotRadiusUm: '',
      spotDefinition: '',
    },
    materialProperties: {
      thermalDiffusivityM2S: '',
      ablationThresholdJcm2: '',
    },
    datasetId: null,
    selectedModelId: null,
    createdAt: now,
    updatedAt: now,
  }
  lastTaskId = initial.taskContextId
  return initial
}

/** 兼容旧版本持久化数据：geometryType → processType，targetMetrics → objective；
 *  旧 deviceProperties 中的热扩散系数/烧蚀阈值迁移为材料参数 materialProperties。 */
export function migrateLegacyContext(state: TaskContextState): TaskContextState {
  const legacyDevice = (state as unknown as { deviceProperties?: Record<string, unknown> }).deviceProperties ?? {}
  const migrated = {
    ...state,
    processParams: state.processParams ?? {},
    deviceProperties: {
      spotRadiusUm: state.deviceProperties?.spotRadiusUm ?? String(legacyDevice.spotRadiusUm ?? ''),
      spotDefinition: state.deviceProperties?.spotDefinition ?? String(legacyDevice.spotDefinition ?? ''),
    },
    materialProperties: state.materialProperties ?? {
      thermalDiffusivityM2S: String(legacyDevice.thermalDiffusivityM2S ?? ''),
      ablationThresholdJcm2: String(legacyDevice.ablationThresholdJcm2 ?? ''),
    },
  }
  let changed = false
  if (!migrated.processType && 'geometryType' in migrated) {
    const legacy = (migrated as unknown as Record<string, unknown>).geometryType
    if (typeof legacy === 'string' && legacy) {
      const valid: ProcessTaskType[] = ['rectangular_groove', 'circular_hole', 'single_line', 'custom']
      migrated.processType = valid.includes(legacy as ProcessTaskType)
        ? (legacy as ProcessTaskType)
        : 'custom'
      changed = true
    }
  }
  if (!migrated.objective && migrated.targetMetrics.length > 0) {
    migrated.objective =
      migrated.targetMetrics[0].target === 'roughness_um' ? 'quality_first' : 'efficiency_first'
    changed = true
  }
  // 科学目标只由加工目标派生：与 objective 冲突的旧 targetMetrics 残留一律清除。
  if (migrated.objective && migrated.targetMetrics.length > 0) {
    const derived = objectiveToTargetForStore(migrated.objective)
    if (
      derived !== null &&
      migrated.targetMetrics.every((metric) => metric.target !== derived)
    ) {
      migrated.targetMetrics = []
      changed = true
    }
  }
  // 设备标识拆分迁移：旧数据把唯一 equipmentId 同时当作数据集设备。
  // 若它本身是 Topic2 设备 ID（EQ-* 前缀），则作为数据集设备使用；
  // 否则保持设备档案语义，数据集设备需用户重新选择。
  if (migrated.datasetEquipmentId == null && migrated.equipmentId) {
    if (/^EQ-/.test(migrated.equipmentId)) {
      migrated.datasetEquipmentId = migrated.equipmentId
      migrated.equipmentId = null
    }
    changed = true
  }
  return changed ? { ...migrated, updatedAt: migrated.updatedAt } : migrated
}

function objectiveToTargetForStore(
  mode: 'quality_first' | 'efficiency_first',
): 'depth_um' | 'roughness_um' | null {
  if (mode === 'quality_first') return 'roughness_um'
  if (mode === 'efficiency_first') return 'depth_um'
  return null
}

interface TaskContextStore {
  context: TaskContextState
  update: (patch: TaskContextPatch) => TaskContextState
  reset: () => TaskContextState
  isComplete: (context?: TaskContextState) => boolean
}

export const useTaskContextStore = create<TaskContextStore>()(
  persist(
    (set, get) => ({
      context: createInitialContext(),
      update: (patch) => {
        const current = get().context
        const next: TaskContextState = {
          ...current,
          ...patch,
          version: current.version + 1,
          updatedAt: new Date().toISOString(),
        }
        set({ context: next })
        return next
      },
      reset: () => {
        const next = createInitialContext()
        set({ context: next })
        return next
      },
      isComplete: (context) => {
        const target = context ?? get().context
        return (
          target.materialId !== null &&
          target.laserType !== null &&
          target.datasetEquipmentId !== null &&
          target.processType !== null &&
          target.objective !== null
        )
      },
    }),
    {
      name: 'topic2-task-context',
      onRehydrateStorage: () => (state) => {
        if (state && state.context) {
          state.context = migrateLegacyContext(state.context)
          lastTaskId = state.context.taskContextId
        }
      },
    },
  ),
)
