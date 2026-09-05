# Low Level Design Document

---

## 1.0 Config Reader

### 1.1 Purpose

This module is responsible for reading external YAML configuration files and constructing an immutable, deeply validated in-memory object graph (`SimulationConfig`) for the execution pipeline. Ingest occurs via a two-phase architecture: Phase 1 enforces structural typing and model constraints via Pydantic v2 schemas; Phase 2 enforces cross-field domain invariants, topological integrity, AST formula expression validation, and security containment. It executes zero simulation logic.

### 1.2 Inputs

* `config_path: Path | str` - File system path to the input `config.yaml` file

### 1.3 Outputs

* `SimulationConfig` - A frozen, immutable Pydantic root model representing the complete simulation contract.

* Raises `ConfigError` (or a specific subclass: `ConfigNotFoundError`, `InvalidSchemaError`, `InitialBoundsError`, `DimensionalMismatchError`) upon any ingestion failure

### 1.4 Invariants

1. **Immutability:** The returned `SimulationConfig` root model and all child sub-objects must be strictly immutable (`frozen = True` and `FrozenDict` / `MappingProxyType` attributes)

2. **Metric Dimension Consistency:** Every metric key referenced across state bounds, drift vectors, volatilities, baseline metrics, initial entity metrics, and deferral drivers must strictly map to declared degrees of freedom in `metrics`.

3. **Initial Coordinate Validity:** An entity's declared `initial_metrics` ($\mu_0$) must lie within the *N*-dimensional `state_bounds` of its declared `initial_state` and within top level `global_limits`.

4. **Probability Clamping:** All probability fields (`probability_per_epoch`, `fulfillment`, `deferral`, `cancellation`) and `boundary_stiffness` values must lie within the closed invterval [0.0,1.0].

5. **Time String ISO Format:** `duration`, `data_resolution`, and `epoch_interval` strings must conform to the quantity-unit regex `^\d+[s|m|h|d|w]$`.

6. **Time Hierarchy Enforcement:** Configured durations must satisfy the strict inequality sequence: $\text{data_resolution}\leq\text{epoch_interval}\leq\text{duration}$.

7. **Graph & DAG Acyclicity:** Workflows declared in `workflow_dag` and derivative metirc dependency chains in `metrics` must form directed acyclic graphs (DAGs), validated via Depth-First Search (DFS).

8. **Topology & Resource Mapping:** All network route endpoints in `network_topology` must exist within declared `nodes`, and all task resource requests in `workflow_dag` must target declared `resource_pools`.

9. **Security Containment & Capping:** Input YAML file size must not exceed 10MB (CWE-776). Output sink paths must resolve via `Path.resolve()` cleanly inside the active workspace or temp directory, explicitly rejecting path traversal attempts into restricted system directories (`/etc`, `/usr`, `C:\Windows`)(CWE-22).

### 1.5 Design Decisions

* **4-Tier Modular Decomposition:** Separates ingestion into `io.py` (file operations & size bounds), `schemas.py` (Pydantic v2 schemas), `invariants.py` (relational domain checks), `formulas.py` (AST formula parsing), `exceptions.py` (domain errors), and `reader.py` (orchestration layer).

* **Custom `FrozenDict` Schema Core:** Implements `__get_pydantic_core_schema__` on `MappingProxyType` to enforce immutable dictionary attributes without triggering Pydantic serialization warnings.

* **AST Formula Whitelisting:** Uses Python's `ast.NodeVisitor` to parse derivative expressions into an abstract syntax tree, enforcing strict node and function whitelists (`abs`, `min`, `max`, `clamp`, `sqrt`, `log`, `exp`, `pow`) while stripping `__builtins__`.

* **Pydantic V2 `BaseModel` with `frozen=True`:** Adopted to handle parsing, strict type validation, custom field validators, and zero-boilerplate immutability natively.

* **Fail-Fast Cross-Field Validation:** Validating N-dimensional key alignment and initial coordinate bounds during parsing prevents silent runtime failures deep into step $t = 1000$.

* **Canonical Path Resolution:** Uses `Path.resolve()` prior to directory containment checks to resolve symlinks and `..` segments before validating write permissions.

### 1.6 Data Structures

