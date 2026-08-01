# Low Level Design Document

---

## 1.0 Config Reader

### 1.1 Purpose

This module is responsible for parsing external YAML configuration files and constructing an immutable, deeply validated in-memory object graph (`SimulationConfig`) for the engine. It performs fail-fast structural and semantic validation (e.g., asserting initial metric coordinates $\mu_0$ lie inside starting state bounds and verifying metric key alignment across N-dimensions). It executes no simulation logic and performs no dynamic defaults interpolation beyond declared schema fallbacks.

### 1.2 Inputs

* `config_path: Path | str` - File system path to the input `config.yaml` file

### 1.3 Outputs

* `SimulationConfig` - A frozen, immutable Pydantic root model representing the complete simulation contract.

* Raises `ConfigError` (or a specific subclass: `ConfigNotFoundError`, `InvalidSchemaError`, `InitialBoundsError`, `DimensionalMismatchError`) upon any ingestion failure

### 1.4 Invariants

1. **Immutability:** The returned `SimulationConfig` root model and all child objects must be strictly immutable (`frozen = True`)

2. **Metric Dimension Consistency:** Every metric key referenced inside `global_limits`, `state_bounds`, `drift_rates`, `volatilities`, and `initial_metrics` must match the manifest defined under top-level `metrics`.

3. **Initial Coordinate Validity:** An entity's declared `initial_metrics` ($\mu_0$) must lie strictly inside the N-dimensional `state_bounds` of its declared `initial_state` and within its global or entity-specific `metric_bounds`.

4. **Probability Clamping:** All probability fields (`probability_per_epoch`, `fulfillment`, `deferral`, `cancellation`) and `boundary_stiffness` values must lie within the closed invterval [0.0,1.0].

5. **Time String ISO Format:** `duration`, `data_resolution`, and `epoch_interval` strings must conform to the quantity-unit regex `^\d+[s|m|h|d|w]$`.

### 1.5 Design Decisions

* **Pydantic V2 `BaseModel` with `frozen=True`:** Adopted to handle parsing, strict type validation, custom field validators, and zero-boilerplate immutability natively.

* **Fail-Fast Cross-Field Validation:** Validating N-dimensional key alignment and initial coordinate bounds during parsing prevents silent runtime failures deep into step $t = 1000$.

* **Path-Based File Ingestion:** Using Python's `pathlib.Path` ensures cross-platform path resolution (POSIX/Windows).

### 1.6 Data Structures

```python
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple
from pydantic import BaseModel, Field, ConfigDict

# Base model enforcing strict immutability across all configuration structs
class FrozenConfigModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SimulationMetadataConfig(FrozenConfigModel):
    seed: str
    start_time: str
    duration: str
    data_resolution: str
    epoch_interval: str


class MetricDefinitionConfig(FrozenConfigModel):
    name: str
    is_derivative: bool = False
    primitive_type: Literal["float", "int", "bool"] = "float"


class StateConfig(FrozenConfigModel):
    name: str
    state_bounds: Dict[str, Tuple[float, float]]  # e.g., {"metric_1": (85.0, 100.0)}
    drift_rates: Dict[str, float]                 # e.g., {"metric_1": 0.1}
    volatilities: Dict[str, float]                # e.g., {"metric_1": 0.5}
    boundary_stiffness: float = Field(ge=0.0, le=1.0)


class MacroShockConfig(FrozenConfigModel):
    name: str
    probability_per_epoch: float = Field(ge=0.0, le=1.0)
    target_state: str
    instant_metric_overrides: Dict[str, float]


class DeferralBaseProbabilitiesConfig(FrozenConfigModel):
    fulfillment: float = Field(ge=0.0, le=1.0)
    deferral: float = Field(ge=0.0, le=1.0)
    cancellation: float = Field(ge=0.0, le=1.0)


class DeferralAgingRulesConfig(FrozenConfigModel):
    cancel_escalation_per_epoch: float = Field(ge=0.0, le=1.0)


class DeferralPolicyConfig(FrozenConfigModel):
    enabled: bool
    driver_metric: str
    max_drift_ttl_epochs: int = Field(gt=0)
    base_probabilities: DeferralBaseProbabilitiesConfig
    aging_rules: DeferralAgingRulesConfig


class TogglesConfig(FrozenConfigModel):
    use_global_limits: bool = True
    use_global_behavior: bool = True
    use_global_macro_shock: bool = True


class EntityConfig(FrozenConfigModel):
    id: str
    entity_type: Optional[str] = None
    initial_state: str
    initial_metrics: Dict[str, float]
    metric_bounds: Optional[Dict[str, Tuple[float, float]]] = None
    behavior_states: Optional[List[StateConfig]] = None
    macro_shocks: Optional[List[MacroShockConfig]] = None
    deferral_policy: DeferralPolicyConfig


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
    fields: List[OutputFieldMappingConfig]
    metadata_toggles: MetadataTogglesConfig


class SimulationConfig(FrozenConfigModel):
    simulation: SimulationMetadataConfig
    metrics: List[MetricDefinitionConfig]
    toggles: TogglesConfig
    global_limits: Dict[str, Tuple[float, float]]
    global_behavior_states: List[StateConfig]
    global_macro_shocks: List[MacroShockConfig]
    entities: List[EntityConfig]
    output: OutputConfig
```

