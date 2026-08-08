from typing import Iterable, TypeVar
import os
from .schemas import SimulationConfig
from .exceptions import DimensionalMismatchError, InitialBoundsError, InvalidSchemaError

T = TypeVar("T")

ALLOWED_ENGINE_SOURCES = {
    "simulation_time",
    "entity_id",
    "entity_type",
    "backlog_depth",
}

TIME_UNIT_MULTIPLIERS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def validate_domain_invariants(config: SimulationConfig) -> None:
    """
    Executes all domain cross-field validation rules against a loaded SimulationConfig.
    """
    _validate_unique_metric_names(config)
    _validate_unique_entity_ids(config)
    _validate_unique_state_and_shock_names(config)
    _validate_toggle_data_alignment(config)
    _validate_dimensional_alignment(config)
    _validate_macro_shocks(config)
    _validate_initial_coordinates(config)
    _validate_time_hierarchy(config)
    _validate_output_field_sources(config)
    _validate_output_field_uniqueness(config)
    _validate_output_path(config)


def _resolve_effective(entity_val: T | None, use_global_toggle: bool, global_val: T | None, default_fallback: T) -> T:
    if use_global_toggle:
        return global_val if global_val is not None else default_fallback
    return entity_val if entity_val is not None else default_fallback


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


def _parse_time_string_to_seconds(time_str: str) -> int:
    unit = time_str[-1]
    qty = int(time_str[:-1])
    return qty * TIME_UNIT_MULTIPLIERS[unit]


def _validate_unique_metric_names(config: SimulationConfig) -> None:
    seen_names: set[str] = set()
    for metric in config.metrics:
        if metric.name in seen_names:
            raise InvalidSchemaError(
                f"Duplicate metric definition found for key '{metric.name}'. Metric names must be unique."
            )
        seen_names.add(metric.name)


def _validate_unique_entity_ids(config: SimulationConfig) -> None:
    seen_ids: set[str] = set()
    for entity in config.entities:
        if not entity.id or not entity.id.strip():
            raise InvalidSchemaError("Entity contains an empty or missing 'id'.")
        if entity.id in seen_ids:
            raise InvalidSchemaError(f"Duplicate entity ID found: '{entity.id}'")
        seen_ids.add(entity.id)


def _validate_unique_state_and_shock_names(config: SimulationConfig) -> None:
    seen_global_states: set[str] = set()
    for state in config.global_behavior_states:
        if state.name in seen_global_states:
            raise InvalidSchemaError(f"Duplicate state name '{state.name}' found in global_behavior_states.")
        seen_global_states.add(state.name)

    seen_global_shocks: set[str] = set()
    for shock in config.global_macro_shocks:
        if shock.name in seen_global_shocks:
            raise InvalidSchemaError(f"Duplicate macro shock name '{shock.name}' found in global_macro_shocks.")
        seen_global_shocks.add(shock.name)

    for entity in config.entities:
        if entity.behavior_states is not None:
            seen_entity_states: set[str] = set()
            for b_state in entity.behavior_states:
                if b_state.name in seen_entity_states:
                    raise InvalidSchemaError(f"Duplicate custom state name '{b_state.name}' found in entity '{entity.id}'.")
                seen_entity_states.add(b_state.name)

        if entity.macro_shocks is not None:
            seen_entity_shocks: set[str] = set()
            for e_shock in entity.macro_shocks:
                if e_shock.name in seen_entity_shocks:
                    raise InvalidSchemaError(f"Duplicate custom macro shock name '{e_shock.name}' found in entity '{entity.id}'.")
                seen_entity_shocks.add(e_shock.name)


