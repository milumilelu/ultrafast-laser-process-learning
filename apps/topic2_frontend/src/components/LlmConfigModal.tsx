/** LLM 配置弹窗：选择 Provider / 模型，保存 API Key（DPAPI 加密），测试连接。 */

import { useEffect, useState } from 'react'

import { agentApi } from '../api/agent'
import type { LlmConfig, LlmTestResult } from '../api/agent'
import { ErrorBanner } from './Banners'
import { StatusBadge } from './StatusBadge'

export function LlmConfigModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [config, setConfig] = useState<LlmConfig | null>(null)
  const [providers, setProviders] = useState<{ name: string; models: string[]; api_base: string }[]>([])
  const [provider, setProvider] = useState('deepseek')
  const [model, setModel] = useState('deepseek-v4-flash')
  const [apiKey, setApiKey] = useState('')
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<LlmTestResult | null>(null)

  useEffect(() => {
    agentApi
      .llmProviders()
      .then((result) => setProviders(result.providers))
      .catch((err) => setError(err instanceof Error ? err.message : '读取 Provider 列表失败'))
    agentApi
      .llmConfig()
      .then((current) => {
        setConfig(current)
        if (current.provider) setProvider(current.provider)
        if (current.model) setModel(current.model)
      })
      .catch(() => undefined)
  }, [])

  const models = providers.find((item) => item.name === provider)?.models ?? []

  const save = async () => {
    setSaving(true)
    setError(null)
    setTestResult(null)
    try {
      await agentApi.saveLlmConfig({ provider, model })
      if (apiKey.trim()) {
        const result = await agentApi.saveLlmApiKey(apiKey.trim())
        setApiKey('')
        onSaved()
        setError(`API Key 已加密保存（${result.encryption === 'dpapi' ? 'Windows DPAPI' : '明文回退'}）。`)
      } else {
        onSaved()
      }
      setConfig({ ...config, provider, model, api_key_available: Boolean(apiKey.trim()) } as LlmConfig)
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const test = async () => {
    setTesting(true)
    setError(null)
    setTestResult(null)
    try {
      // 测试连接前先把当前表单内容保存（provider/model/API Key），
      // 否则后端进程环境变量中还没有 Key，测试必然返回"配置不完整"。
      if (!model) throw new Error('请先选择模型')
      await agentApi.saveLlmConfig({ provider, model })
      if (apiKey.trim()) {
        await agentApi.saveLlmApiKey(apiKey.trim())
        setApiKey('')
      }
      setTestResult(await agentApi.testLlm())
      onSaved()
    } catch (err) {
      setError(err instanceof Error ? err.message : '测试失败')
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="modal-overlay" data-testid="llm-config-modal">
      <div className="modal">
        <h2>Agent LLM 配置</h2>
        <p className="card-sub">
          配置后 Agent 从确定性降级模式切换为真实 LLM 对话。API Key 由后端 DPAPI
          加密存储，明文永不落盘、永不返回。
        </p>

        <ErrorBanner message={error} />
        {config && (
          <div className="row" style={{ marginBottom: 12 }}>
            <StatusBadge tone={config.api_key_available ? 'ok' : 'warn'}>
              当前：{config.provider ?? '未配置'} / {config.model ?? '—'}
              {config.api_key_available ? '（Key 可用）' : '（Key 未配置）'}
            </StatusBadge>
          </div>
        )}

        <div className="grid grid-2">
          <div className="field">
            <label>Provider</label>
            <select value={provider} onChange={(event) => { setProvider(event.target.value); setModel('') }}>
              {providers.map((item) => (
                <option key={item.name} value={item.name}>{item.name}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>模型</label>
            <select value={model} onChange={(event) => setModel(event.target.value)} disabled={models.length === 0}>
              {models.length === 0 && <option value="">— 请先选择 Provider —</option>}
              {models.map((item) => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>API Key（仅写入，不回显）</label>
            <input
              type="password"
              value={apiKey}
              placeholder="sk-..."
              autoComplete="off"
              onChange={(event) => setApiKey(event.target.value)}
            />
          </div>
        </div>

        {testResult && (
          <div className="card" style={{ background: 'var(--bg)' }}>
            <div className="card-title">
              <StatusBadge tone={testResult.valid ? 'ok' : testResult.external_call_performed ? 'err' : 'warn'}>
                {testResult.valid ? '连接成功' : testResult.external_call_performed ? '连接失败' : '未执行外部验证'}
              </StatusBadge>
              <span className="card-sub" style={{ margin: 0 }}>{testResult.provider} / {testResult.model}</span>
            </div>
            {testResult.message && <div>{testResult.message}</div>}
          </div>
        )}

        <div className="row">
          <button className="btn primary" onClick={() => void save()} disabled={saving || !model}>
            {saving ? '保存中…' : '保存'}
          </button>
          <button className="btn" onClick={() => void test()} disabled={testing}>
            {testing ? '测试中…' : '测试连接'}
          </button>
          <button className="btn" onClick={onClose}>关闭</button>
        </div>
      </div>
    </div>
  )
}
