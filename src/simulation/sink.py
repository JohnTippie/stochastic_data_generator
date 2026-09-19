import csv
from pathlib import Path
from typing import Any, Optional
from src.config.schemas import SinkConfig
from src.simulation.nominal_gen import EntityContext, NominalStateVector


class FileSink:
    """
    Real-time streaming file sink that writes state vectors directly to disk
    with a constant O(1) RAM footprint.
    """

    def __init__(self, sink_config: SinkConfig) -> None:
        self.config = sink_config
        self._file = None
        self._writer = None

    def __enter__(self) -> "FileSink":
        # Resolve path and ensure target parent directory exists
        target_path: Path = self.config.output_path.resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if self.config.format == "csv":
            self._file = open(target_path, mode="w", newline="", encoding="utf-8")
            field_names = [f.name for f in self.config.fields]
            self._writer = csv.DictWriter(self._file, fieldnames=field_names)
            self._writer.writeheader()
        else:
            raise NotImplementedError(
                f"Sink output format '{self.config.format}' is not currently supported. Use 'csv'."
            )

        return self

    def write_row(self, row_data: dict[str, Any]) -> None:
        """Writes a single formatted row dictionary to the active file handle."""
        if self._writer and self.config.format == "csv":
            self._writer.writerow(row_data)

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
        """Flushes buffered data and closes open file handles on exit or exception."""
        if self._file:
            self._file.flush()
            self._file.close()


def extract_sink_fields(
    payload: NominalStateVector,
    entity_context: EntityContext,
    sink_config: SinkConfig,
    state_label: str = "NOMINAL",
    backlog_depth: int = 0,
    is_malformed: bool = False,
) -> dict[str, Any]:
    """
    Extracts configured output fields from step payload and context objects
    based on the source namespaces defined in config.sink.fields.
    """
    row: dict[str, Any] = {}

    for field_cfg in sink_config.fields:
        name = field_cfg.name
        src = field_cfg.source

        if src == "system.timestamp":
            row[name] = payload.timestamp
        elif src == "system.state_label":
            row[name] = state_label
        elif src == "system.current_location":
            row[name] = payload.current_node
        elif src == "system.backlog_depth":
            row[name] = backlog_depth
        elif src == "system.is_malformed":
            row[name] = is_malformed
        elif src == "entity.id":
            row[name] = entity_context.entity_id
        elif src == "entity.type":
            row[name] = entity_context.entity_type
        elif src.startswith("metrics."):
            metric_name = src.split("metrics.", 1)[1]
            row[name] = payload.metrics.get(metric_name)
        elif src.startswith("derivative_metrics."):
            metric_name = src.split("derivative_metrics.", 1)[1]
            row[name] = payload.derivative_metrics.get(metric_name)
        else:
            row[name] = None

    return row