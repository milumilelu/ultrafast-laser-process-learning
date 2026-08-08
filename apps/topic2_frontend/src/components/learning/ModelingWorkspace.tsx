/** ModelingWorkspace (UI-4): E2P Model Policy → 多模型训练比较 → 系统推荐 /
 *  人工覆盖（Proposal 记录）。新增 ModelDecisionCard 与选择理由展示。 */

import { useCallback, useEffect } from 'react'

import { topic2Api } from '../../api/topic2'
import type { ModelTrainingResult } from '../../api/types'
import { ErrorBanner, EmptyState } from '../../components/Banners'
import { friendlyApiError } from '../../lib/errors'
import { DataProfileCard } from '../../components/DataProfileCard'
import { EvidencePanel } from '../../components/EvidencePanel'
import { ModelComparisonTable } from '../../components/ModelComparisonTable'
import { ScientificEvidencePanel } from '../../components/ScientificEvidencePanel'
import { StatusBadge } from '../../components/StatusBadge'
import { taskContextToScope } from '../../lib/scope'
import { useScopeExperiments } from '../../lib/scopeData'
import { nextProposalId, useAgentStore } from '../../stores/agent'
import { usePageContextStore } from '../../stores/pageContext'
import { useScienceStore } from '../../stores/science'
import { useTaskContextStore } from '../../stores/taskContext'
import { ModelDecisionCard } from './ModelDecisionCard'

