"""Sensor platform for Synology Active Backup for Business."""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfInformation, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ActiveBackupConfigEntry, ActiveBackupCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class ActiveBackupSensorDescription(SensorEntityDescription):
    """Extends SensorEntityDescription with a task-data extractor."""

    value_fn: Callable[[dict[str, Any]], Any]


SENSOR_DESCRIPTIONS: tuple[ActiveBackupSensorDescription, ...] = (
    ActiveBackupSensorDescription(
        key="status",
        translation_key="task_status",
        icon="mdi:backup-restore",
        value_fn=lambda task: task.get("status_str", "idle"),
    ),
    ActiveBackupSensorDescription(
        key="result",
        translation_key="task_result",
        icon="mdi:check-circle-outline",
        value_fn=lambda task: task.get("result_str", "unknown"),
    ),
    ActiveBackupSensorDescription(
        key="last_backup",
        translation_key="last_backup",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda task: (
            datetime.fromtimestamp(task["last_bkp_time"], tz=timezone.utc)
            if task.get("last_bkp_time") is not None
            else None
        ),
    ),
    ActiveBackupSensorDescription(
        key="next_backup",
        translation_key="next_backup",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda task: (
            datetime.fromtimestamp(task["next_bkp_time"], tz=timezone.utc)
            if task.get("next_bkp_time") is not None
            else None
        ),
    ),
    ActiveBackupSensorDescription(
        key="transferred_size",
        translation_key="transferred_size",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda task: task.get("transferred_size"),
    ),
    ActiveBackupSensorDescription(
        key="duration",
        translation_key="duration",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda task: task.get("duration"),
    ),
    ActiveBackupSensorDescription(
        key="progress",
        translation_key="progress",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        icon="mdi:progress-upload",
        # None when idle — HA shows "Unknown" until next backup starts
        value_fn=lambda task: task.get("progress_pct"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ActiveBackupConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one set of sensors per discovered backup task."""
    coordinator: ActiveBackupCoordinator = entry.runtime_data

    _LOGGER.debug(
        "Setting up sensors — coordinator has %d task(s): %s",
        len(coordinator.data),
        list(coordinator.data.keys()),
    )

    async_add_entities(
        ActiveBackupSensor(coordinator, entry.entry_id, task_id, description)
        for task_id in coordinator.data
        for description in SENSOR_DESCRIPTIONS
    )


class ActiveBackupSensor(CoordinatorEntity[ActiveBackupCoordinator], SensorEntity):
    """A single sensor representing one metric of one Active Backup task."""

    _attr_has_entity_name = True
    entity_description: ActiveBackupSensorDescription

    def __init__(
        self,
        coordinator: ActiveBackupCoordinator,
        entry_id: str,
        task_id: int,
        description: ActiveBackupSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self._task_id = task_id
        self.entity_description = description

        task = coordinator.data[task_id]
        device_name: str = (
            task.get("host_name")
            or task.get("task_name")
            or f"Task {task_id}"
        )

        self._attr_unique_id = f"{entry_id}_{task_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{task_id}")},
            name=device_name,
            manufacturer="Synology",
            model="Active Backup for Business",
            sw_version=task.get("os_name") or None,
            entry_type=None,
        )

    @property
    def available(self) -> bool:
        return super().available and self._task_id in self.coordinator.data

    @property
    def native_value(self):
        task = self.coordinator.data.get(self._task_id)
        if task is None:
            return None
        return self.entity_description.value_fn(task)
