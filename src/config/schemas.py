import math
from datetime import datetime
import numpy as np
from types import MappingProxyType
from typing import Annotated, Any, Literal, Optional, TypeVar
from typing_extensions import Self
from pathlib import Path
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    model_validator
)

# ================================================
# FROZEN CONFIGURATION MODELS
# ================================================
TIME_STRING_PATTERN = r"^\d+[smhdw]$"
TimeString = Annotated[str, Field(pattern=TIME_STRING_PATTERN)]

K = TypeVar("K")
V = TypeVar("V")

def _validate_sanitized_identifier(v: str) -> str:
    if not v or not v.strip():
        raise ValueError("Identifier cannot be empty or pure whitespace")
    if v != v.strip():
        raise ValueError("Identifier cannot contain leading or trailing whitespace.")
    return v

SanitizedString = Annotated[str, AfterValidator(_validate_sanitized_identifier)]

def _validate_bounds_range(bounds: tuple[float, float]) -> tuple[float, float]:
    if len(bounds) == 2:
        min_v, max_v = bounds
        if min_v > max_v:
            raise ValueError(f"Lower bound ({min_v}) must be less than or equal to upper bound ({max_v}).")
    return bounds

BoundTuple = Annotated[tuple[float, float], AfterValidator(_validate_bounds_range)]

def _to_mapping_proxy(d: Any) -> Any:
    if d is None:
        return None
    if isinstance(d, MappingProxyType):
        return d
    if isinstance(d, dict):
        return MappingProxyType(d)
    return d

FrozenDict = Annotated[dict[K, V], AfterValidator(_to_mapping_proxy)]

def _validate_iso8601_timestamp(v: str) -> str:
    if not isinstance(v, str):
        raise ValueError("Timestamp must be a string.")
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError as e:
        raise ValueError(f"Invalid ISO-8601 timestamp '{v}': {e}") from e
    return v

ISO8601Timestamp = Annotated[str, AfterValidator(_validate_iso8601_timestamp)]

def _validate_numpy_seed(v: str | int) -> str | int:
    try:
        val = int(v)
        if val < 0:
            raise ValueError("Seed must be a non-negative integer.")
        np.random.SeedSequence(val)
    except (ValueError, TypeError) as e:
        raise ValueError(
            f"Invalid seed '{v}': must be convertible to a non-negative interger for NumPy SeedSequence"
        ) from e
    return v

SeedPayload = Annotated[str | int, AfterValidator(_validate_numpy_seed)]

class FrozenConfigModel(BaseModel):
    """
    Base model enforcing strict immutability across all configuration structs.
    """
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        arbitrary_types_allowed=True,
        allow_inf_nan=False
    )

class SimulationMetadataConfig(FrozenConfigModel):
    seed: SeedPayload
    start_time: ISO8601Timestamp
    duration: TimeString
    data_resolution: TimeString
    epoch_interval: TimeString

class MetricDefinitionConfig(FrozenConfigModel):
    name: SanitizedString
    is_derivative: bool = False
    primitive_type: Literal["float", "int", "bool"] = "float"
    formula: Optional[str] = None

    @model_validator(mode="after")
    def _validate_derivative_formula(self) -> Self:
        if self.is_derivative:
            if not self.formula or not self.formula.strip():
                raise ValueError(
                    f"Metric '{self.name}' has is_derivative=True but no formula was provided."
                )
        else:
            if self.formula is not None and self.formula.strip():
                raise ValueError(
                    f"Non-derivative metric '{self.name}' must not specify a formula."
                )
        return self

class StateConfig(FrozenConfigModel):
    name: SanitizedString
    state_bounds: FrozenDict[str, BoundTuple]
    drift_rates: FrozenDict[str, float]
    volatilities: FrozenDict[str, float]
    boundary_stiffness: float = Field(gt=0.0, le=1.0)

class MacroShockConfig(FrozenConfigModel):
    name: SanitizedString
    probability_per_epoch: float = Field(ge=0.0, le=1.0)
    target_state: str
    instant_metric_overrides: dict[str, float]

class DeferralBaseProbabilitiesConfig(FrozenConfigModel):
    fulfillment: float = Field(ge=0.0,le=1.0)
    deferral: float = Field(ge=0.0, le=1.0)
    cancellation: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_probability_simplex(self) -> Self:
        total = self.fulfillment + self.deferral + self.cancellation
        if not math.isclose(total, 1.0, abs_tol=1e-5):
            raise ValueError(
                f"Deferral base probabilities must sum to 1.0, got {total:.5f} "
                f"(fulfillment={self.fulfillment}, deferral={self.deferral}, cancellation={self.cancellation})"
            )
        return self

class DeferralAgingRulesConfig(FrozenConfigModel):
    cancel_escalation_per_epoch: float = Field(ge=0.0, le=1.0)

class DeferralPolicyConfig(FrozenConfigModel):
    enabled: bool
    driver_metric: Optional[str] = None
    max_drift_ttl_epochs: int = Field(gt=0)
    base_probabilities: DeferralBaseProbabilitiesConfig
    aging_rules: DeferralAgingRulesConfig

class TogglesConfig(FrozenConfigModel):
    use_global_limits: bool = True
    use_global_behavior: bool = True
    use_global_macro_shock: bool = True
    enable_state_engine: bool = True
    enable_realism_filter: bool = True
    enable_malformations: bool = True

class EntityConfig(FrozenConfigModel):
    id: SanitizedString
    entity_type: Optional[str] = None
    initial_state: str
    initial_metrics: FrozenDict[str, float]
    metric_bounds: Optional[FrozenDict[str, BoundTuple]] = None
    behavior_states: Optional[tuple[StateConfig, ...]] = None
    macro_shocks: Optional[tuple[MacroShockConfig, ...]] = None
    deferral_policy: Optional[DeferralPolicyConfig] = None

class OutputFieldMappingConfig(FrozenConfigModel):
    name: SanitizedString
    source: str

class MetadataTogglesConfig(FrozenConfigModel):
    include_state: bool = True
    include_malformed_flag: bool = False
    include_true_baseline: bool = False

class OutputConfig(FrozenConfigModel):
    format: Literal["csv", "json"]
    path: Path
    fields: tuple[OutputFieldMappingConfig, ...]
    metadata_toggles: MetadataTogglesConfig

class SimulationConfig(FrozenConfigModel):
    simulation: SimulationMetadataConfig
    metrics: tuple[MetricDefinitionConfig, ...]
    toggles: TogglesConfig
    global_limits: Optional[FrozenDict[str, BoundTuple]] = None
    global_behavior_states: tuple[StateConfig, ...] = Field(default_factory=tuple)
    global_macro_shocks: tuple[MacroShockConfig, ...] = Field(default_factory=tuple)
    entities: tuple[EntityConfig, ...]
    output: OutputConfig