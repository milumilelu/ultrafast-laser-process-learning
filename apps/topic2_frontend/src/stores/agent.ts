/** Agent conversation store. The Agent is an enhancement layer: all statuses
 *  (Idle / Thinking / Calling Tool / Waiting Backend / Completed /
 *  Needs Confirmation / Degraded / Error) must be visible, never a bare spinner. */

import { create } from 'zustand'

import type { AgentChatResponse } from '../api/types'
import { config } from '../config'

export type AgentStatus =
  | 'idle'
  | 'thinking'
  | 'calling_tool'
  | 'waiting_backend'
  | 'completed'
  | 'needs_confirmation'
  | 'degraded'
  | 'error'

export interface AgentMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: string
  runId?: string
  toolCalls: Record<string, unknown>[]
  references: string[]
}

export interface AgentProposal {
  proposalId: string
  agentRunId: string | null
  taskContextVersion: number
  type: 'update_task' | 'select_model' | 'run_modeling' | 'run_optimization' | 'use_evidence'
  changes: Record<string, unknown>
  reasons: string[]
  status: 'pending' | 'accepted' | 'rejected'
}

export interface AgentContextState {
  status: AgentStatus
  sessionId: string | null
  degraded: boolean
  messages: AgentMessage[]
  proposals: AgentProposal[]
  lastError: string | null
  followPage: boolean
  expanded: boolean
}

interface AgentStore extends AgentContextState {
  setStatus: (status: AgentStatus) => void
  setSession: (sessionId: string | null) => void
  setDegraded: (degraded: boolean) => void
  setLastError: (error: string | null) => void
  setFollowPage: (follow: boolean) => void
  setExpanded: (expanded: boolean) => void
  addUserMessage: (content: string) => void
  addAssistantMessage: (content: string, meta: Partial<AgentMessage>) => void
  startAssistantMessage: () => string
  appendAssistantContent: (messageId: string, delta: string) => void
  finishAssistantMessage: (messageId: string, meta: Partial<AgentMessage> & { status?: AgentStatus }) => void
  addProposal: (proposal: Omit<AgentProposal, 'status'>) => AgentProposal
  resolveProposal: (proposalId: string, accepted: boolean) => void
  resetConversation: () => void
}

let messageCounter = 0
let proposalCounter = 0

function nextMessageId(): string {
  messageCounter += 1
  return `MSG-${String(messageCounter).padStart(5, '0')}`
}

export function nextProposalId(): string {
  proposalCounter += 1
  return `PROP-${String(proposalCounter).padStart(4, '0')}`
}

const initialState: AgentContextState = {
  status: 'idle',
  sessionId: null,
  degraded: false,
  messages: [],
  proposals: [],
  lastError: null,
  followPage: true,
  expanded: !config.acceptanceMode,
}

export const useAgentStore = create<AgentStore>()((set, get) => ({
  ...initialState,
  setStatus: (status) => set({ status }),
  setSession: (sessionId) => set({ sessionId }),
  setDegraded: (degraded) => set({ degraded, status: degraded ? 'degraded' : get().status }),
  setLastError: (lastError) => set({ lastError }),
  setFollowPage: (followPage) => set({ followPage }),
  setExpanded: (expanded) => set({ expanded }),
  addUserMessage: (content) =>
    set((state) => ({
      status: 'thinking',
      messages: [
        ...state.messages,
        {
          id: nextMessageId(),
          role: 'user',
          content,
          timestamp: new Date().toISOString(),
          toolCalls: [],
          references: [],
        },
      ],
    })),
  addAssistantMessage: (content, meta) =>
    set((state) => ({
      status: 'completed',
      messages: [
        ...state.messages,
        {
          id: nextMessageId(),
          role: 'assistant',
          content,
          timestamp: new Date().toISOString(),
          toolCalls: meta.toolCalls ?? [],
          references: meta.references ?? [],
          runId: meta.runId,
        },
      ],
    })),
  /** 流式：创建空 assistant 消息，返回其 id（后续 append/finish）。 */
  startAssistantMessage: () => {
    const messageId = nextMessageId()
    set((state) => ({
      status: 'thinking',
      messages: [
        ...state.messages,
        {
          id: messageId,
          role: 'assistant',
          content: '',
          timestamp: new Date().toISOString(),
          toolCalls: [],
          references: [],
        },
      ],
    }))
    return messageId
  },
  appendAssistantContent: (messageId, delta) =>
    set((state) => ({
      messages: state.messages.map((message) =>
        message.id === messageId ? { ...message, content: message.content + delta } : message,
      ),
    })),
  finishAssistantMessage: (messageId, meta) =>
    set((state) => ({
      status: meta.status ?? 'completed',
      messages: state.messages.map((message) =>
        message.id === messageId
          ? {
              ...message,
              content: meta.content !== undefined && !message.content ? meta.content : message.content,
              toolCalls: meta.toolCalls ?? message.toolCalls,
              references: meta.references ?? message.references,
              runId: meta.runId ?? message.runId,
            }
          : message,
      ),
    })),
  addProposal: (proposal) => {
    const full: AgentProposal = { ...proposal, status: 'pending' }
    set((state) => ({ proposals: [...state.proposals, full] }))
    return full
  },
  resolveProposal: (proposalId, accepted) =>
    set((state) => ({
      proposals: state.proposals.map((proposal) =>
        proposal.proposalId === proposalId
          ? { ...proposal, status: accepted ? 'accepted' : 'rejected' }
          : proposal,
      ),
    })),
  resetConversation: () =>
    set({ ...initialState, messages: [], proposals: [], sessionId: get().sessionId }),
}))

export function inferAgentStatus(response: AgentChatResponse): AgentStatus {
  if (response.blocked_stages && response.blocked_stages.length > 0) return 'needs_confirmation'
  if (response.current_stage_code && response.current_stage_code.startsWith('error')) {
    return 'error'
  }
  return 'completed'
}

export function collectReferences(response: AgentChatResponse): string[] {
  const refs = new Set<string>()
  for (const trace of response.execution_trace ?? []) {
    if (typeof trace.id === 'string') refs.add(trace.id)
    if (typeof trace.run_id === 'string') refs.add(trace.run_id)
  }
  for (const citation of response.citations ?? []) {
    if (typeof citation.document_id === 'string') refs.add(citation.document_id)
  }
  return [...refs]
}
