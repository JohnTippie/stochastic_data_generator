import math
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from src.config.schemas import *

# ==============================================================================
# TIER 1: BASE TYPES & CUSTOM ALIASES
# ==============================================================================

class TestTier1BaseTypes:
    class DummyTypeModel(BaseModel):
        sanitized: SanitizedString = "valid_id"
        time_str: TimeString = "10m"
        bounds: BoundTuple = (0.0, 100.0)
        timestamp: ISO8601Timestamp = "2026-09-01T00:00:00Z"
        seed: SeedPayload = 42
        frozen_dict: FrozenDict[str, float] = {"a", 1.0}

    @pytest.mark.parametrize(
        "invalid_id", ["", " ", " leading", "trailing ", "\tnewline\n"]
    )
    def test_sanitized_string_invalid(self, invalid_id: str):
        with pytest.raises(ValidationError, match="Identifier"):
            self.DummyTypeModel(sanitized=invalid_id)

    @pytest.mark.parametrize("valid_id", ["VALID_ID", "a", "node-1", "path.to.metric"])
    def test_sanitized_string_valid(self, valid_id: str):
        m = self.DummyTypeModel(sanitized=valid_id)
        assert m.sanitized == valid_id

    @pytest.mark.parametrize(
            "invalid_time", ["90days", "d90", "10.5d", "-5h", "100", "invalid", "w"]
    )
    def test_time_string_invalid(self, invalid_time:str):
        with pytest.raises(ValidationError):
            self.DummyTypeModel(time_str=invalid_time)

    @pytest.mark.parametrize("valid_time", ["10s", "30m", "12h", "90d", "2w"])
    def test_time_string_valid(self, valid_time: str):
        m = self.DummyTypeModel(time_str=valid_time)
        assert m.time_str == valid_time

    def test_bound_tuple_valid(self):
        m = self.DummyTypeModel(bounds=(10.0, 20.0))
        assert m.bounds == (10.0, 20.0)

    def test_bound_tuple_inverted_rejected(self):
        with pytest.raises(ValidationError, match="Lower bound .* must be <= upper bound"):
            self.DummyTypeModel(bounds=(100.0, 0.0))

    def test_frozen_dict_converts_to_mapping_proxy(self):
        m = self.DummyTypeModel(frozen_dict={"key": 10.0})
        with pytest.raises(TypeError):
            m.frozen_dict["key"] = 20.0

    @pytest.mark.parametrize(
        "invalid_ts",
        ["not-a-datetime", "2026-99-99T00:00:00Z", "01/01/2026", "2026-01-01T25:00:00Z"],
    )
    def test_iso8601_timestamp_invalid(self, invalid_ts: str):
        with pytest.raises(ValidationError):
            self.DummyTypeModel(timestamp=invalid_ts)

    @pytest.mark.parametrize("invalid_seed", [-1, -100, "not_a_number", 3.14])
    def test_seed_payload_invalid(self, invalid_seed: Any):
        with pytest.raises(ValidationError):
            self.DummyTypeModel(seed=invalid_seed)

# ==============================================================================
# TIER 2: LEAF MODELS
# ==============================================================================
class TestTier2LeafModels:
    def test_metrics_config_derivative_requires_formula(self):
        with pytest.raises(ValidationError, match="is_derivative=True but no formula"):
            MetricsConfig(name="test_metric", is_derivative=True, formula=None)

    def test_metrics_config_non_derivative_rejects_formula(self):
        with pytest.raises(ValidationError, match="must not specify a formula"):
            MetricsConfig(
                name="test_metric", is_derivative=False, formula="x + y"
            )

    @pytest.mark.parametrize(
        "p_ful, p_def, p_can",
        [(0.8, 0.8, 0.8), (0.5, 0.2, 0.1), (0.0, 0.0, 0.0)],
    )
    def test_deferral_probabilities_simplex_enforced(
        self, p_ful: float, p_def: float, p_can: float
    ):
        with pytest.raises(ValidationError, match="must sum to 1.0"):
            DeferralBaseProbabilitiesConfig(
                fulfillment=p_ful, deferral=p_def, cancellation=p_can
            )

    def test_deferral_policy_enabled_requires_fields(self):
        with pytest.raises(ValidationError, match="driver_metric"):
            DeferralPolicyConfig(
                enabled=True,
                driver_metric=None,
                max_drift_ttl_epochs=5,
                base_probabilities=DeferralBaseProbabilitiesConfig(
                    fulfillment=0.8, deferral=0.15, cancellation=0.05
                ),
            )

    def test_corruption_rule_out_of_range_spike_requires_value(self):
        with pytest.raises(ValidationError, match="spike_value"):
            CorruptionRuleConfig(
                type="out_of_range_spike",
                probability=0.01,
                target_fields=("metric_1",),
                spike_value=None,
            )

    def test_corruption_rule_string_formatting_requires_value(self):
        with pytest.raises(ValidationError, match="corrupted_value"):
            CorruptionRuleConfig(
                type="string_formatting_error",
                probability=0.01,
                target_fields=("metric_1",),
                corrupted_value=None,
            )

