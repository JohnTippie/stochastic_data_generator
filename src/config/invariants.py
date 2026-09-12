import os
import tempfile
import re
from pathlib import Path
from typing import Iterable
from datetime import timedelta

from .exceptions import DimensionalMismatchError, InitialBoundsError, InvalidSchemaError
from .schemas import SimulationConfig
from .formulas import validate_derivative_metric_formulas

TIME_UNIT_MULTIPLIERS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}

TIME_UNIT_DURATIONS = {
    's': timedelta(seconds=1),
    'm': timedelta(minutes=1),
    'h': timedelta(hours=1),
    'd': timedelta(days=1),
    'w': timedelta(weeks=1)
}

ALLOWED_SYSTEM_SOURCES = {
    "system.timestamp",
    "system.state_label",
    "system.current_location",
    "system.backlog_depth",
    "system.is_malformed",
    "entity.id",
    "entity.type",
}

BLOCKED_SYSTEM_PATHS = (
    Path("/etc"),
    Path("/usr"),
    Path("/var"),
    Path("/bin"),
    Path("/sbin"),
    Path("/lib"),
    Path("/root"),
    Path("/boot"),
    Path("C:/Windows"),
    Path("C:/Program Files"),
    Path("C:/Program Files (x86)"),
)

def validate_domain_invariants(config: SimulationConfig) -> None:
    """Executes all Phase 2 domain and relational integrity checks against a loaded SimulationConfig."""
    _validate_toggle_data_alignment(config)
    _validate_unique_metric_names(config)
    validate_derivative_metric_formulas(config.metrics)
    _validate_unique_entity_ids(config)
    _validate_time_hierarchy(config)
    _validate_dimensional_alignment(config)
    _validate_topology_integrity(config)
    _validate_workflow_and_resources(config)
    _validate_state_engine_integrity(config)
    _validate_initial_coordinates(config)
    _validate_sink_sources(config)
    _validate_output_path(config)

# ==============================================================================
# HELPERS
# ==============================================================================

def _parse_time_string_to_seconds(time_str: str) -> int:
    unit = time_str[-1]
    value = float(time_str[:-1])
    
    if value <= 0:
        raise InvalidSchemaError(f"Time duration '{time_str}' must be strictly greater than 0.")
        
    return value * TIME_UNIT_MULTIPLIERS[unit]

def _check_metric_keys_exact(keys: Iterable[str], expected_names: set[str], context: str) -> None:
    keys_set = set(keys)
    if keys_set != expected_names:
        missing = expected_names - keys_set
        extra = keys_set - expected_names
        details = []
        if missing:
            details.append(f"missing required metrics: {sorted(missing)}")
        if extra:
            details.append(f"unexpected extra metrics: {sorted(extra)}")
        raise DimensionalMismatchError(
            f"Dimensional mismatch in {context}: {', '.join(details)}. "
            f"Expected exact set {sorted(expected_names)}."
        )

def _check_metric_keys_subset(keys: Iterable[str], allowed_names: set[str], context: str) -> None:
    keys_set = set(keys)
    if not keys_set.issubset(allowed_names):
        unknown = keys_set - allowed_names
        raise DimensionalMismatchError(
            f"Unrecognized metrics in {context}: {sorted(unknown)}. "
            f"Must be a subset of declared non-derivative metrics: {sorted(allowed_names)}."
        )

def parse_duration_string(duration_str: str) -> timedelta:
    match = re.match(r"^(\d+)([smhdw])$", duration_str.strip())
    if not match:
        raise ValueError(f"Invalid duration string format: '{duration_str}'")
    val, unit = int(match.group(1)), match.group(2)
    return val * TIME_UNIT_DURATIONS[unit]

# ==============================================================================
# INDIVIDUAL DOMAIN INVARIANTS
# ==============================================================================

def _validate_toggle_data_alignment(config: SimulationConfig) -> None:
    t = config.pipeline_toggles
    checks = [
        (t.use_state_engine, config.state_engine, "state_engine"),
        (t.use_network_topology, config.network_topology, "network_topology"),
        (t.use_resource_contention, config.resource_pools, "resource_pools"),
        (t.use_workflow_dag, config.workflow_dag, "workflow_dag"),
        (t.use_realism_filter, config.realism_filter, "realism_filter"),
        (t.use_malformations_filter, config.malformations_filter, "malformations_filter"),
    ]
    for toggle_val, section_obj, section_name in checks:
        if toggle_val and section_obj is None:
            raise InvalidSchemaError(
                f"Pipeline toggle '{section_name}' is set to True, but section '{section_name}' is missing."
            )

