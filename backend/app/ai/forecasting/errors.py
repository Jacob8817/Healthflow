class ForecastingError(RuntimeError):
    code = "forecasting_error"


class ArtifactMissingError(ForecastingError):
    code = "artifact_missing"


class ArtifactInvalidError(ForecastingError):
    code = "artifact_invalid"


class FeatureValidationError(ForecastingError):
    code = "feature_validation"


class ProviderHistoryError(ForecastingError):
    code = "provider_history"
