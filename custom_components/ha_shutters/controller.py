"""Automation controller for one configured window."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.components.cover import DOMAIN as COVER_DOMAIN
from homeassistant.components.cover import (
    SERVICE_CLOSE_COVER,
    SERVICE_OPEN_COVER,
    SERVICE_SET_COVER_POSITION,
    CoverEntityFeature,
)
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
    CONF_FACADE_AZIMUTH,
    CONF_ONLY_AWAY,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_PRESENCE_ENTITIES,
    CONF_PROGRESSIVE_ENABLED,
    CONF_SILL_HEIGHT,
    CONF_SUN_DEPTH,
    CONF_TELEWORK_ENABLED,
    CONF_TELEWORK_END,
    CONF_TELEWORK_START,
    CONF_TEMPERATURE_ENTITY,
    CONF_TEMPERATURE_THRESHOLD,
    CONF_WINDOW_HEIGHT,
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
from .global_settings import GlobalSettingsManager
from .logic import (
    automation_is_allowed,
    azimuth_is_in_range,
    effective_temperature_threshold,
    finite_float,
    geometric_opening,
    opening_step,
    sun_is_in_front,
    time_is_in_range,
)

_LOGGER = logging.getLogger(__name__)
SUN_ENTITY_ID = "sun.sun"
POSITION_TOLERANCE = 3
SOLAR_COMMAND_INTERVAL = timedelta(minutes=30)
TARGET_STABILITY = timedelta(minutes=5)
STOP_CONFIRMATION = timedelta(seconds=15)


class ShutterController:
    """Coordinate one cover using sun, temperature and presence states."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        global_settings: GlobalSettingsManager,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.global_settings = global_settings
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
        self._last_saved_state: dict[str, Any] | None = None
        self._evaluation_lock = asyncio.Lock()
        self.last_position_target: int | None = None
        self._last_attempt: datetime | None = None
        self._last_attempt_target: int | None = None
        self._thermal_active = False
        self._candidate: int | None = None
        self._candidate_since: datetime | None = None
        self._no_sun_since: datetime | None = None
        self._expected_position: int | None = None
        self._command_start_position: float | None = None
        self._pending_stop_since: datetime | None = None
        self._progressive_active = False
        self.calculated_target: float | None = None
        self.effective_threshold: float | None = None
        self.outdoor_temperature_celsius: float | None = None
        self.wait_reason: str | None = None
        self.sun_on_window = False
        self.automation_active = False
        self.shading_required = False
        self.night_away_active = False
        self.temperature_celsius: float | None = None

    @property
    def settings(self) -> dict[str, Any]:
        """Return window data merged with the shared behavior settings."""
        return {
            **self.entry.data,
            **self.entry.options,
            **self.global_settings.settings,
        }

    @property
    def is_global_owner(self) -> bool:
        """Return whether this window hosts the global control entities."""
        return self.global_settings.is_owner(self.entry.entry_id)

    async def async_setup(self) -> None:
        """Restore state and start tracking Home Assistant entities."""
        stored = await self._store.async_load() or {}
        self.managed_closed = bool(stored.get("managed_closed", False))
        self.night_closed = bool(stored.get("night_closed", False))
        self.manual_override = bool(stored.get("manual_override", False))
        self.last_desired_closed = bool(stored.get("last_desired_closed", False))
        target = finite_float(stored.get("last_position_target"))
        if target is not None and 0 <= target <= 100:
            self.last_position_target = int(target)
        self._thermal_active = bool(stored.get("thermal_active", False))
        try:
            self._last_attempt = datetime.fromisoformat(stored["last_attempt"])
            if self._last_attempt.tzinfo is None:
                self._last_attempt = None
        except (KeyError, TypeError, ValueError):
            self._last_attempt = None
        self._last_attempt_target = stored.get("last_attempt_target")
        self._last_saved_state = self._runtime_state()
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
        if outdoor := settings.get(CONF_OUTDOOR_TEMPERATURE_ENTITY):
            entities.add(outdoor)
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
            self.last_position_target = None
            self._last_attempt = None
            self._last_attempt_target = None
            self._thermal_active = False
            self._expected_position = None
            self._pending_stop_since = None
            self._ignore_cover_changes_until = None
        self._candidate = None
        self._candidate_since = None
        self._no_sun_since = None
        self._subscribe_to_entities()
        await self.async_evaluate("settings")

    async def async_global_settings_updated(self) -> None:
        """Apply a shared behavior change to this window."""
        self._subscribe_to_entities()
        await self.async_evaluate("global_settings")

    async def async_update_setting(self, key: str, value: Any) -> None:
        """Persist a shared setting changed by a global control entity."""
        await self.global_settings.async_update(key, value)

    @callback
    def _async_state_changed(self, event: Event) -> None:
        entity_id = event.data["entity_id"]
        if entity_id == self.settings[CONF_COVER_ENTITY]:
            self._handle_cover_state_change(
                event.data.get("new_state"), event.data.get("old_state")
            )
        self.hass.async_create_task(self.async_evaluate(f"state:{entity_id}"))

    @callback
    def _handle_cover_state_change(
        self, new_state: State | None, old_state: State | None = None
    ) -> None:
        """Detect a manual action and pause control for this decision cycle."""
        if new_state is None or new_state.state not in {
            STATE_OPEN,
            STATE_OPENING,
            STATE_CLOSED,
            STATE_CLOSING,
        }:
            return
        if old_state is not None:
            if old_state.state in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
                return
            if old_state.state == new_state.state and old_state.attributes.get(
                "current_position"
            ) == new_state.attributes.get("current_position"):
                return
        if self._progressive_active:
            if self._is_expected_position_change(new_state, old_state):
                return
            if self.last_desired_closed or self.managed_closed:
                self._mark_manual_override()
                self.hass.async_create_task(self._async_save_state())
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
        async with self._evaluation_lock:
            await self._async_evaluate_locked(reason)

    async def _async_evaluate_locked(self, reason: str) -> None:
        settings = self.settings
        sun_state = self.hass.states.get(SUN_ENTITY_ID)
        cover_state = self.hass.states.get(settings[CONF_COVER_ENTITY])
        temperature_state = self.hass.states.get(settings[CONF_TEMPERATURE_ENTITY])

        if cover_state is None or cover_state.state in {
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        }:
            self.automation_active = False
            self.wait_reason = "cover_unavailable"
            self._candidate = None
            self._candidate_since = None
            self._no_sun_since = None
            self._notify_subscribers()
            return
        self._progressive_active = self._can_use_progressive(cover_state)
        if sun_state is None and not self._progressive_active:
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

        if self._progressive_active:
            await self._async_evaluate_progressive(sun_state, cover_state, away)
            await self._async_save_state()
            self._notify_subscribers()
            return

        self.calculated_target = None
        self.effective_threshold = None
        self.outdoor_temperature_celsius = None
        self._thermal_active = False
        self._candidate = None
        self._candidate_since = None
        self._no_sun_since = None
        self.wait_reason = (
            "binary_fallback" if settings.get(CONF_PROGRESSIVE_ENABLED) else None
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
            and (
                self.temperature_celsius is None
                or self.temperature_celsius >= effective_threshold
            )
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

    def _can_use_progressive(self, cover: State) -> bool:
        settings = self.settings
        if not settings.get(CONF_PROGRESSIVE_ENABLED, False):
            return False
        features = finite_float(cover.attributes.get("supported_features"))
        if features is None or not int(features) & CoverEntityFeature.SET_POSITION:
            return False
        facade = finite_float(settings.get(CONF_FACADE_AZIMUTH))
        height = finite_float(settings.get(CONF_WINDOW_HEIGHT))
        sill = finite_float(settings.get(CONF_SILL_HEIGHT))
        depth = finite_float(settings.get(CONF_SUN_DEPTH))
        return (
            facade is not None
            and 0 <= facade <= 360
            and height is not None
            and height > 0
            and sill is not None
            and sill >= 0
            and depth is not None
            and depth > 0
        )

    @staticmethod
    def _cover_position(state: State | None) -> float | None:
        if state is None or state.state in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
            return None
        position = finite_float(state.attributes.get("current_position"))
        if position is not None and 0 <= position <= 100:
            return position
        return 0.0 if state.state == STATE_CLOSED else None

    def _is_expected_position_change(
        self, state: State, old_state: State | None
    ) -> bool:
        """Accept progress towards our target, but not a reversal or early stop."""
        target = self._expected_position
        if (
            target is None
            or self._ignore_cover_changes_until is None
            or dt_util.utcnow() >= self._ignore_cover_changes_until
        ):
            return False
        position = self._cover_position(state)
        if position is not None and abs(position - target) <= POSITION_TOLERANCE:
            # Keep accepting final position reports until the command window
            # expires: some devices publish OPEN at 52, then 51, then 50%.
            self._pending_stop_since = None
            return True
        start = self._command_start_position
        if start is None:
            return False
        direction = STATE_OPENING if target > start else STATE_CLOSING
        old_position = self._cover_position(old_state)
        if old_position is None:
            old_position = start
        moving_towards = position is None or (
            min(start, target) - POSITION_TOLERANCE
            <= position
            <= max(start, target) + POSITION_TOLERANCE
            and (
                position >= old_position if target > start else position <= old_position
            )
        )
        if state.state == direction and moving_towards:
            self._pending_stop_since = None
            return True
        # Schneider reports OPEN with the previous position between updates.
        # Give the next movement report time to arrive before treating it as STOP.
        if state.state == STATE_OPEN and position is not None and moving_towards:
            if abs(position - target) < abs(old_position - target):
                self._pending_stop_since = None
            elif self._pending_stop_since is None:
                self._pending_stop_since = dt_util.utcnow()
            return True
        return False

    def _mark_manual_override(self) -> None:
        """Relinquish ownership after a confirmed unexpected movement or stop."""
        self.manual_override = True
        self.managed_closed = False
        self._expected_position = None
        self._pending_stop_since = None
        self._candidate = None
        self._candidate_since = None

    def _stop_confirmation_pending(self, cover: State, now: datetime) -> bool:
        """Confirm a stationary off-target cover, even without further events."""
        if self._pending_stop_since is None:
            return False
        position = self._cover_position(cover)
        if (
            self._expected_position is None
            or cover.state in {STATE_OPENING, STATE_CLOSING}
            or (
                position is not None
                and abs(position - self._expected_position) <= POSITION_TOLERANCE
            )
        ):
            self._pending_stop_since = None
            return False
        if position is None or now - self._pending_stop_since < STOP_CONFIRMATION:
            return True
        self._mark_manual_override()
        return False

    async def _async_evaluate_progressive(
        self, sun: State | None, cover: State, away: bool
    ) -> None:
        settings = self.settings
        now = dt_util.utcnow()
        self.wait_reason = None
        if self._stop_confirmation_pending(cover, now):
            self.wait_reason = "moving"
            return
        self.calculated_target = None
        self.temperature_celsius = self._temperature_in_celsius(
            self.hass.states.get(settings[CONF_TEMPERATURE_ENTITY])
        )
        outdoor_id = settings.get(CONF_OUTDOOR_TEMPERATURE_ENTITY)
        self.outdoor_temperature_celsius = self._temperature_in_celsius(
            self.hass.states.get(outdoor_id) if outdoor_id else None,
            weather=bool(outdoor_id and outdoor_id.startswith("weather.")),
        )
        self.effective_threshold = effective_temperature_threshold(
            self.get_float(CONF_TEMPERATURE_THRESHOLD, DEFAULT_TEMPERATURE_THRESHOLD),
            self.temperature_celsius,
            self.outdoor_temperature_celsius,
        )
        azimuth = self._float_attribute(sun, "azimuth") if sun else None
        elevation = self._float_attribute(sun, "elevation") if sun else None
        valid_sun = bool(
            sun is not None
            and sun.state in {"above_horizon", "below_horizon"}
            and azimuth is not None
            and elevation is not None
            and -90 <= elevation <= 90
        )
        self.sun_on_window = bool(
            valid_sun
            and elevation > 0
            and sun_is_in_front(azimuth, float(settings[CONF_FACADE_AZIMUTH]))
            and azimuth_is_in_range(
                azimuth,
                float(settings[CONF_AZIMUTH_START]),
                float(settings[CONF_AZIMUTH_END]),
            )
        )
        enabled = self.get_bool(CONF_ENABLED, DEFAULT_ENABLED)
        night_enabled = enabled and self.get_bool(
            CONF_DAWN_DUSK_AWAY, DEFAULT_DAWN_DUSK_AWAY
        )
        if valid_sun:
            self.night_away_active = bool(
                night_enabled
                and sun.state == "below_horizon"
                and (away or self.night_closed)
            )
        elif not night_enabled:
            self.night_away_active = False

        urgent = False
        cycle_active = False
        if self.night_away_active:
            raw_target, target, urgent, cycle_active = 0.0, 0, True, True
            self.shading_required = False
            self._no_sun_since = None
        elif not self.automation_active:
            raw_target, target, urgent = 100.0, 100, True
            self.shading_required = False
            self._thermal_active = False
            self._no_sun_since = None
        elif not valid_sun:
            self._candidate = None
            self._candidate_since = None
            self._no_sun_since = None
            self.wait_reason = "sun_unavailable"
            return
        elif not self.sun_on_window:
            self.shading_required = False
            if self._no_sun_since is None:
                self._no_sun_since = now
            self._candidate = None
            self._candidate_since = None
            if now - self._no_sun_since < TARGET_STABILITY:
                self.wait_reason = "no_sun_confirmation"
                return
            raw_target, target, urgent = 100.0, 100, True
            self._thermal_active = False
        else:
            self._no_sun_since = None
            heat_threshold = self.effective_threshold - (
                TEMPERATURE_HYSTERESIS if self._thermal_active else 0
            )
            self._thermal_active = (
                self.temperature_celsius is None
                or self.temperature_celsius >= heat_threshold
            )
            self.shading_required = self._thermal_active
            cycle_active = self._thermal_active
            if cycle_active:
                raw_target = geometric_opening(
                    azimuth=azimuth,
                    elevation=elevation,
                    facade=float(settings[CONF_FACADE_AZIMUTH]),
                    height=float(settings[CONF_WINDOW_HEIGHT]),
                    sill=float(settings[CONF_SILL_HEIGHT]),
                    depth=float(settings[CONF_SUN_DEPTH]),
                    indoor=self.temperature_celsius,
                    threshold=self.effective_threshold,
                )
                target = opening_step(raw_target, self.last_position_target)
            else:
                raw_target, target = 100.0, 100

        self.calculated_target = raw_target
        if not self.night_away_active:
            self.night_closed = False
        if cycle_active:
            self.last_desired_closed = True
            if self.manual_override:
                self.wait_reason = "manual_override"
                return
        if not urgent:
            if self._candidate != target:
                self._candidate = target
                self._candidate_since = now
            if (
                self._candidate_since is None
                or now - self._candidate_since < TARGET_STABILITY
            ):
                self.wait_reason = "target_confirmation"
                return
        else:
            self._candidate = None
            self._candidate_since = None
        if not cycle_active:
            self.manual_override = False
            self.last_desired_closed = False
        if self.manual_override:
            self.wait_reason = "manual_override"
            return
        if target == 100 and not self.managed_closed:
            self.wait_reason = "not_managed"
            return
        if cover.state in {STATE_OPENING, STATE_CLOSING}:
            self.wait_reason = "moving"
            return
        position = self._cover_position(cover)
        if position is None:
            self.wait_reason = "position_unavailable"
            return
        if (
            self._expected_position is not None
            and self._ignore_cover_changes_until is not None
            and now < self._ignore_cover_changes_until
            and abs(position - self._expected_position) > POSITION_TOLERANCE
        ):
            self.wait_reason = "moving"
            return
        if abs(position - target) <= POSITION_TOLERANCE:
            self.wait_reason = "at_target"
            if target == 100:
                self.managed_closed = False
            if self.night_away_active and self.managed_closed:
                self.night_closed = True
            return
        if (
            self._last_attempt is not None
            and now - self._last_attempt < SOLAR_COMMAND_INTERVAL
        ):
            # Priority transitions may bypass the interval, but a failed priority
            # command must not be retried every minute either.
            if not urgent or self._last_attempt_target == target:
                self.wait_reason = "command_interval"
                return
        self._last_attempt = now
        self._last_attempt_target = target
        self._expected_position = target
        self._command_start_position = position
        self._pending_stop_since = None
        # Retain the retry interval even if Home Assistant stops during the call.
        await self._async_save_state()
        if await self._async_call_cover(SERVICE_SET_COVER_POSITION, position=target):
            self.last_position_target = target
            self.managed_closed = target < 100 and not self.manual_override
            if self.night_away_active and self.managed_closed:
                self.night_closed = True
        else:
            self._expected_position = None
            self._pending_stop_since = None
            self.wait_reason = "command_failed"

    async def _async_call_cover(
        self, service: str, *, position: int | None = None
    ) -> bool:
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
                **(
                    {"service_data": {"position": position}}
                    if position is not None
                    else {}
                ),
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
        return finite_float(state.attributes.get(attribute))

    @staticmethod
    def _temperature_in_celsius(
        state: State | None, *, weather: bool = False
    ) -> float | None:
        if state is None or state.state in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
            return None
        value = finite_float(
            state.attributes.get("temperature") if weather else state.state
        )
        if value is None:
            return None
        unit = state.attributes.get(
            "temperature_unit" if weather else ATTR_UNIT_OF_MEASUREMENT
        )
        if not unit or unit == UnitOfTemperature.CELSIUS:
            return value
        try:
            return finite_float(
                TemperatureConverter.convert(value, unit, UnitOfTemperature.CELSIUS)
            )
        except (TypeError, ValueError):
            return None

    def get_bool(self, key: str, default: bool) -> bool:
        return bool(self.settings.get(key, default))

    def get_float(self, key: str, default: float) -> float:
        value = finite_float(self.settings.get(key, default))
        return default if value is None else value

    def get_time(self, key: str, default: time) -> time:
        value = self.settings.get(key, default.isoformat())
        if isinstance(value, time):
            return value
        try:
            return time.fromisoformat(value)
        except (TypeError, ValueError):
            return default

    def _runtime_state(self) -> dict[str, Any]:
        return {
            "managed_closed": self.managed_closed,
            "night_closed": self.night_closed,
            "manual_override": self.manual_override,
            "last_desired_closed": self.last_desired_closed,
            "last_position_target": self.last_position_target,
            "last_attempt": self._last_attempt.isoformat()
            if self._last_attempt
            else None,
            "last_attempt_target": self._last_attempt_target,
            "thermal_active": self._thermal_active,
        }

    async def _async_save_state(self) -> None:
        current_state = self._runtime_state()
        if current_state == self._last_saved_state:
            return
        await self._store.async_save(current_state)
        self._last_saved_state = current_state
