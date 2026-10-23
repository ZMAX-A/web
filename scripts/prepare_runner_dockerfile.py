"""Add the Web runtime font contract to the pinned TOP build adapter."""
from pathlib import Path
import sys

FONT_PACKAGE = "fonts-noto-cjk=1:20230817+repack1-3"


def prepare(source: str) -> str:
    apt = "apt-get install -y --no-install-recommends novnc x11vnc"
    user = "\nUSER pwuser\n"
    copied_utils = "COPY --from=yanjia_web --chown=pwuser:pwuser utils /opt/yanjia-web/utils"
    if source.count(apt) != 1 or source.count(user) != 1 or copied_utils not in source:
        raise ValueError("Pinned TOP Dockerfile contract changed; review before building a release")
    if FONT_PACKAGE in source or "browser_font_health" in source:
        raise ValueError("Font contract already present; do not apply twice")
    source = source.replace(apt, apt + " " + FONT_PACKAGE + " \\" +
                            "\n    && apt-get purge -y fonts-wqy-zenhei \\" + "\n    && fc-cache -f")
    return source.replace(user, user + "\n# Validate real Chromium CJK advances before publishing the image.\n"
                          "RUN python /opt/yanjia-web/utils/browser_font_health.py\n")


if __name__ == "__main__":
    source, destination = map(Path, sys.argv[1:])
    prepared = prepare(source.read_text(encoding="utf-8"))
    destination.write_text(prepared, encoding="utf-8")
