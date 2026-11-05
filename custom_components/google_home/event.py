"""Events for alarm and timer transitions seen in successful polls."""

from typing import override

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import GoogleHomeFeatureEntity, async_add_device_entities
from .observations import ItemKind
from .types import GoogleHomeConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: GoogleHomeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add both event entities when each supported device answers."""
    async_add_device_entities(entry, async_add_entities, AlarmEvents, TimerEvents)


class GoogleHomeEvents(GoogleHomeFeatureEntity, EventEntity):
    """Publish every item separately, consuming each coordinator batch only once."""

    _kind: ItemKind
    _consumed_sequence = -1

    @property
    @override
    def label(self) -> str:
        """Keep an independent registry identity for the kind of events."""
        return f"{self._kind}_events"

    @override
    async def async_added_to_hass(self) -> None:
        """Start listening without replaying changes from before entity addition."""
        self._consumed_sequence = self.coordinator.event_sequence
        await super().async_added_to_hass()

    @callback
    @override
    def _handle_coordinator_update(self) -> None:
        """Write each event immediately so simultaneous items reach automations."""
        if self._consumed_sequence != self.coordinator.event_sequence:
            self._consumed_sequence = self.coordinator.event_sequence
            for event in self.coordinator.events:
                if event.kind == self._kind:
                    self._trigger_event(event.event_type, event.attributes())
                    self.async_write_ha_state()
        super()._handle_coordinator_update()


class AlarmEvents(GoogleHomeEvents):
    """Observed alarm ringing, snoozing and ending under each reported ID."""

    _kind = "alarm"
    _attr_translation_key = "alarm_events"
    _attr_event_types = ["ringing", "snoozed", "stopped"]


class TimerEvents(GoogleHomeEvents):
    """Observed timer ringing and ending under each reported ID."""

    _kind = "timer"
    _attr_translation_key = "timer_events"
    _attr_event_types = ["ringing", "stopped"]
