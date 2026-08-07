/** Agent sidebar: persistent assistant across all pages, with TaskContext /
 *  PageContext binding, status model, contextual actions and degraded mode. */

import { useCallback, useEffect, useRef, useState } from 'react'

import type { AgentChatResponse } from '../api/types'
import { agentApi, type AgentChatPayload } from '../api/agent'
import { buildAgentSystemPrefix, formatTaskContextLine } from '../lib/context'
import { agentStatusLabel } from '../lib/format'
import { applyProposalChanges } from '../lib/proposals'
import {
  collectReferences,
  inferAgentStatus,
  useAgentStore,
} from '../stores/agent'
import type { AgentProposal } from '../stores/agent'
import { usePageContextStore } from '../stores/pageContext'
import { useTaskContextStore } from '../stores/taskContext'
import { AgentProposalCard } from './AgentProposalCard'
import { LlmConfigModal } from './LlmConfigModal'
import { ScientificAnalysisProgress } from './ScientificAnalysisProgress'
import { StatusBadge } from './StatusBadge'

export type AgentQuickAction = { label: string; prompt: string }

/** 识别 Agent 服务的确定性降级回复（LLM 未配置 / Mock 路径）。 */
const DEGRADED_REPLY_MARKERS = [
  '已保存当前明确任务事实',
  '无法可靠生成下一项结构化行动',
  '本次回复不表示任务完成',
]

function isDegradedReply(response: AgentChatResponse): boolean {
  const text = response.assistant_message ?? ''
  return (
    DEGRADED_REPLY_MARKERS.some((marker) => text.includes(marker)) &&
    (response.tool_calls ?? []).length === 0
  )
}

