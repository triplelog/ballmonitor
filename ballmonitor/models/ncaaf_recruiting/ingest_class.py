"""
Ingest Full Recruiting Class Data from On3 / SportsDataVerse

Fetches the complete recruit rankings and granular scholarship offer lists
for a given year, formats the data according to the project's standard schema,
and writes it to:
    data/recruits/football{year}done.csv

Example usage:
    python ingest_class.py --year 2022
"""

import argparse
import csv
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
import sportsdataverse.cfb as cfb

from ballmonitor.models.ncaaf_recruiting.src.data_loader import DataLoader
from ballmonitor.models.ncaaf_recruiting.src.elo_engine import EloEngine, RankingMethod
from ballmonitor.models.ncaaf_recruiting.src.scrapers.on3 import standardize_team_name

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest_class")


def get_http_session(pool_size: int = 15) -> requests.Session:
    """Create a thread-safe requests session with pooled connections and automatic retry."""
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=0.3,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(
        max_retries=retries,
        pool_connections=pool_size,
        pool_maxsize=pool_size,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; RecruitingModel/2.0)"})
    return session


def clean_mascot_from_team_name(team_name: str, mascot: Optional[str] = None) -> str:
    """Strip mascot suffix from school name if present."""
    name = (team_name or "").strip()
    if not name:
        return ""
    if mascot and mascot.strip():
        m = mascot.strip()
        if name.endswith(" " + m):
            return name[: -len(m) - 1].strip()
    return name


def fetch_ranking_pages(year: int, max_workers: int = 8) -> List[Dict[str, Any]]:
    """Fetch all pages of consensus recruit rankings for a given year."""
    logger.info(f"Querying initial page for {year} class to determine total recruits...")
    raw_p1 = cfb.on3_industry_player_rankings(year=year, page=1, return_parsed=False)
    pdata = raw_p1.get("pageProps", {}).get("playerData", {})
    pagination = pdata.get("pagination", {})
    total_count = pagination.get("count", 0)
    page_count = pagination.get("pageCount", 1)

    logger.info(f"Found {total_count} recruits across {page_count} pages for class of {year}.")

    p1_list = pdata.get("list", [])
    if page_count <= 1:
        return p1_list

    def _fetch_page(page_num: int):
        try:
            res = cfb.on3_industry_player_rankings(year=year, page=page_num, return_parsed=False)
            return res.get("pageProps", {}).get("playerData", {}).get("list", [])
        except Exception as e:
            logger.error(f"Error fetching page {page_num}: {e}")
            return []

    all_players = list(p1_list)
    remaining_pages = list(range(2, page_count + 1))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_page = {executor.submit(_fetch_page, p): p for p in remaining_pages}
        for future in as_completed(future_to_page):
            plist = future.result()
            all_players.extend(plist)

    logger.info(f"Retrieved {len(all_players)} total recruit ranking records.")
    return all_players


def fetch_player_targets(
    session: requests.Session, person_key: int, timeout: float = 6.0
) -> Tuple[str, List[str]]:
    """
    Fetch scholarship offers and commitment for a player from On3 targets endpoint.

    Returns:
        (committed_team, list_of_offers)
    """
    url = f"https://api.on3.com/public/rdb/v1/player/{person_key}/team-targets"
    try:
        resp = session.get(url, timeout=timeout)
        if resp.status_code != 200:
            return "", []
        data = resp.json()
    except Exception as e:
        logger.warning(f"Failed to fetch targets for player_key {person_key}: {e}")
        return "", []

    items = data.get("list", [])
    pagination = data.get("pagination", {})
    page_count = pagination.get("pageCount", 1)

    # If recruit has more than 25 targets, fetch page 2
    if page_count > 1:
        try:
            r2 = session.get(url, params={"page": 2}, timeout=timeout)
            if r2.status_code == 200:
                items.extend(r2.json().get("list", []))
        except Exception:
            pass

    committed = ""
    offers: List[str] = []

    for it in items:
        status = it.get("status")
        team_dict = it.get("team") or {}
        raw_name = team_dict.get("name", "")
        slug = team_dict.get("slug", "")
        t_name = standardize_team_name(raw_name, slug)
        if not t_name:
            continue

        if status in ["Enrolled", "Signed", "Committed"]:
            committed = t_name
        else:
            if t_name not in offers:
                offers.append(t_name)

    # Ensure committed school is not in remaining offers
    if committed and committed in offers:
        offers.remove(committed)

    return committed, offers


def parse_stars(ratings: List[Dict[str, Any]]) -> int:
    """Extract consensus star rating from the ratings list."""
    if not ratings:
        return 3
    # Look for consensus or industry rating first
    for r in ratings:
        if r.get("type") in ["Consensus", "Industry"]:
            s = r.get("stars")
            if s is not None:
                try:
                    return int(s)
                except (ValueError, TypeError):
                    pass
    # Fallback to maximum stars reported
    all_stars = [r.get("stars", 0) for r in ratings if r.get("stars") is not None]
    return int(max(all_stars)) if all_stars else 3


