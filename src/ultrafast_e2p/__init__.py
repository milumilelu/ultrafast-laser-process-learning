"""E2P Core: Evidence Compilation, Applicability, Prior Compilation.

独立于 Agent / RAG / BO 的科学计算边界：

    RAG 负责发现证据（Evidence Discovery）
    E2P 负责理解证据如何影响概率模型（Evidence Compilation + Applicability + Adaptation）
    Topic2 Backend 负责确定性科学计算
    Agent 负责编排与解释

原则：EvidenceClaim 是 RAG chunk 与概率模型之间唯一正式桥梁；
semantic_role 明确区分实验条件 / 搜索范围 / 报告最优 / 推荐区间 / 观测关系；
证据不能自行决定自己是可信 Prior —— 必须经过人工审核（review_status）。
"""
