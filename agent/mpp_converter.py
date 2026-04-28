"""
MPP Converter — converts between .mpp (MS Project binary) and .xml (MSPDI)
using Microsoft Project COM automation via pywin32.

Requires Microsoft Project to be installed on the local machine.
If MS Project is not available (or COM fails), ``is_available()`` returns
False and the caller falls back to XML-only mode — no cycle interruption.

Click-to-Run (C2R) / CO_E_SERVER_EXEC_FAILURE fix
---------------------------------------------------
Standard M365 / Microsoft 365 Business installations use Click-to-Run (C2R),
which virtualises the Office executables inside an AppV container.  Calling
``Dispatch("MSProject.Application")`` from an external process raises
``CO_E_SERVER_EXEC_FAILURE`` because COM activation goes through the C2R
bootstrap layer, which needs to be correctly registered.

**To fix (one-time, ~5 minutes):**

  1. Open Settings → Apps → Installed apps
  2. Find "Microsoft 365 …" (or "Office …") → click the ⋯ menu → Modify
  3. Choose **Quick Repair** → Repair
  4. After the repair completes, COM automation works normally.

Alternatively, install OpenJDK 21 (https://adoptium.net/) then
``pip install mpxj`` and we will switch this module to MPXJ-based conversion
(no MS Project COM required at all).  Update ``_BACKEND`` below to "mpxj"
once Java is available.

Public API:
    is_available()          → bool
    mpp_to_xml(mpp, xml)    → None
    xml_to_mpp(xml, mpp)    → None
    find_latest_mpp(dir)    → Path | None
    diagnose()              → str   (human-readable status string)
"""

import logging
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# MS Project FileFormat constant for MSPDI XML (PjMSPDI = 22)
_MSP_FORMAT_XML = 22

# Path to the MS Project executable (Click-to-Run default)
_WINPROJ_EXE = r"C:\Program Files\Microsoft Office\Root\Office16\WINPROJ.EXE"

# How long to wait (seconds) for WINPROJ to start before connecting via COM
_LAUNCH_WAIT_SEC = 8

# Cached availability result (avoids re-probing on every cycle)
_available: bool | None = None


def is_available() -> bool:
    """Return True if MS Project COM automation is working on this machine.

    The result is cached after the first successful probe.  A failed probe
    logs a one-time WARNING with remediation instructions.
    """
    global _available
    if _available is not None:
        return _available

    if not Path(_WINPROJ_EXE).exists():
        logger.debug("action=mpp_unavailable reason=winproj_not_found")
        _available = False
        return False

    try:
        import win32com.client
        import pythoncom
        pythoncom.CoInitialize()
        msp = win32com.client.Dispatch("MSProject.Application")
        msp.Quit()
        _available = True
        logger.info("action=mpp_available backend=com")
        return True
    except ImportError:
        logger.debug("action=mpp_unavailable reason=pywin32_not_installed")
        _available = False
        return False
    except Exception as exc:
        logger.warning(
            "action=mpp_unavailable reason=com_failed error=%s\n"
            "  MPP conversion is disabled — the agent continues in XML-only mode.\n"
            "  To enable .mpp output, run a Quick Repair on your Microsoft 365 installation:\n"
            "    Settings → Apps → Microsoft 365 → Modify → Quick Repair",
            exc,
        )
        _available = False
        return False


def diagnose() -> str:
    """Return a human-readable status string for the MPP backend."""
    if not Path(_WINPROJ_EXE).exists():
        return f"MS Project not found at {_WINPROJ_EXE}"
    try:
        import win32com.client
        import pythoncom
        pythoncom.CoInitialize()
        msp = win32com.client.Dispatch("MSProject.Application")
        ver = getattr(msp, "Version", "unknown")
        msp.Quit()
        return f"COM OK — MS Project {ver}"
    except ImportError:
        return "pywin32 not installed — run: pip install pywin32"
    except Exception as exc:
        return (
            f"COM failed ({exc})\n"
            "Fix: Settings → Apps → Microsoft 365 → Modify → Quick Repair\n"
            "Alt: Install OpenJDK 21 (https://adoptium.net/) then: pip install mpxj"
        )