* Config models are organized across four schema tiers in `schemas.py`:

  * **Tier 1 (Primitives & Types):** `FrozenDict`, `ISO8601Duration`, `MetricType`, `RoutingType`.

  * **Tier 2 (Leaf Component Models):** `MetricsConfig`, `EntityConfig`, `TaskConfig`, `MacroShockConfig`, `SinkFieldConfig`.

  * **Tier 3 (Section Container Models):** `MetaConfig`, `SimulationParamsConfig`, `StateEngineConfig`, `NetworkTopologyConfig`, `SinkConfig`.

  * **Tier 4 (Root Contract):** `SimulationConfig` (aggregates all section models with `extra='forbid'`).

---

## 2.0 Nominal Generator

### 2.1 Purpose

Calculates determininistic, ideal-world targe state vector ($\mu_{\text{t,nominal}}$) for a target entity over the time step $t\to t + dt$. It establishes an uncorrupted operational baseline, assuming maximum velocity, zero dwell time, zero contention, and 100% efficiency, and is evaluated directly from the entity's active physical position in `EntityContext`. It serves as the foundational pass in the single-tick pipeline, providing the pure target baseline that downstream modules subsequently transform.

### 2.2 Inputs

* `entity_context` (`EntityContext`): Active state context for the entity at time $t$, containing current topological node/route, active DAG task ID, elapsed task duration and current metric state.

* `current_time` (`datetime`): Active simulation clock timestamp t.

* `dt` (`timedelta`): Time step resolution increment ($dt=t_{\text{next}}-t$).

* `config` (`SimulationConfig`): Master immutable configuration object containing global baseline metrics, entity overrides, topology specs, workflow DAGs, and metric declarations.

### 2.3 Outputs

* `NominalStateVector`: Immutable state dataclass containing:

  * `timestamp` (`str`): ISO-8601 formatted string for current time $t$.

  * `entity_id` (`str`): Unique identifier of the evaluated entity.

  * `current_node` (`str`): Active spatial node or topology location label at time $t$.

  * `metrics` (`dict[str, float]`): Dictionary of primitive uncorrupted metric baseline values for step $t$.

  * `derivative_metrics` (`dict[str, float]`): Dictionary of derived metrics evaluated via AST formulas on primitive nominal values

### 2.4 Invariants

* **Zero Noise and Friction Guarantee:** Noise standard deviation ($\sigma$), random pertubations, and macro operational shocks are strictly 0.0.

* **Infinite Resource Capacity:** Bypasses resource pool capacity constraints (`total_capacity`); queue dwell metrics (`queue_dwell_time_min`) are strictly forced to 0.0.

* **Metric Completeness Invariant:** The emitted `metrics` dictionary must contain 100% of all non-derivative primitive metric keys declared in `config.metrics`.

* **State Continuity:** Kinematic and task progress are evaluated relative to the entity's actual physical position at time $t$ (form `EntityContext`), preventing physical desynchronization between nominal intent and actual actions.

* **Kinematic Speed Constraint:** Transit velocity cannot exceed `max_route_speed` or global upper velocity bounds.

### 2.5 Design Decisions
* **Context-Anchored Evaluation (O(1) Memory):** Instead of pre-computing multi-day time series or running parallel "ghost" schedules, the nominal generator calculates step progress from the entitiy's active context at $t$. If an entity was blocked in step $t-dt$, the generator evaluates ideal movement forward from that blocked position for step $t$.

* **Strict Metric Resolution Hierarchy:** Primitive metric defaults are resolved using an all-or-nothing approach per entity:

  * If `entities[i].initial_metrics` is defined, all primitive metrics are read from this map.

  * Otherwise, all primitive metrics fallback to `nominal_generator.baseline_metrics`.

  * Partial key merging across entity and global baseline dictionaries is prohibited.

* **Inline AST Formula Resolution:** Derived metrics are computed dynamically at each tick by passing the nominal primitive values into `formulas.py`, ensuring AST evaluations reflect the ideal baseline conditions.

### 2.6 Data Structures

---

## 3.0 State Engine

### 3.1 Purpose

### 3.2 Inputs

### 3.3 Outputs

### 3.4 Invariants

### 3.5 Design Decisions

### 3.6 Data Structures

---

## 4.0 Realism Filter

### 4.1 Purpose

### 4.2 Inputs

### 4.3 Outputs

### 4.4 Invariants

### 4.5 Design Decisions

### 4.6 Data Structures

---

## 5.0 Malformations Filter

### 5.1 Purpose

### 5.2 Inputs

### 5.3 Outputs

### 5.4 Invariants

### 5.5 Design Decisions

### 5.6 Data Structures

---

## 6.0 File Sink

### 6.1 Purpose

### 6.2 Inputs

### 6.3 Outputs

### 6.4 Invariants

### 6.5 Design Decisions

### 6.6 Data Structures