export function AgentSidebar() {
  const {
    status,
    sessionId,
    degraded,
    messages,
    proposals,
    lastError,
    followPage,
    expanded,
    setStatus,
    setSession,
    setDegraded,
    setLastError,
    setFollowPage,
    setExpanded,
    addUserMessage,
    addAssistantMessage,
    startAssistantMessage,
    appendAssistantContent,
    finishAssistantMessage,
    resolveProposal,
  } = useAgentStore()

  const context = useTaskContextStore((state) => state.context)
  const page = usePageContextStore((state) => state.page)
  const activeRunId = usePageContextStore((state) => state.activeRunId)
  const activeModelId = usePageContextStore((state) => state.activeModelId)
  const quickActions = usePageContextStore((state) => state.quickActions)

  const [draft, setDraft] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, status])

  const checkHealth = useCallback(async () => {
    setLastError(null)
    try {
      await agentApi.health()
      // LLM 未配置时 Agent 只能走确定性降级回复：状态标记为降级而非已完成。
      const config = await agentApi.llmConfig().catch(() => null)
      if (config && config.api_key_available === false) {
        setDegraded(true)
        setLastError('LLM 未配置（DEEPSEEK_API_KEY 缺失），Agent 使用确定性降级模式。')
      } else {
        setDegraded(false)
        setLastError(null)
      }
    } catch {
      setDegraded(true)
    }
  }, [setDegraded, setLastError])

  useEffect(() => {
    let cancelled = false
    agentApi
      .health()
      .then(async () => {
        if (cancelled) return
        const config = await agentApi.llmConfig().catch(() => null)
        if (cancelled) return
        if (config && config.api_key_available === false) {
          setDegraded(true)
          setLastError('LLM 未配置（DEEPSEEK_API_KEY 缺失），Agent 使用确定性降级模式。')
        } else {
          setDegraded(false)
          setLastError(null)
        }
      })
      .catch(() => {
        if (!cancelled) setDegraded(true)
      })
    return () => {
      cancelled = true
    }
  }, [setDegraded, setLastError])

  const sendMessage = useCallback(
    async (rawText: string) => {
      const text = rawText.trim()
      if (!text) return
      const prefix = buildAgentSystemPrefix(context, page, activeRunId, activeModelId)
      addUserMessage(text)
      setDraft('')
      setLastError(null)

      let session = sessionId
      try {
        if (!session) {
          const created = await agentApi.createSession()
          session = created.session_id
          setSession(session)
        }
        // 幂等键：stream 中断 fallback 时复用同一 client_message_id，
        // 后端检测到已执行则返回原结果，绝不重复执行 scientific workflow。
        const clientMessageId = crypto.randomUUID()
        const payload: AgentChatPayload = {
          session_id: session,
          message: `${prefix}\n\n用户：${text}`,
          mode: 'agent',
          stream: true,
          client_message_id: clientMessageId,
        }
        // 流式优先：delta 增量渲染 + 事件状态；流式不可用时回退普通 /chat。
        const messageId = startAssistantMessage()
        let streamFailed = false
        await agentApi.streamChat(
          payload,
          {
            onEvent: (event) => {
              if (event.type === 'delta' && typeof event.content === 'string') {
                appendAssistantContent(messageId, event.content)
                setStatus('thinking')
              } else if (event.type === 'tool_call' || event.event_type === 'tool_call_started') {
                setStatus('calling_tool')
              } else if (event.type === 'progress') {
                setStatus('waiting_backend')
              } else if (event.type === 'error') {
                streamFailed = true
                setStatus('error')
                setLastError(String(event.summary ?? event.content ?? 'Agent 执行错误'))
              }
            },
            onDone: () => {
              setStatus('completed')
            },
            onError: (error) => {
              streamFailed = true
              setLastError(error)
            },
          },
          180_000,
        )
        if (streamFailed) {
          // 流式中断：回退普通请求补全当前消息
          const response = await agentApi.chat({ ...payload, stream: false })
          if (isDegradedReply(response)) {
            setDegraded(true)
            setStatus('degraded')
          } else {
            setStatus(inferAgentStatus(response))
          }
          finishAssistantMessage(messageId, {
            content: response.assistant_message,
            toolCalls: response.tool_calls ?? [],
            references: collectReferences(response),
          })
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : '未知错误'
        setDegraded(true)
        setLastError(message)
        addAssistantMessage(
          'Agent 服务当前不可用，已切换至标准科学计算模式。您可以继续使用参数辨识、建模、优化等全部正式功能。',
          {},
        )
      }
    },
    [
      context,
      page,
      activeRunId,
      activeModelId,
      sessionId,
      addUserMessage,
      setDraft,
      setLastError,
      setSession,
      setStatus,
      setDegraded,
      startAssistantMessage,
      appendAssistantContent,
      finishAssistantMessage,
      addAssistantMessage,
    ],
  )

  const applyProposal = useCallback(
    (proposal: AgentProposal, accepted = true) => {
      resolveProposal(proposal.proposalId, accepted)
      if (!accepted) {
        addAssistantMessage(`已取消建议 ${proposal.proposalId}。`, {})
        return
      }
      const applied = applyProposalChanges(proposal)
      const next = useTaskContextStore.getState().context
      addAssistantMessage(
        applied
          ? `已应用建议 ${proposal.proposalId}，Task Context 为 ${next.taskContextId}:v${next.version}（建议内容已进入审计追溯）。`
          : `建议 ${proposal.proposalId} 已记录：该动作需要您在对应页面上手动执行。`,
        {},
      )
    },
    [resolveProposal, addAssistantMessage],
  )

  const statusTone = (): 'ok' | 'warn' | 'err' | 'neutral' => {
    if (status === 'error' || status === 'degraded') return 'err'
    if (status === 'thinking' || status === 'calling_tool' || status === 'waiting_backend') return 'warn'
    return 'ok'
  }

  const pendingProposals = proposals.filter((proposal) => proposal.status === 'pending')
  const [showLlmConfig, setShowLlmConfig] = useState(false)

  return (
    <aside className={`agent-panel ${expanded ? '' : 'collapsed'}`} data-testid="agent-sidebar">
      {expanded ? (
        <>
          <div className="agent-header">
            <span className="agent-title">超快激光 Agent</span>
            <StatusBadge tone={statusTone()}>{agentStatusLabel(status)}</StatusBadge>
            <button
              className="btn small"
              title="配置 LLM（Provider / 模型 / API Key）"
              onClick={() => setShowLlmConfig(true)}
            >
              配置
            </button>
            <button className="btn small" title="跟随当前页面" onClick={() => setFollowPage(!followPage)}>
              {followPage ? '✓ 跟随页面' : '跟随页面'}
            </button>
            <button className="btn small" onClick={() => setExpanded(false)} title="折叠">
              »
            </button>
          </div>

          {showLlmConfig && (
            <LlmConfigModal
              onClose={() => setShowLlmConfig(false)}
              onSaved={() => void checkHealth()}
            />
          )}

          <div className="agent-context-box">
            <div className="ctx-line">
              <b>当前任务：</b>
              {context.taskContextId}:v{context.version}
            </div>
            <div className="ctx-line" title={formatTaskContextLine(context)}>
              {formatTaskContextLine(context)}
            </div>
          </div>

          {degraded && (
            <div className="warn-banner" style={{ margin: 8 }}>
              <span>
                {lastError
                  ? lastError
                  : 'Agent 当前不可用，已切换至标准科学计算模式。'}
              </span>
              <button className="btn small" onClick={() => void checkHealth()}>
                重新检测
              </button>
            </div>
          )}

          <ScientificAnalysisProgress />
          {lastError && status === 'error' && (
            <div className="error-banner" style={{ margin: 8 }}>
              {lastError}
            </div>
          )}

          <div className="agent-messages">
            {messages.length === 0 && (
              <div className="empty-state">向 Agent 提问，或使用页面快捷动作。</div>
            )}
            {messages.map((message) => (
              <div key={message.id} className={`agent-msg ${message.role}`} data-testid="agent-message">
                {message.content}
                {message.references.length > 0 && (
                  <div className="msg-meta">
                    引用：{message.references.map((ref) => (
                      <span className="id-chip muted" key={ref}>
                        {ref}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {pendingProposals.map((proposal) => (
              <AgentProposalCard key={proposal.proposalId} proposal={proposal} onApply={applyProposal} />
            ))}
            {(status === 'thinking' || status === 'calling_tool' || status === 'waiting_backend') && (
              <div className="agent-msg status">
                <span className="spinner" /> {agentStatusLabel(status)}
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {quickActions.length > 0 && (
            <div className="agent-actions">
              {quickActions.map((action) => (
                <button key={action.label} className="btn small" onClick={() => void sendMessage(action.prompt)}>
                  {action.label}
                </button>
              ))}
            </div>
          )}

          <div className="agent-input">
            <textarea
              value={draft}
              placeholder="向 Agent 提问（Agent 为增强层，不影响科学计算）…"
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  void sendMessage(draft)
                }
              }}
            />
            <button className="btn primary" disabled={!draft.trim()} onClick={() => void sendMessage(draft)}>
              发送
            </button>
          </div>
        </>
      ) : (
        <div className="agent-side-rail">
          <button className="btn small" onClick={() => setExpanded(true)} title="展开 Agent 面板">
            «
          </button>
          <StatusBadge tone={statusTone()}>{agentStatusLabel(status).slice(0, 2)}</StatusBadge>
        </div>
      )}
    </aside>
  )
}
