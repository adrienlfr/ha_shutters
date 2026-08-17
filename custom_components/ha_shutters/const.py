"""Constants for the Solar Shutters integration."""

from datetime import time
from typing import Final

DOMAIN: Final = "ha_shutters"
PLATFORMS: Final = ["binary_sensor", "number", "switch", "time"]
DATA_GLOBAL_MANAGER: Final = "global_settings_manager"

CONF_WINDOW_NAME: Final = "window_name"
CONF_COVER_ENTITY: Final = "cover_entity"
CONF_TEMPERATURE_ENTITY: Final = "temperature_entity"
CONF_PRESENCE_ENTITIES: Final = "presence_entities"
CONF_AZIMUTH_START: Final = "azimuth_start"
CONF_AZIMUTH_END: Final = "azimuth_end"

CONF_ENABLED: Final = "enabled"
CONF_ONLY_AWAY: Final = "only_away"
CONF_TELEWORK_ENABLED: Final = "telework_enabled"
CONF_TELEWORK_START: Final = "telework_start"
CONF_TELEWORK_END: Final = "telework_end"
CONF_DAWN_DUSK_AWAY: Final = "dawn_dusk_away"
CONF_TEMPERATURE_THRESHOLD: Final = "temperature_threshold"

DEFAULT_ENABLED: Final = True
DEFAULT_ONLY_AWAY: Final = True
DEFAULT_TELEWORK_ENABLED: Final = False
DEFAULT_TELEWORK_START: Final = time(8, 0)
DEFAULT_TELEWORK_END: Final = time(18, 0)
DEFAULT_DAWN_DUSK_AWAY: Final = False
DEFAULT_TEMPERATURE_THRESHOLD: Final = 24.0

TEMPERATURE_HYSTERESIS: Final = 0.5
STORAGE_VERSION: Final = 1

GLOBAL_SETTING_KEYS: Final = (
    CONF_ENABLED,
    CONF_ONLY_AWAY,
    CONF_TELEWORK_ENABLED,
    CONF_TELEWORK_START,
    CONF_TELEWORK_END,
    CONF_DAWN_DUSK_AWAY,
    CONF_TEMPERATURE_THRESHOLD,
)
DEFAULT_GLOBAL_SETTINGS: Final = {
    CONF_ENABLED: DEFAULT_ENABLED,
    CONF_ONLY_AWAY: DEFAULT_ONLY_AWAY,
    CONF_TELEWORK_ENABLED: DEFAULT_TELEWORK_ENABLED,
    CONF_TELEWORK_START: DEFAULT_TELEWORK_START.isoformat(),
    CONF_TELEWORK_END: DEFAULT_TELEWORK_END.isoformat(),
    CONF_DAWN_DUSK_AWAY: DEFAULT_DAWN_DUSK_AWAY,
    CONF_TEMPERATURE_THRESHOLD: DEFAULT_TEMPERATURE_THRESHOLD,
}
