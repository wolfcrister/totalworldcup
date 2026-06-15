from __future__ import annotations

import argparse
import csv
import html
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


COMMONS_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "TotalWorldCupFlagImporter/1.0 (local tooling)"


NAME_OVERRIDES = {
    "IR Iran": ["Iran"],
    "Korea Republic": ["South Korea", "Republic of Korea"],
    "Congo DR": ["Democratic Republic of the Congo", "DR Congo"],
    "Czechia": ["Czech Republic"],
    "Cabo Verde": ["Cape Verde"],
    "Kyrgyz Republic": ["Kyrgyzstan"],
    "The Gambia": ["Gambia"],
    "DPR Korea": ["North Korea", "Democratic People's Republic of Korea"],
    "St. Kitts and Nevis": ["Saint Kitts and Nevis"],
    "St. Lucia": ["Saint Lucia"],
    "St. Vincent / Grenadines": ["Saint Vincent and the Grenadines"],
    "Chinese Taipei": ["Taiwan"],
    "China PR": ["China"],
    "USA": ["United States", "United States of America"],
    "Russia": ["Russia", "Russian Federation"],
    "Türkiye": ["Turkey", "Turkiye"],
    "Côte d'Ivoire": ["Ivory Coast", "Cote d'Ivoire"],
    "São Tomé and Príncipe": ["Sao Tome and Principe"],
    "North Macedonia": ["Macedonia", "North Macedonia"],
    "Eswatini": ["Swaziland", "Eswatini"],
    "Hong Kong": ["Hong Kong"],
    "Macau": ["Macau"],
    "US Virgin Islands": ["United States Virgin Islands", "U.S. Virgin Islands"],
    "British Virgin Islands": ["British Virgin Islands"],
    "Curaçao": ["Curacao", "Curaçao"],
    "Timor-Leste": ["East Timor", "Timor-Leste"],
}


def _with_retries(url: str, timeout: float, expect_json: bool) -> Any:
    last_error: Exception | None = None
    for attempt in range(7):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=timeout) as resp:
                payload = resp.read()
                if expect_json:
                    return json.loads(payload.decode("utf-8"))
                content_type = resp.headers.get("Content-Type", "application/octet-stream")
                return payload, content_type
        except HTTPError as err:
            last_error = err
            if err.code not in (429, 500, 502, 503, 504):
                raise
            time.sleep(min(8.0, 0.8 * (2 ** attempt)))
        except (URLError, TimeoutError) as err:
            last_error = err
            time.sleep(min(8.0, 0.8 * (2 ** attempt)))
    if last_error is not None:
        raise last_error
    raise RuntimeError("request failed without error")


def _http_get_json(url: str, timeout: float = 20.0) -> dict[str, Any]:
    return _with_retries(url, timeout=timeout, expect_json=True)


def _http_get_bytes(url: str, timeout: float = 30.0) -> tuple[bytes, str]:
    return _with_retries(url, timeout=timeout, expect_json=False)


def _clean_meta(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def _name_candidates(name: str) -> list[str]:
    candidates = [name]
    candidates.extend(NAME_OVERRIDES.get(name, []))
    if " and " in name:
        candidates.append(name.replace(" and ", " & "))
    return list(dict.fromkeys(candidates))


def _build_query_url(search_name: str, thumb_width: int) -> str:
    gsrsearch = f'intitle:"Flag of {search_name}"'
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrnamespace": "6",
        "gsrsearch": gsrsearch,
        "gsrlimit": "8",
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": str(thumb_width),
    }
    return f"{COMMONS_API}?{urlencode(params)}"


def _pick_best_file(pages: list[dict[str, Any]], search_name: str) -> dict[str, Any] | None:
    preferred_prefixes = [
        f"File:Flag of {search_name}",
        f"File:Flag_of_{search_name.replace(' ', '_')}",
    ]

    def score(page: dict[str, Any]) -> int:
        title = page.get("title", "")
        low = title.lower()
        s = 0
        if low.endswith(".svg"):
            s += 4
        if low.endswith(".png"):
            s += 3
        if "football" in low or "soccer" in low or "association" in low:
            s -= 6
        if "civil ensign" in low or "naval" in low:
            s -= 3
        if "with the royal coat of arms" in low or "coat of arms" in low:
            s -= 5
        if re.search(r"\((?:\d{4}|civil|state|war|government)", low):
            s -= 4
        for p in preferred_prefixes:
            if title.startswith(p):
                s += 8
        if re.match(r"^file:flag of [^()]+\.(svg|png)$", low):
            s += 4
        if "flag of" in low:
            s += 2
        return s

    if not pages:
        return None
    ranked = sorted(pages, key=score, reverse=True)
    if score(ranked[0]) < 2:
        return None
    return ranked[0]