def _validate_unique_metric_names(config: SimulationConfig) -> None:
    seen: set[str] = set()
    for metric in config.metrics:
        if metric.name in seen:
            raise InvalidSchemaError(f"Duplicate metric name '{metric.name}' found in metrics manifest.")
        seen.add(metric.name)

def _validate_unique_entity_ids(config: SimulationConfig) -> None:
    seen: set[str] = set()
    for entity in config.entities:
        if entity.id in seen:
            raise InvalidSchemaError(f"Duplicate entity ID '{entity.id}' found in entities list.")
        seen.add(entity.id)

def _validate_time_hierarchy(config: SimulationConfig) -> None:
    res_sec = _parse_time_string_to_seconds(config.simulation.data_resolution)
    epoch_sec = _parse_time_string_to_seconds(config.simulation.epoch_interval)
    dur_sec = _parse_time_string_to_seconds(config.simulation.duration)

    if res_sec > epoch_sec:
        raise InvalidSchemaError(
            f"Time hierarchy error: data_resolution ('{config.simulation.data_resolution}') "
            f"cannot exceed epoch_interval ('{config.simulation.epoch_interval}')."
        )
    if epoch_sec > dur_sec:
        raise InvalidSchemaError(
            f"Time hierarchy error: epoch_interval ('{config.simulation.epoch_interval}') "
            f"cannot exceed duration ('{config.simulation.duration}')."
        )

    """ CWE-400 guard """
    total_steps = (dur_sec / res_sec) <= 10000000
    if not total_steps:
        raise InvalidSchemaError(f"The current duration and resolution combination exceed 10,000,000 maximum data points")

def _validate_dimensional_alignment(config: SimulationConfig) -> None:
    all_metrics = {m.name for m in config.metrics}
    non_deriv_metrics = {m.name for m in config.metrics if not m.is_derivative}

    # 1. Baseline generator alignment
    _check_metric_keys_exact(
        config.nominal_generator.baseline_metrics.keys(),
        non_deriv_metrics,
        "nominal_generator.baseline_metrics",
    )

    # 2. State engine behavior metrics alignment
    if config.state_engine:
        for s_name, s_cfg in config.state_engine.states.items():
            _check_metric_keys_exact(s_cfg.state_bounds.keys(), non_deriv_metrics, f"state_bounds in state '{s_name}'")
            _check_metric_keys_subset(s_cfg.drift_rates.keys(), non_deriv_metrics, f"drift_rates in state '{s_name}'")
            _check_metric_keys_subset(s_cfg.volatilities.keys(), non_deriv_metrics, f"volatilities in state '{s_name}'")

    # 3. Global limits alignment
    if config.realism_filter and config.realism_filter.global_limits:
        _check_metric_keys_exact(
            config.realism_filter.global_limits.keys(),
            non_deriv_metrics,
            "realism_filter.global_limits",
        )

    # 4. Deferral policy driver metric check
    if config.realism_filter and config.realism_filter.deferral_policy:
        policy = config.realism_filter.deferral_policy
        if policy.enabled and policy.driver_metric and policy.driver_metric not in all_metrics:
            raise DimensionalMismatchError(
                f"Deferral policy driver_metric '{policy.driver_metric}' is not declared in top-level metrics."
            )

    # 5. Entity initial metrics alignment
    for entity in config.entities:
        _check_metric_keys_exact(
            entity.initial_metrics.keys(),
            non_deriv_metrics,
            f"initial_metrics for entity '{entity.id}'",
        )

def _validate_topology_integrity(config: SimulationConfig) -> None:
    if not config.network_topology:
        return

    topo = config.network_topology
    declared_nodes = set(topo.nodes)

    # Validate explicit routes
    if topo.use_defined_routes and topo.routes:
        for route_key in topo.routes.keys():
            if "->" not in route_key:
                raise InvalidSchemaError(f"Route key '{route_key}' must follow 'ORIGIN->DESTINATION' syntax.")
            origin, dest = route_key.split("->", 1)
            missing = {origin, dest} - declared_nodes
            if missing:
                raise InvalidSchemaError(
                    f"Route '{route_key}' references undeclared node(s): {sorted(missing)}."
                )

    # Validate stochastic adjacency matrix
    if not topo.use_defined_routes and topo.adjacency_matrix:
        for origin, edges in topo.adjacency_matrix.items():
            if origin not in declared_nodes:
                raise InvalidSchemaError(f"Adjacency origin node '{origin}' is not in declared nodes list.")
            for edge in edges:
                if edge.destination not in declared_nodes:
                    raise InvalidSchemaError(
                        f"Adjacency edge from '{origin}' references undeclared destination '{edge.destination}'."
                    )

