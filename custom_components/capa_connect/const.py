"""Constants for the Capa Connect (Glen Dimplex / GDHV IoT) integration."""

DOMAIN = "capa_connect"

# --- GDHV IoT device API ---
API_BASE = "https://mobileapi.gdhv-iot.com"

# Headers the device API expects (captured from the app). app_name identifies
# the white-label; api_version gates the endpoint contract.
DEVICE_HEADERS = {
    "app_name": "CapaConnect",
    "app_version": "3.24.0",
    "api_version": "1.0",
    "app_device_os": "iOS",
    "lang_code": "en",
    "logging_required_flag": "0",
    "Accept": "*/*",
}

# --- Azure AD B2C auth ---
B2C_BASE = "https://gdhvb2c.b2clogin.com"
B2C_TENANT = "gdhvb2c.onmicrosoft.com"
B2C_POLICY = "B2C_1A_CapaConnectSignupSignIn"
CLIENT_ID = "fc527388-5067-4934-8e38-27d927457e01"
SCOPE = "https://gdhvb2c.onmicrosoft.com/Mobile/read offline_access openid profile"
REDIRECT_URI = "msalfc527388-5067-4934-8e38-27d927457e01://auth"

AUTHORIZE_URL = f"{B2C_BASE}/tfp/{B2C_TENANT}/{B2C_POLICY}/oauth2/v2.0/authorize"
TOKEN_URL = f"{B2C_BASE}/tfp/{B2C_TENANT}/{B2C_POLICY}/oauth2/v2.0/token"
SELFASSERTED_URL = f"{B2C_BASE}/{B2C_TENANT}/{B2C_POLICY}/SelfAsserted"
CONFIRMED_URL = (
    f"{B2C_BASE}/{B2C_TENANT}/{B2C_POLICY}/api/CombinedSigninAndSignup/confirmed"
)

# --- Zone operating modes (PERMANENT variants only; the +1 "until next schedule
# block" overrides and the schedule-only modes 3/6 are deliberately not used). ---
MODE_OFF = 0
MODE_AWAY = 2  # frost/away, holds ~7 C
MODE_COMFORT = 5  # permanent, uses the zone's ComfortTemp
MODE_ECO = 8  # permanent, uses the zone's EcoTemp
# Standby: the zone's schedule is suspended and the heater is off. The app shows
# "no heating / Standby / Until schedule resumed" with a "Resume schedule" button.
# Distinct from a hard Off (0), but for HA's purposes both mean "not heating".
MODE_STANDBY = 13

# Human-readable labels for every raw GDHV mode observed so far. Unknown values
# (e.g. from a heater family the integration has not been tested against) are
# rendered as ``mode_<n>`` so they remain visible in HA.
MODE_LABELS = {
    0: "off",
    2: "away",
    3: "schedule_comfort",
    4: "comfort_until_next_block",
    5: "comfort",
    6: "schedule_eco",
    7: "eco_until_next_block",
    8: "eco",
    13: "standby",
}


def mode_label(mode: int | None) -> str | None:
    """Return the label for a raw GDHV mode, or ``mode_<n>`` when unknown."""
    if mode is None:
        return None
    return MODE_LABELS.get(mode, f"mode_{mode}")


# "No setpoint" sentinel the API uses for modes without a target temperature.
TEMP_NONE = 255

PRESET_AWAY = "away"
PRESET_ECO = "eco"
PRESET_COMFORT = "comfort"

PRESET_TO_MODE = {
    PRESET_AWAY: MODE_AWAY,
    PRESET_ECO: MODE_ECO,
    PRESET_COMFORT: MODE_COMFORT,
}
MODE_TO_PRESET = {v: k for k, v in PRESET_TO_MODE.items()}
# Any of these mode values means the heater is actively heating (HVAC "heat").
HEATING_MODES = set(PRESET_TO_MODE.values())

# Setpoint bounds for the HA climate entity.
MIN_TEMP = 5
MAX_TEMP = 30

# --- Polling (configurable via the integration's options) ---
CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = 60  # seconds
MIN_SCAN_INTERVAL = 30
MAX_SCAN_INTERVAL = 600

# --- Branding ---
# Capa Connect is a white-label app shared by several Glen Dimplex brands. The
# API only exposes the product model name, so the brand is inferred from it
# where possible and otherwise falls back to the group name.
DEFAULT_MANUFACTURER = "Glen Dimplex (GDHV)"
MANUFACTURER_HINTS = (
    ("dtd", "Dimplex"),  # Alta Wi-Fi panel heaters: DTD2R.., DTD4R..
    ("alta", "Dimplex"),
    ("dimplex", "Dimplex"),
    ("muller", "Noirot"),  # "Muller PH Wifi" = Noirot Spot Plus
    ("noirot", "Noirot"),
    ("nobo", "Nobø"),
    ("intuis", "Intuis"),
    ("heatstore", "Heatstore"),
)


def manufacturer_for(model: str | None, product_type: str | None = None) -> str:
    """Best-effort brand name for a GDHV product.

    ``product_type`` (e.g. "Dimplex Wi-Fi") is checked first because it names
    the brand directly; the model string (e.g. "DTD2R 073L-102 DX") is the
    fallback.
    """
    for text in (product_type, model):
        if not text:
            continue
        lowered = text.lower()
        for needle, brand in MANUFACTURER_HINTS:
            if needle in lowered:
                return brand
    return DEFAULT_MANUFACTURER
