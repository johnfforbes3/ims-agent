"""
SIEM integration — Phase 7.2 (CMMC AU.3.045)

Attaches a ``SysLogHandler`` to the root logger when ``SIEM_SYSLOG_HOST``
is set, forwarding all log events at WARNING and above (which includes all
``action=audit_*`` structured log lines) to the configured syslog endpoint.

Env vars
--------
SIEM_SYSLOG_HOST  Hostname or IP of the syslog receiver (e.g. Splunk HEC,
                  Datadog syslog listener, rsyslog forwarder).
SIEM_SYSLOG_PORT  UDP port (default: 514).

Usage
-----
Call ``configure_siem_logging()`` once at application startup.  If
``SIEM_SYSLOG_HOST`` is not set, the function is a no-op and returns False.
"""

import logging
import logging.handlers
import os

logger = logging.getLogger(__name__)


def configure_siem_logging() -> bool:
    """Attach a SysLogHandler to the root logger if SIEM_SYSLOG_HOST is set.

    Safe to call multiple times — checks whether a SysLogHandler targeting
    the configured host:port is already attached before adding another.

    Returns:
        True if a new handler was attached; False if not configured or
        already attached.
    """
    host = os.getenv("SIEM_SYSLOG_HOST", "").strip()
    if not host:
        return False

    try:
        port = int(os.getenv("SIEM_SYSLOG_PORT", "514"))
    except ValueError:
        port = 514

    root = logging.getLogger()

    # Idempotency: skip if we already have a SysLogHandler for this endpoint.
    for h in root.handlers:
        if (
            isinstance(h, logging.handlers.SysLogHandler)
            and getattr(h, "address", None) == (host, port)
        ):
            return False

    handler = logging.handlers.SysLogHandler(address=(host, port))
    handler.setLevel(logging.WARNING)
    formatter = logging.Formatter(
        "%(asctime)s ims-agent %(levelname)s %(name)s %(message)s"
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)

    logger.info(
        "action=siem_configured host=%s port=%d",
        host,
        port,
    )
    return True
