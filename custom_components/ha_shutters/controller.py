"""Automation controller for one configured window."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.components.cover import DOMAIN as COVER_DOMAIN
from homeassistant.components.cover import SERVICE_CLOSE_COVER, SERVICE_OPEN_COVER
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_CLOSED,
    STATE_CLOSING,
    STATE_HOME,
    STATE_OPEN,
    STATE_OPENING,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    CONF_AZIMUTH_END,
    CONF_AZIMUTH_START,
    CONF_COVER_ENTITY,
    CONF_DAWN_DUSK_AWAY,
    CONF_ENABLED,
    CONF_ONLY_AWAY,
    CONF_PRESENCE_ENTITIES,
    CONF_TELEWORK_ENABLED,
    CONF_TELEWORK_END,
    CONF_TELEWORK_START,
    CONF_TEMPERATURE_ENTITY,
    CONF_TEMPERATURE_THRESHOLD,
    DEFAULT_DAWN_DUSK_AWAY,
    DEFAULT_ENABLED,
    DEFAULT_ONLY_AWAY,
    DEFAULT_TELEWORK_ENABLED,
    DEFAULT_TELEWORK_END,
    DEFAULT_TELEWORK_START,
    DEFAULT_TEMPERATURE_THRESHOLD,
    DOMAIN,
    STORAGE_VERSION,
    TEMPERATURE_HYSTERESIS,
)
from .logic import automation_is_allowed, azimuth_is_in_range, time_is_in_range

_LOGGER = logging.getLogger(__name__)
SUN_ENTITY_ID = "sun.sun"


class ShutterController:
    """Coordinate one cover using sun, temperature and presence states."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._tracked_cover_entity = entry.data[CONF_COVER_ENTITY]
        self._listeners: list[Callable[[], None]] = []
        self._entity_listeners: list[Callable[[], None]] = []
        self._subscribers: set[Callable[[], None]] = set()
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self.managed_closed = False
        self.night_closed = False
        self.manual_override = False
        self.last_desired_closed = False
        self._ignore_cover_changes_until: datetime | None = None
        self._expected_cover_states: set[str] = set()
        self._last_saved_state: tuple[bool, bool, bool, bool] | None = None
        self.sun_on_window = False
        self.automation_active = False
        self.shading_required = False
        self.night_away_active = False
        self.temperature_celsius: float | None = None

    @property
    def settings(self) -> dict[str, Any]:
        """Return merged immutable setup data and mutable UI settings."""
        return {**self.entry.data, **self.entry.options}

    async def async_setup(self) -> None:
        """Restore state and start tracking Home Assistant entities."""
        stored = await self._store.async_load() or {}
        self.managed_closed = bool(stored.get("managed_closed", False))
        self.night_closed = bool(stored.get("night_closed", False))
        self.manual_override = bool(stored.get("manual_override", False))
        self.last_desired_closed = bool(stored.get("last_desired_closed", False))
        self._last_saved_state = (
            self.managed_closed,
            self.night_closed,
            self.manual_override,
            self.last_desired_closed,
        )
        self._subscribe_to_entities()
        self._listeners.append(
            async_track_time_interval(
                self.hass, self._async_periodic_update, timedelta(minutes=1)
            )
        )
        await self.async_evaluate("startup")

    async def async_shutdown(self) -> None:
        """Stop listeners and save runtime ownership state."""
        for remove_listener in self._entity_listeners + self._listeners:
            remove_listener()
        self._entity_listeners.clear()
        self._listeners.clear()
        await self._async_save_state()

    def _subscribe_to_entities(self) -> None:
        """Listen for every input that can change the decision."""
        for remove_listener in self._entity_listeners:
            remove_listener()
        self._entity_listeners.clear()

        settings = self.settings
        entities = {
            SUN_ENTITY_ID,
            settings[CONF_COVER_ENTITY],
            settings[CONF_TEMPERATURE_ENTITY],
            *settings.get(CONF_PRESENCE_ENTITIES, []),
        }
        self._entity_listeners.append(
            async_track_state_change_event(
                self.hass, list(entities), self._async_state_changed
            )
        )

    @callback
    def subscribe(self, subscriber: Callable[[], None]) -> Callable[[], None]:
        """Subscribe an entity to controller updates."""
        self._subscribers.add(subscriber)

        @callback
        def unsubscribe() -> None:
            self._subscribers.discard(subscriber)

        return unsubscribe

    @callback
    def _notify_subscribers(self) -> None:
        for subscriber in self._subscribers:
            subscriber()

    async def async_settings_updated(self) -> None:
        """Apply changes from an entity or the options flow."""
        new_cover_entity = self.settings[CONF_COVER_ENTITY]
        if new_cover_entity != self._tracked_cover_entity:
            # Never transfer ownership state to a newly selected physical cover.
            self._tracked_cover_entity = new_cover_entity
            self.managed_closed = False
            self.night_closed = False
            self.manual_override = False
            self.last_desired_closed = False
        self._subscribe_to_entities()
        await self.async_evaluate("settings")

    async def async_update_setting(self, key: str, value: Any) -> None:
        """Persist a setting changed by a control entity."""
        options = dict(self.entry.options)
        options[key] = value
        self.hass.config_entries.async_update_entry(self.entry, options=options)

    @callback
    def _async_state_changed(self, event: Event) -> None:
        entity_id = event.data["entity_id"]
        if entity_id == self.settings[CONF_COVER_ENTITY]:
            self._handle_cover_state_change(event.data.get("new_state"))
        self.hass.async_create_task(self.async_evaluate(f"state:{entity_id}"))

    @callback
    def _handle_cover_state_change(self, new_state: State | None) -> None:
        """Detect a manual action and pause control for this decision cycle."""
        if new_state is None or new_state.state not in {
            STATE_OPEN,
            STATE_OPENING,
            STATE_CLOSED,
            STATE_CLOSING,
        }:
            return
        if (
            self._ignore_cover_changes_until is not None
            and dt_util.utcnow() < self._ignore_cover_changes_until
            and new_state.state in self._expected_cover_states
        ):
            return
        if self.last_desired_closed:
            self.manual_override = True
            self.managed_closed = False
            self.hass.async_create_task(self._async_save_state())

    async def _async_periodic_update(self, now: datetime) -> None:
        await self.async_evaluate("timer")

    async def async_evaluate(self, reason: str) -> None:
        """Evaluate the desired state and operate the cover if necessary."""
        settings = self.settings
        sun_state = self.hass.states.get(SUN_ENTITY_ID)
        cover_state = self.hass.states.get(settings[CONF_COVER_ENTITY])
        temperature_state = self.hass.states.get(settings[CONF_TEMPERATURE_ENTITY])

        if sun_state is None or cover_state is None:
            self.automation_active = False
            self._notify_subscribers()
            return

        someone_home = self._someone_is_home()
        away = not someone_home
        local_now = dt_util.as_local(dt_util.utcnow())
        telework_active = time_is_in_range(
            local_now.time(),
            self.get_time(CONF_TELEWORK_START, DEFAULT_TELEWORK_START),
            self.get_time(CONF_TELEWORK_END, DEFAULT_TELEWORK_END),
        )
        self.automation_active = automation_is_allowed(
            enabled=self.get_bool(CONF_ENABLED, DEFAULT_ENABLED),
            only_away=self.get_bool(CONF_ONLY_AWAY, DEFAULT_ONLY_AWAY),
            someone_home=someone_home,
            telework_enabled=self.get_bool(
                CONF_TELEWORK_ENABLED, DEFAULT_TELEWORK_ENABLED
            ),
            telework_active=telework_active,
        )

        azimuth = self._float_attribute(sun_state, "azimuth")
        elevation = self._float_attribute(sun_state, "elevation")
        self.sun_on_window = bool(
            azimuth is not None
            and elevation is not None
            and elevation > 0
            and azimuth_is_in_range(
                azimuth,
                float(settings[CONF_AZIMUTH_START]),
                float(settings[CONF_AZIMUTH_END]),
            )
        )
        self.temperature_celsius = self._temperature_in_celsius(temperature_state)
        threshold = self.get_float(
            CONF_TEMPERATURE_THRESHOLD, DEFAULT_TEMPERATURE_THRESHOLD
        )
        effective_threshold = (
            threshold - TEMPERATURE_HYSTERESIS
            if self.managed_closed and self.last_desired_closed
            else threshold
        )
        self.shading_required = bool(
            self.automation_active
            and self.sun_on_window
            and self.temperature_celsius is not None
            and self.temperature_celsius >= effective_threshold
        )

        sun_below_horizon = sun_state.state == "below_horizon"
        self.night_away_active = bool(
            self.get_bool(CONF_ENABLED, DEFAULT_ENABLED)
            and self.get_bool(CONF_DAWN_DUSK_AWAY, DEFAULT_DAWN_DUSK_AWAY)
            and sun_below_horizon
            and (away or self.night_closed)
        )
        desired_closed = self.shading_required or self.night_away_active

        if not desired_closed and self.last_desired_closed:
            self.manual_override = False
        if not self.night_away_active:
            self.night_closed = False

        if desired_closed and not self.manual_override:
            if cover_state.state not in {STATE_CLOSED, STATE_CLOSING}:
                if await self._async_call_cover(SERVICE_CLOSE_COVER):
                    self.managed_closed = True
        elif not desired_closed and self.managed_closed:
            is_opening = cover_state.state in {STATE_OPEN, STATE_OPENING}
            if is_opening or await self._async_call_cover(SERVICE_OPEN_COVER):
                self.managed_closed = False

        if self.night_away_active and self.managed_closed:
            self.night_closed = True

        if desired_closed != self.last_desired_closed:
            _LOGGER.debug(
                "%s desired closed changed to %s (%s)",
                self.entry.title,
                desired_closed,
                reason,
            )
        self.last_desired_closed = desired_closed
        await self._async_save_state()
        self._notify_subscribers()

    async def _async_call_cover(self, service: str) -> bool:
        """Call a cover service and ignore resulting physical transitions briefly."""
        self._ignore_cover_changes_until = dt_util.utcnow() + timedelta(minutes=2)
        self._expected_cover_states = (
            {STATE_CLOSING, STATE_CLOSED}
            if service == SERVICE_CLOSE_COVER
            else {STATE_OPENING, STATE_OPEN}
        )
        try:
            await self.hass.services.async_call(
                COVER_DOMAIN,
                service,
                target={"entity_id": self.settings[CONF_COVER_ENTITY]},
                blocking=True,
            )
            return True
        except Exception:  # Home Assistant services can expose device-specific errors.
            _LOGGER.exception(
                "Unable to call %s for %s", service, self.settings[CONF_COVER_ENTITY]
            )
            return False

    def _someone_is_home(self) -> bool:
        entities = self.settings.get(CONF_PRESENCE_ENTITIES, [])
        # Safe default: an unconfigured/missing presence source never looks "away".
        if not entities:
            return True
        return any(
            (state := self.hass.states.get(entity_id)) is None
            or state.state in {STATE_HOME, STATE_UNKNOWN, STATE_UNAVAILABLE}
            for entity_id in entities
        )

    @staticmethod
    def _float_attribute(state: State, attribute: str) -> float | None:
        try:
            return float(state.attributes[attribute])
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _temperature_in_celsius(state: State | None) -> float | None:
        if state is None or state.state in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
            return None
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return None
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        if not unit or unit == UnitOfTemperature.CELSIUS:
            return value
        try:
            return TemperatureConverter.convert(value, unit, UnitOfTemperature.CELSIUS)
        except (TypeError, ValueError):
            return None

    def get_bool(self, key: str, default: bool) -> bool:
        return bool(self.settings.get(key, default))

    def get_float(self, key: str, default: float) -> float:
        try:
            return float(self.settings.get(key, default))
        except (TypeError, ValueError):
            return default

    def get_time(self, key: str, default: time) -> time:
        value = self.settings.get(key, default.isoformat())
        if isinstance(value, time):
            return value
        try:
            return time.fromisoformat(value)
        except (TypeError, ValueError):
            return default

    async def _async_save_state(self) -> None:
        current_state = (
            self.managed_closed,
            self.night_closed,
            self.manual_override,
            self.last_desired_closed,
        )
        if current_state == self._last_saved_state:
            return
        await self._store.async_save(
            {
                "managed_closed": self.managed_closed,
                "night_closed": self.night_closed,
                "manual_override": self.manual_override,
                "last_desired_closed": self.last_desired_closed,
            }
        )
        self._last_saved_state = current_state
