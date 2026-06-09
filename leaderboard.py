#!/usr/bin/env python3
"""Tesla Supercharger Voting leaderboard.

Loads the public voting page in a real Chrome browser (Tesla's CDN requires
JS-evaluated bot-mitigation cookies), reads the inline `window.tesla = {...};`
payload out of the rendered HTML, and prints the top candidates with vote
count and coordinates.
"""

import argparse
import json
import re
import sys

from patchright.sync_api import sync_playwright

PAGE_URL_TEMPLATE = "https://www.tesla.com/{locale}/supercharger-voting?v=2"
DEFAULT_LOCALE = "en_us"

WINDOW_TESLA_PREFIX_RE = re.compile(r"window\.tesla\s*=\s*\{")


def _extract_window_tesla(script_text: str) -> str | None:
    """Return the `{...}` object literal assigned to window.tesla, or None.

    Uses a balanced-brace scan that respects string and regex literals, since
    the payload is too large/nested for a regex to match correctly.
    """
    m = WINDOW_TESLA_PREFIX_RE.search(script_text)
    if not m:
        return None
    start = m.end() - 1  # position of the opening `{`
    depth = 0
    i = start
    in_str: str | None = None  # the quote char if inside a string
    while i < len(script_text):
        ch = script_text[i]
        if in_str is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
        else:
            if ch in ("'", '"', "`"):
                in_str = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return script_text[start : i + 1]
        i += 1
    return None


def fetch_app(locale: str = DEFAULT_LOCALE, *, headless: bool = False,
              debug: bool = False) -> dict:
    url = PAGE_URL_TEMPLATE.format(locale=locale)
    with sync_playwright() as p:
        # Patchright requires launch_persistent_context with real Chrome and
        # no custom UA / no extra launch args to apply its full anti-detection
        # patch set. Tesla/Akamai blocks headless mode regardless of patches —
        # use the visible window mode (the default).
        ctx = p.chromium.launch_persistent_context(
            user_data_dir="",
            channel="chrome",
            headless=headless,
            no_viewport=True,
        )
        try:
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)

            title = page.title()
            if title.strip().lower() == "access denied":
                if debug:
                    page.screenshot(path="debug.png", full_page=True)
                raise RuntimeError(
                    "Tesla returned an Akamai 'Access Denied' page.\n"
                    "  Headless mode is detected by Akamai — run without "
                    "`--headless` (this is the default)."
                )

            # The inline <script> that defines window.tesla is shipped with
            # the initial HTML. DOM access is shared across patchright's
            # isolated and main worlds, so we can grab the script tag's text
            # directly without needing main-world JS access.
            script_text = page.evaluate(
                """
                () => {
                  const tags = document.querySelectorAll('script');
                  for (const t of tags) {
                    const s = t.textContent || '';
                    if (s.indexOf('window.tesla') !== -1) return s;
                  }
                  return null;
                }
                """
            )

            if not script_text:
                if debug:
                    page.screenshot(path="debug.png", full_page=True)
                    with open("debug.html", "w", encoding="utf-8") as f:
                        f.write(page.content())
                raise RuntimeError(
                    "No <script> tag containing `window.tesla` found.\n"
                    f"  page title : {title!r}\n"
                    f"  page url   : {page.url}\n"
                    + ("  saved debug.png and debug.html\n" if debug else "")
                )

            payload = _extract_window_tesla(script_text)
            if not payload:
                if debug:
                    with open("debug.js", "w", encoding="utf-8") as f:
                        f.write(script_text)
                raise RuntimeError(
                    "Found the script tag but couldn't extract the "
                    "`window.tesla = {…}` object literal.\n"
                    + ("  saved debug.js\n" if debug else "")
                )
        finally:
            ctx.close()
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        try:
            import json5
        except ImportError as exc:
            raise RuntimeError(
                "Tesla payload is not strict JSON; install json5 "
                "(`pip install json5`)."
            ) from exc
        data = json5.loads(payload)

    app = data.get("App")
    if not app or "candidates" not in app:
        raise RuntimeError("Parsed payload has no App.candidates array.")
    return app


def leaderboard(app: dict, country: str | None = None, limit: int = 20,
                under_construction: bool = False) -> list[dict]:
    if under_construction:
        # Sites that won a voting round move to a construction status; the
        # exact enum varies, so match any status mentioning CONSTRUCTION.
        rows = [c for c in app.get("candidates", [])
                if "CONSTRUCTION" in (c.get("status") or "").upper()]
    else:
        rows = [c for c in app.get("candidates", []) if c.get("status") == "ENABLED"]
    if country:
        cc = country.upper()
        rows = [r for r in rows if _country_of(r) == cc]
    rows.sort(key=lambda c: c.get("voteCount", 0), reverse=True)
    return rows[:limit]


def _country_of(candidate: dict) -> str:
    addresses = candidate.get("addresses") or []
    if addresses:
        code = addresses[0].get("countryCode")
        if code:
            return code.upper()
    addr_loc = candidate.get("addressLocation") or {}
    return (addr_loc.get("countryCode") or "").upper()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Show the top Tesla Supercharger voting candidates."
    )
    parser.add_argument(
        "-n", "--top", type=int, default=20,
        help="Number of top candidates to show (default: 20).",
    )
    parser.add_argument(
        "-c", "--country",
        help="ISO-2 country code filter (e.g. US, TR, NZ).",
    )
    parser.add_argument(
        "-u", "--under-construction", action="store_true",
        help="Show sites under construction instead of open voting candidates.",
    )
    parser.add_argument(
        "--locale", default=DEFAULT_LOCALE,
        help=f"Tesla locale path segment (default: {DEFAULT_LOCALE}).",
    )
    parser.add_argument(
        "--headless", action="store_true",
        help="Run Chrome headless (NOT recommended — Akamai blocks headless).",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="On failure, save debug.png / debug.html and print diagnostics.",
    )
    args = parser.parse_args()

    if args.top <= 0:
        print("--top must be a positive integer.", file=sys.stderr)
        return 2

    app = fetch_app(args.locale, headless=args.headless, debug=args.debug)
    rows = leaderboard(app, country=args.country, limit=args.top,
                       under_construction=args.under_construction)

    if not rows:
        scope = f" in {args.country.upper()}" if args.country else ""
        kind = "under-construction sites" if args.under_construction else "candidates"
        print(f"No {kind} found{scope}.", file=sys.stderr)
        return 1

    print(f"{'Rank':<5} {'Votes':>7}  {'Lat':>10}  {'Lon':>11}  {'CC':<3} Site")
    print("-" * 80)
    for i, c in enumerate(rows, start=1):
        lat = c.get("latitude")
        lon = c.get("longitude")
        print(
            f"{i:<5} "
            f"{c.get('voteCount', 0):>7}  "
            f"{lat!s:>10}  {lon!s:>11}  "
            f"{_country_of(c):<3} "
            f"{c.get('siteName', '')}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
