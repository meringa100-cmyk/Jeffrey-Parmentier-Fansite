#!/usr/bin/env python3
"""Refresh JP Fans' static agenda from Jeffrey Parmentier's official agenda."""
from datetime import date, datetime
from html import escape
from pathlib import Path
import re
import sys
import urllib.request

from bs4 import BeautifulSoup

SOURCE = "https://jeffreyparmentier.nl/agenda/"
MONTHS = {
    "jan": 1, "januari": 1, "feb": 2, "februari": 2, "mrt": 3, "maart": 3,
    "apr": 4, "april": 4, "mei": 5, "jun": 6, "juni": 6, "jul": 7,
    "juli": 7, "aug": 8, "augustus": 8, "sep": 9, "september": 9,
    "okt": 10, "oktober": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
DATE_RE = re.compile(r"\b(\d{1,2})\s+(jan(?:uari)?|feb(?:ruari)?|mrt|maart|apr(?:il)?|mei|jun(?:i)?|jul(?:i)?|aug(?:ustus)?|sep(?:tember)?|okt(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{4})\b", re.I)

def parse_events(html):
    soup = BeautifulSoup(html, "html.parser")
    events = []
    seen = set()
    for heading in soup.find_all("h3"):
        title = " ".join(heading.get_text(" ", strip=True).split())
        if not title:
            continue
        container = None
        for ancestor in heading.parents:
            if getattr(ancestor, "name", None) not in ("div", "article", "li", "section"):
                continue
            text = " ".join(ancestor.get_text(" ", strip=True).split())
            if len(ancestor.find_all("h3")) != 1 or "|" not in text or not DATE_RE.search(text):
                continue
            container = text
            break
        if not container:
            continue
        match = DATE_RE.search(container)
        day, month_word, year = match.groups()
        month_key = month_word.lower()
        month = MONTHS.get(month_key)
        if not month:
            continue
        try:
            event_date = date(int(year), month, int(day))
        except ValueError:
            continue
        after_title = container.split(title, 1)[1] if title in container else ""
        chunks = [re.sub(r"\s+", " ", part).strip(" ·|") for part in after_title.split("|")]
        chunks = [part for part in chunks if part]
        if len(chunks) < 2:
            continue
        venue, city = chunks[-2], chunks[-1]
        venue = re.sub(r"^(Tickets?|Koop tickets)\s*", "", venue, flags=re.I).strip(" ·")
        city = re.sub(r"^(Tickets?|Koop tickets)\s*", "", city, flags=re.I).strip(" ·")
        if not venue or not city:
            continue
        key = (event_date.isoformat(), title.casefold(), venue.casefold(), city.casefold())
        if key in seen:
            continue
        seen.add(key)
        events.append({"date": event_date, "title": title, "venue": venue, "city": city})
    return sorted(events, key=lambda item: (item["date"], item["title"].casefold()))

def main():
    request = urllib.request.Request(SOURCE, headers={"User-Agent": "JP-Fans-AgendaBot/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        source_html = response.read().decode("utf-8", errors="replace")
    events = parse_events(source_html)
    if len(events) < 3:
        raise RuntimeError(f"Only {len(events)} events parsed; refusing to overwrite the agenda.")
    today = datetime.now().astimezone().date()
    future = [event for event in events if event["date"] >= today]
    if not future:
        raise RuntimeError("No future events found; refusing to replace the highlighted next event.")
    next_event = future[0]
    path = Path("index.html")
    html = path.read_text(encoding="utf-8")
    start = html.find('<section id="agenda"')
    if start < 0:
        raise RuntimeError("Agenda section not found in index.html.")
    end_tag = "</section>"
    end = html.find(end_tag, start)
    if end < 0:
        raise RuntimeError("Agenda section closing tag not found.")
    end += len(end_tag)

    month_names = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]
    rows = []
    for event in future:
        d = event["date"]
        label = f"{d.day:02d} {month_names[d.month - 1].upper()} {d.year}"
        is_next = event is next_event
        badge = ' <span class="badge">VOLGEND</span>' if is_next else ""
        cls = ' class="show next"' if is_next else ' class="show"'
        rows.append(
            f'<div{cls}><div class="date">{label}{badge}</div>'
            f'<div><h3>{escape(event["title"])}</h3>'
            f'<p>{escape(event["venue"])} · {escape(event["city"])}</p></div></div>'
        )
    checked = today.strftime("%-d %B %Y")
    agenda = (
        '<section id="agenda" class="section dark"><div class="eyebrow">AGENDA</div>'
        '<h2>Komende optredens</h2>'
        f'<p class="copy">Automatisch bijgewerkt op {escape(checked)} vanaf de '
        f'<a href="{SOURCE}" target="_blank" rel="noopener">officiële agenda van Jeffrey</a>. '
        'Controleer bij twijfel altijd de officiële bron.</p>'
        '<div class="shows">\n' + "\n".join(rows) + '\n</div></section>'
    )
    updated = html[:start] + agenda + html[end:]
    hero_pattern = re.compile(
        r'(<div class="next-gig">.*?<strong>).*?(</strong><small>).*?(</small><b id="countdown">)',
        re.S,
    )
    date_label = f'{next_event["date"].day} {month_names[next_event["date"].month - 1]} {next_event["date"].year}'
    hero_replacement = (
        r'\g<1>' + escape(next_event["title"]) + r'\g<2>'
        + escape(date_label + " · " + next_event["city"]) + r'\g<3>'
    )
    updated, hero_count = hero_pattern.subn(hero_replacement, updated, count=1)
    if hero_count != 1:
        raise RuntimeError("Featured next-event card not found; refusing to publish.")
    countdown_pattern = re.compile(r"function countdown\(\)\{.*?\}countdown\(\);setInterval\(countdown,60000\);", re.S)
    d = next_event["date"]
    # Use local midnight on the event date: the counter is a date countdown, not an asserted showtime.
    countdown_code = (
        "function countdown(){const el=document.getElementById('countdown');if(!el)return;"
        f"const d=new Date('{d.isoformat()}T00:00:00').getTime(),e=d-Date.now();"
        "if(e<=0){el.textContent='🎉 Vandaag!'}else{const days=Math.floor(e/86400000),"
        "h=Math.floor(e%86400000/3600000),m=Math.floor(e%3600000/60000);"
        "el.textContent=days+' dagen · '+h+' uur · '+m+' min'}}countdown();setInterval(countdown,60000);"
    )
    updated, countdown_count = countdown_pattern.subn(lambda _: countdown_code, updated, count=1)
    if countdown_count != 1:
        raise RuntimeError("Countdown function not found; refusing to publish.")
    if updated != html:
        path.write_text(updated, encoding="utf-8")
        print(f"Updated {len(future)} upcoming events; next: {next_event['date']} — {next_event['title']}.")
    else:
        print(f"Agenda already current ({len(future)} future events).")

if __name__ == "__main__":
    main()