# ==============================================================================
# TIER 3: SECTION CONTAINERS
# ==============================================================================
class TestTier3SectionContainers:
    def test_network_topology_requires_routes_when_enabled(self):
        with pytest.raises(ValidationError, match="Field 'routes' is required"):
            NetworkTopologyConfig(
                routing_type="dijkstra",
                nodes=("A", "B"),
                use_defined_routes=True,
                routes=None,
            )

    def test_network_topology_requires_adjacency_when_routes_disabled(self):
        with pytest.raises(ValidationError, match="Field 'adjacency_matrix' is required"):
            NetworkTopologyConfig(
                routing_type="stochastic_walk",
                nodes=("A", "B"),
                use_defined_routes=False,
                adjacency_matrix=None,
            )

    def test_network_topology_speed_physics_guardrail(self):
        # 100 miles in 30 mins = 200 mph required speed > 65 max_route_speed
        bad_route = RouteConfig(
            distance_miles=100.0,
            nominal_travel_time_min=30,
            max_throughput_capacity=10,
            max_route_speed=65,
        )
        with pytest.raises(ValidationError, match="exceeds max supported speed"):
            NetworkTopologyConfig(
                routing_type="dijkstra",
                nodes=("A", "B"),
                use_defined_routes=True,
                routes={"A->B": bad_route},
            )

    def test_network_topology_adjacency_weights_must_sum_to_one(self):
        bad_matrix = {
            "A": (
                AdjacencyConfig(destination="B", weight=0.5),
                AdjacencyConfig(destination="C", weight=0.2),  # Sums to 0.7
            )
        }
        with pytest.raises(ValidationError, match="adjacency weights must sum to 1.0"):
            NetworkTopologyConfig(
                routing_type="stochastic_walk",
                nodes=("A", "B", "C"),
                use_defined_routes=False,
                adjacency_matrix=bad_matrix,
            )

    def test_state_engine_transition_row_sum_enforced(self):
        bad_matrix = {
            "OPTIMAL": {"OPTIMAL": 0.8, "DEGRADED": 0.5}  # Sums to 1.3
        }
        state_data = StateBehaviorConfig(
            state_bounds={"m1": (0.0, 10.0)}, boundary_stiffness=0.5
        )
        with pytest.raises(ValidationError, match="must sum to 1.0"):
            StateEngineConfig(
                initial_state="OPTIMAL",
                states={"OPTIMAL": state_data, "DEGRADED": state_data},
                transition_matrix=bad_matrix,
            )

# ==============================================================================
# TIER 4: ROOT MODEL
# ==============================================================================
class TestTier4RootModel:
    @pytest.fixture
    def valid_root_config(self) -> SimulationConfig:
        return SimulationConfig(
            meta=MetaConfig(
                scenario_name="test_sim", description="desc", seed=42
            ),
            simulation=SimulationParamsConfig(
                start_time="2026-09-01T00:00:00Z",
                duration="1d",
                data_resolution="1m",
                epoch_interval="1h",
            ),
            pipeline_toggles=PipelineTogglesConfig(
                use_state_engine=False,
                use_network_topology=False,
                use_resource_contention=False,
                use_workflow_dag=False,
                use_realism_filter=False,
                use_malformations_filter=False,
            ),
            metrics=(
                MetricsConfig(
                    name="velocity", is_derivative=False, primitive_type="float"
                ),
            ),
            nominal_generator=NominalGeneratorConfig(
                baseline_metrics={"velocity": 60.0}
            ),
            sink=SinkConfig(
                format="csv",
                output_path=Path("./out.csv"),
                metadata_toggles=SinkMetadataTogglesConfig(
                    include_state=True,
                    include_malformed_flag=True,
                    include_true_baseline=False,
                ),
                fields=(SinkFieldConfig(name="v", source="metrics.velocity"),),
            ),
        )

    def test_immutability_attribute_reassignment_rejected(
        self, valid_root_config: SimulationConfig
    ):
        with pytest.raises(ValidationError):
            valid_root_config.simulation.duration = "10m"

    def test_extra_forbid_top_level_rejected(
        self, valid_root_config: SimulationConfig
    ):
        raw_data = valid_root_config.model_dump()
        raw_data["unauthorized_root_field"] = "bad_data"
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            SimulationConfig.model_validate(raw_data)

    def test_extra_forbid_nested_rejected(
        self, valid_root_config: SimulationConfig
    ):
        raw_data = valid_root_config.model_dump()
        raw_data["meta"]["unauthorized_nested_field"] = "bad_data"
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            SimulationConfig.model_validate(raw_data)

    @pytest.mark.parametrize("non_finite", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_floats_rejected(
        self, valid_root_config: SimulationConfig, non_finite: float
    ):
        raw_data = valid_root_config.model_dump()
        # Convert mappingproxy to standard mutable dict before item assignment
        raw_data["nominal_generator"]["baseline_metrics"] = dict(
            raw_data["nominal_generator"]["baseline_metrics"]
        )
        raw_data["nominal_generator"]["baseline_metrics"]["velocity"] = non_finite

        with pytest.raises(ValidationError):
            SimulationConfig.model_validate(raw_data)