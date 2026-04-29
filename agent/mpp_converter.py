"""
MPP Converter — converts between .mpp (MS Project binary) and .xml (MSPDI).

Two backends, tried in order:

1. COM (pywin32) — uses MS Project itself.  Full .mpp fidelity.
   Blocked on C2R installations until a Quick Repair is run:
     Settings → Apps → Microsoft Project Professional → Modify → Quick Repair

2. MPXJ (jpype + mpxj.jar) — JVM-based, reads any .mpp and writes MSPDI XML.
   Can READ real .mpp files without MS Project installed.
   Cannot WRITE native .mpp binary — writes MSPDI XML (.xml) instead.
   MS Project opens MSPDI XML natively (same data, different container).
   Requires: pip install jpype1 mpxj  +  OpenJDK 21 at _JAVA_HOME.

   MPXJ write output uses extension .xml, not .mpp.  The master-IMS folder
   will contain  IMS_2026-04-28_1014z.xml  until COM is repaired, at which
   point every cycle switches automatically to  IMS_2026-04-28_1014z.mpp.

Public API
----------
    is_com_available()  → bool          COM backend ready
    is_mpxj_available() → bool          MPXJ backend ready
    is_available()      → bool          either backend ready
    master_extension()  → str           ".mpp" or ".xml" based on backend
    mpp_to_xml(mpp, xml)  → None        read .mpp → write MSPDI XML
    xml_to_master(xml, out)  → str      write best-available output; returns actual path
    find_latest_master(dir) → Path|None find the one .mpp/.xml in ims_master/
    diagnose()          → str           human-readable status
"""

import glob as _glob
import logging
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# COM constants
_MSP_FORMAT_XML = 22
_WINPROJ_EXE = r"C:\Program Files\Microsoft Office\Root\Office16\WINPROJ.EXE"
_LAUNCH_WAIT_SEC = 12

# MPXJ / Java constants
_JAVA_HOME = r"C:\Users\forbe\.jre21"
_JVM_DLL   = rf"{_JAVA_HOME}\bin\server\jvm.dll"

# Cached probe results
_com_ok:  bool | None = None
_mpxj_ok: bool | None = None


# ---------------------------------------------------------------------------
# Availability probes
# ---------------------------------------------------------------------------

def is_com_available() -> bool:
    """Return True if MS Project COM automation works."""
    global _com_ok
    if _com_ok is not None:
        return _com_ok

    if not Path(_WINPROJ_EXE).exists():
        _com_ok = False
        return False
    try:
        import win32com.client, pythoncom
        pythoncom.CoInitialize()
        msp = win32com.client.Dispatch("MSProject.Application")
        msp.DisplayAlerts = False  # suppress Planning Wizard + all modal dialogs
        msp.Quit()
        _com_ok = True
        logger.info("action=com_available")
        return True
    except Exception as exc:
        logger.warning(
            "action=com_unavailable error=%s — falling back to MPXJ.\n"
            "  To restore .mpp output: Settings → Apps → "
            "Microsoft Project → Modify → Quick Repair", exc,
        )
        _com_ok = False
        return False


def is_mpxj_available() -> bool:
    """Return True if the MPXJ/JPype backend can start."""
    global _mpxj_ok
    if _mpxj_ok is not None:
        return _mpxj_ok

    if not Path(_JVM_DLL).exists():
        logger.debug("action=mpxj_unavailable reason=jvm_dll_not_found path=%s", _JVM_DLL)
        _mpxj_ok = False
        return False
    try:
        import mpxj as _mpxj_mod, jpype
        if not jpype.isJVMStarted():
            jars = _glob.glob(_mpxj_mod.mpxj_dir + "/*.jar")
            jpype.startJVM(_JVM_DLL, classpath=jars, convertStrings=False)
        # Quick class probe
        jpype.JClass("org.mpxj.reader.UniversalProjectReader")
        _mpxj_ok = True
        logger.info("action=mpxj_available jvm=%s", _JVM_DLL)
        return True
    except Exception as exc:
        logger.warning("action=mpxj_unavailable error=%s", exc)
        _mpxj_ok = False
        return False


def is_available() -> bool:
    """Return True if any backend can perform conversions."""
    return is_com_available() or is_mpxj_available()


