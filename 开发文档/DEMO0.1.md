但有一点需要调整：`CFA`、`EvidenceIR`、`SourceCondition` 实际不是严格单线关系。更合理的是 EvidenceIR 引用 source condition，然后做 applicability。第一版不必把对象关系做得过于复杂，只要 provenance/reference 保留即可。





现有 Demo 虽然计算了 physics features，但 `_hybrid_frame()` 实际仍返回原始五列，因此当前：

```
RAW == HYBRID training matrix
```

不要为了 V0 强行修所有 Physics features。

第一版明确：

```
Baseline Process Learning
= RAW
+ 已经确定可计算且已验证的 physics（没有就不加）
```

甚至第一轮只做 RAW 完全可以。

等 workflow 跑通后，再真正实现：

```
RAW
PHYSICS
HYBRID
```

这样不会让假的 HYBRID 进入科研结论。





