"""
onboard_devices.py — Bulk device registration for Vantage NMS.

Usage:
    python onboard_devices.py --csv devices.csv

CSV columns (required):
    name, device_class, location, protocol, asset_group

CSV columns (optional):
    description

Outputs: credentials.csv  (name, device_id, access_token)

device_class values : hvac | energy | occupancy | elevator | fire | network | infra
asset_group values  : BMS/HVAC | BMS/Energy | BMS/Occupancy | BMS/Elevator |
                      BMS/Fire_Access | NMS/Network | NMS/Infrastructure
protocol values     : mqtt | snmp | bacnet | modbus
"""

import argparse
import csv
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

TB_URL = os.getenv("TB_URL", "http://localhost:8080")
TB_ADMIN_USER = os.getenv("TB_ADMIN_USER", "tenant@thingsboard.org")
TB_ADMIN_PASSWORD = os.getenv("TB_ADMIN_PASSWORD", "changeme")

# Asset hierarchy to create
ASSET_GROUPS = [
    "Site",
    "BMS",
    "BMS/HVAC",
    "BMS/Energy",
    "BMS/Occupancy",
    "BMS/Elevator",
    "BMS/Fire_Access",
    "NMS",
    "NMS/Network",
    "NMS/Infrastructure",
]

ASSET_GROUP_TO_DEVICE_CLASS = {
    "BMS/HVAC": "hvac",
    "BMS/Energy": "energy",
    "BMS/Occupancy": "occupancy",
    "BMS/Elevator": "elevator",
    "BMS/Fire_Access": "fire",
    "NMS/Network": "network",
    "NMS/Infrastructure": "infra",
}


class TBOnboardClient:
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.token: str | None = None
        self.client = httpx.Client(timeout=30)

    def login(self) -> None:
        resp = self.client.post(
            f"{self.base_url}/api/auth/login",
            json={"username": self.username, "password": self.password},
        )
        resp.raise_for_status()
        self.token = resp.json()["token"]
        self.client.headers["X-Authorization"] = f"Bearer {self.token}"
        print(f"[auth] Logged in as {self.username}")

    def _get(self, path: str, **kwargs) -> dict:
        resp = self.client.get(f"{self.base_url}{path}", **kwargs)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, json: dict) -> dict:
        resp = self.client.post(f"{self.base_url}{path}", json=json)
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str) -> None:
        resp = self.client.delete(f"{self.base_url}{path}")
        resp.raise_for_status()

    # ── Asset management ────────────────────────────────────────────────────

    def get_or_create_asset(self, name: str) -> dict:
        """Create an asset if it doesn't exist; return the asset dict."""
        try:
            existing = self._get(
                "/api/tenant/assets",
                params={"pageSize": 100, "page": 0, "textSearch": name},
            )
            for asset in existing.get("data", []):
                if asset["name"] == name:
                    return asset
        except httpx.HTTPStatusError:
            pass

        asset = self._post("/api/asset", {"name": name, "type": "asset_group"})
        print(f"  [asset] Created: {name}")
        return asset

    def create_asset_relation(self, parent_id: str, child_id: str) -> None:
        """Create a Contains relation from parent asset to child asset."""
        self._post(
            "/api/relation",
            {
                "from": {"id": parent_id, "entityType": "ASSET"},
                "to": {"id": child_id, "entityType": "ASSET"},
                "type": "Contains",
                "typeGroup": "COMMON",
            },
        )

    # ── Device management ────────────────────────────────────────────────────

    def create_device(self, name: str, device_type: str, description: str = "") -> dict:
        payload: dict = {
            "name": name,
            "type": device_type,
        }
        if description:
            payload["additionalInfo"] = {"description": description}
        return self._post("/api/device", payload)

    def get_device_credentials(self, device_id: str) -> dict:
        return self._get(f"/api/device/{device_id}/credentials")

    def set_shared_attributes(self, device_id: str, attributes: dict) -> None:
        resp = self.client.post(
            f"{self.base_url}/api/plugins/telemetry/DEVICE/{device_id}/attributes/SHARED_SCOPE",
            json=attributes,
        )
        resp.raise_for_status()

    def assign_device_to_asset(self, asset_id: str, device_id: str) -> None:
        self._post(
            "/api/relation",
            {
                "from": {"id": asset_id, "entityType": "ASSET"},
                "to": {"id": device_id, "entityType": "DEVICE"},
                "type": "Contains",
                "typeGroup": "COMMON",
            },
        )