def master_extension() -> str:
    """Return '.mpp' when COM works, '.xml' when MPXJ is the active backend."""
    return ".mpp" if is_com_available() else ".xml"


def diagnose() -> str:
    """Human-readable status string covering both backends."""
    lines = []
    # COM
    if not Path(_WINPROJ_EXE).exists():
        lines.append(f"COM: MS Project not found at {_WINPROJ_EXE}")
    elif is_com_available():
        lines.append("COM: OK ✓")
    else:
        lines.append(
            "COM: BLOCKED (C2R AppV isolation)\n"
            "  Fix: Settings → Apps → Microsoft Project Professional → Modify → Quick Repair"
        )
    # MPXJ
    if is_mpxj_available():
        lines.append(f"MPXJ: OK ✓  (reads .mpp, writes .xml — JVM at {_JAVA_HOME})")
    elif not Path(_JVM_DLL).exists():
        lines.append(
            f"MPXJ: JVM not found at {_JVM_DLL}\n"
            "  Install: https://adoptium.net/  (OpenJDK 21, zip/no-install)"
        )
    else:
        lines.append("MPXJ: jpype/mpxj not installed — run: pip install jpype1 mpxj")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JVM helpers
# ---------------------------------------------------------------------------

def _ensure_jvm() -> None:
    """Start the JVM with the MPXJ classpath if not already running."""
    import mpxj as _m, jpype
    if not jpype.isJVMStarted():
        jars = _glob.glob(_m.mpxj_dir + "/*.jar")
        jpype.startJVM(_JVM_DLL, classpath=jars, convertStrings=False)


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------

def mpp_to_xml(mpp_path: str, xml_path: str) -> None:
    """Read a .mpp file and write it as MSPDI XML.

    Tries COM first (full fidelity), falls back to MPXJ.
    Raises RuntimeError if neither backend is available.
    """
    mpp_abs = str(Path(mpp_path).resolve())
    xml_abs = str(Path(xml_path).resolve())
    Path(xml_abs).parent.mkdir(parents=True, exist_ok=True)

    if is_com_available():
        _com_mpp_to_xml(mpp_abs, xml_abs)
    elif is_mpxj_available():
        _mpxj_mpp_to_xml(mpp_abs, xml_abs)
    else:
        raise RuntimeError(f"No MPP backend available.\n{diagnose()}")


def xml_to_master(xml_path: str, out_path: str) -> str:
    """Write the best-available output from an MSPDI XML source.

    - COM available  → writes real .mpp to out_path, returns out_path
    - MPXJ only      → writes MSPDI .xml; if out_path ends in .mpp the
                        extension is changed to .xml automatically
    - Neither        → raises RuntimeError

    Returns the actual path written.
    """
    xml_abs = str(Path(xml_path).resolve())

    if is_com_available():
        mpp_abs = str(Path(out_path).resolve())
        Path(mpp_abs).parent.mkdir(parents=True, exist_ok=True)
        _com_xml_to_mpp(xml_abs, mpp_abs)
        return mpp_abs
    elif is_mpxj_available():
        # Force .xml extension — MPXJ can't write binary .mpp
        xml_out = str(Path(out_path).with_suffix(".xml").resolve())
        Path(xml_out).parent.mkdir(parents=True, exist_ok=True)
        _mpxj_xml_to_xml(xml_abs, xml_out)
        logger.info(
            "action=master_written_as_xml path=%s "
            "(COM unavailable — Quick Repair to enable .mpp output)", xml_out,
        )
        return xml_out
    else:
        raise RuntimeError(f"No MPP backend available.\n{diagnose()}")