def _extension_from_type(content_type: str) -> str:
    ctype = content_type.lower()
    if "image/png" in ctype:
        return ".png"
    if "image/jpeg" in ctype:
        return ".jpg"
    if "image/webp" in ctype:
        return ".webp"
    if "image/svg+xml" in ctype:
        return ".svg"
    return ".img"


def _find_existing_flag_filename(out_dir: Path, fifa_code: str) -> str:
    code = fifa_code.lower()
    for p in sorted(out_dir.glob(f"{code}.*")):
        if p.is_file() and p.name not in {"flags_manifest.csv", "flags_missing.csv"}:
            return p.name
    return ""


def _download_flag_for_team(team_name: str, fifa_code: str, out_dir: Path, thumb_width: int) -> dict[str, str]:
    for candidate in _name_candidates(team_name):
        try:
            query_url = _build_query_url(candidate, thumb_width)
            data = _http_get_json(query_url)
        except (HTTPError, URLError, TimeoutError) as err:
            return {
                "status": "error",
                "team_name": team_name,
                "fifa_code": fifa_code,
                "error": f"query failed: {err}",
            }

        pages_map = data.get("query", {}).get("pages", {})
        pages = list(pages_map.values())
        best = _pick_best_file(pages, candidate)
        if best is None:
            continue

        imageinfo = (best.get("imageinfo") or [{}])[0]
        image_url = imageinfo.get("thumburl") or imageinfo.get("url")
        if not image_url:
            continue

        try:
            raw, content_type = _http_get_bytes(image_url)
        except (HTTPError, URLError, TimeoutError) as err:
            return {
                "status": "error",
                "team_name": team_name,
                "fifa_code": fifa_code,
                "error": f"download failed: {err}",
            }

        ext = _extension_from_type(content_type)
        filename = f"{fifa_code.lower()}{ext}"
        file_path = out_dir / filename
        file_path.write_bytes(raw)

        meta = imageinfo.get("extmetadata") or {}
        license_short = _clean_meta((meta.get("LicenseShortName") or {}).get("value", ""))
        license_url = _clean_meta((meta.get("LicenseUrl") or {}).get("value", ""))
        artist = _clean_meta((meta.get("Artist") or {}).get("value", ""))
        credit = _clean_meta((meta.get("Credit") or {}).get("value", ""))

        return {
            "status": "ok",
            "team_name": team_name,
            "fifa_code": fifa_code,
            "candidate": candidate,
            "file": filename,
            "commons_title": best.get("title", ""),
            "image_url": image_url,
            "license": license_short,
            "license_url": license_url,
            "artist": artist,
            "credit": credit,
            "source_page": f"https://commons.wikimedia.org/wiki/{quote(best.get('title', ''), safe=':/_')}" if best.get("title") else "",
        }

    return {
        "status": "missing",
        "team_name": team_name,
        "fifa_code": fifa_code,
        "error": "no suitable Wikimedia file found",
    }