def build_asset_tree(client: TBOnboardClient) -> dict[str, str]:
    """Create the full asset hierarchy; return {name: asset_id}."""
    print("\n[assets] Building asset hierarchy...")
    asset_ids: dict[str, str] = {}

    for group_name in ASSET_GROUPS:
        asset = client.get_or_create_asset(group_name)
        asset_ids[group_name] = asset["id"]["id"]

    # Wire parent→child relations
    relations = [
        ("Site", "BMS"),
        ("Site", "NMS"),
        ("BMS", "BMS/HVAC"),
        ("BMS", "BMS/Energy"),
        ("BMS", "BMS/Occupancy"),
        ("BMS", "BMS/Elevator"),
        ("BMS", "BMS/Fire_Access"),
        ("NMS", "NMS/Network"),
        ("NMS", "NMS/Infrastructure"),
    ]
    for parent, child in relations:
        try:
            client.create_asset_relation(asset_ids[parent], asset_ids[child])
        except httpx.HTTPStatusError:
            pass  # Relation may already exist

    print(f"  [assets] {len(asset_ids)} asset groups ready")
    return asset_ids


def onboard_devices(csv_path: str, asset_ids: dict[str, str], client: TBOnboardClient) -> list[dict]:
    print(f"\n[devices] Reading {csv_path}...")
    results: list[dict] = []

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"  [devices] Found {len(rows)} devices to register")

    for i, row in enumerate(rows, 1):
        name = row["name"].strip()
        device_class = row["device_class"].strip().lower()
        location = row["location"].strip()
        protocol = row["protocol"].strip().lower()
        asset_group = row["asset_group"].strip()
        description = row.get("description", "").strip()

        print(f"  [{i}/{len(rows)}] Registering {name} ({device_class})...", end=" ")

        try:
            device = client.create_device(name, device_class, description)
            device_id = device["id"]["id"]

            # Set shared attributes
            client.set_shared_attributes(device_id, {
                "device_class": device_class,
                "location": location,
                "protocol": protocol,
                "baseline_days": 30,
            })

            # Assign to asset group
            if asset_group in asset_ids:
                client.assign_device_to_asset(asset_ids[asset_group], device_id)

            # Get access token
            creds = client.get_device_credentials(device_id)
            access_token = creds.get("credentialsId", "")

            results.append({
                "name": name,
                "device_id": device_id,
                "device_class": device_class,
                "asset_group": asset_group,
                "access_token": access_token,
            })
            print("OK")

        except httpx.HTTPStatusError as e:
            print(f"FAILED: {e.response.status_code} {e.response.text}")

        # Throttle to avoid overwhelming ThingsBoard
        if i % 10 == 0:
            time.sleep(0.5)

    return results


def write_credentials(results: list[dict], output_path: str) -> None:
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "device_id", "device_class", "asset_group", "access_token"])
        writer.writeheader()
        writer.writerows(results)
    print(f"\n[done] Credentials written to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk device registration for Vantage NMS")
    parser.add_argument("--csv", required=True, help="Path to devices CSV file")
    parser.add_argument("--output", default="credentials.csv", help="Output credentials file (default: credentials.csv)")
    args = parser.parse_args()

    if not Path(args.csv).exists():
        print(f"ERROR: CSV file not found: {args.csv}")
        sys.exit(1)

    client = TBOnboardClient(TB_URL, TB_ADMIN_USER, TB_ADMIN_PASSWORD)
    client.login()

    asset_ids = build_asset_tree(client)
    results = onboard_devices(args.csv, asset_ids, client)
    write_credentials(results, args.output)

    print(f"\nSummary: {len(results)} devices registered successfully")


if __name__ == "__main__":
    main()
