/** 科学分析 Job 轮询单例（UI：工艺任务分析面板 + Agent Drawer 共用同一轮询）。
 *  同一 jobId 只存在一个轮询循环；完成/失败后停止。
 *
 *  轮询状态完全透明：每次成功更新记录 lastUpdatedAt；中断时记录连续失败次数
 *  pollAttempts 与原始错误 lastPollError（HTTP 状态/网络原因），界面据此展示
 *  「最后成功更新 HH:mm:ss · 已重试 N 次」而非猜测性文案。
 */

import { agentApi } from '../api/agent'
import { candidatesToEvidence } from '../lib/candidatesToEvidence'
import { useScienceStore } from './science'

let activeJobId: string | null = null
let timer: number | null = null
let failures = 0

/** 启动（或复用）指定 job 的全局轮询；同一 jobId 幂等。 */
export function ensureAnalysisPolling(jobId: string): void {
  if (activeJobId === jobId) return
  if (timer !== null) {
    window.clearTimeout(timer)
    timer = null
  }
  activeJobId = jobId
  failures = 0
  void poll(jobId)
}

/** 立即手动重试一次轮询（界面按钮），并重置失败计数。 */
export function retryPollingNow(jobId: string): void {
  if (activeJobId !== jobId) {
    activeJobId = jobId
  }
  failures = 0
  if (timer !== null) {
    window.clearTimeout(timer)
    timer = null
  }
  void poll(jobId)
}

/** 停止轮询（页面卸载时调用；job 完成时自动停止）。 */
export function stopAnalysisPolling(): void {
  if (timer !== null) {
    window.clearTimeout(timer)
    timer = null
  }
  activeJobId = null
}

function errorDetail(error: unknown): string {
  if (error instanceof Error) {
    const message = error.message
    if (message.includes('超时')) return `请求超时（${message}）`
    if (message.startsWith('HTTP')) return `后端返回 ${message}`
    return message
  }
  return String(error)
}

async function poll(jobId: string): Promise<void> {
  if (activeJobId !== jobId) return
  const store = useScienceStore.getState()
  try {
    const job = await agentApi.getAnalysisJob(jobId)
    if (activeJobId !== jobId) return
    failures = 0
    const finished = job.status === 'completed' || job.status === 'failed'
    store.setAnalysisJob(
      {
        jobId: job.analysis_run_id,
        status: job.status,
        stage: job.stage,
        progress: job.progress,
        detail: job.detail,
        error: job.error,
        lastUpdatedAt: new Date().toISOString(),
        pollAttempts: 0,
        lastPollError: null,
      },
      !finished,
    )
    if (job.status === 'completed' && job.result) {
      const knowledge = job.result as Record<string, unknown>
      store.setScientificPack({
        corpus: null,
        knowledge,
        validation: null,
        degraded: false,
        llmModel: String(knowledge.llm_model ?? 'unknown'),
      })
      const taskScope = (job.result.task_scope ?? {}) as Record<string, unknown>
      const converted = candidatesToEvidence(knowledge, {
        material: (taskScope.material as string | null) ?? null,
        laser_type: (taskScope.laser_type as string | null) ?? null,
        geometry_type: (taskScope.geometry_type as string | null) ?? null,
        equipment_id: (taskScope.equipment_id as string | null) ?? null,
        target: (taskScope.target as string | null) ?? null,
      })
      if (converted.length > 0) {
        store.setRagEvidence(converted, {
          retrievedHits: converted.length,
          reviewedHits: converted.length,
          evidenceStatus: 'scientific_analysis',
        })
      }
      activeJobId = null
      return
    }
    if (job.status === 'failed') {
      activeJobId = null
      return
    }
    timer = window.setTimeout(() => void poll(jobId), 3000)
  } catch (error) {
    if (activeJobId !== jobId) return
    failures += 1
    const current = useScienceStore.getState().analysisJob
    if (current) {
      store.setAnalysisJob(
        {
          ...current,
          pollAttempts: failures,
          lastPollError: errorDetail(error),
          error: null,
        },
        true,
      )
    }
    // 中断不停止：指数退避 3s → 10s → 30s，持续自动重试
    const delay = failures <= 1 ? 3000 : failures <= 3 ? 10_000 : 30_000
    timer = window.setTimeout(() => void poll(jobId), delay)
  }
}
