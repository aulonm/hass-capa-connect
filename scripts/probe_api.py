#!/usr/bin/env python3
"""Dump what the Capa Connect cloud knows about your heaters.

Run this before (or instead of) installing the integration to see the raw API
payloads for your account. It is the quickest way to check whether a heater
model that has not been tested yet (e.g. Dimplex Alta DTD2R / DTD4R) exposes
the same fields and mode codes as the ones the integration was built against.

Usage (from the repository root):

    python3 -m venv .venv && .venv/bin/pip install aiohttp
    CAPA_EMAIL=you@example.com CAPA_PASSWORD='...' .venv/bin/python scripts/probe_api.py

Or omit the environment variables and you will be prompted (the password
prompt does not echo). Pass ``--out FILE`` to also write the full JSON to disk
and ``--redact`` to blank out personal fields before printing/saving.

Nothing is written to the heaters; this script only reads.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
import types
from pathlib import Path
from typing import Any

import aiohttp

# Reuse the integration's own client so the probe exercises exactly the code HA
# will run. ``api.py`` and ``const.py`` only need aiohttp, but the package's
# ``__init__.py`` imports Home Assistant, so register the package by hand
# (with its search path) instead of importing it — submodules then load
# without ``__init__`` ever running.
ROOT = Path(__file__).resolve().parent.parent
_pkg = types.ModuleType("capa_connect")
_pkg.__path__ = [str(ROOT / "custom_components" / "capa_connect")]
sys.modules["capa_connect"] = _pkg

from capa_connect.api import CapaAuth, CapaClient  # noqa: E402
from capa_connect.const import mode_label  # noqa: E402

REDACT_KEYS = {
    "Email",
    "UserName",
    "FirstName",
    "LastName",
    "PhoneNumber",
    "Address",
    "AddressLine1",
    "AddressLine2",
    "PostCode",
    "Postcode",
    "City",
    "Latitude",
    "Longitude",
    "MacAddress",
    "SerialNumber",
    "DeviceId",
    "PrimaryUserEmail",
    # BLE pairing identity + 6-digit pairing code of each heater.
    "BLEIdentifier",
    "SecurityCode",
}


def redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: ("**REDACTED**" if k in REDACT_KEYS else redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


async def probe(email: str, password: str) -> dict[str, Any]:
    # Same cookie-jar quirk as the config flow: B2C rejects quoted cookies.
    jar = aiohttp.CookieJar(quote_cookie=False)
    async with aiohttp.ClientSession(cookie_jar=jar) as session:
        auth = CapaAuth(session)
        print("Signing in to Azure B2C…", file=sys.stderr)
        await auth.login(email, password)
        client = CapaClient(session, auth)

        result: dict[str, Any] = {"sites": [], "zones": {}}
        sites = await client.get_sites()
        result["sites"] = sites
        for site in sites:
            site_id = site["Id"]
            print(f"Site {site.get('Name')!r} ({site_id})", file=sys.stderr)
            temps, zone_list = await asyncio.gather(
                client.get_room_temps(site_id), client.get_zones(site_id)
            )
            result["zones"][site_id] = {
                "room_temperatures": temps,
                "zone_list": zone_list,
                "zone_details": {},
            }
            for z in zone_list:
                detail = await client.get_zone(z["Id"], site_id)
                result["zones"][site_id]["zone_details"][z["Id"]] = detail
        return result


def summarise(data: dict[str, Any]) -> None:
    """Print a compact human-readable table before the raw JSON."""
    print("\n=== Summary ===")
    for site in data["sites"]:
        site_id = site["Id"]
        block = data["zones"].get(site_id, {})
        temps = block.get("room_temperatures", {})
        print(f"Site: {site.get('Name')}")
        for zone_id, detail in block.get("zone_details", {}).items():
            setting = detail.get("DirectZoneSetting") or {}
            mode = setting.get("CurrentMode")
            print(
                f"  Zone {detail.get('ZoneName') or zone_id}: "
                f"mode={mode} ({mode_label(mode)}) "
                f"setpoint={setting.get('CurrentTemperature')} "
                f"comfort={setting.get('ComfortTemp')} eco={setting.get('EcoTemp')} "
                f"schedule={(setting.get('DirectSchedule') or {}).get('ScheduleName')!r}"
            )
            if not detail.get("DirectAppliances"):
                print("    (no heaters assigned — the integration skips this zone)")
            for app in detail.get("DirectAppliances") or []:
                print(
                    f"    Heater {app.get('FriendlyName')!r}: "
                    f"model={app.get('ProductModelName')!r} "
                    f"type={app.get('ProductTypeName')!r} "
                    f"fw={app.get('FirmwareVersion')} "
                    f"connected={app.get('IsConnected')} "
                    f"room_temp={temps.get(app.get('Id'))}"
                )
                extra = sorted(
                    k
                    for k in app
                    if k
                    not in {
                        "Id",
                        "FriendlyName",
                        "ProductModelName",
                        "FirmwareVersion",
                        "IsConnected",
                    }
                )
                print(f"      other appliance fields: {', '.join(extra)}")
            extra_setting = sorted(
                k
                for k in setting
                if k
                not in {
                    "CurrentMode",
                    "CurrentTemperature",
                    "ComfortTemp",
                    "EcoTemp",
                    "DirectSchedule",
                    "ScheduleId",
                }
            )
            print(
                f"    lock_status={setting.get('LockStatus')} "
                f"override_until={setting.get('OverrideDateTo')}"
            )
            print(f"    other zone-setting fields: {', '.join(extra_setting)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, help="write full JSON to this file")
    parser.add_argument(
        "--redact", action="store_true", help="blank out personal fields"
    )
    parser.add_argument(
        "--quiet", action="store_true", help="print the summary only, not the JSON"
    )
    args = parser.parse_args()

    email = os.environ.get("CAPA_EMAIL") or input("Capa Connect email: ")
    password = os.environ.get("CAPA_PASSWORD") or getpass.getpass(
        "Capa Connect password: "
    )

    try:
        data = asyncio.run(probe(email, password))
    except Exception as err:  # noqa: BLE001 - a probe should show any failure
        print(f"FAILED: {type(err).__name__}: {err}", file=sys.stderr)
        return 1

    if args.redact:
        data = redact(data)
    summarise(data)
    if args.out:
        args.out.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        print(f"\nFull JSON written to {args.out}")
    if not args.quiet:
        print("\n=== Raw JSON ===")
        print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
