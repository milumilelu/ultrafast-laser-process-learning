"""Topic2 demo report generator (single-file HTML, zero dependencies).

Input : outputs/t2_slice_run.json (frozen Demo Scenario 01 run, seed 42)
Output: outputs/topic2_demo_report.html (self-contained, offline, browser-open)

Presentation discipline (enforced by --check):
  - CFA is always "Uncalibrated CFA", calibration_status = NOT_YET_CALIBRATED
  - facet statuses only KNOWN/PARTIAL/UNKNOWN/MISMATCH + warnings
  - no probability/confidence pseudo-calibration wording
  - B1-25 is referenced only as a diagnostic audit, never as generalization
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from demo.t2_slice.pipeline import _cfa_facet_summary

FACETS = ("Material", "Task", "InteractionState", "Reconstructibility", "Reachability")
FORBIDDEN_WORDS = ("probability", "transfer_probability", "confidence", "confidence_score")


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _facet_badge(status: str) -> str:
    color = {
        "KNOWN": "#1b7f3b",
        "PARTIAL": "#b07a00",
        "UNKNOWN": "#7a7a7a",
        "MISMATCH": "#b3392e",
    }.get(str(status).upper(), "#7a7a7a")
    return f'<span style="background:{color};color:#fff;padding:2px 8px;border-radius:10px;font-size:12px">{_esc(status)}</span>'


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    thead = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = ""
    for row in rows:
        body += "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
    return (
        f"<table style='border-collapse:collapse;width:100%;font-size:13px'>"
        f"<thead style='background:#eef1f5'><tr>{thead}</tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def _section(number: str, title: str, body: str) -> str:
    return (
        f"<section style='margin:28px 0'>"
        f"<h2 style='border-bottom:2px solid #2c5f8a;padding-bottom:6px'>"
        f"{number}. {_esc(title)}</h2>{body}</section>"
    )


def _per_paper_facets(result: dict) -> list[dict]:
    claims = result["evidence_ir"]["claims"]
    claim_to_paper = {c["claim_id"]: (c.get("source") or {}).get("paper_id", "?") for c in claims}
    by_paper: dict[str, list[dict]] = {}
    for report in result["cfa"]["reports"]:
        paper = claim_to_paper.get(report.get("evidence_claim_id"), "?")
        by_paper.setdefault(paper, []).append(report)
    papers: list[dict] = []
    for paper_id, reports in by_paper.items():
        summary = _cfa_facet_summary(reports)
        papers.append({"paper_id": paper_id, "facets": summary, "reports": len(reports)})
    return papers


def build_report(result: dict, scenario: str = "Demo Scenario 01") -> str:
    target = result["target_task"]
    pl = result["process_learning"]
    e2p = result["e2p_prior"]
    bo = result["bo"]
    audit = result["audit"]
    cfa = result["cfa"]
    meta = result["evidence_ir"]["meta"]
    claims = result["evidence_ir"]["claims"]
    governed = e2p["governed_prior"]

    # ① target
    bounds = target.get("parameter_domain") or {}
    rows = [[k, f"{v[0]} – {v[1]}"] for k, v in sorted(bounds.items())] if bounds else []
    body1 = (
        f"<p>目标材料 <b>{_esc(target['material'])}</b> · 目标指标 <b>{_esc(target['objective'])}</b>"
        f" · 激光 {_esc(target.get('laser_type', ''))} · 数据集 {_esc(target.get('dataset', ''))}"
        f" · 样本 <b>{target.get('sample_count')}</b></p>"
        + _table(["参数", "范围（固定边界）"], rows)
    )

    # ② model selection
    views = pl["feature_views"]
    rows2 = []
    for view_name in ("RAW", "HYBRID"):
        comp = pl["model_comparison"].get(view_name) or {}
        metrics = comp.get("metrics_by_model") or {}
        for model, m in metrics.items():
            rows2.append([
                view_name,
                model,
                f"{m.get('RMSE', '') if m.get('RMSE') is not None else '—':.3f}" if isinstance(m.get("RMSE"), (int, float)) else "—",
                f"{m.get('MAE', ''):.3f}" if isinstance(m.get("MAE"), (int, float)) else "—",
                f"{m.get('R2', ''):.3f}" if isinstance(m.get("R2"), (int, float)) else "—",
                f"{m.get('n_samples', '')} 样本 / {m.get('cv_folds', '')} 折 Group-CV",
            ])
    hybrid_note = ""
    if views.get("HYBRID"):
        h = views["HYBRID"]
        hybrid_note = (
            f"<p style='color:#555'>HYBRID 视图：可用物理特征 {_esc(h.get('available_physics', []))}"
            f"，阻塞坐标 {_esc(h.get('blocked_coordinates', []))}（缺设备属性，如实报告不可用）。</p>"
        )
    body2 = (
        f"<p>选定特征视图 <b>{pl.get('selected_feature_view')}</b> · 选定模型 <b>{pl.get('selected_model')}</b>"
        f"（Group-CV {pl.get('cv_folds')} 折）</p>{hybrid_note}"
        + _table(["视图", "模型", "RMSE", "MAE", "R²", "评估设置"], rows2)
    )

    # ③ readiness
    tr = cfa["target_physics_readiness"] or {}
    rows3 = [
        ["可用坐标", tr.get("available_coordinate_count", "—")],
        ["阻塞坐标", tr.get("blocked_coordinate_count", "—")],
        ["含未验证假设（UNVERIFIED）", tr.get("unverified_assumption_coordinate_count", "—")],
        ["未验证输入", tr.get("unverified_input_count", "—")],
        ["已验证输入", tr.get("verified_input_count", "—")],
        ["缺失输入", tr.get("missing_input_count", "—")],
    ]
    body3 = (
        "<p>Target 侧物理可计算性（设备画像 spot=5 µm 为 <b>UNVERIFIED</b>，M7 显式标记；"
        "未验证物理量不得作为有效匹配证据）。</p>"
        + _table(["项目", "数量"], rows3)
    )

    # ④ literature
    rows4 = []
    per_paper: dict[str, int] = {}
    for c in claims:
        paper = (c.get("source") or {}).get("paper_id", "?")
        per_paper[paper] = per_paper.get(paper, 0) + 1
    for paper, n in sorted(per_paper.items()):
        rows4.append([_esc(paper), n])
    body4 = (
        f"<p>读取 <b>{result['literature_evidence']['paper_count']}</b> 篇论文，生成 "
        f"<b>{len(per_paper)}</b> 个实验条件 ledger（共 {meta.get('ledger_candidate_count', '—')} 条候选），"
        f"证据 claim <b>{meta.get('claim_count', 0)}</b> 条，每条可回溯到 paper:page:block 与原文引用。</p>"
        + _table(["论文", "claims"], rows4)
    )

    # ⑤ CFA facets (per paper)
    rows5 = []
    for p in _per_paper_facets(result):
        cells = [_facet_badge(p["facets"].get(f, "UNKNOWN")) for f in FACETS]
        rows5.append([_esc(p["paper_id"]), *cells, p["reports"]])
    body5 = (
        f"<p><b>Uncalibrated CFA</b>（{_esc(cfa.get('version', ''))}）——五 facet 判定："
        f"<code>KNOWN / PARTIAL / UNKNOWN / MISMATCH</code>，不含任何概率输出。"
        f"校准状态：<b>NOT_YET_CALIBRATED</b>。逐条件报告 {len(cfa.get('reports', []))} 份。</p>"
        + _table(["论文", *FACETS, "条件数"], rows5)
        + f"<p style='color:#555'>全局汇总：{', '.join(f'{f}={v}' for f, v in audit['cfa_facets'].items())}。</p>"
    )

    # ⑥ evidence
    rejected = e2p.get("rejected") or []
    body6 = (
        f"<p>EvidenceIR → bundle：<b>{e2p['prior_count']}</b> 条先验，接受 <b>{e2p['accepted_count']}</b>，"
        f"拒绝 <b>{len(rejected)}</b>（本 demo 为显式 auto-approve 模式，生产环境必须人工审核）。</p>"
        + _table(
            ["claim_id", "参数", "区间（prior 偏好）", "strength"],
            [
                [
                    _esc(p.get("claim_id", "")),
                    _esc(p.get("parameter", "")),
                    f"{p.get('lower', '')} – {p.get('upper', '')}",
                    _esc(p.get("strength", "")),
                ]
                for p in (governed.get("prior_spec") or {}).get("range_preferences", [])[:10]
            ],
        )
    )

    # ⑦ governed prior
    body7 = (
        f"<p>GovernedPriorArtifact：hash <code>{_esc(governed.get('content_hash'))}</code> · "
        f"evidence_ids <b>{len(governed.get('evidence_ids', []))}</b> 条 · 校验 "
        f"<code>{_esc(governed.get('verification'))}</code> · 编译器 "
        f"<code>{_esc(governed.get('compiler_version'))}</code> · 先验规格 "
        f"<code>{_esc((governed.get('prior_spec') or {}).get('prior_spec_version', ''))}</code>。</p>"
        f"<p style='color:#555'>每个 prior 均保留 claim 级证据 ID，可逐条回溯到原文。</p>"
    )

    # ⑧ BO comparison
    vanilla = bo["vanilla"]
    assisted = bo["evidence_assisted"]
    v_params = vanilla.get("recommended_parameters") or {}
    a_params = assisted.get("recommended_parameters") or {}
    v_acq = vanilla.get("acquisition") or {}
    a_acq = assisted.get("acquisition") or {}
    rows8 = []
    for k in sorted(set(v_params) | set(a_params)):
        rows8.append([_esc(k), f"{v_params.get(k, '—')}", f"{a_params.get(k, '—')}"])
    body8 = (
        f"<p>Vanilla（无文献先验）vs Evidence-assisted（governed prior）。"
        f"Acquisition：Vanilla <code>{v_acq.get('type', '')}</code> score={v_acq.get('score', '—'):.4f}"
        f"（prior_guidance={v_acq.get('prior_guidance')}）· Assisted score={a_acq.get('score', '—'):.4f}"
        f"（prior_guidance=<code>{_esc(a_acq.get('prior_guidance'))}</code>）。</p>"
        + _table(["参数", "Vanilla", "Evidence-assisted"], rows8)
        + _table(
            ["机制证据", "值"],
            [
                ["assisted search_prior_applied", bo["prior_applied_evidence"]["assisted_search_prior_applied"]],
                ["vanilla search_prior_applied", bo["prior_applied_evidence"]["vanilla_search_prior_applied"]],
                ["assisted prior_guidance", bo["prior_applied_evidence"]["assisted_prior_guidance"]],
                ["governed_prior_hash", bo["prior_applied_evidence"]["governed_prior_hash"]],
            ],
        )
    )

    # ⑨ next candidates
    body9 = (
        "<p>下一轮候选实验（Evidence-assisted BO 推荐，seed 固定 42）：</p>"
        + _table(["参数", "推荐值"], [[_esc(k), f"{v}"] for k, v in sorted(a_params.items())])
        + f"<p style='color:#555'>不确定性接口：acquisition variance（UCB），模型 <code>{_esc(assisted.get('model_version'))}</code>。</p>"
    )

    # ⑩ traceback
    trace = assisted.get("audit_trace") or []
    rows10 = [[_esc(t.get("step")), _esc(t.get("status")), _esc(str(t.get("content_hash") or t.get("verification") or ""))] for t in trace]
    body10 = (
        _table(["步骤", "状态", "校验/哈希"], rows10)
        + _table(
            ["运行标识", "值"],
            [
                ["bo_run_id (assisted)", audit.get("bo_run_id_assisted")],
                ["bo_run_id (vanilla)", audit.get("bo_run_id_vanilla")],
                ["ledger_version_ids", ", ".join(audit.get("ledger_version_ids") or [])],
                ["feature_view / model_version", f"{audit.get('feature_view')} / {audit.get('model_version')}"],
                ["dataset / 复现命令", "data/test_fixture/topic2_experiments_v1.csv · python scripts/demo_t2_vertical_slice.py"],
            ],
        )
    )

    html_text = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>Topic 2 端到端演示 — {_esc(scenario)}</title>
<style>
 body {{ font-family: "Segoe UI", "Microsoft YaHei", sans-serif; max-width: 980px; margin: 0 auto; padding: 24px; color: #222; }}
 h1 {{ color: #2c5f8a; }} code {{ background: #f0f0f0; padding: 1px 5px; border-radius: 4px; }}
 table td, table th {{ border: 1px solid #d5d9de; padding: 6px 8px; text-align: left; }}
 .banner {{ background: #fdf3e3; border-left: 5px solid #b07a00; padding: 10px 14px; margin: 14px 0; }}
 .foot {{ margin-top: 40px; padding-top: 12px; border-top: 1px solid #ccc; color: #666; font-size: 12px; }}
</style>
</head>
<body>
<h1>课题二：参数辨识 → 过程建模 → 文献知识适配（E2P）→ 适用性判断 → 参数优化</h1>
<p style="color:#555">{_esc(scenario)} · Uncalibrated CFA v2.0 · 固定 seed 42 · 可复现（重跑逐字节一致，仅运行 ID 不同）</p>
<div class="banner">
<b>展示纪律</b>：本演示只呈现 <b>Uncalibrated CFA</b> 的定性判定（KNOWN / PARTIAL / UNKNOWN /
MISMATCH + warnings），校准状态一律 <b>NOT_YET_CALIBRATED</b>，<u>不产生任何概率/置信度结论</u>。
B1-25 仅作为 diagnostic audit 背景，不构成泛化性能声明。
</div>
{_section("①", "导入目标实验数据", body1)}
{_section("②", "自动参数辨识与模型选择", body2)}
{_section("③", "物理可计算性与缺口", body3)}
{_section("④", "读取文献并重建实验条件", body4)}
{_section("⑤", "Source ↔ Target CFA 五 facet（Uncalibrated）", body5)}
{_section("⑥", "文献 Evidence：采用 / 拒绝 / 未知", body6)}
{_section("⑦", "E2P 编译为受治理先验（GovernedPriorArtifact）", body7)}
{_section("⑧", "Vanilla BO vs Evidence-assisted BO", body8)}
{_section("⑨", "下一轮候选实验", body9)}
{_section("⑩", "全链路回溯", body10)}
<div class="foot">
复现：<code>python scripts/demo_t2_vertical_slice.py --output outputs/t2_slice_run.json</code> →
<code>python scripts/demo_report.py</code>（生成本报告）。<br>
验证状态：v1.1/v2 验证详见 <code>artifacts/cfa_holdout/</code>（H1 severe=0 保持；v2 独立验证 H3/H5 未过，
根因登记：facet 聚合语义 / 表格提取 / review-sweep 文档语义，均不影响本演示的诚实呈现）。
</div>
</body>
</html>"""
    return html_text


def check_report(text: str) -> list[str]:
    problems: list[str] = []
    lower = text.lower()
    if "uncalibrated" not in lower:
        problems.append("must state Uncalibrated CFA")
    if "not_yet_calibrated" not in lower:
        problems.append("must show NOT_YET_CALIBRATED")
    for word in FORBIDDEN_WORDS:
        if word in lower:
            problems.append(f"forbidden word leaked: {word}")
    if "diagnostic" not in lower:
        problems.append("B1-25 must be described as diagnostic only")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=REPO / "outputs" / "t2_slice_run.json")
    parser.add_argument("--output", type=Path, default=REPO / "outputs" / "topic2_demo_report.html")
    args = parser.parse_args()

    result = json.loads(args.input.read_text(encoding="utf-8"))
    text = build_report(result)
    problems = check_report(text)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(f"report written: {args.output} ({len(text) // 1024} KB)")
    if problems:
        print("DISCIPLINE FAILURES:")
        for p in problems:
            print("  -", p)
        raise SystemExit(1)
    print("discipline check: PASS (Uncalibrated / NOT_YET_CALIBRATED / no probability wording)")


if __name__ == "__main__":
    main()
