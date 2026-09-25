import html
import logging
import os
import re
from datetime import datetime, date
from typing import List, Tuple, Optional
from scrapers.base import JobPosting


def get_fit_marker_color(score: Optional[int]) -> str:
    """Returns Leaflet.awesome-markers color corresponding to 1-10 candidate fit score."""
    if score is None:
        return "blue"
    try:
        s = int(score)
    except (ValueError, TypeError):
        return "blue"

    if s >= 9:
        return "darkgreen"   # Outstanding match (9-10)
    elif s >= 7:
        return "green"       # Strong match (7-8)
    elif s >= 5:
        return "orange"      # Moderate match (5-6)
    elif s >= 3:
        return "lightred"    # Low match (3-4)
    else:
        return "gray"        # Minimal / Screened match (1-2)


def get_fit_score_tier(score: Optional[int]) -> Optional[str]:
    """
    Returns the score tier key for filtering.
    Per user specification, scores 1-2 and unscored are excluded from the filter/legend.
    """
    if score is None:
        return None
    try:
        s = int(score)
    except (ValueError, TypeError):
        return None

    if s >= 9:
        return "tier_9_10"
    elif s >= 7:
        return "tier_7_8"
    elif s >= 5:
        return "tier_5_6"
    elif s >= 3:
        return "tier_3_4"
    return None


MONTH_NAMES = (
    "january|february|march|april|may|june|july|august|september|october|november|december|"
    "jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)


def parse_deadline_info(deadline_str: Optional[str], ref_date: Optional[date] = None) -> Tuple[str, str, Optional[int]]:
    """
    Parses deadline text and computes relative urgency against ref_date (default: today).
    Supports:
      - ISO dates (YYYY-MM-DD)
      - Standard dates (Month DD, YYYY)
      - Dates without explicit year (e.g. 'September 30', 'Nov 1')
      - Dual/multiple deadlines (e.g. 'Priority: Sep 15 / Final: Nov 1')
    Returns (category_key, badge_label, days_difference).
    """
    if not deadline_str:
        return ("open", "🟢 Open / Rolling", None)

    if ref_date is None:
        ref_date = date.today()

    s = str(deadline_str).strip()
    found_dates = []

    # 1. Search for ISO format (YYYY-MM-DD)
    for iso_match in re.finditer(r'\b(\d{4})-(\d{1,2})-(\d{1,2})\b', s):
        try:
            d = date(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))
            found_dates.append(d)
        except ValueError:
            pass

    # 2. Search for Month DD, YYYY formats (e.g., September 30, 2026 or Nov. 1, 2026)
    for m in re.finditer(rf'\b({MONTH_NAMES})[\.]?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b', s, re.IGNORECASE):
        month_str = m.group(1).replace('.', '')
        day_str = m.group(2)
        year_str = m.group(3)
        for fmt in ('%B %d %Y', '%b %d %Y'):
            try:
                d = datetime.strptime(f"{month_str} {day_str} {year_str}", fmt).date()
                found_dates.append(d)
                break
            except ValueError:
                pass

    # 3. Search for Month DD without year (e.g. "September 30", "Nov 1")
    if not found_dates:
        for m in re.finditer(rf'\b({MONTH_NAMES})[\.]?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b', s, re.IGNORECASE):
            month_str = m.group(1).replace('.', '')
            day_str = m.group(2)
            for fmt in ('%B %d', '%b %d'):
                try:
                    dt = datetime.strptime(f"{month_str} {day_str}", fmt)
                    cand_year = ref_date.year
                    if dt.month < ref_date.month and (ref_date.month - dt.month) > 2:
                        cand_year = ref_date.year + 1
                    found_dates.append(date(cand_year, dt.month, dt.day))
                    break
                except ValueError:
                    pass

    if found_dates:
        found_dates = sorted(set(found_dates))
        # Per user specification: If multiple deadlines exist, use the later one
        target_date = found_dates[-1]
        diff = (target_date - ref_date).days
        date_label = target_date.strftime('%b %d')

        if diff < -30:
            return ("past_due", f"🚫 Past Due ({abs(diff)}d ago)", diff)
        elif diff < 0:
            return ("passed", f"⏳ Passed ({abs(diff)}d ago)", diff)
        elif diff <= 7:
            return ("urgent", f"🔥 Urgent: {diff}d left ({date_label})", diff)
        elif diff <= 30:
            return ("closing_soon", f"⚡ Closing: {diff}d left ({date_label})", diff)
        else:
            return ("future", f"📅 Due in {diff}d ({target_date.strftime('%Y-%m-%d')})", diff)

    return ("open", "🟢 Open Until Filled / Rolling", None)


