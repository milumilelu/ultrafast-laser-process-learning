"""真实加工数据导入：根目录 SiCp/Al/CFRP/SiC/ZrO2 CSV + 金刚石实验结果.xlsx → Topic2 实验库。

映射规则（透明、不伪造）：
- equipment_id 使用统一标记 "EQ-REAL"（真实数据无设备档案，字段为数据来源标记）
- geometry_type = rectangular_groove（数据为沟槽加工测量）
- 5 个核心工艺参数完整映射；质量取 mean_depth_um 与 Sa_um（roughness_type=Sa）
- 相同参数组合归入同一 parameter_combination_id（保持设计矩阵语义）
- data_origin = real_machining_data，is_synthetic = False

用法：
    python scripts/import_real_data.py --api http://127.0.0.1:8010/api/v1
    python scripts/import_real_data.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
EQUIPMENT_ID = "EQ-REAL"
GEOMETRY_TYPE = "rectangular_groove"
DATA_ORIGIN = "real_machining_data"

CSV_SOURCES: dict[str, Path] = {
    "SiCp/Al": ROOT / "SiCpAl.csv",
    "CFRP": ROOT / "CFRP.csv",
    "SiC": ROOT / "SiC.csv",
    "ZrO2": ROOT / "ZrO2.csv",
}
XLSX_SOURCE: dict[str, Path] = {
    "Diamond": ROOT / "金刚石实验结果.xlsx",
}


def _csv_records(material: str, path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open("r", encoding="gbk", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            values = {str(key).strip(): value for key, value in row.items()}
            parameters = {
                "pulse_width_ps": _num(values.get("脉宽fs")) / 1000.0,
                "frequency_kHz": _num(values.get("频率kHz")),
                "hatch_spacing_um": _num(values.get("间距mm")) * 1000.0,
                "passes": int(_num(values.get("重复加工次数"))),
                "scan_speed_mm_s": _num(values.get("速度mm/s")),
            }
            quality = {
                "depth_um": _num(values.get("mean_depth_um")),
                "roughness_um": _num(values.get("Sa_um")),
                "roughness_type": "Sa",
            }
            if any(v is None for v in parameters.values()) or quality["depth_um"] is None:
                continue
            combination_id = f"REAL-{material}-D{_design_index(records, parameters):03d}"
            records.append(
                _record(
                    material,
                    seq=len(records) + 1,
                    parameters=parameters,
                    quality=quality,
                    combination_id=combination_id,
                    source_file=path.name,
                )
            )
    return records


def _xlsx_records(material: str, path: Path) -> list[dict[str, Any]]:
    import pandas as pd

    frame = pd.read_excel(path)
    records = []
    for _, row in frame.iterrows():
        parameters = {
            "pulse_width_ps": _num(row.get("脉冲宽度")) / 1000.0,
            "frequency_kHz": _num(row.get("重复频率")),
            "hatch_spacing_um": _num(row.get("填充间距")) * 1000.0,
            "passes": int(_num(row.get("加工次数"))),
            "scan_speed_mm_s": _num(row.get("扫描速度")),
        }
        quality = {
            "depth_um": _num(row.get("深度/μm")),
            "roughness_um": _num(row.get("粗糙度/μm")),
            "roughness_type": "Sa",
        }
        if any(v is None for v in parameters.values()) or quality["depth_um"] is None:
            continue
        records.append(
            _record(
                material,
                seq=len(records) + 1,
                parameters=parameters,
                quality=quality,
                combination_id=f"REAL-{material}-D{_design_index(records, parameters):03d}",
                source_file=path.name,
            )
        )
    return records


def _design_index(records: list[dict[str, Any]], parameters: dict[str, Any]) -> int:
    keys = [tuple(sorted(r["parameters"].items())) for r in records]
    if tuple(sorted(parameters.items())) in keys:
        return keys.index(tuple(sorted(parameters.items())))
    return len(records)


def _record(
    material: str,
    seq: int,
    parameters: dict[str, Any],
    quality: dict[str, Any],
    combination_id: str,
    source_file: str,
) -> dict[str, Any]:
    return {
        "experiment_id": f"REAL-{material}-{seq:04d}",
        "scope": {
            "material": material,
            "laser_type": "fs",
            "equipment_id": EQUIPMENT_ID,
            "geometry_type": GEOMETRY_TYPE,
            "target": "depth_um",
        },
        "parameters": parameters,
        "quality": quality,
        "experiment_batch_id": f"REAL-{material}-B1",
        "parameter_combination_id": combination_id,
        "source_file": source_file,
        "data_origin": DATA_ORIGIN,
        "is_synthetic": False,
        "valid_flag": True,
    }


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None  # noqa: PLR0124 - NaN 判定


def build_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for material, path in CSV_SOURCES.items():
        records.extend(_csv_records(material, path))
    for material, path in XLSX_SOURCE.items():
        records.extend(_xlsx_records(material, path))
    return records


def import_via_api(records: list[dict[str, Any]], api_base: str) -> dict[str, Any]:
    payload = json.dumps({"records": records}, ensure_ascii=False).encode("utf-8")
    request = Request(
        f"{api_base.rstrip('/')}/experiments/import",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import real machining data into Topic2")
    parser.add_argument("--api", default="http://127.0.0.1:8010/api/v1")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    records = build_records()
    by_material: dict[str, int] = {}
    for record in records:
        by_material[record["scope"]["material"]] = by_material.get(record["scope"]["material"], 0) + 1
    print(f"待导入 {len(records)} 条：{by_material}")
    if args.dry_run:
        print("dry-run：未写入。示例：")
        print(json.dumps(records[0], ensure_ascii=False, indent=2))
        return 0
    result = import_via_api(records, args.api)
    print(f"导入完成：{result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