def _validate_state_engine_integrity(config: SimulationConfig) -> None:
    if not config.state_engine:
        return

    engine = config.state_engine
    declared_states = set(engine.states.keys())
    non_deriv_metrics = {m.name for m in config.metrics if not m.is_derivative}

    # 1. Initial state existence
    if engine.initial_state not in declared_states:
        raise InvalidSchemaError(
            f"State engine initial_state '{engine.initial_state}' does not exist in declared states."
        )

    # 2. Transition matrix completeness & relational/probability checks
    missing_rows = declared_states - set(engine.transition_matrix.keys())
    if missing_rows:
        raise InvalidSchemaError(
            f"State transition matrix is incomplete; missing row definitions for state(s): {missing_rows}"
        )

    for origin_state, targets in engine.transition_matrix.items():
        if origin_state not in declared_states:
            raise InvalidSchemaError(
                f"Transition matrix contains undeclared origin state '{origin_state}'."
            )
        for target_state, prob in targets.items():
            if target_state not in declared_states:
                raise InvalidSchemaError(
                    f"Transition row for state '{origin_state}' references undeclared destination state '{target_state}'."
                )
            if not (0.0 <= prob <= 1.0):
                raise InvalidSchemaError(
                    f"Transition probability from '{origin_state}' to '{target_state}' ({prob}) "
                    f"must lie within closed interval [0.0, 1.0]."
                )

    # 3. Macro shock validation
    for shock in engine.macro_shocks:
        if shock.target_state not in declared_states:
            raise InvalidSchemaError(
                f"Macro shock '{shock.name}' references undeclared target state '{shock.target_state}'."
            )
        _check_metric_keys_subset(
            shock.instant_metric_overrides.keys(),
            non_deriv_metrics,
            f"instant_metric_overrides in macro shock '{shock.name}'",
        )

        target_state_cfg = engine.states[shock.target_state]
        global_limits = (
            config.realism_filter.global_limits if config.realism_filter else None
        )

        for m_name, val in shock.instant_metric_overrides.items():
            if global_limits and m_name in global_limits:
                min_l, max_l = global_limits[m_name]
                if not (min_l <= val <= max_l):
                    raise InitialBoundsError(
                        f"Macro shock '{shock.name}' override for metric '{m_name}' ({val}) "
                        f"violates global limits [{min_l}, {max_l}]."
                    )
            if m_name in target_state_cfg.state_bounds:
                min_b, max_b = target_state_cfg.state_bounds[m_name]
                if not (min_b <= val <= max_b):
                    raise InitialBoundsError(
                        f"Macro shock '{shock.name}' override for metric '{m_name}' ({val}) "
                        f"violates target state '{shock.target_state}' bounds [{min_b}, {max_b}]."
                    )


def _validate_workflow_and_resources(config: SimulationConfig) -> None:
    # 1. Resource pool uniqueness & foreign key mapping
    declared_pools: set[str] = set()
    if config.resource_pools:
        for pool in config.resource_pools:
            if pool.id in declared_pools:
                raise InvalidSchemaError(
                    f"Duplicate resource pool ID '{pool.id}' detected."
                )
            declared_pools.add(pool.id)

    if not config.workflow_dag or not config.workflow_dag.tasks:
        return

    tasks = config.workflow_dag.tasks

    # 2. Task ID uniqueness check
    declared_tasks: set[str] = set()
    for task in tasks:
        if task.task_id in declared_tasks:
            raise InvalidSchemaError(
                f"Duplicate task ID '{task.task_id}' detected in workflow DAG."
            )
        declared_tasks.add(task.task_id)

    # 3. Task relational validation (resource pools, predecessors, self-references)
    for task in tasks:
        if task.required_resource_pool and task.required_resource_pool not in declared_pools:
            raise InvalidSchemaError(
                f"Task '{task.task_id}' references undeclared resource pool '{task.required_resource_pool}'."
            )

        for pred in task.predecessors:
            if pred not in declared_tasks:
                raise InvalidSchemaError(
                    f"Task '{task.task_id}' references undeclared predecessor task '{pred}'."
                )
            if pred == task.task_id:
                raise InvalidSchemaError(
                    f"Task '{task.task_id}' cannot reference itself as a predecessor."
                )

    # 4. DAG cycle detection (DFS)
    graph = {t.task_id: list(t.predecessors) for t in tasks}
    visited: dict[str, int] = {}  # 0: unvisited, 1: visiting, 2: visited

    def dfs(node: str, path: list[str]) -> None:
        visited[node] = 1
        path.append(node)
        for pred in graph.get(node, []):
            if visited.get(pred, 0) == 1:
                cycle_str = " -> ".join(path[path.index(pred):] + [pred])
                raise InvalidSchemaError(
                    f"Circular dependency detected in workflow DAG: {cycle_str}"
                )
            if visited.get(pred, 0) == 0:
                dfs(pred, path)
        path.pop()
        visited[node] = 2

    for task_id in graph:
        if visited.get(task_id, 0) == 0:
            dfs(task_id, [])

