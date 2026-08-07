/** Ultrafast Laser Agent adapter. The agent is an enhancement layer; its absence must not block Topic2 flows. */

import { config } from '../config'
import { request } from './client'
import type {
  AgentChatResponse,
  AgentSession,
  EquipmentProfile,
  EquipmentProfileBase,
  EquipmentProfileCreate,
  EquipmentProfileCreated,
  MachineBoundsResponse,
} from './types'

export interface AgentChatPayload {
  session_id?: string | null
  message: string
  mode: string
  stream: boolean
  /** 幂等键：同一 client_message_id 后端只执行一次（stream 中断 fallback 防重复执行）。 */
  client_message_id?: string | null
}

/** /chat/stream_ndjson 统一事件（normalize 后由后端保证形状）。 */
export interface StreamChatEvent {
  type: string
  event_type?: string
  event_id?: string
  sequence?: number
  stage?: string
  status?: string
  title?: string
  summary?: string
  content?: string
  [key: string]: unknown
}

export interface StreamChatHandlers {
  onEvent: (event: StreamChatEvent) => void
  onDone: () => void
  onError: (error: string) => void
}

export interface LlmConfig {
  provider: string | null
  model: string | null
  api_base: string | null
  api_key_env: string | null
  api_key_available: boolean
}

export interface LlmProviderInfo {
  providers: { name: string; models: string[]; api_base: string }[]
}

export interface LlmTestResult {
  configured: boolean
  provider: string | null
  model: string | null
  api_key_available: boolean
  external_call_performed: boolean
  valid: boolean
  message: string | null
}

