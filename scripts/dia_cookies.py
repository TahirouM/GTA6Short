"""Export YouTube/Google cookies from the Dia browser to a Netscape cookies.txt.

yt-dlp knows Chromium browsers but not Dia (keychain item "Dia Safe Storage"),
so we reuse its Chromium extractor with Dia's paths patched in.

Usage: uv run --with yt-dlp python -I scripts/dia_cookies.py OUT_FILE
"""
import os
import sys
from http.cookiejar import MozillaCookieJar

import yt_dlp.cookies as yc

DIA_DIR = os.path.expanduser("~/Library/Application Support/Dia/User Data")
_orig = yc._get_chromium_based_browser_settings


def _patched(browser_name):
    if browser_name == "chrome":
        s = _orig(browser_name)
        s.update(browser_dir=DIA_DIR, keyring_name="Dia")
        return s
    return _orig(browser_name)


yc._get_chromium_based_browser_settings = _patched
jar = yc.extract_cookies_from_browser("chrome", profile="Default")
out = MozillaCookieJar(sys.argv[1])
keep = (".youtube.com", "youtube.com", ".google.com", "accounts.google.com")
n = 0
for c in jar:
    if c.domain.endswith(keep):
        out.set_cookie(c)
        n += 1
out.save(ignore_discard=True, ignore_expires=True)
os.chmod(sys.argv[1], 0o600)
print(f"{n} youtube/google cookies exported")
