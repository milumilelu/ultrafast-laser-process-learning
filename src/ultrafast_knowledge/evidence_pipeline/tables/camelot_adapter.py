"""Camelot 2 ML adapter. Import is lazy so the main service can degrade safely."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from ultrafast_knowledge.evidence_pipeline.tables.extractor import TableExtractionError
from ultrafast_knowledge.evidence_pipeline.tables.models import RawExtractedTable

VALIDATED_MODEL_VERSIONS = {
    "microsoft/table-transformer-detection": "2357cbe2b5a5d1c03e54f32764f06058933b65ab",
    "microsoft/table-transformer-structure-recognition-v1.1-all": (
        "7587a7ef111d9dcbf8ac695f1376ab7014340a0c"
    ),
    "timm/resnet18.a1_in1k": "491b427b45c94c7fb0e78b5474cc919aff584bbf",
}


class CamelotMLTableExtractor:
    name = "camelot_ml"

    def __init__(
        self,
        *,
        pages: str = "all",
        model_versions: dict[str, str] | None = None,
        require_offline: bool = True,
    ) -> None:
        self.pages = pages
        self.model_versions = {**VALIDATED_MODEL_VERSIONS, **(model_versions or {})}
        self.require_offline = require_offline
        try:
            self.version = version("camelot-py")
        except PackageNotFoundError:
            self.version = "unavailable"

    def extract(self, pdf_path: Path) -> list[RawExtractedTable]:
        if self.require_offline and not self._offline_enabled():
            raise TableExtractionError(
                "offline model mode is required: set HF_HUB_OFFLINE=1 and "
                "TRANSFORMERS_OFFLINE=1 after preloading Camelot ML models"
            )
        self._validate_model_cache()
        try:
            import camelot
        except ImportError as exc:
            raise TableExtractionError(
                "camelot-py is not installed in the table-extraction runtime"
            ) from exc
        try:
            tables = camelot.read_pdf(str(pdf_path), pages=self.pages, flavor="ml")
        except Exception as exc:  # vendor boundary
            raise TableExtractionError(f"Camelot ML extraction failed: {exc}") from exc

        output: list[RawExtractedTable] = []
        for index, table in enumerate(tables):
            page = self._page(table)
            bbox = self._bbox(table)
            try:
                rows = table.df.fillna("").astype(str).values.tolist()
            except Exception as exc:  # vendor boundary
                raise TableExtractionError(
                    f"Camelot table {index} dataframe conversion failed: {exc}"
                ) from exc
            try:
                report = dict(table.parsing_report or {})
            except (AttributeError, TypeError, ValueError):
                report = {}
            output.append(
                RawExtractedTable(
                    page=page,
                    pdf_page_index=page - 1,
                    table_index=index,
                    bbox=bbox,
                    rows=rows,
                    parsing_report=report,
                )
            )
        return output

    @staticmethod
    def _offline_enabled() -> bool:
        truthy = {"1", "true", "yes", "on"}
        return (
            os.environ.get("HF_HUB_OFFLINE", "").casefold() in truthy
            and os.environ.get("TRANSFORMERS_OFFLINE", "").casefold() in truthy
        )

    def _validate_model_cache(self) -> None:
        cache = self._hub_cache()
        errors: list[str] = []
        for model_id, expected_revision in VALIDATED_MODEL_VERSIONS.items():
            expected_revision = self.model_versions.get(model_id, expected_revision)
            ref = cache / f"models--{model_id.replace('/', '--')}" / "refs" / "main"
            if not ref.is_file():
                errors.append(f"missing:{model_id}")
                continue
            actual = ref.read_text(encoding="utf-8").strip()
            if actual != expected_revision:
                errors.append(f"revision:{model_id}:{actual}!={expected_revision}")
        if errors:
            raise TableExtractionError(
                "Camelot ML cache does not match the validated model set: " + ";".join(errors)
            )

    @staticmethod
    def _hub_cache() -> Path:
        configured = os.environ.get("HF_HUB_CACHE") or os.environ.get(
            "HUGGINGFACE_HUB_CACHE"
        )
        if configured:
            return Path(configured)
        hf_home = os.environ.get("HF_HOME")
        if hf_home:
            return Path(hf_home) / "hub"
        return Path.home() / ".cache" / "huggingface" / "hub"

    @staticmethod
    def _page(table: Any) -> int:
        raw = getattr(table, "page", 1)
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _bbox(table: Any) -> tuple[float, float, float, float] | None:
        raw = getattr(table, "_bbox", None) or getattr(table, "bbox", None)
        if raw is None:
            return None
        try:
            values = tuple(float(value) for value in raw)
        except (TypeError, ValueError):
            return None
        return values if len(values) == 4 else None


class CamelotWorkerTableExtractor(CamelotMLTableExtractor):
    """Run Camelot in its own dependency environment via a JSON boundary."""

    name = "camelot_ml_worker"

    def __init__(
        self,
        python_executable: Path,
        *,
        pages: str = "all",
        model_versions: dict[str, str] | None = None,
        timeout: float = 300.0,
        require_offline: bool = True,
    ) -> None:
        super().__init__(
            pages=pages,
            model_versions=model_versions,
            require_offline=require_offline,
        )
        self.python_executable = Path(python_executable)
        self.timeout = timeout
        self.version = "2.0.0"

    def extract(self, pdf_path: Path) -> list[RawExtractedTable]:
        if self.require_offline and not self._offline_enabled():
            raise TableExtractionError(
                "offline model mode is required: set HF_HUB_OFFLINE=1 and "
                "TRANSFORMERS_OFFLINE=1 after preloading Camelot ML models"
            )
        self._validate_model_cache()
        if not self.python_executable.is_file():
            raise TableExtractionError(
                f"configured Camelot worker Python does not exist: {self.python_executable}"
            )
        worker = Path(__file__).with_name("_camelot_worker.py")
        output_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
                output_path = Path(handle.name)
            completed = subprocess.run(
                [
                    str(self.python_executable),
                    str(worker),
                    "--pdf",
                    str(pdf_path),
                    "--pages",
                    self.pages,
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
            if completed.returncode != 0:
                message = completed.stderr.strip() or completed.stdout.strip()
                raise TableExtractionError(
                    f"Camelot worker failed with exit code {completed.returncode}: {message}"
                )
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.version = str(payload.get("camelot_version") or self.version)
            return [RawExtractedTable.model_validate(item) for item in payload["tables"]]
        except subprocess.TimeoutExpired as exc:
            raise TableExtractionError(
                f"Camelot worker exceeded {self.timeout:.0f}s timeout"
            ) from exc
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise TableExtractionError(f"invalid Camelot worker result: {exc}") from exc
        finally:
            if output_path is not None:
                output_path.unlink(missing_ok=True)
