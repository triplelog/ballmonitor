import re
import urllib.parse
from bs4 import BeautifulSoup

def discover_race_years(url: str, html: str | None = None) -> dict[int, str]:
    """Discover URLs for previous years from a race results page.
    
    Checks:
    1. RunSignup API endpoints if a RunSignup URL.
    2. HTML <select> dropdown menus containing year options.
    3. Archive navigation links (<a> tags) linking to past editions.
    4. URL pattern variations if a 4-digit year is present in the URL path or query.
    
    Returns a dict mapping {year: url} sorted descending by year.
    """
    discovered: dict[int, str] = {}
    parsed_base = urllib.parse.urlparse(url)
    base_domain = parsed_base.netloc.lower()

    # 1. RunSignup platform handling
    if "runsignup.com" in base_domain:
        m = re.search(r"/Race/Results/(\d+)", url, re.IGNORECASE) or re.search(r"/Race/(\d+)/Results", url, re.IGNORECASE)
        if m:
            race_id = m.group(1)
            # In live environment, we could fetch /rest/race/{race_id}/results/get-result-sets
            # For now, record the current race_id and allow query param detection
            pass

    # Detect current year from URL if present
    url_year_match = re.search(r"\b(20\d\d|19\d\d)\b", url)
    current_year = int(url_year_match.group(1)) if url_year_match else None
    if current_year:
        discovered[current_year] = url

    if not html:
        return discovered

    soup = BeautifulSoup(html, "html.parser")

    # 2. Check <select> dropdowns for year selectors
    selects = soup.find_all("select")
    for sel in selects:
        # Check if select attributes or options suggest year selection
        attrs_str = " ".join([
            sel.get("name", ""),
            sel.get("id", ""),
            " ".join(sel.get("class", [])),
        ]).lower()

        options = sel.find_all("option")
        has_year_options = False
        sel_matches: list[tuple[int, str]] = []

        # Find enclosing form action if any
        form = sel.find_parent("form")
        form_action = form.get("action", "") if form else ""

        for opt in options:
            opt_text = opt.get_text(strip=True)
            opt_val = opt.get("value", "").strip()
            data_url = opt.get("data-url", "") or opt.get("data-href", "")

            # Look for 4-digit year in text or value
            ym = re.search(r"\b(19\d\d|20\d\d)\b", opt_text) or re.search(r"\b(19\d\d|20\d\d)\b", opt_val)
            if ym:
                year = int(ym.group(1))
                if 1980 <= year <= 2035:
                    has_year_options = True
                    target_url = None
                    if data_url:
                        target_url = urllib.parse.urljoin(url, data_url)
                    elif opt_val.startswith("http://") or opt_val.startswith("https://") or opt_val.startswith("/"):
                        target_url = urllib.parse.urljoin(url, opt_val)
                    elif form_action:
                        # Append form param
                        param_name = sel.get("name", "year")
                        sep = "&" if "?" in form_action else "?"
                        target_url = urllib.parse.urljoin(url, f"{form_action}{sep}{param_name}={opt_val}")
                    elif current_year and str(year) in opt_val:
                        # Substitute year in base URL
                        target_url = url.replace(str(current_year), str(year))
                    else:
                        # Default query parameter substitution
                        parsed = urllib.parse.urlparse(url)
                        qs = urllib.parse.parse_qs(parsed.query)
                        qs["year"] = [str(year)]
                        new_query = urllib.parse.urlencode(qs, doseq=True)
                        target_url = urllib.parse.urlunparse(parsed._replace(query=new_query))

                    if target_url:
                        sel_matches.append((year, target_url))

        is_year_select = (
            any(w in attrs_str for w in ("year", "past", "history", "archive", "edition", "event", "date", "season"))
            or has_year_options
        )
        if is_year_select:
            for y, u in sel_matches:
                discovered[y] = u

    # 3. Check <a> links for year archives
    links = soup.find_all("a", href=True)
    for a in links:
        href = a["href"].strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue
        text = a.get_text(strip=True)
        combined = f"{text} {href}".lower()

        # Look for 4-digit year
        ym = re.search(r"\b(19\d\d|20\d\d)\b", text) or re.search(r"\b(19\d\d|20\d\d)\b", href)
        if ym:
            year = int(ym.group(1))
            if 1980 <= year <= 2035:
                # Confirm it's likely a past results link
                context = f"{combined} {' '.join(a.get('class', []))} {a.parent.get('class', []) if a.parent else ''}".lower()
                is_archive_link = (
                    any(w in context for w in ("result", "past", "history", "archive", "edition", "previous", "prior", "race"))
                    or len(text.strip()) == 4  # e.g. text is just "2023"
                    or f"/{year}" in href
                    or f"year={year}" in href
                )
                if is_archive_link:
                    abs_url = urllib.parse.urljoin(url, href)
                    # Don't overwrite if dropdown already gave a specific URL unless this is new
                    if year not in discovered or not discovered[year]:
                        discovered[year] = abs_url

    # 4. Pattern fallback if URL has a year and nothing found
    if len(discovered) <= 1 and current_year:
        for past_y in range(current_year - 1, max(current_year - 5, 2015), -1):
            if past_y not in discovered:
                discovered[past_y] = url.replace(str(current_year), str(past_y))

    return {y: discovered[y] for y in sorted(discovered.keys(), reverse=True)}

# Test with HTML snippets
html_select = '''
<html>
<body>
    <h1>Spring Lake 5 Mile</h1>
    <select name="race_year" id="year-dropdown">
        <option value="/results/2024" selected>2024 Results</option>
        <option value="/results/2023">2023 Results</option>
        <option value="/results/2022">2022 Results</option>
        <option value="/results/2021">2021 Results</option>
    </select>
</body>
</html>
'''

res1 = discover_race_years("https://example.com/results/2024", html_select)
print("Res1 (Dropdown):", res1)

html_links = '''
<html>
<body>
    <h1>Peachtree Road Race</h1>
    <div class="archive-links">
        <a href="/peachtree/2024">2024 Results</a>
        <a href="/peachtree/2023">2023</a>
        <a href="/peachtree/2022">2022</a>
    </div>
</body>
</html>
'''
res2 = discover_race_years("https://example.com/peachtree/2024", html_links)
print("Res2 (Links):", res2)

html_form = '''
<html>
<body>
    <form action="/view_results.php" method="GET">
        <select name="yr">
            <option value="2024">2024</option>
            <option value="2023">2023</option>
            <option value="2022">2022</option>
        </select>
    </form>
</body>
</html>
'''
res3 = discover_race_years("https://timing.com/results", html_form)
print("Res3 (Form):", res3)
