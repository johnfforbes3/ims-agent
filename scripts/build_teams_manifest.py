"""
Build Teams app manifest zip for the ATLAS Scheduler bot.

Creates:
  teams_manifest/manifest.json
  teams_manifest/color.png     (192x192 solid blue)
  teams_manifest/outline.png   (32x32 white)
  atlas-scheduler-teams-app.zip

Upload the zip to:
  Teams Admin Center -> Teams apps -> Manage apps -> Upload new app
"""

import json
import os
import struct
import zlib
import zipfile
from pathlib import Path

BOT_APP_ID = os.getenv("TEAMS_BOT_APP_ID", "9afa38ea-6efc-45b5-9f70-248aa32ff9a4")
OUT_DIR = Path("teams_manifest")
ZIP_PATH = Path("atlas-scheduler-teams-app.zip")


def _make_png(width: int, height: int, r: int, g: int, b: int) -> bytes:
    """Create a minimal valid RGB PNG of solid color."""
    raw = b""
    for _ in range(height):
        raw += b"\x00" + bytes([r, g, b] * width)

    compressed = zlib.compress(raw, 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        c = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", c)

    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    idat = chunk(b"IDAT", compressed)
    iend = chunk(b"IEND", b"")
    return b"\x89PNG\r\n\x1a\n" + ihdr + idat + iend


MANIFEST = {
    "$schema": "https://developer.microsoft.com/en-us/json-schemas/teams/v1.17/MicrosoftTeams.schema.json",
    "manifestVersion": "1.17",
    "version": "1.0.0",
    "id": BOT_APP_ID,
    "packageName": "com.intelligenceexpanse.atlas.scheduler",
    "developer": {
        "name": "Intelligence Expanse",
        "websiteUrl": "https://intelligenceexpanse.onmicrosoft.com",
        "privacyUrl": "https://intelligenceexpanse.onmicrosoft.com/privacy",
        "termsOfUseUrl": "https://intelligenceexpanse.onmicrosoft.com/terms",
    },
    "icons": {
        "color": "color.png",
        "outline": "outline.png",
    },
    "name": {
        "short": "ATLAS Scheduler",
        "full": "ATLAS Program Schedule Intelligence Agent",
    },
    "description": {
        "short": "Automated schedule status interviewer for ATLAS program CAMs.",
        "full": "The ATLAS Scheduler bot interviews Control Account Managers (CAMs) via Teams chat to collect weekly status updates, detects blockers and risks, and updates the Integrated Master Schedule.",
    },
    "accentColor": "#0066CC",
    "bots": [
        {
            "botId": BOT_APP_ID,
            "scopes": ["personal"],
            "supportsFiles": False,
            "isNotificationOnly": False,
            "commandLists": [
                {
                    "scopes": ["personal"],
                    "commands": [
                        {
                            "title": "status",
                            "description": "Check current cycle status",
                        }
                    ],
                }
            ],
        }
    ],
    "permissions": ["identity", "messageTeamMembers"],
    "validDomains": [],
}


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)

    manifest_path = OUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(MANIFEST, indent=2), encoding="utf-8")
    print(f"  wrote {manifest_path}")

    color_path = OUT_DIR / "color.png"
    color_path.write_bytes(_make_png(192, 192, 0, 102, 204))
    print(f"  wrote {color_path} (192x192 blue)")

    outline_path = OUT_DIR / "outline.png"
    outline_path.write_bytes(_make_png(32, 32, 255, 255, 255))
    print(f"  wrote {outline_path} (32x32 white)")

    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(manifest_path, "manifest.json")
        zf.write(color_path, "color.png")
        zf.write(outline_path, "outline.png")
    print(f"\n  => {ZIP_PATH}  ({ZIP_PATH.stat().st_size} bytes)")
    print("\nUpload atlas-scheduler-teams-app.zip at:")
    print("  Teams Admin Center -> Teams apps -> Manage apps -> Upload new app")


if __name__ == "__main__":
    main()
