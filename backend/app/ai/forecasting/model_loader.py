from __future__ import annotations
import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import joblib
from app.ai.forecasting.errors import ArtifactInvalidError, ArtifactMissingError
from app.core.logging import logger
from app.core.metrics import MODEL_LOAD_FAILURES


@dataclass(frozen=True)
class ModelBundle:
    pipeline: Any
    metadata: dict
    feature_schema: dict
    configuration: dict
    validation_metrics: dict
    test_metrics: dict
    checksum: str


class ForecastModelLoader:
    def __init__(self, model_dir: Path, model_file: str) -> None:
        self.model_dir = model_dir.resolve()
        self.model_path = (self.model_dir / model_file).resolve()
        self._bundle: ModelBundle | None = None
        self._error: str | None = None
        self._lock = threading.Lock()
        if self.model_path.parent != self.model_dir:
            raise ArtifactInvalidError("Model path escapes the allow-listed directory.")

    @staticmethod
    def _json(path: Path) -> dict:
        if not path.is_file():
            raise ArtifactMissingError(f"Required artifact metadata is missing: {path.name}")
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def load(self) -> ModelBundle:
        if self._bundle is not None:
            return self._bundle
        with self._lock:
            if self._bundle is not None:
                return self._bundle
            try:
                if not self.model_path.is_file():
                    raise ArtifactMissingError(f"Model artifact not found: {self.model_path}")
                metadata = self._json(self.model_dir / "model_metadata.json")
                schema = self._json(self.model_dir / "feature_schema.json")
                configuration = self._json(self.model_dir / "forecast_configuration.json")
                validation = self._json(self.model_dir / "validation_metrics.json")
                test = self._json(self.model_dir / "test_metrics.json")
                if metadata.get("selected_model") not in {"Random Forest", "Random Forest Regressor"}:
                    raise ArtifactInvalidError("Artifact metadata does not select Random Forest.")
                if metadata.get("forecast_horizon_months") != 1:
                    raise ArtifactInvalidError("Only the exported one-month horizon is supported.")
                features = schema.get("features")
                if not isinstance(features, list) or len(features) != len(set(features)):
                    raise ArtifactInvalidError("Feature schema is missing or contains duplicates.")
                if metadata.get("data_source") != "NHS England Monthly A&E Attendances and Emergency Admissions":
                    raise ArtifactInvalidError("Unexpected training dataset metadata.")
                checksum = self._sha256(self.model_path)
                expected = metadata.get("artifact_checksum")
                if expected and expected != checksum:
                    raise ArtifactInvalidError("Artifact checksum does not match metadata.")
                pipeline = joblib.load(self.model_path)
                if not callable(getattr(pipeline, "predict", None)):
                    raise ArtifactInvalidError("Loaded artifact does not expose predict().")
                self._bundle = ModelBundle(
                    pipeline, metadata, schema, configuration, validation, test, checksum
                )
                self._error = None
                logger.info("forecast_model_loaded", model=metadata.get("selected_model"),
                            checksum=checksum, data_end=metadata.get("data_end_month"))
                return self._bundle
            except Exception as exc:
                self._error = str(exc)
                MODEL_LOAD_FAILURES.inc()
                if isinstance(exc, (ArtifactMissingError, ArtifactInvalidError)):
                    raise
                raise ArtifactInvalidError(f"Unable to load model artifact: {exc}") from exc

    def status(self) -> dict:
        if self._bundle:
            return {"state": "loaded", "model": self._bundle.metadata.get("selected_model"),
                    "version": self._bundle.checksum[:12], "error": None}
        if not self.model_path.exists():
            return {"state": "missing", "model": None, "version": None,
                    "error": f"Missing {self.model_path.name}"}
        if self._error:
            return {"state": "invalid", "model": None, "version": None, "error": self._error}
        return {"state": "degraded", "model": None, "version": None,
                "error": "Artifact has not been loaded."}