def _get_msp_instance() -> "win32com.client.CDispatch":
    """Launch WINPROJ.EXE (if not already running) and return a COM handle.

    Uses the C2R-safe pattern: subprocess launch → brief wait → GetActiveObject.
    Falls back to a normal Dispatch if GetActiveObject is not available
    (e.g. a perpetual-licence non-C2R install).
    """
    import win32com.client
    import win32api
    import pythoncom

    pythoncom.CoInitialize()

    # Try connecting to an already-running instance first
    try:
        msp = win32com.client.GetActiveObject("MSProject.Application")
        logger.debug("action=msp_got_active_instance")
        return msp
    except Exception:
        pass  # not running yet — launch it

    # Launch WINPROJ.EXE in the background (minimised, no splash)
    proc = subprocess.Popen(
        [_WINPROJ_EXE, "/s"],          # /s suppresses the splash screen
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    logger.info("action=winproj_launched pid=%d wait=%ss", proc.pid, _LAUNCH_WAIT_SEC)
    time.sleep(_LAUNCH_WAIT_SEC)

    # Connect to the now-running instance
    for attempt in range(1, 4):
        try:
            msp = win32com.client.GetActiveObject("MSProject.Application")
            logger.info("action=msp_connected attempt=%d", attempt)
            return msp
        except Exception:
            time.sleep(2)

    raise RuntimeError(
        "MS Project launched but COM connection timed out.  "
        "Ensure Project is fully started and not blocked by a dialog."
    )


def mpp_to_xml(mpp_path: str, xml_path: str) -> None:
    """Open a .mpp file with MS Project COM and save it as MSPDI XML.

    Args:
        mpp_path: Absolute (or resolvable) path to the source .mpp file.
        xml_path: Absolute (or resolvable) path for the output .xml file.

    Raises:
        RuntimeError: If pywin32 / MS Project is not available or COM fails.
    """
    if not is_available():
        raise RuntimeError("pywin32 not installed or MS Project not found")

    mpp_abs = str(Path(mpp_path).resolve())
    xml_abs = str(Path(xml_path).resolve())
    Path(xml_abs).parent.mkdir(parents=True, exist_ok=True)

    logger.info("action=mpp_to_xml_start src=%s dst=%s", mpp_abs, xml_abs)
    msp = _get_msp_instance()
    _owned = False
    try:
        msp.FileOpen(mpp_abs, ReadOnly=True)
        msp.FileSaveAs(xml_abs, Format=_MSP_FORMAT_XML)
        msp.FileClose(Save=False)
        logger.info("action=mpp_to_xml_done src=%s dst=%s", mpp_abs, xml_abs)
    except Exception as exc:
        logger.error("action=mpp_to_xml_failed error=%s", exc)
        raise


def xml_to_mpp(xml_path: str, mpp_path: str) -> None:
    """Open an MSPDI XML file with MS Project COM and save it as .mpp.

    Args:
        xml_path: Absolute (or resolvable) path to the source .xml file.
        mpp_path: Absolute (or resolvable) path for the output .mpp file.

    Raises:
        RuntimeError: If pywin32 / MS Project is not available or COM fails.
    """
    if not is_available():
        raise RuntimeError("pywin32 not installed or MS Project not found")

    xml_abs = str(Path(xml_path).resolve())
    mpp_abs = str(Path(mpp_path).resolve())
    Path(mpp_abs).parent.mkdir(parents=True, exist_ok=True)

    logger.info("action=xml_to_mpp_start src=%s dst=%s", xml_abs, mpp_abs)
    msp = _get_msp_instance()
    try:
        msp.FileOpen(xml_abs)
        msp.FileSaveAs(mpp_abs)      # default format → .mpp
        msp.FileClose(Save=False)
        logger.info("action=xml_to_mpp_done src=%s dst=%s", xml_abs, mpp_abs)
    except Exception as exc:
        logger.error("action=xml_to_mpp_failed error=%s", exc)
        raise


def find_latest_mpp(directory: str) -> Path | None:
    """Return the single .mpp file in *directory*, or None if absent.

    The master folder is maintained with exactly one .mpp at a time
    (the latest cycle's output).  This helper returns it regardless of
    its timestamped name.
    """
    d = Path(directory)
    if not d.is_dir():
        return None
    mpps = sorted(d.glob("*.mpp"), key=lambda p: p.stat().st_mtime, reverse=True)
    return mpps[0] if mpps else None