def _validate_initial_coordinates(config: SimulationConfig) -> None:
    declared_nodes = set(config.network_topology.nodes) if config.network_topology else set()
    declared_states = set(config.state_engine.states.keys()) if config.state_engine else set()
    global_limits = config.realism_filter.global_limits if config.realism_filter else None

    for entity in config.entities:
        # Location check
        if config.pipeline_toggles.use_network_topology and entity.initial_location not in declared_nodes:
            raise InvalidSchemaError(
                f"Entity '{entity.id}' initial_location '{entity.initial_location}' "
                f"does not exist in network topology nodes."
            )

        # State check
        if config.pipeline_toggles.use_state_engine and entity.initial_state not in declared_states:
            raise InvalidSchemaError(
                f"Entity '{entity.id}' initial_state '{entity.initial_state}' "
                f"does not exist in state engine states."
            )

        # Metric coordinate bounds check
        matching_state = config.state_engine.states.get(entity.initial_state) if config.state_engine else None
        for m_name, val in entity.initial_metrics.items():
            if not isinstance(val, (int, float)):
                continue

            if matching_state and m_name in matching_state.state_bounds:
                min_b, max_b = matching_state.state_bounds[m_name]
                if not (min_b <= val <= max_b):
                    raise InitialBoundsError(
                        f"Entity '{entity.id}' initial metric '{m_name}' ({val}) "
                        f"lies outside initial state '{matching_state}' bounds [{min_b}, {max_b}]."
                    )

            if global_limits and m_name in global_limits:
                min_l, max_l = global_limits[m_name]
                if not (min_l <= val <= max_l):
                    raise InitialBoundsError(
                        f"Entity '{entity.id}' initial metric '{m_name}' ({val}) "
                        f"lies outside global safety limits [{min_l}, {max_l}]."
                    )

def _validate_sink_sources(config: SimulationConfig) -> None:
    non_deriv_metrics = {m.name for m in config.metrics if not m.is_derivative}
    deriv_metrics = {m.name for m in config.metrics if m.is_derivative}
    seen_headers: set[str] = set()

    for field in config.sink.fields:
        if field.name in seen_headers:
            raise InvalidSchemaError(f"Duplicate output sink field name '{field.name}' found.")
        seen_headers.add(field.name)

        src = field.source
        if src in ALLOWED_SYSTEM_SOURCES:
            continue
        elif src.startswith("metrics."):
            metric_name = src.split("metrics.", 1)[1]
            if metric_name not in non_deriv_metrics:
                raise InvalidSchemaError(
                    f"Sink field '{field.name}' references non-existent non-derivative metric '{metric_name}'."
                )
        elif src.startswith("derivative_metrics."):
            metric_name = src.split("derivative_metrics.", 1)[1]
            if metric_name not in deriv_metrics:
                raise InvalidSchemaError(
                    f"Sink field '{field.name}' references non-existent derivative metric '{metric_name}'."
                )
        else:
            raise InvalidSchemaError(
                f"Sink field '{field.name}' references invalid source namespace '{src}'."
            )

def _validate_output_path(config: SimulationConfig) -> None:
    """Protect against CWE-22"""
    raw_path = config.sink.output_path

    try:
        resolved_target = raw_path.resolve()
    except Exception as e:
        raise InvalidSchemaError(f"Invalid output path string '{raw_path}': {e}") from e

    for blocked in BLOCKED_SYSTEM_PATHS:
        if resolved_target == blocked or resolved_target.is_relative_to(blocked):
            raise InvalidSchemaError(
                f"Security Violation: Output path '{raw_path}' targets restricted system directory '{blocked}'."
            )
    workspace_dir = Path.cwd().resolve()
    temp_dir = Path(tempfile.gettempdir()).resolve()

    is_in_workspace = resolved_target.is_relative_to(workspace_dir)
    is_in_temp = resolved_target.is_relative_to(temp_dir)

    if not (is_in_workspace or is_in_temp):
        raise InvalidSchemaError(
            f"Security Violation: Output path '{raw_path}' attempts to write outside "
            f"the workspace directory ('{workspace_dir}') or temp directory."
        )

    output_dir = resolved_target.parent
    existing_parent = output_dir
    while not existing_parent.exists() and existing_parent != existing_parent.parent:
        existing_parent = existing_parent.parent

    if existing_parent.exists() and not os.access(existing_parent, os.W_OK):
        raise InvalidSchemaError(f"Output path target directory '{output_dir}' is not writable.")