class MapGenerator:
    """Generates an interactive Folium map visualization of hiring university locations."""

    def __init__(self, output_filepath: str = "map.html"):
        self.output_filepath = output_filepath
        self.logger = logging.getLogger("processor.map")

    def generate_map(self, postings: List[JobPosting], include_filtered: bool = False):
        """Create and save the interactive map with color-coded fit scores and 2-way interactive filters."""
        try:
            import folium
            from folium.plugins import MarkerCluster
            import shutil

            if isinstance(postings, dict):
                postings = list(postings.values())

            if not include_filtered:
                postings = [p for p in postings if not p.status.startswith("Filtered")]

            from scrapers.base import sort_postings_by_deadline
            postings = sort_postings_by_deadline(postings)

            # Center map on geographic center of contiguous United States
            job_map = folium.Map(
                location=[39.8283, -98.5795],
                zoom_start=4.5,
                tiles=None,
            )

            # 1. Base Layer Options
            folium.TileLayer(
                tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
                attr="Esri, DeLorme, NAVTEQ, USGS, Intermap, iPC, NRCAN, METI",
                name="Street Map (Esri)",
                control=True,
                overlay=False,
            ).add_to(job_map)

            folium.TileLayer(
                tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
                attr="Esri, HERE, Garmin, &copy; OpenStreetMap contributors",
                name="Light Gray Canvas",
                control=True,
                overlay=False,
            ).add_to(job_map)

            folium.TileLayer(
                tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
                attr="Esri, FAO, NOAA, USGS, EPA",
                name="Topographic (Esri)",
                control=True,
                overlay=False,
            ).add_to(job_map)

            # 2. MarkerCluster
            marker_cluster = MarkerCluster(
                control=False,
                showCoverageOnHover=False,
                spiderfyOnMaxZoom=True,
                maxClusterRadius=40,
            ).add_to(job_map)

            # 3. Dynamic Google Sheet Link
            raw_sheet_id = os.environ.get("GOOGLE_SHEET_ID", "1IYVg0CeSIq3OdUtvluMo7dm6usRFcIn8oeIiwy3y3w4").strip()
            sheet_match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", raw_sheet_id)
            sheet_id = sheet_match.group(1) if sheet_match else raw_sheet_id
            sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"

            # 4. Filter categories setup and count tracking
            score_tiers_def = {
                "tier_9_10": {"label": "9–10: Outstanding Match", "color": "#2d6a4f", "count": 0},
                "tier_7_8": {"label": "7–8: Strong Match", "color": "#52b788", "count": 0},
                "tier_5_6": {"label": "5–6: Moderate Match", "color": "#f77f00", "count": 0},
                "tier_3_4": {"label": "3–4: Low Match", "color": "#fb6f92", "count": 0},
            }

            deadline_cats_def = {
                "urgent": {"label": "🔥 Urgent: ≤ 7 Days", "badge_bg": "#fee2e2", "badge_color": "#991b1b", "count": 0},
                "closing_soon": {"label": "⚡ Closing: 8–30 Days", "badge_bg": "#fef9c3", "badge_color": "#854d0e", "count": 0},
                "future": {"label": "📅 Due in > 30 Days", "badge_bg": "#e0f2fe", "badge_color": "#075985", "count": 0},
                "open": {"label": "🟢 Open / Rolling", "badge_bg": "#f0fdf4", "badge_color": "#166534", "count": 0},
                "passed": {"label": "⏳ Passed (≤ 30d ago)", "badge_bg": "#fee2e2", "badge_color": "#991b1b", "count": 0},
            }

            plotted_count = 0
            marker_js_items = []

            for p in postings:
                if p.latitude is None or p.longitude is None:
                    continue

                # 1) Exclude entries whose status is 'Past Due'
                if p.status == "Past Due":
                    continue

                # 2) Deadline parsing
                cat_key, timing_badge_text, diff = parse_deadline_info(p.deadline)

                # If deadline is past more than 30 days, do NOT show on map
                if cat_key == "past_due" or (diff is not None and diff < -30):
                    continue

                # 3) Fit score tier check (exclude 1-2 / Unscored from map and filter per user instructions)
                score_tier = get_fit_score_tier(p.fit_score)
                if not score_tier:
                    continue

                # Update counts
                score_tiers_def[score_tier]["count"] += 1
                if cat_key in deadline_cats_def:
                    deadline_cats_def[cat_key]["count"] += 1

                safe_title = html.escape(p.title)
                safe_inst = html.escape(p.institution)
                safe_loc = html.escape(p.location)
                safe_deadline = html.escape(p.deadline)
                safe_salary = html.escape(p.salary)
                safe_summary = html.escape(p.summary or "No summary available.")
                safe_topics = html.escape(p.research_topics or "Not specified")
                safe_source = html.escape(p.source)
                safe_link = html.escape(p.link)
                safe_tenure = html.escape(p.tenure_track)
                safe_reason = html.escape(p.fit_reason) if p.fit_reason else ""

                # Fit Score Badge & Marker Color
                marker_color = get_fit_marker_color(p.fit_score)
                fit_badge_html = ""
                if p.fit_score is not None:
                    badge_bg = (
                        "#dcfce7" if p.fit_score >= 8
                        else ("#e0e7ff" if p.fit_score >= 5
                              else ("#fee2e2" if p.fit_score <= 2 else "#fef3c7"))
                    )
                    badge_color = (
                        "#15803d" if p.fit_score >= 8
                        else ("#3730a3" if p.fit_score >= 5
                              else ("#991b1b" if p.fit_score <= 2 else "#92400e"))
                    )
                    fit_badge_html = f"""
                    <span style="font-size: 11px; background: {badge_bg}; color: {badge_color}; padding: 2px 8px; border-radius: 12px; font-weight: 700; margin-left: 4px;">
                        ⭐ {p.fit_score}/10 Fit
                    </span>
                    """

                # Timing pill badge in header
                timing_pill_bg = (
                    "#fee2e2" if cat_key == "passed"
                    else ("#ffedd5" if cat_key == "urgent"
                          else ("#fef9c3" if cat_key == "closing_soon"
                                else ("#e0f2fe" if cat_key == "future" else "#f0fdf4")))
                )
                timing_pill_color = (
                    "#991b1b" if cat_key == "passed"
                    else ("#9a3412" if cat_key == "urgent"
                          else ("#854d0e" if cat_key == "closing_soon"
                                else ("#075985" if cat_key == "future" else "#166534")))
                )
                timing_pill_html = f"""
                <span style="font-size: 11px; background: {timing_pill_bg}; color: {timing_pill_color}; padding: 2px 8px; border-radius: 12px; font-weight: 600;">
                    {html.escape(timing_badge_text)}
                </span>
                """

                fit_reason_html = ""
                if safe_reason:
                    fit_reason_html = f"""<div>🎯 <b>Fit:</b> {safe_reason}</div>"""

                popup_html = f"""
                <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; width: 310px; padding: 4px;">
                    <div style="display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 6px;">
                        <span style="font-size: 11px; background: #e0f2fe; color: #0369a1; padding: 2px 8px; border-radius: 12px; font-weight: 600; text-transform: uppercase;">
                            {safe_source}
                        </span>
                        <span style="font-size: 11px; background: #fef3c7; color: #92400e; padding: 2px 8px; border-radius: 12px; font-weight: 600;">
                            {safe_tenure}
                        </span>
                        {fit_badge_html}
                        {timing_pill_html}
                    </div>
                    <h3 style="margin: 6px 0 4px 0; font-size: 14px; color: #0f172a; line-height: 1.3;">{safe_title}</h3>
                    <p style="margin: 0 0 6px 0; font-size: 13px; font-weight: bold; color: #2563eb;">🏛️ {safe_inst}</p>

                    <div style="font-size: 12px; color: #475569; margin-bottom: 8px; line-height: 1.5;">
                        <div>📍 <b>Location:</b> {safe_loc}</div>
                        <div>🔬 <b>Topics:</b> {safe_topics}</div>
                        {fit_reason_html}
                        <div>📅 <b>Deadline:</b> {safe_deadline} ({html.escape(timing_badge_text)})</div>
                        <div>💰 <b>Salary:</b> {safe_salary}</div>
                    </div>

                    <div style="background: #f8fafc; border-left: 3px solid #3b82f6; padding: 6px 10px; margin-bottom: 10px; font-size: 12px; color: #334155; line-height: 1.4;">
                        <b>Summary:</b><br>{safe_summary}
                    </div>

                    <a href="{safe_link}" target="_blank" style="display: block; text-align: center; background: #2563eb; color: white; text-decoration: none; padding: 7px 10px; border-radius: 6px; font-size: 13px; font-weight: bold;">
                        View Full Job Posting →
                    </a>
                </div>
                """

                iframe = folium.IFrame(popup_html, width=330, height=330)
                popup = folium.Popup(iframe, max_width=360)

                score_label = f"⭐ {p.fit_score}/10" if p.fit_score is not None else "Unscored"
                marker = folium.Marker(
                    location=[p.latitude, p.longitude],
                    popup=popup,
                    tooltip=f"{p.institution}: {p.title} ({score_label})",
                    icon=folium.Icon(color=marker_color, icon="graduation-cap", prefix="fa"),
                )
                marker.add_to(marker_cluster)

                marker_js_items.append({
                    "var_name": marker.get_name(),
                    "score_tier": score_tier,
                    "deadline_cat": cat_key,
                })
                plotted_count += 1

            # 5. Build Unified 2-Way Filter & Legend Control HTML
            cluster_var = marker_cluster.get_name()

            filter_control_html = f"""
            <style>
            @keyframes filterFadeIn {{
                from {{ opacity: 0; transform: scale(0.96) translateY(-4px); }}
                to {{ opacity: 1; transform: scale(1) translateY(0); }}
            }}
            #filter-legend-panel {{
                animation: filterFadeIn 0.2s ease-out;
                max-height: calc(100vh - 50px);
                overflow-y: auto;
                box-sizing: border-box;
            }}
            #filter-legend-panel::-webkit-scrollbar {{
                width: 5px;
            }}
            #filter-legend-panel::-webkit-scrollbar-thumb {{
                background: #cbd5e1;
                border-radius: 3px;
            }}
            #filter-legend-panel::-webkit-scrollbar-thumb:hover {{
                background: #94a3b8;
            }}
            #filter-toggle-pill {{
                animation: filterFadeIn 0.2s ease-out;
                box-sizing: border-box;
            }}
            @media (max-width: 640px) {{
                #filter-legend-panel {{
                    top: 10px !important;
                    right: 10px !important;
                    left: 10px !important;
                    max-width: none !important;
                    width: auto !important;
                    max-height: 82vh !important;
                    padding: 12px 14px !important;
                }}
                #filter-toggle-pill {{
                    top: 10px !important;
                    right: 10px !important;
                    padding: 7px 12px !important;
                    font-size: 11px !important;
                }}
            }}
            </style>

            <!-- Floating Minimized Pill Button -->
            <button id="filter-toggle-pill" onclick="toggleFilterPanel(true)" type="button" style="
                position: fixed;
                top: 25px;
                right: 25px;
                z-index: 9999;
                background: rgba(255, 255, 255, 0.96);
                padding: 8px 14px;
                border-radius: 20px;
                box-shadow: 0 8px 20px rgba(0, 0, 0, 0.15), 0 2px 6px rgba(0, 0, 0, 0.08);
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                font-size: 12px;
                font-weight: 600;
                color: #0f172a;
                border: 1px solid #cbd5e1;
                backdrop-filter: blur(10px);
                cursor: pointer;
                display: none;
                align-items: center;
                gap: 6px;
                user-select: none;
                touch-action: manipulation;
                transition: transform 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
            " onmouseover="this.style.background='#f8fafc'; this.style.boxShadow='0 10px 24px rgba(0,0,0,0.2)';"
              onmouseout="this.style.background='rgba(255, 255, 255, 0.96)'; this.style.boxShadow='0 8px 20px rgba(0, 0, 0, 0.15), 0 2px 6px rgba(0, 0, 0, 0.08)';"
              aria-label="Open filter panel" title="Show filters and legend">
                <span style="font-size: 14px;">🎯</span>
                <span>Filters & Legend</span>
                <span style="background: #e0f2fe; color: #0369a1; padding: 1px 7px; border-radius: 10px; font-size: 11px; font-weight: 700;">
                    <span id="min-filter-count">{plotted_count}</span>
                </span>
                <span style="font-size: 10px; color: #64748b; margin-left: 2px;">▾</span>
            </button>

            <!-- Expanded Filter & Legend Panel -->
            <div id="filter-legend-panel" style="
                position: fixed;
                top: 25px;
                right: 25px;
                z-index: 9999;
                background: rgba(255, 255, 255, 0.96);
                padding: 14px 18px;
                border-radius: 12px;
                box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.15), 0 8px 10px -6px rgba(0, 0, 0, 0.1);
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                font-size: 12px;
                line-height: 1.5;
                border: 1px solid #e2e8f0;
                backdrop-filter: blur(10px);
                max-width: 340px;
                color: #1e293b;
            ">
                <!-- Header with Title, GitHub Link, Google Sheets Link, and Minimize Button -->
                <div style="display: flex; align-items: center; justify-content: space-between; gap: 6px; margin-bottom: 10px; border-bottom: 1px solid #f1f5f9; padding-bottom: 8px; flex-wrap: wrap;">
                    <div style="font-weight: 700; font-size: 12px; color: #0f172a; display: flex; align-items: center; gap: 4px;">
                        <span>🎯 Fit Score Marker Legend & 2-Way Filter</span>
                    </div>
                    <div style="display: flex; align-items: center; gap: 4px; flex-wrap: wrap;">
                        <a href="https://github.com/KBaek0316/AssistantProfessorJobScraper" target="_blank" style="
                            font-size: 11px;
                            background: #24292f;
                            color: white;
                            text-decoration: none;
                            padding: 2px 7px;
                            border-radius: 6px;
                            font-weight: 600;
                            display: inline-flex;
                            align-items: center;
                            gap: 3px;
                            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                            white-space: nowrap;
                            transition: background 0.15s ease;
                        " onmouseover="this.style.background='#0969da';"
                          onmouseout="this.style.background='#24292f';"
                          title="Open GitHub Repository">
                            <svg height="12" viewBox="0 0 16 16" width="12" fill="white" style="vertical-align: text-bottom;"><path d="M8 0c4.42 0 8 3.58 8 8a8.013 8.013 0 0 1-5.45 7.59c-.4.08-.55-.17-.55-.38 0-.27.01-1.13.01-2.2 0-.75-.25-1.23-.54-1.48 1.78-.2 3.65-.88 3.65-3.95 0-.88-.31-1.59-.82-2.15.08-.2.36-1.02-.08-2.12 0 0-.67-.22-2.2.82-.64-.18-1.32-.27-2-.27-.68 0-1.36.09-2 .27-1.53-1.03-2.2-.82-2.2-.82-.44 1.1-.16 1.92-.08 2.12-.51.56-.82 1.28-.82 2.15 0 3.06 1.86 3.75 3.64 3.95-.23.2-.44.55-.51 1.07-.46.21-1.61.55-2.33-.66-.15-.24-.6-.83-1.23-.82-.67.01-.27.38.01.53.34.19.73.9.82 1.13.16.45.68 1.31 2.69.94 0 .67.01 1.3.01 1.49 0 .21-.15.45-.55.38A7.995 7.995 0 0 1 0 8c0-4.42 3.58-8 8-8Z"></path></svg>
                            <span>GitHub</span>
                        </a>
                        <a href="{sheet_url}" target="_blank" style="
                            font-size: 11px;
                            background: #0284c7;
                            color: white;
                            text-decoration: none;
                            padding: 2px 7px;
                            border-radius: 6px;
                            font-weight: 600;
                            display: inline-flex;
                            align-items: center;
                            gap: 3px;
                            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                            white-space: nowrap;
                        " title="Open Google Sheet">
                            📊 Sheets ↗
                        </a>
                        <button id="filter-collapse-btn" onclick="toggleFilterPanel(false)" type="button" style="
                            font-size: 11px;
                            background: #f1f5f9;
                            color: #475569;
                            border: 1px solid #cbd5e1;
                            padding: 2px 7px;
                            border-radius: 6px;
                            font-weight: 600;
                            display: inline-flex;
                            align-items: center;
                            gap: 3px;
                            cursor: pointer;
                            white-space: nowrap;
                            transition: all 0.15s ease;
                        " onmouseover="this.style.background='#e2e8f0'; this.style.color='#0f172a';"
                          onmouseout="this.style.background='#f1f5f9'; this.style.color='#475569';"
                          aria-label="Minimize filter panel" title="Minimize filter panel">
                            <span>−</span>
                            <span>Hide</span>
                        </button>
                    </div>
                </div>

                <!-- Section 1: Candidate Fit Score Filter -->
                <div style="margin-bottom: 10px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                        <span style="font-weight: 700; color: #334155; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px;">Fit Score</span>
                        <div style="font-size: 10px; display: flex; gap: 6px;">
                            <a href="javascript:void(0)" onclick="setScoreAll(true)" style="color: #2563eb; text-decoration: none; font-weight: 600;">All</a>
                            <span style="color: #cbd5e1;">|</span>
                            <a href="javascript:void(0)" onclick="setScoreAll(false)" style="color: #64748b; text-decoration: none;">None</a>
                        </div>
                    </div>
                    <div style="display: flex; flex-direction: column; gap: 4px;">
                        <label style="display: flex; align-items: center; gap: 7px; cursor: pointer; user-select: none;">
                            <input type="checkbox" class="score-filter-cb" value="tier_9_10" checked onchange="applyFilters()" style="cursor: pointer;">
                            <span style="width: 10px; height: 10px; border-radius: 50%; background: #2d6a4f; display: inline-block;"></span>
                            <span style="flex-grow: 1;"><b>9–10:</b> Outstanding Match</span>
                            <span style="color: #64748b; font-size: 11px; font-weight: 600;">({score_tiers_def['tier_9_10']['count']})</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 7px; cursor: pointer; user-select: none;">
                            <input type="checkbox" class="score-filter-cb" value="tier_7_8" checked onchange="applyFilters()" style="cursor: pointer;">
                            <span style="width: 10px; height: 10px; border-radius: 50%; background: #52b788; display: inline-block;"></span>
                            <span style="flex-grow: 1;"><b>7–8:</b> Strong Match</span>
                            <span style="color: #64748b; font-size: 11px; font-weight: 600;">({score_tiers_def['tier_7_8']['count']})</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 7px; cursor: pointer; user-select: none;">
                            <input type="checkbox" class="score-filter-cb" value="tier_5_6" checked onchange="applyFilters()" style="cursor: pointer;">
                            <span style="width: 10px; height: 10px; border-radius: 50%; background: #f77f00; display: inline-block;"></span>
                            <span style="flex-grow: 1;"><b>5–6:</b> Moderate Match</span>
                            <span style="color: #64748b; font-size: 11px; font-weight: 600;">({score_tiers_def['tier_5_6']['count']})</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 7px; cursor: pointer; user-select: none;">
                            <input type="checkbox" class="score-filter-cb" value="tier_3_4" checked onchange="applyFilters()" style="cursor: pointer;">
                            <span style="width: 10px; height: 10px; border-radius: 50%; background: #fb6f92; display: inline-block;"></span>
                            <span style="flex-grow: 1;"><b>3–4:</b> Low Match</span>
                            <span style="color: #64748b; font-size: 11px; font-weight: 600;">({score_tiers_def['tier_3_4']['count']})</span>
                        </label>
                    </div>
                </div>

                <!-- Section 2: Deadline Urgency Filter -->
                <div style="margin-bottom: 10px; border-top: 1px solid #f1f5f9; padding-top: 8px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                        <span style="font-weight: 700; color: #334155; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px;">Deadline Urgency</span>
                        <div style="font-size: 10px; display: flex; gap: 6px;">
                            <a href="javascript:void(0)" onclick="setDeadlineAll(true)" style="color: #2563eb; text-decoration: none; font-weight: 600;">All</a>
                            <span style="color: #cbd5e1;">|</span>
                            <a href="javascript:void(0)" onclick="setDeadlineAll(false)" style="color: #64748b; text-decoration: none;">None</a>
                        </div>
                    </div>
                    <div style="display: flex; flex-direction: column; gap: 4px;">
                        <label style="display: flex; align-items: center; gap: 7px; cursor: pointer; user-select: none;">
                            <input type="checkbox" class="dl-filter-cb" value="urgent" checked onchange="applyFilters()" style="cursor: pointer;">
                            <span style="flex-grow: 1;">🔥 Deadline ≤ 7 Days</span>
                            <span style="color: #64748b; font-size: 11px; font-weight: 600;">({deadline_cats_def['urgent']['count']})</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 7px; cursor: pointer; user-select: none;">
                            <input type="checkbox" class="dl-filter-cb" value="closing_soon" checked onchange="applyFilters()" style="cursor: pointer;">
                            <span style="flex-grow: 1;">⚡ Deadline in 8–30 Days</span>
                            <span style="color: #64748b; font-size: 11px; font-weight: 600;">({deadline_cats_def['closing_soon']['count']})</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 7px; cursor: pointer; user-select: none;">
                            <input type="checkbox" class="dl-filter-cb" value="future" checked onchange="applyFilters()" style="cursor: pointer;">
                            <span style="flex-grow: 1;">📅 Deadline > 30 Days</span>
                            <span style="color: #64748b; font-size: 11px; font-weight: 600;">({deadline_cats_def['future']['count']})</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 7px; cursor: pointer; user-select: none;">
                            <input type="checkbox" class="dl-filter-cb" value="open" checked onchange="applyFilters()" style="cursor: pointer;">
                            <span style="flex-grow: 1;">🟢 Open Until Filled / Rolling</span>
                            <span style="color: #64748b; font-size: 11px; font-weight: 600;">({deadline_cats_def['open']['count']})</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 7px; cursor: pointer; user-select: none;">
                            <input type="checkbox" class="dl-filter-cb" value="passed" checked onchange="applyFilters()" style="cursor: pointer;">
                            <span style="flex-grow: 1;">⏳ Passed (≤ 30d ago)</span>
                            <span style="color: #64748b; font-size: 11px; font-weight: 600;">({deadline_cats_def['passed']['count']})</span>
                        </label>
                    </div>
                </div>

                <!-- Footer Summary Counter -->
                <div style="border-top: 1px solid #f1f5f9; padding-top: 8px; display: flex; justify-content: space-between; align-items: center; font-size: 11px; color: #475569;">
                    <span>Showing: <b id="visible-job-count" style="color: #0f172a;">{plotted_count}</b> / {plotted_count}</span>
                    <div style="display: flex; gap: 8px; align-items: center;">
                        <a href="javascript:void(0)" onclick="resetAllFilters()" style="color: #2563eb; text-decoration: none; font-weight: 600;">Reset</a>
                        <button onclick="toggleFilterPanel(false)" type="button" style="
                            background: #eff6ff;
                            color: #2563eb;
                            border: 1px solid #bfdbfe;
                            padding: 2px 7px;
                            border-radius: 4px;
                            font-size: 10px;
                            font-weight: 600;
                            cursor: pointer;
                        " title="Hide filter panel and view map">Map ✕</button>
                    </div>
                </div>

                <!-- Attribution Margin -->
                <div style="margin-top: 8px; padding-top: 6px; border-top: 1px dashed #e2e8f0; display: flex; justify-content: space-between; align-items: center; font-size: 10px; color: #94a3b8;">
                    <span>Developed by <a href="https://github.com/KBaek0316" target="_blank" style="color: #475569; font-weight: 600; text-decoration: none;">Kwangho Baek</a></span>
                    <a href="https://github.com/KBaek0316/AssistantProfessorJobScraper" target="_blank" style="color: #64748b; text-decoration: none;">★ Star on GitHub</a>
                </div>
            </div>
            """
            job_map.get_root().html.add_child(folium.Element(filter_control_html))

            # 6. Build JavaScript for real-time 2-Way Filtering and Panel Toggle
            js_items_str = ",\n".join(
                f"{{ marker: {item['var_name']}, scoreTier: '{item['score_tier']}', deadlineCat: '{item['deadline_cat']}' }}"
                for item in marker_js_items
            )

            filter_script = f"""
            <script>
            (function() {{
                var clusterGroup = null;
                var allMarkers = [];

                function initFilterSystem() {{
                    if (typeof {cluster_var} === 'undefined') {{
                        setTimeout(initFilterSystem, 100);
                        return;
                    }}
                    clusterGroup = {cluster_var};
                    allMarkers = [
                        {js_items_str}
                    ];
                    initPanelState();
                }}

                window.toggleFilterPanel = function(show) {{
                    var panel = document.getElementById('filter-legend-panel');
                    var pill = document.getElementById('filter-toggle-pill');
                    if (!panel || !pill) return;

                    if (show) {{
                        panel.style.display = 'block';
                        pill.style.display = 'none';
                        try {{ localStorage.setItem('map_filter_collapsed', 'false'); }} catch (e) {{}}
                    }} else {{
                        panel.style.display = 'none';
                        pill.style.display = 'inline-flex';
                        try {{ localStorage.setItem('map_filter_collapsed', 'true'); }} catch (e) {{}}
                    }}
                }};

                function initPanelState() {{
                    var saved = null;
                    try {{
                        saved = localStorage.getItem('map_filter_collapsed');
                    }} catch (e) {{}}

                    // On mobile screens (<= 768px), default to collapsed so map is visible
                    var isMobile = (window.innerWidth <= 768);
                    var shouldCollapse = (saved !== null) ? (saved === 'true') : isMobile;
                    window.toggleFilterPanel(!shouldCollapse);
                }}

                window.applyFilters = function() {{
                    if (!clusterGroup) return;

                    var scoreCheckboxes = document.querySelectorAll('.score-filter-cb:checked');
                    var activeScores = Array.from(scoreCheckboxes).map(function(cb) {{ return cb.value; }});

                    var dlCheckboxes = document.querySelectorAll('.dl-filter-cb:checked');
                    var activeDeadlines = Array.from(dlCheckboxes).map(function(cb) {{ return cb.value; }});

                    var visibleCount = 0;
                    allMarkers.forEach(function(item) {{
                        var matchScore = activeScores.indexOf(item.scoreTier) !== -1;
                        var matchDeadline = activeDeadlines.indexOf(item.deadlineCat) !== -1;

                        if (matchScore && matchDeadline) {{
                            if (!clusterGroup.hasLayer(item.marker)) {{
                                clusterGroup.addLayer(item.marker);
                            }}
                            visibleCount++;
                        }} else {{
                            if (clusterGroup.hasLayer(item.marker)) {{
                                clusterGroup.removeLayer(item.marker);
                            }}
                        }}
                    }});

                    var counterElem = document.getElementById('visible-job-count');
                    if (counterElem) {{
                        counterElem.innerText = visibleCount;
                    }}
                    var minCounterElem = document.getElementById('min-filter-count');
                    if (minCounterElem) {{
                        minCounterElem.innerText = visibleCount;
                    }}
                }};

                window.setScoreAll = function(val) {{
                    document.querySelectorAll('.score-filter-cb').forEach(function(cb) {{
                        cb.checked = val;
                    }});
                    applyFilters();
                }};

                window.setDeadlineAll = function(val) {{
                    document.querySelectorAll('.dl-filter-cb').forEach(function(cb) {{
                        cb.checked = val;
                    }});
                    applyFilters();
                }};

                window.resetAllFilters = function() {{
                    document.querySelectorAll('.score-filter-cb').forEach(function(cb) {{ cb.checked = true; }});
                    document.querySelectorAll('.dl-filter-cb').forEach(function(cb) {{ cb.checked = true; }});
                    applyFilters();
                }};

                if (document.readyState === 'complete' || document.readyState === 'interactive') {{
                    initFilterSystem();
                }} else {{
                    window.addEventListener('DOMContentLoaded', initFilterSystem);
                }}
            }})();
            </script>
            """
            job_map.get_root().html.add_child(folium.Element(filter_script))

            # 7. Add LayerControl for base layers (placed bottom-left to avoid colliding with upper-right filter)
            folium.LayerControl(collapsed=True, position='bottomleft').add_to(job_map)
            job_map.save(self.output_filepath)
            self.logger.info(f"Generated interactive map with {plotted_count} locations across 2-way filters at {self.output_filepath}")

            # Also mirror to index.html if saving map.html for direct root hosting on GitHub Pages
            if os.path.basename(self.output_filepath) == "map.html":
                try:
                    index_path = os.path.join(os.path.dirname(self.output_filepath) or ".", "index.html")
                    shutil.copyfile(self.output_filepath, index_path)
                    self.logger.info(f"Mirrored map to {index_path} for GitHub Pages")
                except Exception as mirror_err:
                    self.logger.warning(f"Could not mirror map to index.html: {mirror_err}")

        except ImportError:
            self.logger.warning("folium not installed. Map generation skipped.")
        except Exception as e:
            self.logger.error(f"Error generating interactive map: {e}", exc_info=True)
