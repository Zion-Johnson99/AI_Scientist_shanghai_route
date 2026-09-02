"""Structured logging with secret redaction (design doc section 20).

Log records carry ``run_id`` / ``stage`` / ``operation`` / ``status`` /
``elapsed_ms`` extras; file output uses RotatingFileHandler. API keys,
Authorization headers, URL credentials and absolute user-home paths are
redacted before anything reaches disk or console.
"""

from __future__ import annotations

import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "qwen_harness"

_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}\b")
_AUTH_HEADER_RE = re.compile(r"(?i)(authorization\s*[:=]\s*)[^\s,;\"']+")
_URL_CRED_RE = re.compile(r"(https?://)([^:/@\s]+):([^@\s]+)@")
_KV_SECRET_RE = re.compile(
    r"(?i)\b(DASHSCOPE_API_KEY|API_KEY|ACCESS_TOKEN|SECRET|PASSWORD)(\s*[:=]\s*)[^\s\"',}]+"
)

_HOME_CANDIDATES: tuple[str, ...] = tuple(
    p
    for p in {
        str(Path.home()),
        os.environ.get("USERPROFILE", ""),
        os.environ.get("HOME", ""),
    }
    if p
)


def redact_text(text: str) -> str:
    """Remove secrets and user-home absolute paths from a log string."""
    if not text:
        return text
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if api_key and len(api_key) >= 8 and api_key in text:
        text = text.replace(api_key, "[REDACTED]")
    text = _KEY_RE.sub("[REDACTED]", text)
    text = _AUTH_HEADER_RE.sub(r"\1[REDACTED]", text)
    text = _URL_CRED_RE.sub(r"\1[REDACTED]@", text)
    text = _KV_SECRET_RE.sub(r"\1\2[REDACTED]", text)
    for home in _HOME_CANDIDATES:
        if home and home in text:
            text = text.replace(home, "<HOME>")
    return text


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = []
        for field in ("run_id", "stage", "operation", "status", "elapsed_ms"):
            value = getattr(record, field, None)
            if value is not None:
                extras.append(f"{field}={value}")
        if extras:
            base = f"{base} | {' '.join(extras)}"
        return redact_text(base)


def get_logger(name: str | None = None) -> logging.Logger:
    if name:
        return logging.getLogger(f"{LOGGER_NAME}.{name}")
    return logging.getLogger(LOGGER_NAME)


def setup_logging(log_dir: Path | None = None, verbose: bool = False) -> logging.Logger:
    """Configure console + rotating file handlers. Idempotent."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(
        RedactingFormatter("%(asctime)s %(levelname)-5s %(name)s: %(message)s", datefmt="%H:%M:%S")
    )
    logger.addHandler(console)

    if log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_dir / "qwen-harness.log",
                maxBytes=1_000_000,
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(
                RedactingFormatter(
                    "%(asctime)s %(levelname)-5s %(name)s: %(message)s",
                    datefmt="%Y-%m-%dT%H:%M:%S",
                )
            )
            logger.addHandler(file_handler)
        except OSError as exc:  # pragma: no cover - defensive
            logger.warning("日志目录不可写，仅输出到控制台: %s", exc)
    return logger


def log_event(
    logger: logging.Logger,
    level: int,
    message: str,
    *,
    run_id: str | None = None,
    stage: str | None = None,
    operation: str | None = None,
    status: str | None = None,
    elapsed_ms: float | None = None,
    exc_info: bool = False,
) -> None:
    """Emit a record with the structured fields required by section 20."""
    logger.log(
        level,
        message,
        exc_info=exc_info,
        extra={
            "run_id": run_id,
            "stage": stage,
            "operation": operation,
            "status": status,
            "elapsed_ms": round(elapsed_ms, 1) if elapsed_ms is not None else None,
        },
    )
