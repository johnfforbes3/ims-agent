"""CAM identity map — maps IMS CAM names to Teams account identities."""
import json
import os
from pathlib import Path

_MAP_PATH = Path(os.getenv("DATA_DIR", "data")) / "cam_identity_map.json"


def load_identity_map() -> dict:
    if not _MAP_PATH.exists():
        return {}
    return json.loads(_MAP_PATH.read_text(encoding="utf-8"))


def get_cam_email(cam_name: str) -> str:
    return load_identity_map().get(cam_name, {}).get("email", "")


def is_auto_respond(cam_name: str) -> bool:
    return load_identity_map().get(cam_name, {}).get("auto_respond", False)


def get_auto_respond_cams() -> dict:
    """Return {cam_name: info} for all auto_respond=true accounts."""
    return {k: v for k, v in load_identity_map().items() if v.get("auto_respond")}
