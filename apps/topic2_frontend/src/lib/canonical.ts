/** Canonical ID helpers and display labels: the system never uses free text as a formal entity identifier. */

import type { LaserType, TargetName } from '../api/types'
import type { ObjectiveMode, ProcessTaskType } from '../stores/taskContext'

export interface LabeledOption {
  value: string
  label: string
}

export const MATERIAL_LABELS: Record<string, string> = {
  'SiCp/Al': '铝碳化硅 SiCp/Al',
  CFRP: '碳纤维复合材料 CFRP',
  Diamond: '金刚石 Diamond',
  FusedSilica: '熔融石英 FusedSilica',
  SiC: '碳化硅 SiC',
  Ti6Al4V: '钛合金 Ti6Al4V',
  ZrO2: '氧化锆 ZrO2',
}

export const LASER_LABELS: Record<LaserType, string> = {
  fs: '飞秒 (fs)',
  ps: '皮秒 (ps)',
}

export const TARGET_LABELS: Record<TargetName, string> = {
  depth_um: '深度 depth_um',
  roughness_um: '表面粗糙度 roughness_um',
}

export const PROCESS_TASK_LABELS: Record<ProcessTaskType, string> = {
  rectangular_groove: '矩形槽',
  circular_hole: '圆孔',
  single_line: '单线',
  custom: '自定义',
}

export const PROCESS_TASK_OPTIONS: { value: ProcessTaskType; label: string; description: string }[] = [
  { value: 'rectangular_groove', label: '矩形槽', description: '加工矩形沟槽，可设置槽宽、槽深等参数' },
  { value: 'circular_hole', label: '圆孔', description: '加工圆孔，可设置孔径、孔深等参数' },
  { value: 'single_line', label: '单线', description: '单线刻划，可设置线宽、切深等参数' },
  { value: 'custom', label: '自定义', description: '其他任务形态，通过 Agent 对话描述具体任务' },
]

/** 加工任务 → 后端 geometry_type Canonical ID（与数据库记录保持一致） */
export const PROCESS_TASK_CANONICAL: Record<ProcessTaskType, string> = {
  rectangular_groove: 'rectangular_groove',
  circular_hole: 'circular_hole',
  single_line: 'single_line',
  custom: 'custom',
}

export const OBJECTIVE_LABELS: Record<ObjectiveMode, string> = {
  quality_first: '质量优先',
  efficiency_first: '效率优先',
}

export const OBJECTIVE_OPTIONS: { value: ObjectiveMode; label: string; description: string }[] = [
  { value: 'quality_first', label: '质量优先', description: '以表面质量为核心（最小化表面粗糙度）' },
  { value: 'efficiency_first', label: '效率优先', description: '以加工效率为核心（最大化加工深度）' },
]

export const PROCESS_PARAM_LABELS: Record<string, string> = {
  groove_width_um: '槽宽 (μm)',
  groove_depth_um: '槽深 (μm)',
  hole_diameter_um: '孔径 (μm)',
  hole_depth_um: '孔深 (μm)',
  line_width_um: '线宽 (μm)',
  cut_depth_um: '切深 (μm)',
  custom_description: '任务描述',
}

export const GEOMETRY_LABELS: Record<string, string> = {
  rectangular_groove: '矩形槽',
  circular_hole: '圆孔',
  single_line: '单线',
  custom: '自定义',
}

export const PARAMETER_LABELS: Record<string, string> = {
  pulse_width_ps: '脉宽 (ps)',
  frequency_kHz: '频率 (kHz)',
  hatch_spacing_um: '填充间距 (μm)',
  passes: '加工遍数',
  scan_speed_mm_s: '扫描速度 (mm/s)',
}

