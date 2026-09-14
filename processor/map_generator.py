import html
import logging
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
        future_dates = [d for d in found_dates if (d - ref_date).days >= 0]
        target_date = future_dates[0] if future_dates else found_dates[-1]
        diff = (target_date - ref_date).days
        date_label = target_date.strftime('%b %d')

        if diff < 0:
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
        """Create and save the interactive map with color-coded fit scores and deadline filters."""
        try:
            import folium
            from folium.plugins import MarkerCluster, FeatureGroupSubGroup
            import os
            import shutil

            if isinstance(postings, dict):
                postings = list(postings.values())

            if not include_filtered:
                postings = [p for p in postings if not p.status.startswith("Filtered")]

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

            # 2. MarkerCluster: aggregates nearby markers with job count badges when zoomed out
            marker_cluster = MarkerCluster(
                control=False,
                showCoverageOnHover=False,
                spiderfyOnMaxZoom=True,
                maxClusterRadius=40,
            ).add_to(job_map)

            # 3. Deadline Categories Definitions
            categories = {
                "urgent": {"label": "🔥 Deadline ≤ 7 Days", "markers": []},
                "closing_soon": {"label": "⚡ Deadline in 8–30 Days", "markers": []},
                "future": {"label": "📅 Deadline > 30 Days", "markers": []},
                "open": {"label": "🟢 Open Until Filled / Rolling", "markers": []},
                "passed": {"label": "⏳ Deadline / Priority Passed", "markers": []},
            }

            plotted_count = 0

            for p in postings:
                if p.latitude is None or p.longitude is None:
                    continue

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

                # Deadline parsing & timing badge
                cat_key, timing_badge_text, _ = parse_deadline_info(p.deadline)

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

                categories[cat_key]["markers"].append(marker)
                plotted_count += 1

            # 4. Attach each deadline category to marker_cluster via FeatureGroupSubGroup so they can be toggled
            for cat_key, cat_data in categories.items():
                count = len(cat_data["markers"])
                group_name = f"{cat_data['label']} ({count})"
                group = FeatureGroupSubGroup(marker_cluster, name=group_name, show=True).add_to(job_map)
                for marker in cat_data["markers"]:
                    marker.add_to(group)

            # 5. Add floating Fit Score Color Legend
            legend_html = """
            <div style="
                position: fixed;
                bottom: 25px;
                left: 25px;
                z-index: 9999;
                background: rgba(255, 255, 255, 0.95);
                padding: 12px 16px;
                border-radius: 10px;
                box-shadow: 0 4px 15px rgba(0, 0, 0, 0.15);
                font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
                font-size: 12px;
                line-height: 1.5;
                border: 1px solid #e2e8f0;
                backdrop-filter: blur(8px);
                pointer-events: auto;
                max-width: 250px;
            ">
                <div style="font-weight: 700; font-size: 13px; color: #0f172a; margin-bottom: 8px; display: flex; align-items: center; gap: 6px;">
                    <span>🎯 Fit Score Marker Legend</span>
                </div>
                <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
                    <span style="display: inline-block; width: 12px; height: 12px; border-radius: 50%; background: #2d6a4f; border: 1px solid rgba(0,0,0,0.2);"></span>
                    <span><b>9–10:</b> Outstanding Match</span>
                </div>
                <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
                    <span style="display: inline-block; width: 12px; height: 12px; border-radius: 50%; background: #52b788; border: 1px solid rgba(0,0,0,0.2);"></span>
                    <span><b>7–8:</b> Strong Match</span>
                </div>
                <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
                    <span style="display: inline-block; width: 12px; height: 12px; border-radius: 50%; background: #f77f00; border: 1px solid rgba(0,0,0,0.2);"></span>
                    <span><b>5–6:</b> Moderate Match</span>
                </div>
                <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
                    <span style="display: inline-block; width: 12px; height: 12px; border-radius: 50%; background: #fb6f92; border: 1px solid rgba(0,0,0,0.2);"></span>
                    <span><b>3–4:</b> Low Match</span>
                </div>
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="display: inline-block; width: 12px; height: 12px; border-radius: 50%; background: #94a3b8; border: 1px solid rgba(0,0,0,0.2);"></span>
                    <span><b>1–2 / Unscored:</b> Minimal / Other</span>
                </div>
            </div>
            """
            job_map.get_root().html.add_child(folium.Element(legend_html))

            # 6. Add LayerControl with expanded view so deadline filters are immediately visible
            folium.LayerControl(collapsed=False).add_to(job_map)
            job_map.save(self.output_filepath)
            self.logger.info(f"Generated interactive map with {plotted_count} locations across deadline filters at {self.output_filepath}")

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
