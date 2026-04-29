"""
FtpUpload - Ladda upp HTML-filer som matchar ett regexp via FTP.

Söker igenom DATA_AREA_ROOT_DIR efter .html-filer vars sökväg matchar
det konfigurerade regexpmönstret (FTP_HTML_REGEXP) och laddar upp dem
till angiven FTP-server (FTP_HOST) i angiven katalog (FTP_DIR).
"""
from __future__ import annotations

import ftplib
import logging
import re
from pathlib import Path
from typing import List

from .config import Config

log = logging.getLogger(__name__)


class FtpUpload:
    """Hitta och ladda upp HTML-filer till FTP-server."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.data_root = Path(cfg.data_area_root_dir)

    def _find_html_files(self, pattern: str) -> List[Path]:
        """Hitta alla .html-filer under data_root som matchar regexp-mönstret."""
        regex = re.compile(pattern)
        matched: List[Path] = []
        for html_file in sorted(self.data_root.rglob("*.html")):
            if regex.search(str(html_file)):
                matched.append(html_file)
        return matched

    def _upload_files(self, files: List[Path], host: str, directory: str,
                      username: str, password: str) -> int:
        """Ladda upp filer via FTP. Returnerar antal uppladdade filer."""
        uploaded = 0
        log.info("Connecting to FTP %s as %s ...", host, username)
        ftp = ftplib.FTP(host)
        try:
            ftp.login(username, password)
            if directory:
                ftp.cwd(directory)
                log.info("Changed FTP directory to %s", directory)
            for filepath in files:
                remote_name = filepath.name
                log.info("Uploading %s -> %s", filepath, remote_name)
                with open(filepath, "rb") as f:
                    ftp.storbinary(f"STOR {remote_name}", f)
                uploaded += 1
                log.info("Upload completed: %s", remote_name)
        finally:
            try:
                ftp.quit()
            except Exception:
                ftp.close()
        return uploaded

    def run(self) -> bool:
        """
        Kör FTP-uppladdning av HTML-filer som matchar konfigurerat regexp.

        Returns:
            True om minst en fil laddades upp, False annars.
        """
        log.info("=== Starting FtpUpload ===")
        cfg = self.cfg

        if not cfg.ftp_host:
            raise ValueError("FTP_HOST must be set for FTP upload.")
        if not cfg.ftp_username:
            raise ValueError("FTP_USERNAME must be set for FTP upload.")
        if not cfg.ftp_password:
            raise ValueError("FTP_PASSWORD must be set for FTP upload.")
        if not cfg.ftp_html_regexp:
            raise ValueError("FTP_HTML_REGEXP must be set for FTP upload.")

        pattern = cfg.ftp_html_regexp
        files = self._find_html_files(pattern)
        if not files:
            log.warning("No HTML files matched pattern: %s", pattern)
            return False

        log.info("Found %d HTML files matching pattern '%s'", len(files), pattern)
        uploaded = self._upload_files(
            files,
            host=cfg.ftp_host,
            directory=cfg.ftp_dir or "",
            username=cfg.ftp_username,
            password=cfg.ftp_password,
        )
        log.info("FtpUpload completed: %d/%d files uploaded", uploaded, len(files))
        return uploaded > 0


def ftp_upload_main(cfg: Config) -> None:
    """Entrypoint för att köra FTP-uppladdning från main.py."""
    uploader = FtpUpload(cfg)
    success = uploader.run()
    if not success:
        log.warning("FtpUpload: no files were uploaded")
