import math
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Any, Literal, get_args, Optional, Self, TypeVar

import numpy as np
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    GetCoreSchemaHandler,
    model_validator,
    PlainSerializer
)
from pydantic_core import core_schema

# ==============================================================================
# HELPERS & UTILITIES
# ==============================================================================
TIME_STRING_PATTERN = r"^\d+[smhdw]$"

K = TypeVar("K")
V = TypeVar("V")

class _FrozenDictAnnotation:
    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        args = get_args(source_type)
        dict_type = dict[args[0], args[1]] if len(args) == 2 else dict

        dict_schema = handler.generate_schema(dict_type)

        return core_schema.no_info_after_validator_function(
            lambda v: v if isinstance(v, MappingProxyType) else MappingProxyType(v),
            dict_schema, 
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda v: dict(v) if isinstance(v, MappingProxyType) else v,
                return_schema=dict_schema
            )
        )

def _validate_sanitized_identifier(v: str) -> str:
    if not v or not v.strip():
        raise ValueError("Identifier cannot be empty or pure whitespace.")
    if v != v.strip():
        raise ValueError("Identifier cannot contain leading or trailing whitespace.")
    return v

def _validate_bounds_range(bounds: tuple[float, float]) -> tuple[float, float]:
    if len(bounds) == 2:
        min_v, max_v = bounds
        if min_v > max_v:
            raise ValueError(f"Lower bound ({min_v}) must be <= upper bound ({max_v}).")
    return bounds

def _to_mapping_proxy(d: Any) -> Any:
    if d is None or isinstance(d, MappingProxyType):
        return d
    if isinstance(d, dict):
        return MappingProxyType(d)
    return d

def _dump_mapping_proxy(v: Any) -> dict:
    if isinstance(v, MappingProxyType):
        return dict(v)
    return v

def _validate_iso8601_timestamp(v: str) -> str:
    if not isinstance(v, str):
        raise ValueError("Timestamp must be a string.")
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError as e:
        raise ValueError(f"Invalid ISO-8601 timestamp '{v}': {e}") from e
    return v

def _validate_numpy_seed(v: int) -> int:
    try:
        val = int(v)
        if val < 0:
            raise ValueError("Seed must be a non-negative integer.")
        np.random.SeedSequence(val)
    except (ValueError, TypeError) as e:
        raise ValueError(
            f"Invalid seed '{v}': must be convertible to a non-negative integer for NumPy SeedSequence."
        ) from e
    return v

def _assert_sum_to_one(total: float, context: str) -> None:
    if not math.isclose(total, 1.0, abs_tol=1e-4):
        raise ValueError(f"{context} must sum to 1.0, got {total:.4f}.")

# ==============================================================================
# TIER 1: BASE TYPES & CUSTOM ALIASES
# ==============================================================================
PrimitiveValue = float | int | bool | str
TimeString = Annotated[str, Field(pattern=TIME_STRING_PATTERN)]
SanitizedString = Annotated[str, AfterValidator(_validate_sanitized_identifier)]
BoundTuple = Annotated[tuple[float, float], AfterValidator(_validate_bounds_range)]
FrozenDict = Annotated[MappingProxyType[K, V], _FrozenDictAnnotation]
ISO8601Timestamp = Annotated[str, AfterValidator(_validate_iso8601_timestamp)]
SeedPayload = Annotated[str | int, AfterValidator(_validate_numpy_seed)]

