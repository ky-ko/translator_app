"""
credits_logger.py
-----------------
A Python logger handler that keeps a single log file with a configurable
maximum number of lines. Like movie end-credits: the oldest lines scroll
off the top while the newest entries always appear at the bottom.

Usage
-----
    from credits_logger import CreditsLogger

    log = CreditsLogger("app.log", max_lines=200)
    log.info("Application started")
    log.warning("Something looks off")
    log.error("Boom!")

    # Or attach to the standard logging module:
    import logging
    from credits_logger import CreditsFileHandler

    logger = logging.getLogger("myapp")
    logger.setLevel(logging.DEBUG)
    handler = CreditsFileHandler("app.log", max_lines=100)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    logger.info("Ready to roll.")
"""

import logging
import os
from collections import deque
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Low-level handler (plugs into Python's standard logging machinery)
# ---------------------------------------------------------------------------

class CreditsFileHandler(logging.FileHandler):
    """
    A logging.FileHandler that enforces a rolling max-line limit.

    After every write the file is checked; if it exceeds *max_lines* the
    oldest lines are dropped so that exactly *max_lines* remain.  The newest
    entry is always the last line in the file — just like credits rolling up.

    Parameters
    ----------
    filename : str
        Path to the log file.  Created if it does not exist.
    max_lines : int
        Maximum number of lines to keep in the file (default: 500).
    mode : str
        File open mode.  Use 'a' (default) to append to an existing file or
        'w' to start fresh each run.
    encoding : str | None
        File encoding (default: 'utf-8').
    """

    def __init__(
        self,
        filename: str,
        max_lines: int = 500,
        mode: str = "a",
        encoding: Optional[str] = "utf-8",
        delay: bool = False,
    ):
        if max_lines < 1:
            raise ValueError("max_lines must be >= 1")
        self.max_lines = max_lines
        super().__init__(filename, mode=mode, encoding=encoding, delay=delay)

    # ------------------------------------------------------------------
    def emit(self, record: logging.LogRecord) -> None:
        """Write the record then trim the file to max_lines."""
        super().emit(record)
        self._trim()

    # ------------------------------------------------------------------
    def _trim(self) -> None:
        """Read the file, drop excess leading lines, rewrite if needed."""
        path = self.baseFilename

        # Flush so the OS sees the latest write before we read it back.
        self.flush()

        try:
            with open(path, "r", encoding=self.encoding or "utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            return  # File might not exist yet in edge cases; ignore.

        if len(lines) <= self.max_lines:
            return  # Nothing to trim.

        # Keep only the *last* max_lines lines (newest = last).
        trimmed = lines[-self.max_lines :]

        # Rewrite atomically via a temp file to avoid corruption.
        tmp_path = path + ".credits_tmp"
        try:
            with open(tmp_path, "w", encoding=self.encoding or "utf-8") as fh:
                fh.writelines(trimmed)
            os.replace(tmp_path, path)
        except OSError:
            # Non-fatal — the log file stays untrimmed this cycle.
            try:
                os.remove(tmp_path)
            except OSError:
                pass

        # Re-open the handler so the internal file pointer is valid again.
        self.close()
        self._open()


# ---------------------------------------------------------------------------
# Convenience wrapper — works without touching logging.getLogger()
# ---------------------------------------------------------------------------

class CreditsLogger:
    """
    Convenience wrapper that sets up a named logger with a CreditsFileHandler
    and optional console output in one call.

    Parameters
    ----------
    log_file : str
        Path to the log file.
    max_lines : int
        Maximum lines to keep in *log_file* (default: 500).
    name : str
        Logger name (default: derived from *log_file*).
    level : int
        Minimum log level (default: logging.DEBUG).
    fmt : str | None
        Log format string.  ``None`` uses a sensible default.
    console : bool
        Also print to stdout (default: True).
    mode : str
        'a' to append, 'w' to overwrite on startup (default: 'a').

    Examples
    --------
    >>> log = CreditsLogger("run.log", max_lines=100)
    >>> log.info("Step 1 complete")
    >>> log.warning("Disk space low")
    >>> log.error("Connection refused")
    >>> log.debug("x = %s", 42)
    """

    DEFAULT_FMT = "%(asctime)s [%(levelname)-8s] %(name)s — %(message)s"
    DATE_FMT    = "%Y-%m-%d %H:%M:%S"

    def __init__(
        self,
        log_file: str,
        max_lines: int = 500,
        name: Optional[str] = None,
        level: int = logging.DEBUG,
        fmt: Optional[str] = None,
        console: bool = True,
        mode: str = "a",
    ):
        self.log_file  = log_file
        self.max_lines = max_lines

        logger_name = name or os.path.splitext(os.path.basename(log_file))[0]
        self._logger = logging.getLogger(logger_name)
        self._logger.setLevel(level)

        # Avoid duplicate handlers if re-instantiated with the same name.
        self._logger.handlers.clear()

        formatter = logging.Formatter(fmt or self.DEFAULT_FMT, datefmt=self.DATE_FMT)

        file_handler = CreditsFileHandler(log_file, max_lines=max_lines, mode=mode)
        file_handler.setFormatter(formatter)
        self._logger.addHandler(file_handler)

        if console:
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(formatter)
            self._logger.addHandler(stream_handler)

    # ------------------------------------------------------------------
    # Delegate the standard log-level methods to the underlying logger.
    # ------------------------------------------------------------------

    def debug(self, msg, *args, **kwargs):    self._logger.debug(msg, *args, **kwargs)
    def info(self, msg, *args, **kwargs):     self._logger.info(msg, *args, **kwargs)
    def warning(self, msg, *args, **kwargs):  self._logger.warning(msg, *args, **kwargs)
    def error(self, msg, *args, **kwargs):    self._logger.error(msg, *args, **kwargs)
    def critical(self, msg, *args, **kwargs): self._logger.critical(msg, *args, **kwargs)
    def exception(self, msg, *args, **kwargs):self._logger.exception(msg, *args, **kwargs)

    @property
    def logger(self) -> logging.Logger:
        """Return the underlying :class:`logging.Logger` for advanced use."""
        return self._logger

    def __repr__(self):
        return (
            f"CreditsLogger(log_file={self.log_file!r}, "
            f"max_lines={self.max_lines})"
        )


# ---------------------------------------------------------------------------
# Quick demo — run this file directly to see it in action
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile, time

    DEMO_FILE  = "credits_demo.log"
    MAX_LINES  = 10          # Keep only 10 lines for the demo
    TOTAL_MSGS = 25          # Write 25 messages to force rolling

    print(f"Demo: writing {TOTAL_MSGS} log entries with max_lines={MAX_LINES}")
    print(f"Log file: {DEMO_FILE}\n")

    log = CreditsLogger(DEMO_FILE, max_lines=MAX_LINES, console=False)

    levels = [log.debug, log.info, log.warning, log.error]
    labels = ["DEBUG", "INFO ", "WARN ", "ERROR"]

    for i in range(1, TOTAL_MSGS + 1):
        fn = levels[i % len(levels)]
        fn("Message #%02d — the credits keep rolling...", i)

    # Show the resulting file
    print(f"File contents after {TOTAL_MSGS} writes (only last {MAX_LINES} lines kept):\n")
    with open(DEMO_FILE) as fh:
        for line in fh:
            print(" ", line, end="")

    print(f"\nTotal lines in file: {sum(1 for _ in open(DEMO_FILE))}")
    print("Oldest messages have scrolled off — newest are at the bottom.")