def _validate_dimensional_alignment(config: SimulationConfig) -> None:
    all_metric_names = {m.name for m in config.metrics}
    non_derivative_metric_names = {m.name for m in config.metrics if not m.is_derivative}

    if config.toggles.use_global_limits and config.global_limits is not None:
        _check_metric_keys_exact(config.global_limits.keys(), non_derivative_metric_names, "global_limits")

    if config.toggles.use_global_behavior:
        for state in config.global_behavior_states:
            _check_metric_keys_exact(state.state_bounds.keys(), non_derivative_metric_names, f"state_bounds in global state '{state.name}'")
            _check_metric_keys_exact(state.drift_rates.keys(), non_derivative_metric_names, f"drift_rates in global state '{state.name}'")
            _check_metric_keys_exact(state.volatilities.keys(), non_derivative_metric_names, f"volatilities in global state '{state.name}'")

    for entity in config.entities:
        _check_metric_keys_exact(entity.initial_metrics.keys(), non_derivative_metric_names, f"initial_metrics in entity '{entity.id}'")

        if not config.toggles.use_global_limits and entity.metric_bounds is not None:
            _check_metric_keys_exact(entity.metric_bounds.keys(), non_derivative_metric_names, f"metric_bounds in entity '{entity.id}'")

        if not config.toggles.use_global_behavior and entity.behavior_states is not None:
            for b_state in entity.behavior_states:
                _check_metric_keys_exact(b_state.state_bounds.keys(), non_derivative_metric_names, f"state_bounds in custom state '{b_state.name}' for entity '{entity.id}'")
                _check_metric_keys_exact(b_state.drift_rates.keys(), non_derivative_metric_names, f"drift_rates in custom state '{b_state.name}' for entity '{entity.id}'")
                _check_metric_keys_exact(b_state.volatilities.keys(), non_derivative_metric_names, f"volatilities in custom state '{b_state.name}' for entity '{entity.id}'")

        if entity.deferral_policy and entity.deferral_policy.enabled:
            driver = entity.deferral_policy.driver_metric
            if driver and driver not in all_metric_names:
                raise DimensionalMismatchError(
                    f"Deferral policy driver_metric '{driver}' in entity '{entity.id}' does not exist in top-level metrics manifest."
                )


def _validate_macro_shocks(config: SimulationConfig) -> None:
    non_derivative_metric_names = {m.name for m in config.metrics if not m.is_derivative}
    global_states_dict = {s.name: s for s in config.global_behavior_states}

    if config.toggles.use_global_macro_shock:
        for shock in config.global_macro_shocks:
            _check_metric_keys_exact(shock.instant_metric_overrides.keys(), non_derivative_metric_names, f"instant_metric_overrides in global macro shock '{shock.name}'")

            if shock.target_state not in global_states_dict:
                raise InvalidSchemaError(f"Global macro shock '{shock.name}' references target_state '{shock.target_state}' which does not exist in global_behavior_states.")

            target_state = global_states_dict[shock.target_state]
            for m_name, val in shock.instant_metric_overrides.items():
                if config.toggles.use_global_limits and config.global_limits and m_name in config.global_limits:
                    min_l, max_l = config.global_limits[m_name]
                    if not (min_l <= val <= max_l):
                        raise InvalidSchemaError(f"Global macro shock '{shock.name}' override for metric '{m_name}' value {val} lies outside global limits [{min_l}, {max_l}].")

                if m_name in target_state.state_bounds:
                    min_b, max_b = target_state.state_bounds[m_name]
                    if not (min_b <= val <= max_b):
                        raise InvalidSchemaError(f"Global macro shock '{shock.name}' override for metric '{m_name}' value {val} lies outside target state '{shock.target_state}' bounds [{min_b}, {max_b}].")

    for entity in config.entities:
        effective_states = _resolve_effective(entity.behavior_states, config.toggles.use_global_behavior, config.global_behavior_states, default_fallback=())
        effective_shocks = _resolve_effective(entity.macro_shocks, config.toggles.use_global_macro_shock, config.global_macro_shocks, default_fallback=())
        effective_limits = _resolve_effective(entity.metric_bounds, config.toggles.use_global_limits, config.global_limits, default_fallback=())

        entity_states_dict = {s.name: s for s in effective_states}

        for shock in effective_shocks:
            _check_metric_keys_exact(shock.instant_metric_overrides.keys(), non_derivative_metric_names, f"instant_metric_overrides in shock '{shock.name}' for entity '{entity.id}'")

            if shock.target_state not in entity_states_dict:
                raise InvalidSchemaError(f"Macro shock '{shock.name}' in entity '{entity.id}' references target_state '{shock.target_state}' which does not exist in resolved active states.")

            target_state = entity_states_dict[shock.target_state]
            for m_name, val in shock.instant_metric_overrides.items():
                if effective_limits and m_name in effective_limits:
                    min_l, max_l = effective_limits[m_name]
                    if not (min_l <= val <= max_l):
                        raise InvalidSchemaError(f"Macro shock '{shock.name}' in entity '{entity.id}' override for metric '{m_name}' value {val} lies outside limits [{min_l}, {max_l}].")

                if m_name in target_state.state_bounds:
                    min_b, max_b = target_state.state_bounds[m_name]
                    if not (min_b <= val <= max_b):
                        raise InvalidSchemaError(f"Macro shock '{shock.name}' in entity '{entity.id}' override for metric '{m_name}' value {val} lies outside target state '{shock.target_state}' bounds [{min_b}, {max_b}].")