export const EQUIPMENT_PARAM_LABELS: Record<string, string> = {
  wavelength_nm: '波长 (nm)',
  pulse_width_min_fs: '最小脉宽 (fs)',
  pulse_width_max_fs: '最大脉宽 (fs)',
  pulse_width_fixed_fs: '固定脉宽 (fs)',
  average_power_min_W: '平均功率下限 (W)',
  average_power_max_W: '平均功率上限 (W)',
  rated_max_power_W: '额定最大功率 (W)',
  actual_max_power_W: '实际最大功率 (W)',
  frequency_min_kHz: '最小频率 (kHz)',
  frequency_max_kHz: '最大频率 (kHz)',
  pulse_energy_max_uJ: '最大单脉冲能量 (μJ)',
  beam_quality_M2: '光束质量 M²',
  polarization: '偏振',
  objective_name: '物镜',
  objective_NA: '物镜 NA',
  focal_length_mm: '焦距 (mm)',
  spot_diameter_um: '光斑直径 (μm)',
  working_distance_mm: '工作距离 (mm)',
  beam_expander: '扩束',
  focus_control_mode: '聚焦控制',
  focus_offset_min_um: '离焦最小 (μm)',
  focus_offset_max_um: '离焦最大 (μm)',
  scan_system_type: '扫描系统',
  galvo_max_speed_mm_s: '振镜最大速度 (mm/s)',
  stage_max_speed_mm_s: '平台最大速度 (mm/s)',
  scan_speed_min_mm_s: '最小扫描速度 (mm/s)',
  scan_speed_max_mm_s: '最大扫描速度 (mm/s)',
  positioning_accuracy_um: '定位精度 (μm)',
  repeatability_um: '重复精度 (μm)',
  work_area_x_mm: '加工范围 X (mm)',
  work_area_y_mm: '加工范围 Y (mm)',
  work_area_z_mm: '加工范围 Z (mm)',
  passes_min: '最小遍数',
  passes_max: '最大遍数',
  hatch_spacing_min_um: '最小填充间距 (μm)',
  hatch_spacing_max_um: '最大填充间距 (μm)',
  layer_step_min_um: '最小层深 (μm)',
  layer_step_max_um: '最大层深 (μm)',
  laser_name: '激光器名称',
}

/** Backend values are already canonical ids; these maps only add display labels. */
export function materialLabel(id: string): string {
  return MATERIAL_LABELS[id] ?? id
}

export function laserTypeLabel(type: LaserType): string {
  return LASER_LABELS[type] ?? type
}

export function geometryLabel(id: string): string {
  return GEOMETRY_LABELS[id] ?? id
}

export function processTaskLabel(type: ProcessTaskType): string {
  return PROCESS_TASK_LABELS[type] ?? type
}

export function objectiveLabel(mode: ObjectiveMode): string {
  return OBJECTIVE_LABELS[mode] ?? mode
}

export function targetLabel(target: TargetName): string {
  return TARGET_LABELS[target] ?? target
}

export function parameterLabel(name: string): string {
  return PARAMETER_LABELS[name] ?? name
}

export function equipmentParamLabel(name: string): string {
  return EQUIPMENT_PARAM_LABELS[name] ?? name
}

export function processParamLabel(name: string): string {
  return PROCESS_PARAM_LABELS[name] ?? name
}

/** 加工目标 → 后端优化目标：质量优先 → 粗糙度最小化，效率优先 → 深度最大化 */
export function objectiveToTarget(mode: ObjectiveMode | null): TargetName | null {
  if (mode === 'quality_first') return 'roughness_um'
  if (mode === 'efficiency_first') return 'depth_um'
  return null
}

/** A formal identifier must match the canonical pattern and resolve to a known entity. */
export function isCanonicalId(kind: string, value: string | null | undefined): boolean {
  if (value === null || value === undefined || value.trim() === '') return false
  if (kind === 'material') return Object.prototype.hasOwnProperty.call(MATERIAL_LABELS, value)
  if (kind === 'laser_type') return value === 'fs' || value === 'ps'
  if (kind === 'target') return value === 'depth_um' || value === 'roughness_um'
  return /^[A-Za-z0-9_-]+$/.test(value)
}

/** Direction derived from the backend BO convention: depth is maximized, roughness minimized. */
export function targetDirection(target: TargetName): 'maximize' | 'minimize' {
  return target === 'depth_um' ? 'maximize' : 'minimize'
}

export function formatTargetGoal(target: TargetName): string {
  return target === 'depth_um' ? '深度最大化' : '粗糙度最小化'
}