export function ModelingWorkspace({
  readonly = false,
  trainingOverride = null,
}: {
  readonly?: boolean
  /** ApplicationRun 的建模结果（processLearning.modelComparison），存在时优先展示 */
  trainingOverride?: ModelTrainingResult | null
}) {
  const context = useTaskContextStore((state) => state.context)
  const updateTask = useTaskContextStore((state) => state.update)
  const setActiveRun = usePageContextStore((state) => state.setActiveRun)
  const setActiveModel = usePageContextStore((state) => state.setActiveModel)
  const setQuickActions = usePageContextStore((state) => state.setQuickActions)
  const addProposal = useAgentStore((state) => state.addProposal)
  const {
    modelPolicy,
    modelPolicyLoading,
    modelPolicyError,
    training,
    trainingLoading,
    trainingError,
    evidence,
    evidenceLoading,
    evidenceError,
    dataProfile,
    selectedModelId,
    selectionMode,
    ragEvidence,
    ragEvidenceMeta,
    ragEvidenceError,
    scientificPack,
    scientificLoading,
    scientificError,
    setModelPolicy,
    setTraining,
    setEvidence,
    setSelection,
  } = useScienceStore()
  const { gates, loading } = useScopeExperiments()

  const compileEvidence = useCallback(() => {
    let scope
    try {
      scope = taskContextToScope(context)
    } catch (error) {
      setEvidence(null, error instanceof Error ? error.message : '任务不完整')
      return
    }
    setEvidence(null, null, true)
    topic2Api
      .compileEvidence(scope, ragEvidence)
      .then((result) => setEvidence(result))
      .catch((error) =>
        setEvidence(null, friendlyApiError(error)),
      )
  }, [context, ragEvidence, setEvidence])

  const runPolicy = useCallback(() => {
    let scope
    try {
      scope = taskContextToScope(context)
    } catch (error) {
      setModelPolicy(null, error instanceof Error ? error.message : '任务不完整')
      return
    }
    if (!dataProfile) {
      setModelPolicy(null, '请先在工艺数据库或本页加载实验数据以生成 DataProfile。')
      return
    }
    setModelPolicy(null, null, true)
    topic2Api
      .modelPolicy({ scope, data_profile: dataProfile, evidence: ragEvidence })
      .then((result) => {
        setModelPolicy(result)
        setActiveRun(result.run_id)
      })
      .catch((error) =>
        setModelPolicy(null, friendlyApiError(error)),
      )
  }, [context, dataProfile, ragEvidence, setModelPolicy, setActiveRun])

  const runTraining = useCallback(() => {
    let scope
    try {
      scope = taskContextToScope(context)
    } catch (error) {
      setTraining(null, error instanceof Error ? error.message : '任务不完整')
      return
    }
    setTraining(null, null, true)
    topic2Api
      .trainModels(
        scope,
        modelPolicy?.candidate_models ?? null,
        modelPolicy?.run_id ?? null,
      )
      .then((result) => {
        setTraining(result)
        setActiveRun(result.run_id)
        setSelection(result.selected_model, 'system')
        if (result.model_id) {
          setActiveModel(result.model_id)
          updateTask({ selectedModelId: result.model_id })
        }
      })
      .catch((error) =>
        setTraining(null, friendlyApiError(error)),
      )
  }, [context, modelPolicy, setTraining, setActiveRun, setActiveModel, setSelection, updateTask])

  const handleManualSelect = useCallback(
    (modelName: string) => {
      if (!training) return
      addProposal({
        proposalId: nextProposalId(),
        agentRunId: null,
        taskContextVersion: context.version,
        type: 'select_model',
        changes: {
          model_name: modelName,
          selection_mode: 'manual',
        },
        reasons: [
          `人工覆盖系统推荐模型（${training.selected_model}）为 ${modelName}。该操作将被记录并进入审计追溯。`,
        ],
      })
    },
    [training, addProposal, context.version],
  )

  useEffect(() => {
    if (training) {
      setQuickActions([
        {
          label: '为什么推荐这个模型？',
          prompt: `请解释 run_id=${training.run_id} 中为什么推荐 ${training.selected_model}？`,
        },
        {
          label: '比较 GP 与 RF',
          prompt: `请比较 run_id=${training.run_id} 中 GPR 与 RandomForest 的验证指标差异。`,
        },
        { label: '解释 Evidence 适用性', prompt: '请解释当前任务的 Evidence 适用性状态。' },
      ])
    } else {
      setQuickActions([])
    }
    return () => setQuickActions([])
  }, [training, setQuickActions])

  // 应用运行结果优先：完整分析已执行时直接展示正式训练比较
  const displayedTraining = trainingOverride ?? training

  return (
    <div>
      <p className="card-sub">
        依据当前 Task Context（{context.taskContextId}:v{context.version}）。模型策略由 E2P
        Service 判定，模型性能由 Topic2 Backend 以 Group-CV 计算，系统推荐仅依据 RMSE/MAE。
      </p>

      <ErrorBanner message={modelPolicyError ?? trainingError ?? evidenceError ?? ragEvidenceError} />

      <div className="row" style={{ marginBottom: 16 }}>
        <button className="btn" onClick={compileEvidence} disabled={evidenceLoading || readonly}>
          {evidenceLoading ? (
            <>
              <span className="spinner" /> 编译中…
            </>
          ) : (
            '编译 Evidence'
          )}
        </button>
        <button className="btn" onClick={runPolicy} disabled={modelPolicyLoading || loading || !gates?.modeling || readonly}>
          {modelPolicyLoading ? (
            <>
              <span className="spinner" /> 计算中…
            </>
          ) : (
            '获取 E2P Model Policy'
          )}
        </button>
        <button
          className="btn primary"
          onClick={runTraining}
          disabled={trainingLoading || loading || !gates?.modeling || readonly}
          title={gates?.modeling ? undefined : '当前 scope 数据不足（建模需 ≥2 独立设计）'}
        >
          {trainingLoading ? (
            <>
              <span className="spinner" /> Backend 训练中…
            </>
          ) : (
            '训练并比较模型'
          )}
        </button>
        <StatusBadge tone={gates?.modeling ? 'ok' : 'warn'}>
          当前 scope 数据：{dataProfile ? `${dataProfile.n_samples} 样本 / ${dataProfile.n_unique_designs} 设计` : '—'}
        </StatusBadge>
        {ragEvidenceMeta && (
          <StatusBadge tone={ragEvidence.length > 0 ? 'ok' : 'warn'}>
            RAG 证据：{ragEvidence.length} 条已编译（检索 {ragEvidenceMeta.retrievedHits} / 审核通过 {ragEvidenceMeta.reviewedHits}）
          </StatusBadge>
        )}
      </div>

      {displayedTraining && (
        <>
          <ModelDecisionCard
            selectedModel={displayedTraining.selected_model}
            metrics={
              displayedTraining.selected_model
                ? displayedTraining.validation_metrics[displayedTraining.selected_model]
                : null
            }
            cvFolds={
              displayedTraining.selected_model
                ? displayedTraining.validation_metrics[displayedTraining.selected_model]?.cv_folds
                : undefined
            }
            cvStrategy={displayedTraining.cv_strategy}
          />
          {trainingOverride && (
            <div className="row" style={{ marginBottom: 8 }}>
              <span className="badge ok">应用运行正式结果（ApplicationRun）</span>
            </div>
          )}
        </>
      )}

      <div className="card">
        <div className="card-title">
          E2P Evidence 状态
          {evidence && <span className="badge info">编译版本 {evidence.version}</span>}
        </div>
        {evidence ? (
          <EvidencePanel evidence={evidence} />
        ) : (
          <EmptyState message="尚未编译 Evidence。证据由 RAG / Agent 检索提供，前端不虚构 Evidence。" />
        )}
      </div>

      <ScientificEvidencePanel pack={scientificPack} loading={scientificLoading} error={scientificError} />

      {dataProfile && (
        <div className="card">
          <div className="card-title">DataProfile（供 Model Policy 使用）</div>
          <DataProfileCard profile={dataProfile} />
        </div>
      )}

      {modelPolicy && (
        <div className="card">
          <div className="card-title">
            E2P Model Policy
            <span className="id-chip">{modelPolicy.run_id}</span>
            <span className="badge neutral">{modelPolicy.model_policy_version}</span>
          </div>
          <div className="row" style={{ marginBottom: 12 }}>
            <StatusBadge tone="info">
              优先模型：{modelPolicy.preferred_models.join(' → ')}
            </StatusBadge>
            <StatusBadge tone="neutral">
              不确定性要求：{modelPolicy.requirements.uncertainty_required ? '必需' : '非必需'}
            </StatusBadge>
          </div>
          <ul className="detail-list">
            <li>
              <span className="dl-key">reason_codes</span>
              <span className="dl-value mono">{modelPolicy.reason_codes.join(', ')}</span>
            </li>
            <li>
              <span className="dl-key">final_selection_rule</span>
              <span className="dl-value">{modelPolicy.final_selection_rule}</span>
            </li>
          </ul>
        </div>
      )}

      {displayedTraining && (
        <div className="card">
          <div className="card-title">
            模型比较
            <span className="id-chip">{displayedTraining.run_id}</span>
            <span className="badge neutral">数据集 {displayedTraining.dataset_version}</span>
            {selectionMode === 'manual' && <span className="badge warn">人工覆盖已记录</span>}
          </div>
          <ModelComparisonTable
            training={displayedTraining}
            onSelect={trainingOverride ? () => undefined : handleManualSelect}
          />
          {selectionMode === 'system' && selectedModelId && (
            <div style={{ marginTop: 8 }}>
              <StatusBadge tone="ok">系统推荐模型已应用：{displayedTraining.selected_model}</StatusBadge>
            </div>
          )}
        </div>
      )}

      {!displayedTraining && !trainingLoading && !trainingError && (
        <EmptyState message="尚未训练模型。完成后将展示多模型比较表与系统推荐。" />
      )}
    </div>
  )
}