### 1.7 Function Signatures

```python
# Custom Exception Hierarchy for Config Ingestion
class ConfigError(Exception):
    """Base exception for all configuration ingestion failures."""
    pass

class ConfigNotFoundError(ConfigError):
    """Raised when the target YAML file does not exist on disk."""
    pass

class InvalidSchemaError(ConfigError):
    """Raised when YAML structure fails Pydantic type validation."""
    pass

class DimensionalMismatchError(ConfigError):
    """Raised when state bounds/drift rates do not match defined metric keys."""
    pass

class InitialBoundsError(ConfigError):
    """Raised when an entity's initial_metrics lie outside its state or metric bounds."""
    pass


class ConfigReader:
    """Reads, validates, and constructs immutable SimulationConfig instances."""

    @classmethod
    def load_config(cls, config_path: Path | str) -> SimulationConfig:
        """
        Parses a YAML configuration file into a frozen SimulationConfig object hierarchy.

        Args:
            config_path: Path to the target YAML configuration file.

        Returns:
            SimulationConfig: Immutable, fully validated configuration object graph.

        Raises:
            ConfigNotFoundError: If file path is invalid or unreadable.
            InvalidSchemaError: If YAML fails Pydantic schema verification.
            DimensionalMismatchError: If metric keys across states/metrics disagree.
            InitialBoundsError: If initial entity coordinates lie outside bounding boxes.
        """
        ...

    @classmethod
    def _validate_dimensional_alignment(cls, config: SimulationConfig) -> None:
        """Private validator: Ensures all state metric keys exist in the metrics manifest."""
        ...

    @classmethod
    def _validate_initial_coordinates(cls, config: SimulationConfig) -> None:
        """Private validator: Ensures mu_0 lies inside initial_state bounds for all entities."""
        ...
```

---

## 2.0 Nominal Generator

### 2.1 Purpose

### 2.2 Inputs

### 2.3 Outputs

### 2.4 Invariants

### 2.5 Design Decisions

### 2.6 Data Structures

### 2.7 Function Signatures

---

## 3.0 State Engine

### 3.1 Purpose

### 3.2 Inputs

### 3.3 Outputs

### 3.4 Invariants

### 3.5 Design Decisions

### 3.6 Data Structures

### 3.7 Function Signatures

---

## 4.0 Realism Filter

### 4.1 Purpose

### 4.2 Inputs

### 4.3 Outputs

### 4.4 Invariants

### 4.5 Design Decisions

### 4.6 Data Structures

### 4.7 Function Signatures

---

## 5.0 Malformations Filter

### 5.1 Purpose

### 5.2 Inputs

### 5.3 Outputs

### 5.4 Invariants

### 5.5 Design Decisions

### 5.6 Data Structures

### 5.7 Function Signatures

---

## 6.0 File Sink

### 6.1 Purpose

### 6.2 Inputs

### 6.3 Outputs

### 6.4 Invariants

### 6.5 Design Decisions

### 6.6 Data Structures

### 6.7 Function Signatures