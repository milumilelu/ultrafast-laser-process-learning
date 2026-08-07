"""Literature Metadata Extraction 评测器（stdlib only）。

用法：
  python scripts/evaluate_extraction.py --gold gold/annotations.jsonl --pred <predictions.jsonl>
  python scripts/evaluate_extraction.py --schema-check <file.jsonl>

指标定义见 benchmarks/literature_metadata/README.md。

方法学约定（2026-08-05 v2）：
1. material 的 FP 无条件统计：gold 材料为空（非激光/abstain）时模型乱报材料计入 FP，
   并单独报告 material_fp_on_abstain_papers（乱报率）。
2. process/laser/grade accuracy 的分母 = 该字段 gold 非空的全样本；模型 abstain 按错（miss）计，
   不允许通过排除 abstain 样本虚高 accuracy。
3. 每个核心字段独立报告 abstention recall/precision。
4. 比例指标输出 Wilson 95% CI。
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

MATERIAL_ROLES = {
    "primary_workpiece", "substrate", "coating", "reinforcement",
    "comparison_material", "tool_material", "background_only",
}
PROCESS_ROLES = {"primary_process", "pretreatment", "postprocess", "comparison_process", "background_only"}
CORE_FIELDS = ("primary_material", "material_grade", "primary_process", "laser_type", "wavelength_nm")
# evidence-page 只允许 primary 语义角色命中（防止规则候选 mention 蹭中）
EVIDENCE_PAGE_ROLES = {"primary_workpiece", "substrate", "coating", "reinforcement"}
WAVELENGTH_TOLERANCE_NM = 2.0
PULSE_WIDTH_REL_TOLERANCE = 0.05
Z = 1.96

# 显式 ontology hierarchy（副指标用，不影响 strict 指标）。
# 声明：这些是"标注实践中观察到的层级/组成关系"的显式映射，可审计可扩展；
# 不等价于"同义"——strict 指标仍为主，hierarchy 指标只报告宽容视角。
MATERIAL_HIERARCHY: dict[str, tuple[str, ...]] = {
    "GlassCeramic": ("Glass",),            # 微晶玻璃 ⊂ 玻璃族
    "SiCp/Al": ("Aluminum", "SiC"),        # SiCp/Al 复合材料 → 组成相（Al 基体 + SiC 颗粒）
    "TBC": ("ZrO2",),                      # TBC 涂层系统 → 常见陶瓷组成（非必然，按论文证据）
    "FusedSilica": ("Glass",),             # 熔石英 ⊂ 玻璃族（弱）
}


def hierarchy_related(material_id: str) -> set[str]:
    """材料自身 + 层级相关集合（子类展开 + 组成相展开）。"""
    related = {material_id}
    for parent, children in MATERIAL_HIERARCHY.items():
        if material_id == parent:
            related |= set(children)
        elif material_id in children:
            related.add(parent)
    return related

REQUIRED = ("paper_id", "primary_material", "primary_process", "laser_type")
OPTIONAL = {
    "title": str, "is_review": bool, "material_grade": dict, "wavelength_nm": (float, int, type(None)),
    "pulse_width": (dict, type(None)), "geometry": str, "material_mentions": list,
    "process_mentions": list, "evidence_page_primary_material": (int, type(None)), "notes": str,
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    records = []
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no} invalid JSON: {exc}") from exc
            if not isinstance(record, dict):
                raise TypeError(f"{path}:{line_no} expected JSON object")
            records.append(record)
    return records


def check_schema(record: dict[str, Any], path: str, line_no: int, *, allow_unknown_roles: bool = False) -> list[str]:
    errors = []
    for field in REQUIRED:
        if field not in record:
            errors.append(f"{path}:{line_no} missing required field '{field}'")
    for field, expected in OPTIONAL.items():
        value = record.get(field)
        if value is None or value == "" or value == [] or value == {}:
            continue
        if isinstance(expected, tuple):
            if not isinstance(value, expected):
                errors.append(f"{path}:{line_no} field '{field}' wrong type {type(value).__name__}")
        elif not isinstance(value, expected):
            errors.append(f"{path}:{line_no} field '{field}' wrong type {type(value).__name__}")
    if not isinstance(record.get("primary_material", []), list):
        errors.append(f"{path}:{line_no} primary_material must be a list")
    if not isinstance(record.get("material_grade", {}), dict):
        errors.append(f"{path}:{line_no} material_grade must be an object")
    if not isinstance(record.get("material_mentions", []), list):
        errors.append(f"{path}:{line_no} material_mentions must be a list")
    if not isinstance(record.get("process_mentions", []), list):
        errors.append(f"{path}:{line_no} process_mentions must be a list")
    for mention in record.get("material_mentions", []):
        if not isinstance(mention, dict):
            errors.append(f"{path}:{line_no} invalid material mention: {mention!r}")
            continue
        role_ok = mention.get("role") in MATERIAL_ROLES or (
            allow_unknown_roles and mention.get("role") == "unknown"
        )
        if not role_ok:
            errors.append(f"{path}:{line_no} invalid material mention role: {mention!r}")
        if not mention.get("canonical_material_id"):
            errors.append(f"{path}:{line_no} material mention missing canonical_material_id")
    for mention in record.get("process_mentions", []):
        if not isinstance(mention, dict):
            errors.append(f"{path}:{line_no} invalid process mention: {mention!r}")
            continue
        role_ok = mention.get("role") in PROCESS_ROLES or (
            allow_unknown_roles and mention.get("role") == "unknown"
        )
        if not role_ok:
            errors.append(f"{path}:{line_no} invalid process mention role: {mention!r}")
        if not mention.get("canonical_process_id"):
            errors.append(f"{path}:{line_no} process mention missing canonical_process_id")
    return errors


def schema_check(records: list[dict[str, Any]], path: Path, *, allow_unknown_roles: bool = False) -> list[str]:
    errors: list[str] = []
    for line_no, record in enumerate(records, start=1):
        errors.extend(check_schema(record, str(path), line_no, allow_unknown_roles=allow_unknown_roles))
    return errors


def _unknown(record: dict[str, Any], field: str) -> bool:
    value = record.get(field)
    if field == "primary_material":
        return not isinstance(value, list) or not value
    if field == "material_grade":
        return not isinstance(value, dict) or not value
    if field == "wavelength_nm":
        return value is None or value == "" or value == 0
    return value in (None, "")


def _materials(record: dict[str, Any]) -> set[str]:
    return {str(item) for item in record.get("primary_material") or [] if item}


def _equals(gold_value: Any, pred_value: Any) -> bool:
    if isinstance(gold_value, dict) and isinstance(pred_value, dict):
        return pred_value == gold_value
    return str(pred_value or "") == str(gold_value or "")


def wilson_ci(k: int, n: int, z: float = Z) -> tuple[float, float] | None:
    """Wilson score interval；n=0 返回 None。"""
    if n <= 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(max(0.0, center - half), 4), round(min(1.0, center + half), 4))


def _ratio_metric(k: int, n: int) -> dict[str, Any]:
    if n <= 0:
        return {"value": None, "n": 0, "ci": None}
    return {"value": round(k / n, 4), "n": n, "ci": wilson_ci(k, n)}


def compute_metrics(gold: list[dict[str, Any]], pred: list[dict[str, Any]], *, only_paired: bool = False) -> dict[str, Any]:
    pred_by_id = {record.get("paper_id"): record for record in pred}
    if only_paired:
        gold = [g for g in gold if g.get("paper_id") in pred_by_id]
    paired = [(g, pred_by_id.get(g.get("paper_id"), {})) for g in gold]

    tp = fp = fn = 0
    material_exact_k = material_exact_n = 0
    abstain_gold_papers = 0
    fp_on_abstain_papers = 0
    page_k = page_n = 0
    wavelength_k = wavelength_n = 0
    wavelength_abs_error = 0.0
    pulse_k = pulse_n = 0

    field_acc = {field: {"k": 0, "n": 0} for field in ("primary_process", "laser_type", "material_grade", "geometry")}
    field_abstain = {field: {"tp": 0, "pred_unknown": 0, "gold_unknown": 0} for field in CORE_FIELDS}

    for g, p in paired:
        gold_materials = _materials(g)
        pred_materials = _materials(p)
        # FP 无条件统计：gold 空材料时 pred 报材料也计入 FP（乱报惩罚）
        tp += len(gold_materials & pred_materials)
        fp += len(pred_materials - gold_materials)
        fn += len(gold_materials - pred_materials)
        if gold_materials:
            material_exact_n += 1
            if pred_materials == gold_materials:
                material_exact_k += 1
        else:
            abstain_gold_papers += 1
            if pred_materials:
                fp_on_abstain_papers += 1

        for field in CORE_FIELDS:
            gold_unknown = _unknown(g, field)
            pred_unknown = _unknown(p, field)
            stats = field_abstain[field]
            if gold_unknown:
                stats["gold_unknown"] += 1
                if pred_unknown:
                    stats["tp"] += 1
            if pred_unknown:
                stats["pred_unknown"] += 1

        for field in ("primary_process", "laser_type", "material_grade", "geometry"):
            if _unknown(g, field):
                continue
            field_acc[field]["n"] += 1
            if not _unknown(p, field) and _equals(g.get(field), p.get(field)):
                field_acc[field]["k"] += 1

        gold_wavelength = g.get("wavelength_nm")
        if isinstance(gold_wavelength, (int, float)) and not isinstance(gold_wavelength, bool) and gold_wavelength > 0:
            wavelength_n += 1
            pred_wavelength = p.get("wavelength_nm")
            if isinstance(pred_wavelength, (int, float)) and not isinstance(pred_wavelength, bool) and pred_wavelength > 0:
                wavelength_abs_error += abs(float(pred_wavelength) - float(gold_wavelength))
                if abs(float(pred_wavelength) - float(gold_wavelength)) <= WAVELENGTH_TOLERANCE_NM:
                    wavelength_k += 1
        gold_pulse = g.get("pulse_width")
        if isinstance(gold_pulse, dict) and gold_pulse.get("value") is not None:
            pulse_n += 1
            pred_pulse = p.get("pulse_width")
            if isinstance(pred_pulse, dict) and pred_pulse.get("value") is not None:
                gold_value = float(gold_pulse["value"])
                pred_value = float(pred_pulse["value"])
                if (
                    str(gold_pulse.get("unit", "")).lower() == str(pred_pulse.get("unit", "")).lower()
                    and gold_value > 0
                    and abs(pred_value - gold_value) / gold_value <= PULSE_WIDTH_REL_TOLERANCE
                ):
                    pulse_k += 1

        gold_page = g.get("evidence_page_primary_material")
        if isinstance(gold_page, int):
            page_n += 1
            if _has_mention_on_page(
                p, "material_mentions", "canonical_material_id", gold_materials, gold_page, roles=EVIDENCE_PAGE_ROLES
            ):
                page_k += 1

    metrics: dict[str, Any] = {
        "papers": len(paired),
        "paired": sum(1 for _, p in paired if p),
        "gold_material_abstain_papers": abstain_gold_papers,
    }
    for name, k, n in (
        ("material_exact_accuracy", material_exact_k, material_exact_n),
        ("material_multi_label_precision", tp, tp + fp),
        ("material_multi_label_recall", tp, tp + fn),
        ("material_fp_on_abstain_papers", fp_on_abstain_papers, abstain_gold_papers),
        ("evidence_page_accuracy", page_k, page_n),
        ("wavelength_accuracy", wavelength_k, wavelength_n),
        ("pulse_width_accuracy", pulse_k, pulse_n),
    ):
        metrics[name] = _ratio_metric(k, n)
    if wavelength_n:
        metrics["wavelength_mae_nm"] = round(wavelength_abs_error / wavelength_n, 3)
    if tp + fp + fn > 0:
        f1 = 2 * tp / (2 * tp + fp + fn)
        metrics["material_multi_label_f1"] = {"value": round(f1, 4), "n": tp + fp + fn, "ci": None}
    else:
        metrics["material_multi_label_f1"] = {"value": None, "n": 0, "ci": None}

    for field in ("primary_process", "laser_type", "material_grade", "geometry"):
        acc = field_acc[field]
        display = {"primary_process": "process", "laser_type": "laser_regime"}.get(field, field)
        metrics[f"{display}_accuracy"] = _ratio_metric(acc["k"], acc["n"])
    for field in CORE_FIELDS:
        stats = field_abstain[field]
        metrics[f"abstention_recall_{field}"] = _ratio_metric(stats["tp"], stats["gold_unknown"])
        metrics[f"abstention_precision_{field}"] = _ratio_metric(stats["tp"], stats["pred_unknown"])

    # hierarchy-aware 副指标（宽容视角；strict 指标为主，本组不改变 strict 语义）
    hierarchy_hit = 0
    hierarchy_tp = hierarchy_fp = hierarchy_fn = 0
    for g, p in paired:
        gold_materials = _materials(g)
        pred_materials = _materials(p)
        gold_related = set().union(*(hierarchy_related(m) for m in gold_materials)) if gold_materials else set()
        pred_related = set().union(*(hierarchy_related(m) for m in pred_materials)) if pred_materials else set()
        # 命中：gold 每个材料在 pred 层级相关中出现，且 pred 每个材料在 gold 层级相关中出现
        if gold_materials and gold_materials <= pred_related and pred_materials <= gold_related:
            hierarchy_hit += 1
        for item in pred_materials:
            if item in gold_related:
                hierarchy_tp += 1
            else:
                hierarchy_fp += 1
        for item in gold_materials:
            if item not in pred_related:
                hierarchy_fn += 1
    metrics["hierarchy_material_exact_accuracy"] = _ratio_metric(hierarchy_hit, material_exact_n)
    metrics["hierarchy_material_precision"] = _ratio_metric(hierarchy_tp, hierarchy_tp + hierarchy_fp)
    metrics["hierarchy_material_recall"] = _ratio_metric(hierarchy_tp, hierarchy_tp + hierarchy_fn)
    metrics["hierarchy_material_f1"] = (
        {"value": round(2 * hierarchy_tp / (2 * hierarchy_tp + hierarchy_fp + hierarchy_fn), 4),
         "n": hierarchy_tp + hierarchy_fp + hierarchy_fn, "ci": None}
        if (hierarchy_tp + hierarchy_fp + hierarchy_fn) else {"value": None, "n": 0, "ci": None}
    )

    return metrics


def _has_mention_on_page(
    record: dict[str, Any],
    mentions_key: str,
    id_key: str,
    expected_ids: set[str],
    page: int,
    *,
    roles: set[str] | None = None,
) -> bool:
    for mention in record.get(mentions_key) or []:
        if not isinstance(mention, dict):
            continue
        if roles is not None and mention.get("role") not in roles:
            continue
        if mention.get(id_key) in expected_ids and mention.get("page") == page:
            return True
    return False


def _format_value(metric: dict[str, Any]) -> str:
    value = metric.get("value")
    if value is None:
        return "-"
    ci = metric.get("ci")
    if ci:
        return f"{value:.4f} [{ci[0]:.3f},{ci[1]:.3f}]"
    return f"{value:.4f}"


def _format_table(metrics: dict[str, Any], label: str = "metrics") -> str:
    rows = [
        ("papers", None),
        ("paired", None),
        ("gold_material_abstain_papers", None),
        ("material_exact_accuracy", None),
        ("material_multi_label_f1", None),
        ("material_multi_label_precision", None),
        ("material_multi_label_recall", None),
        ("material_fp_on_abstain_papers", None),
        ("process_accuracy", "primary_process"),
        ("laser_regime_accuracy", "laser_type"),
        ("material_grade_accuracy", "material_grade"),
        ("geometry_accuracy", "geometry"),
        ("wavelength_accuracy", None),
        ("wavelength_mae_nm", None),
        ("pulse_width_accuracy", None),
        ("evidence_page_accuracy", None),
        ("hierarchy_material_exact_accuracy", None),
        ("hierarchy_material_f1", None),
        ("hierarchy_material_precision", None),
        ("hierarchy_material_recall", None),
    ]
    for field in CORE_FIELDS:
        rows.append((f"abstention_recall_{field}", None))
    for field in CORE_FIELDS:
        rows.append((f"abstention_precision_{field}", None))
    lines = [f"== {label} ==", f"{'metric':40s} {'value':>26s}  n"]
    for name, _ in rows:
        metric = metrics.get(name)
        if metric is None:
            continue
        if isinstance(metric, dict):
            shown = _format_value(metric)
            count = f"({metric.get('n', 0)})"
        else:
            shown = str(metric)
            count = ""
        lines.append(f"{name:40s} {shown:>26s}  {count}")
    for suffix in ("material_exact_accuracy_ci_boot", "material_multi_label_f1_ci_boot"):
        value = metrics.get(suffix)
        if value:
            lines.append(f"{suffix:40s} {value!s:>26s}")
    return "\n".join(lines)


def bootstrap_ci(
    gold: list[dict[str, Any]],
    pred: list[dict[str, Any]],
    *,
    n_boot: int = 1000,
    seed: int = 42,
) -> dict[str, Any]:
    """论文级 bootstrap（有放回重采样论文对），对 material exact/F1 计算 95% CI。

    论文是抽样单元：同一论文内多标签不再被当作独立样本（修正 Wilson 假设）。
    """
    import random

    rng = random.Random(seed)
    pred_by_id = {record.get("paper_id"): record for record in pred}
    paired = [(g, pred_by_id.get(g.get("paper_id"), {})) for g in gold]
    if not paired:
        return {}
    exact_samples: list[float] = []
    f1_samples: list[float] = []
    for _ in range(n_boot):
        sample = [rng.choice(paired) for _ in paired]
        tp = fp = fn = 0
        exact_k = exact_n = 0
        for g, p in sample:
            gold_materials = _materials(g)
            pred_materials = _materials(p)
            tp += len(gold_materials & pred_materials)
            fp += len(pred_materials - gold_materials)
            fn += len(gold_materials - pred_materials)
            if gold_materials:
                exact_n += 1
                if pred_materials == gold_materials:
                    exact_k += 1
        if exact_n:
            exact_samples.append(exact_k / exact_n)
        if tp + fp + fn:
            f1_samples.append(2 * tp / (2 * tp + fp + fn))

    def percentile_ci(values: list[float]) -> tuple[float, float] | None:
        if not values:
            return None
        ordered = sorted(values)
        lo = ordered[max(0, int(0.025 * len(ordered)) - 1)]
        hi = ordered[min(len(ordered) - 1, int(0.975 * len(ordered)) - 1)]
        return (round(lo, 4), round(hi, 4))

    result: dict[str, Any] = {}
    exact_ci = percentile_ci(exact_samples)
    if exact_ci:
        result["material_exact_accuracy_ci_boot"] = exact_ci
    f1_ci = percentile_ci(f1_samples)
    if f1_ci:
        result["material_multi_label_f1_ci_boot"] = f1_ci
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Literature metadata extraction evaluator")
    parser.add_argument("--gold", type=Path, help="gold annotations JSONL")
    parser.add_argument("--pred", type=Path, help="predictions JSONL (same schema)")
    parser.add_argument("--schema-check", type=Path, help="validate a JSONL file only")
    parser.add_argument("--out", type=Path, default=None, help="write metrics JSON")
    parser.add_argument("--only-paired", action="store_true", help="只输出条件指标（仅 pred 中出现的论文）")
    parser.add_argument("--bootstrap", type=int, default=0, help="论文级 bootstrap 次数（如 1000）计算 exact/F1 95% CI")
    args = parser.parse_args()
    if args.schema_check:
        records = load_jsonl(args.schema_check)
        errors = schema_check(records, args.schema_check)
        print(f"{args.schema_check}: {len(records)} records, {len(errors)} errors")
        for error in errors[:50]:
            print("  " + error)
        raise SystemExit(1 if errors else 0)
    if not args.gold:
        parser.error("--gold is required")
    gold = load_jsonl(args.gold)
    gold_errors = schema_check(gold, args.gold)
    if gold_errors:
        raise SystemExit("\n".join(gold_errors[:20]))
    if args.pred:
        pred = load_jsonl(args.pred)
        pred_errors = schema_check(pred, args.pred, allow_unknown_roles=True)
        if pred_errors:
            raise SystemExit("\n".join(pred_errors[:20]))
    else:
        pred = []
    if args.only_paired:
        metrics = compute_metrics(gold, pred, only_paired=True)
        if args.bootstrap:
            metrics.update(bootstrap_ci(gold, pred, n_boot=args.bootstrap))
        print(_format_table(metrics, label="conditional (paired only)"))
    else:
        conditional = compute_metrics(gold, pred, only_paired=True)
        end_to_end = compute_metrics(gold, pred, only_paired=False)
        if args.bootstrap:
            conditional.update(bootstrap_ci(gold, pred, n_boot=args.bootstrap))
            end_to_end.update(bootstrap_ci(gold, pred, n_boot=args.bootstrap))
        print(_format_table(conditional, label="conditional (parse-success / paired)"))
        print()
        print(_format_table(end_to_end, label="end-to-end (parse failures counted as miss)"))
        metrics = {"conditional": conditional, "end_to_end": end_to_end}
    if args.out:
        args.out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
