"""Small HA boundary doubles; serialization uses the real pinned ical library."""
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for name in (
    'homeassistant', 'homeassistant.components', 'homeassistant.components.frontend',
    'homeassistant.components.http', 'homeassistant.core', 'homeassistant.helpers',
    'homeassistant.helpers.entity_registry', 'homeassistant.helpers.typing',
    'homeassistant.helpers.selector', 'homeassistant.config_entries',
    'homeassistant.exceptions', 'homeassistant.helpers.storage',
    'homeassistant.helpers.aiohttp_client',
):
    module = ModuleType(name)
    sys.modules[name] = module
    if '.' in name:
        parent, child = name.rsplit('.', 1)
        setattr(sys.modules[parent], child, module)

class Flow:
    def __init_subclass__(cls, **kwargs):
        pass

ha = sys.modules['homeassistant']
ha.core.HomeAssistant = MagicMock
ha.config_entries.ConfigEntry = MagicMock
ha.config_entries.ConfigFlow = Flow
ha.config_entries.OptionsFlow = Flow
ha.config_entries.SOURCE_USER = 'user'
ha.config_entries.FlowType = MagicMock()
ha.exceptions.ConfigEntryNotReady = type('ConfigEntryNotReady', (Exception,), {})
ha.helpers.typing.ConfigType = dict
ha.components.http.HomeAssistantView = object
ha.components.frontend.DEFAULT_THEME_COLOR = '#03a9f4'
ha.components.frontend.DATA_THEMES = 'themes'
ha.components.frontend.DATA_DEFAULT_THEME = 'default_theme'
ha.components.frontend.DEFAULT_THEME = 'default'
ha.helpers.entity_registry.async_get = lambda hass: hass.registry

ha.exceptions.HomeAssistantError = type("HomeAssistantError", (Exception,), {})
ha.helpers.storage.Store = MagicMock()

ha.helpers.aiohttp_client.async_get_clientsession = MagicMock()