export const agentApi = {
  health(): Promise<{ status: string; api_version: string }> {
    return request(config.agentApiUrl, 'GET', '/health')
  },

  llmConfig(): Promise<LlmConfig> {
    return request(config.agentApiUrl, 'GET', '/llm/config')
  },

  llmProviders(): Promise<LlmProviderInfo> {
    return request(config.agentApiUrl, 'GET', '/llm/providers')
  },

  saveLlmConfig(payload: {
    provider: string
    model: string
    api_base?: string | null
    api_key_env?: string | null
  }): Promise<{ saved: boolean; provider: string; model: string }> {
    return request(config.agentApiUrl, 'POST', '/llm/config', payload)
  },

  saveLlmApiKey(apiKey: string): Promise<{
    saved: boolean
    encryption: string
    api_key_available: boolean
  }> {
    return request(config.agentApiUrl, 'POST', '/llm/api-key', { api_key: apiKey })
  },

  testLlm(): Promise<LlmTestResult> {
    return request(config.agentApiUrl, 'POST', '/llm/test', {}, { timeoutMs: 60_000 })
  },

  /** RAG → Topic2 Evidence[]：按任务 scope 检索并把已审核文献数值编译为证据。 */
  evidenceCandidates(payload: {
    task_scope: {
      material: string | null
      laser_type: string | null
      geometry_type: string | null
      equipment_id: string | null
      target: string | null
    }
    query?: string | null
    top_k?: number
    include_unreviewed_candidates?: boolean
  }): Promise<{
    evidence: Record<string, unknown>[]
    retrieved_hits: number
    reviewed_hits: number
    evidence_status: string
  }> {
    return request(config.agentApiUrl, 'POST', '/e2p/evidence-candidates', payload, {
      timeoutMs: 120_000,
    })
  },

  /** 科学检索：按任务 scope 构建 EvidenceCorpusPack（多意图 + 论文内上下文扩展）。 */
  buildCorpus(payload: {
    task_scope: {
      material: string | null
      laser_type: string | null
      geometry_type: string | null
      process_type?: string | null
      equipment_id?: string | null
      target: string | null
    }
    task_context_id?: string
    task_context_version?: number
    retrieval_intents?: string[]
  }): Promise<Record<string, unknown>> {
    return request(config.agentApiUrl, 'POST', '/api/v1/scientific-retrieval/build-corpus', payload, {
      timeoutMs: 120_000,
    })
  },

  /** 科学精读：CorpusPack → ScientificKnowledgePack（强制真实 LLM，无 mock 降级）。 */
  analyzeCorpus(payload: {
    corpus_pack: Record<string, unknown>
  }): Promise<Record<string, unknown>> {
    return request(config.agentApiUrl, 'POST', '/api/v1/scientific-analysis/analyze', payload, {
      timeoutMs: 300_000,
    })
  },

  /** 异步科学分析 Job：RAG 检索 → Map → Reduce → Selective Critic，实时进度。 */
  createAnalysisJob(payload: {
    task_scope: Record<string, unknown>
    retrieval_intents?: string[]
    level?: string
  }): Promise<{ analysis_run_id: string; status: string; stage: string }> {
    return request(config.agentApiUrl, 'POST', '/api/v1/scientific-analysis/jobs', payload, {
      timeoutMs: 30_000,
    })
  },

  getAnalysisJob(jobId: string): Promise<{
    analysis_run_id: string
    status: string
    stage: string
    progress: Record<string, unknown>
    detail: { stage: string; [key: string]: unknown }[]
    result: Record<string, unknown> | null
    error: string | null
  }> {
    return request(config.agentApiUrl, 'GET', `/api/v1/scientific-analysis/jobs/${jobId}`, {
      timeoutMs: 30_000,
    })
  },

  /** 科学分析 Run Trace：task→job→corpus→knowledge→pipeline 统计。 */
  listAnalysisRuns(): Promise<{
    items: {
      run_id: string
      task_id: string | null
      job_id: string | null
      corpus_pack_id: string | null
      knowledge_pack_id: string | null
      pipeline_stats: Record<string, unknown>
      status: string
      created_at: string
    }[]
  }> {
    return request(config.agentApiUrl, 'GET', '/api/v1/scientific-analysis/runs', {
      timeoutMs: 30_000,
    })
  },

  /** 确定性验证：Schema/单位/来源/陷阱四重校验。 */
  validateKnowledge(payload: {
    knowledge_pack: Record<string, unknown>
  }): Promise<{
    validated_candidates: string[]
    rejected_candidates: string[]
    issues: { candidate_id: string; code: string; message: string; severity: string }[]
  }> {
    return request(config.agentApiUrl, 'POST', '/api/v1/scientific-analysis/validate', payload, {
      timeoutMs: 60_000,
    })
  },

  /** 参数辨识 V2：raw / physics / hybrid 三模式 + 双排名输出。 */
  runIdentificationV2(payload: {
    rows: Record<string, unknown>[]
    target: string
    mode: 'raw' | 'physics' | 'hybrid'
    device_properties?: Record<
      string,
      { value: number; unit: string }
    >
  }): Promise<Record<string, unknown>> {
    return request(config.agentApiUrl, 'POST', '/api/v1/scientific/identification-v2', payload, {
      timeoutMs: 120_000,
    })
  },

  createSession(title?: string): Promise<AgentSession> {
    return request(config.agentApiUrl, 'POST', '/chat/sessions', {
      title: title ?? '超快激光工艺智能工作台',
      mode: 'agent',
    })
  },

  chat(payload: AgentChatPayload): Promise<AgentChatResponse> {
    return request(config.agentApiUrl, 'POST', '/chat', payload, { timeoutMs: 120_000 })
  },

  /** NDJSON 流式聊天：逐行消费统一事件（delta/thinking_status/tool/progress/done）。 */
  async streamChat(
    payload: AgentChatPayload,
    handlers: StreamChatHandlers,
    timeoutMs = 120_000,
  ): Promise<void> {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    try {
      const response = await fetch(`${config.agentApiUrl}/chat/stream_ndjson`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...payload, stream: true }),
        signal: controller.signal,
      })
      if (!response.ok) {
        let detail = `HTTP ${response.status}`
        try {
          const body = (await response.json()) as { detail?: { message?: string } }
          if (body.detail?.message) detail = body.detail.message
        } catch {
          /* 非 JSON 错误体，保留状态码 */
        }
        throw new Error(detail)
      }
      const reader = response.body?.getReader()
      if (!reader) throw new Error('stream body unavailable')
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed) continue
          let event: StreamChatEvent
          try {
            event = JSON.parse(trimmed) as StreamChatEvent
          } catch {
            continue
          }
          if (event.type === 'done') {
            handlers.onDone()
            return
          }
          handlers.onEvent(event)
        }
      }
      if (buffer.trim()) {
        try {
          const event = JSON.parse(buffer.trim()) as StreamChatEvent
          if (event.type === 'done') {
            handlers.onDone()
            return
          }
          handlers.onEvent(event)
        } catch {
          /* 尾部残片忽略 */
        }
      }
      handlers.onDone()
    } catch (error) {
      handlers.onError(error instanceof Error ? error.message : '流式请求失败')
    } finally {
      clearTimeout(timer)
    }
  },

  listEquipmentProfiles(): Promise<EquipmentProfileBase[]> {
    return request(config.agentApiUrl, 'GET', '/equipment/profiles')
  },

  getEquipmentProfile(id: string): Promise<EquipmentProfile> {
    return request(config.agentApiUrl, 'GET', `/equipment/profiles/${id}`)
  },

  createEquipmentProfile(payload: EquipmentProfileCreate): Promise<EquipmentProfileCreated> {
    return request(config.agentApiUrl, 'POST', '/equipment/profiles', payload)
  },

  activateEquipmentProfile(id: string): Promise<{ equipment_profile_id: string; is_active: boolean }> {
    return request(config.agentApiUrl, 'POST', `/equipment/profiles/${id}/activate`)
  },

  machineBounds(): Promise<MachineBoundsResponse> {
    return request(config.agentApiUrl, 'GET', '/equipment/active/machine-bounds')
  },

  profileMachineBounds(profileId: string): Promise<MachineBoundsResponse> {
    return request(
      config.agentApiUrl,
      'GET',
      `/equipment/profiles/${encodeURIComponent(profileId)}/machine-bounds`,
    )
  },
}
