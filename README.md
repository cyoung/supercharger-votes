# Supercharger Votes

Tiny CLI that scrapes Tesla's public Supercharger Voting page and prints the
top candidate sites by vote count, with their coordinates.

## Setup

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
patchright install chrome       # one-time browser download
```

You also need a working installation of Google Chrome on your machine — the
script launches it via `channel="chrome"`. (Patchright deliberately uses the
real Chrome binary rather than bundled Chromium, because Akamai fingerprints
the Chromium build.)

Tesla's CDN (Akamai) blocks plain HTTP clients and even off-the-shelf
Playwright, so the script uses [Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright)
(a drop-in Playwright fork with anti-detection patches) to load the page,
then reads `window.tesla.App` directly.

## Usage

```sh
# Top 20 worldwide (default)
python leaderboard.py

# Top 50 worldwide
python leaderboard.py -n 50

# Top 10 in Turkey
python leaderboard.py -n 10 -c TR

# Use a different Tesla locale
python leaderboard.py --locale es_co
```

### Options

| Flag | Default | Description |
| --- | --- | --- |
| `-n`, `--top` | `20` | How many top candidates to show. |
| `-c`, `--country` | _(none)_ | ISO-2 country code filter (e.g. `US`, `TR`). |
| `--locale` | `en_us` | Tesla locale path segment. |
| `--headless` | off | Run Chrome with no visible window. Akamai detects headless and returns "Access Denied" — not recommended. |
| `--debug` | off | On failure, write `debug.png` and `debug.html` and print page diagnostics. |

Read-only — does not vote or require authentication.

### Headless note

Tesla sits behind Akamai bot mitigation, which detects headless Chrome even
with anti-detection patches. The script defaults to a visible browser window
that opens briefly while the page loads and closes once the data is read.
