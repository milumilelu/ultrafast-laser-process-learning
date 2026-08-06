# Prior Ablation Benchmark（等预算顺序 BO 闭环）

## 协议
三臂（vanilla / correct-prior / wrong-prior）等预算独立顺序闭环：
初始 5 随机样本 → 每轮 BO 推荐 → 真函数 + 观测噪声评估 → 推荐点回填训练集。
三臂共享初始样本与噪声流（同 seed），保证公平比较。

- 真函数：`depth = 45 − 0.12|freq−20| − 0.06|speed−50| − 0.003·(pulse−1500)/1000`，最优 freq=20, speed=50
- correct prior：freq∈[15,25], speed∈[40,60]；wrong prior：freq∈[155,165], speed∈[150,170]
- 运行：`PYTHONPATH=src python benchmarks/prior_ablation/run_prior_ablation.py --budget 20 --seeds 5 --lambda-0 0.6`

## 实测结果（seeds=5, budget=20, init=5）

| λ₀ | 指标 | vanilla | correct | wrong |
|---|---|---|---|---|
| 0.2 | best-so-far / cumulative | 0.79 / 64.5 | 0.79 / 64.5 | 0.79 / 67.8 |
| 0.6 | best-so-far / cumulative | 0.79 / 64.5 | 1.19 / 66.4 | 2.16 / 78.2 |
| 1.0 | best-so-far / cumulative | 0.79 / 64.5 | 2.25 / 75.8 | 3.85 / 99.9 |

## 科学发现（三个真实问题，本 benchmark 暴露）

1. **量纲爆炸（已修复）**：原 `_smooth_range_penalty` 以 prior 区间宽度为
   分母，窄 prior（5 kHz）对远处候选产生数百量级二次惩罚，归一化后
   99.9% 候选分数坍缩为 0，prior 退化为"只惩罚最远点"；且错误 prior 的
   误导量级可压过 UCB 排序（早期 wrong regret 12.9 → 后期 21.8 恶化）。
   修复：惩罚距离按机器范围归一化（`log_prior_score(scale_by=...)`），
   prior 分数归一化到 [-1,0] 后按 λ 叠加。

2. **correct prior 无法显著提升 sample efficiency**：三个 λ 档下正确先验
   均未优于 vanilla。机制原因：惩罚型先验只压低区间外候选、对区间内
   无区分度；而正确区无观测 → GPR std 高 → UCB 探索优先权高于先验引导，
   二者对抗使先验引导要么被淹没（λ 小）要么锁定次优（λ 大，
   correct 锁 f4/v69 regret 3.0）。

3. **wrong prior 危害受控但不为零**：修复后 wrong 从灾难（cumulative 99.9
   @λ=1.0 仍是最差）变为有限代价；λ 衰减（0.2/(1+0.1n)）不足以完全抵消
   误导，因为惩罚型先验对"远离正确区"的候选持续有效。

## 结论与后续方向
- 验证了"错误 prior 不再灾难性误导、可被数据恢复"（机制成立）；
- "正确 prior 提高前期 sample efficiency"在当前惩罚型平滑先验 + UCB 组合下
  **未成立**——需要正先验（πBO 式 acquisition 内嵌先验均值）或
  prior-aware acquisition（在 UCB 中把先验均值作为虚拟观测注入 GPR）验证；
- 这是 benchmark 的首要价值：可复现地暴露机制缺口，而非掩盖。
