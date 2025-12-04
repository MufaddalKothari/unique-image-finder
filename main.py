#!/usr/bin/env python3
"""
main.py - application entrypoint with robust logging setup.

Drop this into your repo root (overwrite existing main.py). It configures logging
to both console and a rotating file, installs an excepthook to capture uncaught
exceptions, and then starts the Qt application using ui.main_window.MainWindow.

Notes:
- LOG_LEVEL can be changed with environment variable UNIQUE_IMAGE_FINDER_LOG_LEVEL (defaults to DEBUG).
- Log file defaults to ~/.unique_image_finder/unique-image-finder.log.
"""
import os
import sys
import logging
from logging.handlers import RotatingFileHandler

# ---- Logging configuration ----
LOG_LEVEL = os.environ.get("UNIQUE_IMAGE_FINDER_LOG_LEVEL", "DEBUG").upper()
LOG_DIR = os.environ.get("UNIQUE_IMAGE_FINDER_LOG_DIR", os.path.join(os.path.expanduser("~"), ".unique_image_finder"))
LOG_FILE = os.path.join(LOG_DIR, "unique-image-finder.log")

os.makedirs(LOG_DIR, exist_ok=True)

# Create root logger
root_logger = logging.getLogger()
root_logger.setLevel(getattr(logging, LOG_LEVEL, logging.DEBUG))

# Console handler
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(getattr(logging, LOG_LEVEL, logging.DEBUG))
console_fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
ch.setFormatter(console_fmt)
root_logger.addHandler(ch)

# Rotating file handler
fh = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
fh.setLevel(logging.DEBUG)
file_fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s [%(threadName)s]: %(message)s", "%Y-%m-%d %H:%M:%S")
fh.setFormatter(file_fmt)
root_logger.addHandler(fh)

# Ensure 3rd-party libraries propagate to root logger level
logging.getLogger("PIL").setLevel(logging.INFO)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# Uncaught exception handler to log stack traces
def _handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        # Let default handler handle keyboard interrupt
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logging.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

sys.excepthook = _handle_exception

# Optional: capture warnings via logging
import warnings
logging.captureWarnings(True)
warnings.simplefilter("default")

# ---- Start GUI ----
def main(argv):
    logging.info("Starting Unique Image Finder application")
    try:
        from PyQt5.QtWidgets import QApplication
        # import the MainWindow from the UI package
        from ui.main_window import MainWindow
    except Exception:
        logging.exception("Failed to import GUI modules.")
        raise

    app = QApplication(argv)
    mw = MainWindow()
    mw.show()
    # When running from terminal, ensure logging flushes on exit
    exit_code = app.exec_()
    logging.info("Application exiting with code %s", exit_code)
    # Give logging handlers a chance to flush
    for h in logging.getLogger().handlers:
        try:
            h.flush()
        except Exception:
            pass
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