def run_import(
    nations_csv: Path,
    output_dir: Path,
    thumb_width: int,
    delay_s: float,
    only_missing: bool,
    only_codes: set[str] | None,
) -> tuple[int, int, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "flags_manifest.csv"
    missing_path = output_dir / "flags_missing.csv"

    with nations_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        all_rows = [r for r in reader if r.get("is_playable", "").strip().lower() == "true"]
    rows = all_rows
    if only_codes:
        rows = [r for r in all_rows if (r.get("fifa_code") or "").strip().upper() in only_codes]

    existing_ok_codes: set[str] = set()
    if only_missing and manifest_path.exists():
        with manifest_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if row.get("status") == "ok":
                    existing_ok_codes.add((row.get("fifa_code") or "").upper())

    results: list[dict[str, str]] = []
    for idx, row in enumerate(rows, start=1):
        name = row["name"].strip()
        code = row["fifa_code"].strip().upper()
        if code in existing_ok_codes:
            print(f"[{idx:>3}/{len(rows)}] {name}: skipped")
            continue
        result = _download_flag_for_team(name, code, output_dir, thumb_width)
        results.append(result)
        print(f"[{idx:>3}/{len(rows)}] {name}: {result['status']}")
        if delay_s > 0:
            time.sleep(delay_s)

    if only_missing and manifest_path.exists():
        with manifest_path.open("r", encoding="utf-8", newline="") as handle:
            old_rows = list(csv.DictReader(handle))
    else:
        old_rows = []

    merged_by_code: dict[str, dict[str, str]] = {}
    for row in old_rows:
        merged_by_code[(row.get("fifa_code") or "").upper()] = row
    for row in results:
        merged_by_code[(row.get("fifa_code") or "").upper()] = row

    merged_results: list[dict[str, str]] = []
    for row in all_rows:
        code = row["fifa_code"].strip().upper()
        if code in merged_by_code:
            merged_results.append(merged_by_code[code])
            continue

        existing_file = _find_existing_flag_filename(output_dir, code)
        if existing_file:
            merged_results.append(
                {
                    "team_name": row["name"].strip(),
                    "fifa_code": code,
                    "status": "ok",
                    "candidate": "",
                    "file": existing_file,
                    "commons_title": "",
                    "image_url": "",
                    "source_page": "",
                    "license": "",
                    "license_url": "",
                    "artist": "",
                    "credit": "",
                    "error": "",
                }
            )
        else:
            merged_results.append(
                {
                    "team_name": row["name"].strip(),
                    "fifa_code": code,
                    "status": "missing",
                    "candidate": "",
                    "file": "",
                    "commons_title": "",
                    "image_url": "",
                    "source_page": "",
                    "license": "",
                    "license_url": "",
                    "artist": "",
                    "credit": "",
                    "error": "no file downloaded",
                }
            )

    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "team_name",
                "fifa_code",
                "status",
                "candidate",
                "file",
                "commons_title",
                "image_url",
                "source_page",
                "license",
                "license_url",
                "artist",
                "credit",
                "error",
            ],
        )
        writer.writeheader()
        writer.writerows(merged_results)

    missing = [r for r in merged_results if r.get("status") != "ok"]
    with missing_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["team_name", "fifa_code", "status", "error"])
        writer.writeheader()
        writer.writerows(missing)

    ok_count = sum(1 for r in merged_results if r.get("status") == "ok")
    missing_count = sum(1 for r in merged_results if r.get("status") == "missing")
    error_count = sum(1 for r in merged_results if r.get("status") == "error")
    return ok_count, missing_count, error_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Download flags from Wikimedia Commons with attribution metadata.")
    parser.add_argument(
        "--nations-csv",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "nations.csv",
        help="Path to nations CSV.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "assets" / "flags",
        help="Directory for downloaded flags and manifests.",
    )
    parser.add_argument(
        "--thumb-width",
        type=int,
        default=128,
        help="Requested thumbnail width from Wikimedia.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.35,
        help="Delay between requests to avoid API burst.",
    )
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help="Only process nations that are not already marked ok in flags_manifest.csv.",
    )
    parser.add_argument(
        "--only-codes",
        type=str,
        default="",
        help="Comma-separated FIFA codes to process (e.g. SVN,NIR,MNE).",
    )
    args = parser.parse_args()

    if not args.nations_csv.exists():
        print(f"nations csv not found: {args.nations_csv}")
        return 1

    only_codes = {
        code.strip().upper()
        for code in args.only_codes.split(",")
        if code.strip()
    }

    ok_count, missing_count, error_count = run_import(
        args.nations_csv,
        args.output_dir,
        args.thumb_width,
        args.delay,
        args.only_missing,
        (only_codes or None),
    )
    print("\nImport complete")
    print(f"  downloaded: {ok_count}")
    print(f"  missing:    {missing_count}")
    print(f"  errors:     {error_count}")
    print(f"  output dir: {args.output_dir}")
    return 0 if error_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
