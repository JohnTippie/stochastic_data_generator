from typing import Literal, Optional
from pathlib import Path
from pydantic import (
    BaseModel,
    ConfigDict,
    Field
)

# ================================================
# FROZEN CONFIGURATION MODELS
# ================================================
TIME_STRING_PATTERN = r"^\d+[smhdw]$"

class FrozenConfigModel(BaseModel):
    """
    Base model enforcing strict immutability across all configuration structs.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

class SimulationMetadataConfig(FrozenConfigModel):
    seed: str
    start_time: str
    duration: str = Field(pattern=TIME_STRING_PATTERN)
    data_resolution: str = Field(pattern=TIME_STRING_PATTERN)
    epoch_interval: str = Field(pattern=TIME_STRING_PATTERN)

class MetricDefinitionConfig(FrozenConfigModel):
    name: str
    is_derivative: bool = False
    primitive_type: Literal["float", "int", "bool"] = "float"

class StateConfig(FrozenConfigModel):
    name: str
    state_bounds: dict[str, tuple[float, float]]
    drift_rates: dict[str, float]
    volatilities: dict[str, float]
    boundary_stiffness: float = Field(ge=0.0, le=1.0)

class MacroShockConfig(FrozenConfigModel):
    name: str
    probability_per_epoch: float = Field(ge=0.0, le=1.0)
    target_state: str
    instant_metric_overrides: dict[str, float]

class DeferralBaseProbabilitiesConfig(FrozenConfigModel):
    fulfillment: float = Field(ge=0.0,le=1.0)
    deferral: float = Field(ge=0.0, le=1.0)
    cancellation: float = Field(ge=0.0, le=1.0)

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
    id: str
    entity_type: Optional[str] = None
    initial_state: str
    initial_metrics: dict[str, float]
    metric_bounds: Optional[dict[str, tuple[float, float]]] = None
    behavior_states: Optional[list[StateConfig]] = None
    macro_shocks: Optional[list[MacroShockConfig]] = None
    deferral_policy: Optional[DeferralPolicyConfig] = None

class OutputFieldMappingConfig(FrozenConfigModel):
    name: str
    source: str

class MetadataTogglesConfig(FrozenConfigModel):
    include_state: bool = True
    include_malformed_flag: bool = False
    include_true_baseline: bool = False

class OutputConfig(FrozenConfigModel):
    format: Literal["csv", "json"]
    path: Path
    fields: list[OutputFieldMappingConfig]
    metadata_toggles: MetadataTogglesConfig

class SimulationConfig(FrozenConfigModel):
    simulation: SimulationMetadataConfig
    metrics: list[MetricDefinitionConfig]
    toggles: TogglesConfig
    global_limits: Optional[dict[str, tuple[float, float]]] = None
    global_behavior_states: list[StateConfig] = Field(default_factory=list)
    global_macro_shocks: list[MacroShockConfig] = Field(default_factory=list)
    entities: list[EntityConfig]
    output: OutputConfig