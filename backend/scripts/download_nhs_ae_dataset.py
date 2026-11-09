"""Discover, download, and validate official NHS England monthly A&E files."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from tqdm import tqdm
from urllib3.util.retry import Retry

COLLECTION_PAGE = (
    "https://www.england.nhs.uk/statistics/statistical-work-areas/"
    "ae-waiting-times-and-activity/"
)
OFFICIAL_HOSTS = {"www.england.nhs.uk", "england.nhs.uk"}
USER_AGENT = "HealthFlow-NHS-AE-downloader/1.0 (research capacity-planning workflow)"
MONTH_PATTERN = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+(20\d{2})\b", re.I
)
YEAR_PAGE_PATTERN = re.compile(
    r"(?:monthly\s+)?a\s*&?\s*e.*(?:admissions|attendances).*(20\d{2})\s*[-–]\s*(\d{2,4})",
    re.I,
)
FILE_EXTENSIONS = {".csv", ".xls", ".xlsx"}


class DiscoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class Candidate:
    reporting_month: str
    financial_year: str
    source_page: str
    source_url: str
    original_filename: str
    file_format: str
    revised: bool
    link_text: str


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def month(value: str) -> pd.Period:
    try:
        return pd.Period(value, freq="M")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected YYYY-MM or 'latest'.") from exc


def financial_year(period: pd.Period) -> str:
    start = period.year if period.month >= 4 else period.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def official_url(url: str) -> bool:
    return urlparse(url).hostname in OFFICIAL_HOSTS


def session_with_retries(retries: int) -> requests.Session:
    retry = Retry(
        total=retries, connect=retries, read=retries,
        backoff_factor=1.0, status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}), raise_on_status=False,
    )
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def fetch_html(session: requests.Session, url: str, timeout: float) -> BeautifulSoup:
    if not official_url(url):
        raise DiscoveryError(f"Refusing non-NHS-England URL: {url}")
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    if "html" not in response.headers.get("content-type", "").lower():
        raise DiscoveryError(f"Expected HTML from {url}; page structure may have changed.")
    return BeautifulSoup(response.content, "lxml")


def discover_archive_pages(
    session: requests.Session, timeout: float
) -> list[tuple[str, str]]:
    soup = fetch_html(session, COLLECTION_PAGE, timeout)
    pages: dict[str, str] = {}
    for anchor in soup.find_all("a", href=True):
        text = " ".join(anchor.get_text(" ", strip=True).split())
        match = YEAR_PAGE_PATTERN.search(text)
        if not match:
            continue
        url = urljoin(COLLECTION_PAGE, anchor["href"])
        if official_url(url):
            start = int(match.group(1))
            pages[f"{start}-{str(start + 1)[-2:]}"] = url
    if not pages:
        raise DiscoveryError(
            "No monthly financial-year archive pages were found on the official "
            "collection page; its structure may have changed."
        )
    return sorted(pages.items())


def reporting_month(text: str, url: str) -> pd.Period | None:
    decoded = unquote(url)
    for value in (text, decoded):
        match = MONTH_PATTERN.search(value)
        if match:
            return pd.Period(
                f"{match.group(2)}-{datetime.strptime(match.group(1)[:3], '%b').month:02}",
                freq="M",
            )
    return None


def discover_candidates(
    session: requests.Session,
    pages: list[tuple[str, str]],
    timeout: float,
    sleep_seconds: float,
) -> list[Candidate]:
    found: list[Candidate] = []
    for index, (fy, page_url) in enumerate(pages):
        if index and sleep_seconds:
            time.sleep(sleep_seconds)
        soup = fetch_html(session, page_url, timeout)
        for anchor in soup.find_all("a", href=True):
            text = " ".join(anchor.get_text(" ", strip=True).split())
            url = urljoin(page_url, anchor["href"])
            suffix = Path(urlparse(url).path).suffix.lower()
            combined = f"{text} {unquote(url)}"
            if suffix not in FILE_EXTENSIONS:
                continue
            if re.search(r"\bquarter(?:ly)?\b", combined, re.I):
                continue
            if not official_url(url):
                continue
            if not re.search(r"(monthly|month).*(a\s*&?\s*e|ae)|a\s*&?\s*e.*(csv|xls)", combined, re.I):
                continue
            period = reporting_month(text, url)
            if period is None:
                continue
            found.append(Candidate(
                reporting_month=str(period), financial_year=fy,
                source_page=page_url, source_url=url,
                original_filename=Path(unquote(urlparse(url).path)).name,
                file_format=suffix.lstrip("."),
                revised=bool(re.search(r"\brevis(?:ed|ion)\b|\brev\b", combined, re.I)),
                link_text=text,
            ))
    return found


def choose_candidates(
    candidates: list[Candidate], start: pd.Period, end: pd.Period, prefer_csv: bool
) -> tuple[list[Candidate], list[dict]]:
    selected, rejected = [], []
    grouped: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        period = pd.Period(candidate.reporting_month, freq="M")
        if start <= period <= end:
            grouped.setdefault(candidate.reporting_month, []).append(candidate)
    for key in sorted(grouped):
        options = grouped[key]
        ranked = sorted(
            options,
            key=lambda c: (
                not c.revised,
                0 if prefer_csv and c.file_format == "csv" else
                1 if c.file_format == "csv" else 2,
                c.source_url,
            ),
        )
        selected.append(ranked[0])
        for candidate in ranked[1:]:
            rejected.append({
                "reporting_month": key,
                "rejected_url": candidate.source_url,
                "selected_url": ranked[0].source_url,
                "reason": "lower preference by revised/CSV/deduplication policy",
            })
    return selected, rejected


def read_headers(path: Path, file_format: str) -> list[str]:
    if file_format == "csv":
        errors = []
        for encoding in ("utf-8-sig", "cp1252", "latin1"):
            for separator in (",", "\t"):
                try:
                    frame = pd.read_csv(
                        path, encoding=encoding, sep=separator, nrows=5,
                        skip_blank_lines=True, engine="python",
                    )
                    if len(frame.columns) > 3:
                        return [str(value).strip() for value in frame.columns]
                except Exception as exc:
                    errors.append(str(exc))
        raise DiscoveryError(f"CSV is not parseable: {path}; {errors[-1:]}")
    frame = pd.read_excel(path, nrows=5)
    if len(frame.columns) < 4:
        raise DiscoveryError(f"Spreadsheet has too few columns: {path}")
    return [str(value).strip() for value in frame.columns]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_one(
    session: requests.Session, candidate: Candidate, timeout: float, force: bool
) -> dict:
    root = repository_root()
    destination = (
        root / "backend/dataset/raw/nhs_england_ae/monthly"
        / candidate.reporting_month[:4]
        / f"nhs_ae_{candidate.reporting_month.replace('-', '_')}.csv"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not force:
        headers = read_headers(destination, "csv")
    else:
        part = destination.with_name(destination.name + ".part")
        source_part = destination.with_name(destination.name + f".source.{candidate.file_format}.part")
        for temporary in (part, source_part):
            if temporary.exists():
                temporary.unlink()
        try:
            with session.get(candidate.source_url, stream=True, timeout=timeout) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length", 0))
                with source_part.open("wb") as target, tqdm(
                    total=total or None, unit="B", unit_scale=True,
                    desc=destination.name,
                ) as progress:
                    for block in response.iter_content(1024 * 1024):
                        if block:
                            target.write(block)
                            progress.update(len(block))
            if candidate.file_format == "csv":
                source_part.replace(part)
            else:
                raw = pd.read_excel(source_part, header=None)
                header_row = None
                for row_index, row in raw.head(40).iterrows():
                    values = {str(value).strip().lower() for value in row.dropna()}
                    has_code = bool(values & {"code", "org code", "organisation code"})
                    has_name = bool(values & {"name", "org name", "organisation name"})
                    has_activity = any(
                        "emergency admission" in value or "a&e attend" in value
                        for value in values
                    )
                    if has_code and has_name and has_activity:
                        header_row = row_index
                        break
                if header_row is None:
                    raise DiscoveryError(
                        f"Could not locate provider-table header in spreadsheet: {source_part}"
                    )
                frame = raw.iloc[header_row + 1:].copy()
                frame.columns = [
                    str(value).strip() if pd.notna(value) else f"unnamed_{index}"
                    for index, value in enumerate(raw.iloc[header_row])
                ]
                frame = frame.dropna(how="all")
                frame.to_csv(part, index=False)
            headers = read_headers(part, "csv")
            part.replace(destination)
        finally:
            for temporary in (part, source_part):
                if temporary.exists():
                    temporary.unlink()
    return {
        **asdict(candidate),
        "local_relative_path": destination.relative_to(root).as_posix(),
        "source_file_format": candidate.file_format,
        "file_format": "csv",
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "sha256": sha256(destination),
        "size_bytes": destination.stat().st_size,
        "column_headers": headers,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-month", default="2018-04", type=month)
    parser.add_argument("--end-month", default="latest")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--sleep-between-requests", type=float, default=0.25)
    parser.add_argument("--prefer-csv", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.end_month != "latest":
        args.end_month = month(args.end_month)
    if args.timeout <= 0 or args.retries < 0 or args.sleep_between_requests < 0:
        parser.error("Timeout/sleep must be non-negative and timeout positive.")
    return args


def main() -> int:
    args = parse_args()
    session = session_with_retries(args.retries)
    pages = discover_archive_pages(session, args.timeout)
    print(f"Archive pages found ({len(pages)}):")
    for fy, url in pages:
        print(f"  {fy}: {url}")
    candidates = discover_candidates(
        session, pages, args.timeout, args.sleep_between_requests
    )
    if not candidates:
        raise DiscoveryError(
            "No monthly data files were found; official archive structure may have changed."
        )
    latest = max(pd.Period(c.reporting_month, freq="M") for c in candidates)
    end = latest if args.end_month == "latest" else args.end_month
    if end < args.start_month:
        raise DiscoveryError("End month precedes start month.")
    selected, rejected = choose_candidates(candidates, args.start_month, end, args.prefer_csv)
    selected_months = {pd.Period(c.reporting_month, freq="M") for c in selected}
    expected = set(pd.period_range(args.start_month, end, freq="M"))
    missing = sorted(str(value) for value in expected - selected_months)
    print(f"Monthly files selected ({len(selected)}), latest discovered: {latest}")
    for item in selected:
        output = (
            repository_root() / "backend/dataset/raw/nhs_england_ae/monthly"
            / item.reporting_month[:4]
            / f"nhs_ae_{item.reporting_month.replace('-', '_')}.csv"
        )
        print(f"  {item.reporting_month}: {item.source_url} -> {output}")
    print(f"Duplicate candidates rejected: {len(rejected)}")
    print(f"Missing months ({len(missing)}): {missing}")
    if args.dry_run:
        print("DRY RUN: no files or manifest written.")
        return 0
    records = []
    warnings = []
    for index, candidate in enumerate(selected):
        if index and args.sleep_between_requests:
            time.sleep(args.sleep_between_requests)
        try:
            records.append(download_one(session, candidate, args.timeout, args.force))
        except Exception as exc:
            warning = f"{candidate.reporting_month}: {type(exc).__name__}: {exc}"
            warnings.append(warning)
            print(f"WARNING: {warning}")
    manifest = {
        "dataset_name": "NHS England Monthly A&E Attendances and Emergency Admissions",
        "official_collection_page": COLLECTION_PAGE,
        "requested_start_month": str(args.start_month),
        "requested_end_month": "latest" if args.end_month == "latest" else str(end),
        "latest_month_discovered": str(latest),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "files": records,
        "missing_months": missing,
        "duplicate_candidates_rejected": rejected,
        "warnings": warnings,
    }
    manifest_path = (
        repository_root() / "backend/dataset/manifests/nhs_ae_download_manifest.json"
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Downloaded/validated {len(records)} files; manifest: {manifest_path}")
    return 0 if records else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DiscoveryError, requests.RequestException) as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(2)