def _validate_initial_coordinates(config: SimulationConfig) -> None:
    for entity in config.entities:
        effective_limits = _resolve_effective(entity.metric_bounds, config.toggles.use_global_limits, config.global_limits, default_fallback=None)
        states = _resolve_effective(entity.behavior_states, config.toggles.use_global_behavior, config.global_behavior_states, default_fallback=()) if config.toggles.enable_state_engine else ()

        matching_state = None
        if config.toggles.enable_state_engine and entity.initial_state and states:
            matching_state = next((s for s in states if s.name == entity.initial_state), None)
            if not matching_state:
                raise InitialBoundsError(f"Entity '{entity.id}' initial_state '{entity.initial_state}' does not exist in defined states.")

        for metric_name, val in entity.initial_metrics.items():
            if matching_state and metric_name in matching_state.state_bounds:
                min_b, max_b = matching_state.state_bounds[metric_name]
                if not (min_b <= val <= max_b):
                    raise InitialBoundsError(f"Entity '{entity.id}' initial metric '{metric_name}' value {val} lies outside state '{matching_state.name}' bounds [{min_b}, {max_b}].")

            if effective_limits and metric_name in effective_limits:
                min_l, max_l = effective_limits[metric_name]
                if not (min_l <= val <= max_l):
                    raise InitialBoundsError(f"Entity '{entity.id}' initial metric '{metric_name}' value {val} lies outside safety limits [{min_l}, {max_l}].")


def _validate_toggle_data_alignment(config: SimulationConfig) -> None:
    if config.toggles.use_global_behavior and not config.global_behavior_states:
        raise InvalidSchemaError("Toggle 'use_global_behavior' is True, but 'global_behavior_states' is empty.")

    if config.toggles.use_global_macro_shock and not config.global_macro_shocks:
        raise InvalidSchemaError("Toggle 'use_global_macro_shock' is True, but 'global_macro_shocks' is empty.")

    if config.toggles.use_global_limits and not config.global_limits:
        raise InvalidSchemaError("Toggle 'use_global_limits' is True, but 'global_limits' is empty.")

    if config.toggles.enable_state_engine:
        for entity in config.entities:
            effective_states = _resolve_effective(entity.behavior_states, config.toggles.use_global_behavior, config.global_behavior_states, default_fallback=())
            if not effective_states:
                raise InvalidSchemaError(f"State engine is enabled, but entity '{entity.id}' resolves to no behavior states.")


def _validate_time_hierarchy(config: SimulationConfig) -> None:
    res_sec = _parse_time_string_to_seconds(config.simulation.data_resolution)
    epoch_sec = _parse_time_string_to_seconds(config.simulation.epoch_interval)
    dur_sec = _parse_time_string_to_seconds(config.simulation.duration)

    if res_sec > epoch_sec:
        raise InvalidSchemaError(f"Time hierarchy error: data_resolution ('{config.simulation.data_resolution}') cannot be greater than epoch_interval ('{config.simulation.epoch_interval}').")

    if epoch_sec > dur_sec:
        raise InvalidSchemaError(f"Time hierarchy error: epoch_interval ('{config.simulation.epoch_interval}') cannot be greater than simulation duration ('{config.simulation.duration}').")


def _validate_output_field_sources(config: SimulationConfig) -> None:
    valid_metric_names = {m.name for m in config.metrics}

    for field in config.output.fields:
        src = field.source
        if src in ALLOWED_ENGINE_SOURCES:
            continue
        elif src.startswith("metrics."):
            target_metric = src.split("metrics.", 1)[1]
            if target_metric not in valid_metric_names:
                raise InvalidSchemaError(f"Output field '{field.name}' references non-existent metric '{target_metric}' in source '{src}'.")
        else:
            raise InvalidSchemaError(f"Output field '{field.name}' references unrecognized source '{src}'. Source must be one of {sorted(ALLOWED_ENGINE_SOURCES)} or 'metrics.<metric_name>'.")

def _validate_output_field_uniqueness(config: SimulationConfig) -> None:
    seen_headers: set[str] = set()
    for field in config.output.fields:
        if field.name in seen_headers:
            raise InvalidSchemaError(
                f"Duplicate output field header name '{field.name}' found in output."
            )
        seen_headers.add(field.name)

def _validate_output_path(config:SimulationConfig) -> None:
    out_path = config.output.path
    parent = out_path.parent

    curr = parent
    while not curr.exists() and curr != curr.parent:
        curr = curr.parent

    if not curr.is_dir():
        raise InvalidSchemaError(
            f"Output path parent '{parent}' ancestor '{curr}' is not a directory."
        )

    if not os.access(curr, os.W_OK):
        raise InvalidSchemaError(
            f"Output path parent directory '{parent}' (via ancestor '{curr}') is not writable."
        )