def ingest_class(
    year: int,
    data_dir: Path,
    max_workers: int = 10,
    limit: Optional[int] = None,
) -> Path:
    """Scrape and save the full recruiting class to data/recruits/football{year}done.csv."""
    start_time = time.time()
    logger.info(f"Starting ingestion of {year} recruiting class...")

    # 1. Fetch ranking pages
    all_players = fetch_ranking_pages(year=year, max_workers=max_workers)
    if limit is not None and limit > 0:
        logger.info(f"Limiting to first {limit} recruits for test run.")
        all_players = all_players[:limit]

    # Sort players by consensus rank if available
    def _rank_key(p):
        return p.get("consensusOverallRank") or p.get("overallRank") or 999999

    all_players.sort(key=_rank_key)

    # 2. Concurrently fetch targets and offers
    logger.info(f"Fetching granular offer lists for {len(all_players)} recruits using {max_workers} threads...")
    session = get_http_session(pool_size=max_workers + 5)

    player_records: List[List[Any]] = []
    processed = 0
    multi_offer_count = 0
    committed_count = 0

    def _process_player(p: Dict[str, Any]) -> List[Any]:
        person = p.get("person") or {}
        person_key = person.get("key")
        name = str(person.get("name") or "").strip().upper()
        slug = str(person.get("slug") or "").strip()
        url = f"https://www.on3.com/db/{slug}/" if slug else ""
        pos = str(p.get("positionAbbreviation") or "").strip()
        hometown = str(person.get("homeTownName") or "").strip()
        stars = parse_stars(p.get("ratings", []))

        # Fetch offers
        committed, offers = "", []
        if person_key:
            committed, offers = fetch_player_targets(session, person_key)

        # Fallback for committed school if not labeled Enrolled/Signed in targets
        if not committed:
            college_team = p.get("collegeTeam") or {}
            raw_team_name = str(college_team.get("name") or "").strip()
            mascot = str(college_team.get("mascot") or "").strip()
            slug = str(college_team.get("slug") or "").strip()
            cleaned = clean_mascot_from_team_name(raw_team_name, mascot)
            committed = standardize_team_name(cleaned, slug)

        return [url, year, name, pos, hometown, stars, committed] + offers

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_player, p): p for p in all_players}
        for future in as_completed(futures):
            row = future.result()
            player_records.append(row)
            processed += 1
            if row[6]:  # committed school
                committed_count += 1
            if len(row) > 7:  # has offers
                multi_offer_count += 1

            if processed % 200 == 0 or processed == len(all_players):
                logger.info(
                    f"Progress: {processed}/{len(all_players)} recruits processed "
                    f"({committed_count} committed, {multi_offer_count} multi-offer)."
                )

    # Sort records alphabetically or by star descending for consistency
    player_records.sort(key=lambda r: (-r[5], r[2]))

    # 3. Write CSV output
    recruits_dir = data_dir / "recruits"
    recruits_dir.mkdir(parents=True, exist_ok=True)
    out_file = recruits_dir / f"football{year}done.csv"

    logger.info(f"Writing {len(player_records)} records to {out_file}...")
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for row in player_records:
            writer.writerow(row)

    total_time = time.time() - start_time
    logger.info(
        f"Completed {year} class ingestion in {total_time:.1f}s. "
        f"Total recruits: {len(player_records)}, Committed: {committed_count}, "
        f"Multi-offer: {multi_offer_count}."
    )

    # 4. Verify with DataLoader
    loader = DataLoader(data_dir)
    loaded_recruits = loader.load_recruits(year, geolocate=False)
    logger.info(f"DataLoader successfully verified {len(loaded_recruits)} recruits for {year}!")

    return out_file


def main():
    parser = argparse.ArgumentParser(description="Ingest recruiting class data from On3.")
    parser.add_argument("--year", type=int, default=2022, help="Recruiting class year (default: 2022)")
    parser.add_argument("--workers", type=int, default=10, help="Concurrent workers (default: 10)")
    parser.add_argument("--limit", type=int, default=None, help="Optional limit for testing")
    parser.add_argument(
        "--data-dir",
        type=str,
        default=str(Path(__file__).parent / "data"),
        help="Path to data directory",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    out_file = ingest_class(
        year=args.year,
        data_dir=data_dir,
        max_workers=args.workers,
        limit=args.limit,
    )

    # Run Plackett-Luce model on the new dataset
    logger.info(f"Running Plackett-Luce Elo engine on new {args.year} class...")
    loader = DataLoader(data_dir)
    recruits = loader.load_recruits(args.year, geolocate=True)
    engine = EloEngine(method=RankingMethod.PLACKETT_LUCE)
    result = engine.run(args.year, recruits)

    print("\n" + "=" * 80)
    print(f"Top 20 Recruiting Classes for {args.year} (Plackett-Luce Choice Model)")
    print("=" * 80)
    print(f"{'Rank':<5} {'Team':<22} {'Elo':<8} {'Commits':<9} {'Offers':<8} {'Score':<8} {'Avg Mi':<8} {'Natl %':<8}")
    print("-" * 80)
    for t in result.teams[:20]:
        print(
            f"{t.rank:<5} {t.name:<22} {t.elo:<8.1f} {t.commits_count:<9} "
            f"{t.offers_count:<8} {t.total_score:<8.2f} {t.avg_recruit_distance:<8.1f} {t.national_pct:<8.1f}%"
        )
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