def find_latest_master(directory: str) -> Path | None:
    """Return the single .mpp or .xml master file in *directory*, or None."""
    d = Path(directory)
    if not d.is_dir():
        return None
    # Prefer .mpp; fall back to .xml
    for ext in ("*.mpp", "*.xml"):
        files = sorted(d.glob(ext), key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            return files[0]
    return None


# ---------------------------------------------------------------------------
# COM backend
# ---------------------------------------------------------------------------

def _get_com_instance():
    import win32com.client, pythoncom
    pythoncom.CoInitialize()
    try:
        msp = win32com.client.GetActiveObject("MSProject.Application")
        msp.DisplayAlerts = False  # suppress Planning Wizard immediately
        return msp
    except Exception:
        pass
    proc = subprocess.Popen(
        [_WINPROJ_EXE, "/s"],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    logger.info("action=winproj_launched pid=%d", proc.pid)
    time.sleep(_LAUNCH_WAIT_SEC)
    for _ in range(3):
        try:
            msp = win32com.client.GetActiveObject("MSProject.Application")
            msp.DisplayAlerts = False  # suppress Planning Wizard immediately
            return msp
        except Exception:
            time.sleep(2)
    raise RuntimeError("MS Project launched but COM connection timed out.")


def _com_mpp_to_xml(mpp_abs: str, xml_abs: str) -> None:
    logger.info("action=com_mpp_to_xml src=%s dst=%s", mpp_abs, xml_abs)
    msp = _get_com_instance()
    try:
        msp.DisplayAlerts = False  # suppress Planning Wizard and all modal dialogs
        msp.FileOpen(mpp_abs, ReadOnly=True)
        msp.FileSaveAs(xml_abs, Format=_MSP_FORMAT_XML)
        msp.FileClose(Save=False)
        # Verify the output was actually written — COM can silently fail to produce output.
        if not Path(xml_abs).exists() or Path(xml_abs).stat().st_size == 0:
            raise RuntimeError(
                f"COM mpp_to_xml produced no output at {xml_abs}. "
                "Verify MS Project is not blocked by a dialog (run Quick Repair if needed)."
            )
        logger.info("action=com_mpp_to_xml_done size=%d", Path(xml_abs).stat().st_size)
    except Exception as exc:
        logger.error("action=com_mpp_to_xml_failed error=%s", exc)
        raise
    finally:
        try:
            msp.DisplayAlerts = True
        except Exception:
            pass


def _com_xml_to_mpp(xml_abs: str, mpp_abs: str) -> None:
    logger.info("action=com_xml_to_mpp src=%s dst=%s", xml_abs, mpp_abs)
    msp = _get_com_instance()
    try:
        msp.DisplayAlerts = False  # suppress Planning Wizard and all modal dialogs
        msp.FileOpen(xml_abs)
        msp.FileSaveAs(mpp_abs)
        msp.FileClose(Save=False)
        # Verify the output was actually written — COM can silently fail to produce output.
        if not Path(mpp_abs).exists() or Path(mpp_abs).stat().st_size == 0:
            raise RuntimeError(
                f"COM xml_to_mpp produced no output at {mpp_abs}. "
                "Verify MS Project is not blocked by a dialog (run Quick Repair if needed)."
            )
        logger.info("action=com_xml_to_mpp_done size=%d", Path(mpp_abs).stat().st_size)
    except Exception as exc:
        logger.error("action=com_xml_to_mpp_failed error=%s", exc)
        raise
    finally:
        try:
            msp.DisplayAlerts = True
        except Exception:
            pass


# ---------------------------------------------------------------------------
# MPXJ backend
# ---------------------------------------------------------------------------

def _mpxj_mpp_to_xml(mpp_abs: str, xml_abs: str) -> None:
    """Read .mpp via MPXJ and write MSPDI XML."""
    import jpype
    _ensure_jvm()
    logger.info("action=mpxj_mpp_to_xml src=%s dst=%s", mpp_abs, xml_abs)
    reader = jpype.JClass("org.mpxj.reader.UniversalProjectReader")()
    proj = reader.read(mpp_abs)
    writer = jpype.JClass("org.mpxj.mspdi.MSPDIWriter")()
    writer.write(proj, xml_abs)
    logger.info("action=mpxj_mpp_to_xml_done tasks=%d", proj.getTasks().size())


def _mpxj_xml_to_xml(xml_src: str, xml_dst: str) -> None:
    """Round-trip MSPDI XML through MPXJ (normalises the file)."""
    import jpype
    _ensure_jvm()
    logger.info("action=mpxj_xml_to_xml src=%s dst=%s", xml_src, xml_dst)
    reader = jpype.JClass("org.mpxj.reader.UniversalProjectReader")()
    proj = reader.read(xml_src)
    writer = jpype.JClass("org.mpxj.mspdi.MSPDIWriter")()
    writer.write(proj, xml_dst)
    logger.info("action=mpxj_xml_to_xml_done tasks=%d", proj.getTasks().size())
