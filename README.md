# Capa Connect for Home Assistant

A custom Home Assistant integration for Wi-Fi panel heaters controlled by the
**Capa Connect** app — the Glen Dimplex Heating & Ventilation (GDHV) IoT cloud
used by **Dimplex** (Alta Wi-Fi, DTD2R/DTD4R), **Nobø**, **Noirot**, **Intuis**
and **Heatstore** heaters.

It talks to the same cloud API the app uses (`mobileapi.gdhv-iot.com`, behind
Azure AD B2C). There is no local API on these heaters, so this is a
`cloud_polling` integration.

This is a fork of [guiguan/hass-capa-connect](https://github.com/guiguan/hass-capa-connect),
which was built and tested against a **Noirot "Spot Plus"** (model DM73588TPRO
FDFS, product type "Muller PH Wifi"). This fork adds multi-site / multi-heater
support, extra sensors, diagnostics, a configurable polling interval, a
Norwegian translation and a probe script, with the goal of verifying and
supporting the **Dimplex Alta DTD2R** family.

> **Status for Dimplex Alta DTD2R:** the *read* path is verified against three
> `DTD2R 073L-102 DX` heaters (product type "Dimplex Wi-Fi", firmware
> `EP4139_WIFI_5_0_PRD_260326`) via `scripts/probe_api.py`: same zone/appliance
> model and field names as the Noirot heater, including a zone with two heaters.
> Writing modes and setpoints has not been exercised on Alta yet. Run the probe
> script or download diagnostics from HA and open an issue if something looks off.

## Features

Each heater zone becomes a **device** with:

- **`climate`** entity
  - HVAC modes `off` / `heat`; presets `comfort`, `eco`, `away` (frost, ~7 °C)
  - Current temperature (mean of the zone's heaters) and whole-degree target
    temperature (the heater only accepts integers; half-degrees round up)
  - **Resume on turn-on** — turning off and back on restores the previous mode
    and setpoint (remembered across HA restarts) instead of defaulting to Comfort
  - **Instant feedback** — changes made in HA are reflected immediately; the next
    poll reconciles them
  - Attributes: `gdhv_mode`, `gdhv_mode_label`, `schedule`, `site`, `heaters`
- **`sensor`** entities: room temperature, comfort setpoint, eco setpoint,
  raw heater mode (enum), active schedule name. Zones with more than one heater
  also get one temperature sensor per heater.
- **`binary_sensor`** entities: connectivity (stays available when the heater is
  offline, unlike the climate entity, so automations can react to drop-outs) and
  the app's child lock on the heater's buttons (read-only)
- **Diagnostics download** with the normalised state *and* the last raw API
  payloads (personal fields redacted)
- **Options**: polling interval, 30–600 s (default 60)

The integration controls the heater using the cloud's four **permanent** modes:
Off (0), Away (2), Comfort (5), Eco (8).

## How it works

- **Polling:** the cloud has no push API, so state is polled on an interval.
  Changes made elsewhere (the Capa app, the heater's own buttons) appear at the
  next poll.
- **Authentication:** you sign in once with your email and password; only the
  rotating OAuth refresh token is stored — never the password. The token
  auto-renews on each poll. If it ever expires, HA prompts you to re-enter your
  password (reauth).
- **All sites** on the account are imported, each with all its zones. Zones
  with no heater assigned (the app lets you create them ahead of time) are
  skipped.

## Installation

### HACS (custom repository)

1. HACS → Integrations → ⋮ → Custom repositories.
2. Add `https://github.com/aulonm/hass-capa-connect` as an **Integration**.
3. Install "Capa Connect (Dimplex / Noirot / GDHV)" and restart Home Assistant.

### Manual

Copy `custom_components/capa_connect/` into your HA `config/custom_components/`
directory and restart.

## Configuration

Settings → Devices & Services → **Add Integration** → "Capa Connect", then enter
the email and password for your Capa Connect account. The polling interval can
be changed afterwards under the integration's **Configure** button.

## Checking your heaters before installing (probe script)

`scripts/probe_api.py` signs in with your account, reads every site, zone and
heater, prints a summary and the raw JSON, and writes nothing to the heaters.
Use it to confirm a new model works, or to gather data for an issue.

```bash
python3 -m venv .venv && .venv/bin/pip install -r scripts/requirements.txt
CAPA_EMAIL=you@example.com .venv/bin/python scripts/probe_api.py --redact --out probe.json
```

You are prompted for the password (or set `CAPA_PASSWORD`). `--redact` blanks
personal fields; `probe*.json` is git-ignored.

## Known limitations

- **Standby and schedules.** Putting the zone in **standby** — the app's "no
  heating / Until schedule resumed" state, where the schedule is suspended —
  reports mode 13, and the integration shows this as **off** to match the app.
  Actively *running* a schedule with heating blocks is not modelled: the
  `until-next-block` modes (4/7) show as generic `heat` without a preset. The
  `heater mode` sensor exposes the raw device mode.
- **HomeKit temperature step.** Apple's Home app always offers a 0.5° slider for
  thermostats — HA's HomeKit bridge hardcodes the characteristic step and ignores
  the entity's step. The heater still lands on a whole degree, because
  half-degree values are rounded before being sent.
- **Out-of-band changes** appear at the next poll, not instantly.
- **Comfort/eco setpoints and the controls lock** are read-only for now; the
  API calls the app uses to edit them have not been captured yet.
- **Away schedule.** A zone following the default "24 hour Away" schedule
  reports raw mode 0 with a 7 °C setpoint. The integration shows this as `off`,
  the same way the app shows "no heating", even though the heater is holding
  frost protection.
- This is **unofficial** and not affiliated with Glen Dimplex, Dimplex, Nobø or
  Noirot. It relies on a private API that could change at any time.

## Development notes

- Mode codes, endpoints and headers live in `custom_components/capa_connect/const.py`
  and `api.py`. New endpoints should be added to `CapaClient`.
- Unknown raw modes are shown as `mode_<n>` in the mode sensor's `raw_mode`
  attribute so they are visible without breaking the enum.
- Related project for the sibling "Dimplex Control / Hub" app (same cloud,
  different B2C policy and endpoints):
  [KRoperUK/dimplex-controller-py](https://github.com/KRoperUK/dimplex-controller-py).