class FrozenConfigModel(BaseModel):
    """Base model enforcing strict immutability across all configuration structs."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        arbitrary_types_allowed=True,
        allow_inf_nan=False,
    )

# ==============================================================================
# TIER 2: LEAF MODELS
# ==============================================================================
class MetaConfig(FrozenConfigModel):
    scenario_name: SanitizedString
    description: SanitizedString
    seed: SeedPayload

class SimulationParamsConfig(FrozenConfigModel):
    start_time: ISO8601Timestamp
    duration: TimeString
    data_resolution: TimeString
    epoch_interval: TimeString

class PipelineTogglesConfig(FrozenConfigModel):
    use_state_engine: bool
    use_network_topology: bool
    use_resource_contention: bool
    use_workflow_dag: bool
    use_realism_filter: bool
    use_malformations_filter: bool

class MetricsConfig(FrozenConfigModel):
    name: SanitizedString
    is_derivative: bool
    primitive_type: Literal["float", "int", "bool"] = "float"
    formula: Optional[SanitizedString] = None

    @model_validator(mode="after")
    def _validate_derivative_formula(self) -> Self:
        if self.is_derivative:
            if not self.formula or not self.formula.strip():
                raise ValueError(
                    f"Metric '{self.name}' has is_derivative=True but no formula was provided."
                )
        elif self.formula is not None and self.formula.strip():
            raise ValueError(
                f"Non-derivative metric '{self.name}' must not specify a formula."
            )
        return self

class RouteConfig(FrozenConfigModel):
    distance_miles: float = Field(gt=0.0)
    nominal_travel_time_min: int = Field(gt=0)
    max_throughput_capacity: int = Field(gt=0)
    max_route_speed: int = Field(gt=0)

class AdjacencyConfig(FrozenConfigModel):
    destination: SanitizedString
    weight: float = Field(ge=0.0, le=1.0)

class PoolConfig(FrozenConfigModel):
    id: SanitizedString
    total_capacity: int = Field(gt=0)
    queue_policy: Literal["FIFO", "PRIORITY_QUEUE", "LIFO"] = "FIFO"
    queue_contention_penalty_min: float = Field(gt=0.0)

class DAGTaskConfig(FrozenConfigModel):
    task_id: SanitizedString
    nominal_duration_min: int = Field(gt=0)
    predecessors: tuple[SanitizedString, ...] = ()
    required_resource_pool: Optional[SanitizedString] = None

class NominalGeneratorConfig(FrozenConfigModel):
    baseline_metrics: FrozenDict[SanitizedString, PrimitiveValue]

class StateBehaviorConfig(FrozenConfigModel):
    state_bounds: FrozenDict[SanitizedString, BoundTuple]
    drift_rates: FrozenDict[SanitizedString, float] = Field(default_factory=dict)
    volatilities: FrozenDict[SanitizedString, float] = Field(default_factory=dict)
    boundary_stiffness: float = Field(ge=0.0, le=1.0)

class MacroShockConfig(FrozenConfigModel):
    name: SanitizedString
    probability_per_epoch: float = Field(ge=0.0, le=1.0)
    target_state: SanitizedString
    instant_metric_overrides: FrozenDict[SanitizedString, float]

class DeferralBaseProbabilitiesConfig(FrozenConfigModel):
    fulfillment: float = Field(ge=0.0, le=1.0)
    deferral: float = Field(ge=0.0, le=1.0)
    cancellation: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_sum_to_one(self) -> Self:
        _assert_sum_to_one(
            self.fulfillment + self.deferral + self.cancellation,
            context="Base probabilities",
        )
        return self

class AgingRulesConfig(FrozenConfigModel):
    cancel_escalation_per_epoch: float = Field(ge=0.0)

class DeferralPolicyConfig(FrozenConfigModel):
    enabled: bool = True
    driver_metric: Optional[SanitizedString] = None
    max_drift_ttl_epochs: Optional[int] = Field(default=None, gt=0)
    base_probabilities: Optional[DeferralBaseProbabilitiesConfig] = None
    aging_rules: Optional[AgingRulesConfig] = None

    @model_validator(mode="after")
    def _validate_enabled_requirements(self) -> Self:
        if self.enabled:
            if not self.driver_metric:
                raise ValueError(
                    "Field 'driver_metric' is required when deferral policy is enabled."
                )
            if self.max_drift_ttl_epochs is None:
                raise ValueError(
                    "Field 'max_drift_ttl_epochs' is required when deferral policy is enabled."
                )
            if self.base_probabilities is None:
                raise ValueError(
                    "Field 'base_probabilities' is required when deferral policy is enabled."
                )
        return self

class CorruptionRuleConfig(FrozenConfigModel):
    type: Literal["null_injection", "out_of_range_spike", "string_formatting_error"]
    probability: float = Field(ge=0.0, le=1.0)
    target_fields: tuple[SanitizedString, ...]
    spike_value: Optional[float] = None
    corrupted_value: Optional[PrimitiveValue] = None

    @model_validator(mode="after")
    def _validate_payload_requirements(self) -> Self:
        if self.type == "out_of_range_spike" and self.spike_value is None:
            raise ValueError(
                "Field 'spike_value' is required when rule type is 'out_of_range_spike'."
            )
        if self.type == "string_formatting_error" and self.corrupted_value is None:
            raise ValueError(
                "Field 'corrupted_value' is required when rule type is 'string_formatting_error'."
            )
        return self

class EntityConfig(FrozenConfigModel):
    id: SanitizedString
    entity_type: SanitizedString
    initial_location: SanitizedString
    initial_state: SanitizedString
    initial_metrics: FrozenDict[SanitizedString, PrimitiveValue]

class SinkMetadataTogglesConfig(FrozenConfigModel):
    include_state: bool = True
    include_malformed_flag: bool = True
    include_true_baseline: bool = False

class SinkFieldConfig(FrozenConfigModel):
    name: SanitizedString
    source: SanitizedString

# ==============================================================================
# TIER 3: SECTION CONTAINERS
# ==============================================================================
class NetworkTopologyConfig(FrozenConfigModel):
    routing_type: SanitizedString
    network_class: Literal["linear"] = "linear"
    nodes: tuple[SanitizedString, ...]
    use_defined_routes: bool = True
    routes: Optional[FrozenDict[SanitizedString, RouteConfig]] = None
    adjacency_matrix: Optional[
        FrozenDict[SanitizedString, tuple[AdjacencyConfig, ...]]
    ] = None

    @model_validator(mode="after")
    def _validate_routing_dependencies(self) -> Self:
        if self.use_defined_routes and not self.routes:
            raise ValueError(
                "Field 'routes' is required when 'use_defined_routes' is true."
            )
        if not self.use_defined_routes and not self.adjacency_matrix:
            raise ValueError(
                "Field 'adjacency_matrix' is required when 'use_defined_routes' is false."
            )
        return self

    @field_validator("routes")
    @classmethod
    def _validate_route_speed(
        cls, routes: Optional[FrozenDict[str, RouteConfig]]
    ) -> Optional[FrozenDict[str, RouteConfig]]:
        if routes is None:
            return routes

        for route_name, r in routes.items():
            travel_hours = r.nominal_travel_time_min / 60.0
            required_speed = r.distance_miles / travel_hours
            if required_speed > r.max_route_speed:
                raise ValueError(
                    f"Route '{route_name}' is invalid: required speed ({required_speed:.1f} mph) "
                    f"exceeds max supported speed ({r.max_route_speed} mph)."
                )
        return routes

    @field_validator("adjacency_matrix")
    @classmethod
    def _validate_probabilities(
        cls, adj_matrix: Optional[FrozenDict[str, tuple[AdjacencyConfig, ...]]]
    ) -> Optional[FrozenDict[str, tuple[AdjacencyConfig, ...]]]:
        if adj_matrix is None:
            return adj_matrix

        for origin, edges in adj_matrix.items():
            total_weight = sum(edge.weight for edge in edges)
            _assert_sum_to_one(
                total_weight, context=f"Origin node '{origin}' adjacency weights"
            )
        return adj_matrix

class WorkflowDagConfig(FrozenConfigModel):
    tasks: tuple[DAGTaskConfig, ...]

class StateEngineConfig(FrozenConfigModel):
    initial_state: SanitizedString
    states: FrozenDict[SanitizedString, StateBehaviorConfig]
    transition_matrix: FrozenDict[
        SanitizedString, FrozenDict[SanitizedString, float]
    ]
    macro_shocks: tuple[MacroShockConfig, ...] = ()

    @field_validator("transition_matrix")
    @classmethod
    def _validate_transition_matrix_rows(
        cls, matrix: Optional[FrozenDict[str, FrozenDict[str, float]]]
    ) -> Optional[FrozenDict[str, FrozenDict[str, float]]]:
        if matrix is None:
            return matrix

        for origin_state, transitions in matrix.items():
            if not transitions:
                raise ValueError(
                    f"Transition row for origin state '{origin_state}' cannot be empty."
                )
            _assert_sum_to_one(
                sum(transitions.values()),
                context=f"Transition probabilities from state '{origin_state}'",
            )
        return matrix

class RealismFilterConfig(FrozenConfigModel):
    deferral_policy: Optional[DeferralPolicyConfig] = None
    global_limits: Optional[FrozenDict[SanitizedString, BoundTuple]] = None

class MalformationsFilterConfig(FrozenConfigModel):
    enabled: bool = True
    corruption_rules: tuple[CorruptionRuleConfig, ...] = ()

class SinkConfig(FrozenConfigModel):
    format: Literal["csv", "json", "parquet"] = "csv"
    output_path: Path
    metadata_toggles: SinkMetadataTogglesConfig
    fields: tuple[SinkFieldConfig, ...]

# ==============================================================================
# TIER 4: ROOT MODEL
# ==============================================================================
class SimulationConfig(FrozenConfigModel):
    meta: MetaConfig
    simulation: SimulationParamsConfig
    pipeline_toggles: PipelineTogglesConfig
    metrics: tuple[MetricsConfig, ...]
    network_topology: Optional[NetworkTopologyConfig] = None
    resource_pools: Optional[tuple[PoolConfig, ...]] = None
    workflow_dag: Optional[WorkflowDagConfig] = None
    nominal_generator: NominalGeneratorConfig
    state_engine: Optional[StateEngineConfig] = None
    realism_filter: Optional[RealismFilterConfig] = None
    malformations_filter: Optional[MalformationsFilterConfig] = None
    entities: tuple[EntityConfig, ...] = ()
    sink: SinkConfig