import html
import logging
from typing import List
from scrapers.base import JobPosting


class MapGenerator:
    """Generates an interactive Folium map visualization of hiring university locations."""

    def __init__(self, output_filepath: str = "map.html"):
        self.output_filepath = output_filepath
        self.logger = logging.getLogger("processor.map")

    def generate_map(self, postings: List[JobPosting], include_filtered: bool = False):
        """Create and save the interactive map."""
        try:
            import folium
            from folium.plugins import MarkerCluster

            if not include_filtered:
                postings = [p for p in postings if not p.status.startswith("Filtered")]

            # Center map on geographic center of contiguous United States
            job_map = folium.Map(
                location=[39.8283, -98.5795],
                zoom_start=4.5,
                tiles=None,
            )

            # Add Esri World Street Map as primary basemap (reliable, high-uptime CDN, never blocked)
            folium.TileLayer(
                tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
                attr="Esri, DeLorme, NAVTEQ, USGS, Intermap, iPC, NRCAN, METI",
                name="Street Map (Esri)",
                control=True,
                overlay=False,
            ).add_to(job_map)

            # Add Esri Light Gray Canvas (clean, modern, minimalist)
            folium.TileLayer(
                tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
                attr="Esri, HERE, Garmin, &copy; OpenStreetMap contributors",
                name="Light Gray Canvas",
                control=True,
                overlay=False,
            ).add_to(job_map)

            # Add Esri Topographic layer
            folium.TileLayer(
                tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
                attr="Esri, FAO, NOAA, USGS, EPA",
                name="Topographic (Esri)",
                control=True,
                overlay=False,
            ).add_to(job_map)

            marker_cluster = MarkerCluster(name="Universities").add_to(job_map)
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

                # Fit Score Badge
                fit_badge_html = ""
                if p.fit_score is not None:
                    badge_bg = "#dcfce7" if p.fit_score >= 8 else ("#e0e7ff" if p.fit_score >= 5 else "#f3f4f6")
                    badge_color = "#15803d" if p.fit_score >= 8 else ("#3730a3" if p.fit_score >= 5 else "#4b5563")
                    fit_badge_html = f"""
                    <span style="font-size: 11px; background: {badge_bg}; color: {badge_color}; padding: 2px 8px; border-radius: 12px; font-weight: 700; margin-left: 4px;">
                        ⭐ {p.fit_score}/10 Fit
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
                    </div>
                    <h3 style="margin: 6px 0 4px 0; font-size: 14px; color: #0f172a; line-height: 1.3;">{safe_title}</h3>
                    <p style="margin: 0 0 6px 0; font-size: 13px; font-weight: bold; color: #2563eb;">🏛️ {safe_inst}</p>
                    
                    <div style="font-size: 12px; color: #475569; margin-bottom: 8px; line-height: 1.5;">
                        <div>📍 <b>Location:</b> {safe_loc}</div>
                        <div>🔬 <b>Topics:</b> {safe_topics}</div>
                        {fit_reason_html}
                        <div>📅 <b>Deadline:</b> {safe_deadline}</div>
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

                folium.Marker(
                    location=[p.latitude, p.longitude],
                    popup=popup,
                    tooltip=f"{p.institution}: {p.title}",
                    icon=folium.Icon(color="blue", icon="graduation-cap", prefix="fa"),
                ).add_to(marker_cluster)

                plotted_count += 1

            folium.LayerControl().add_to(job_map)
            job_map.save(self.output_filepath)
            self.logger.info(f"Generated interactive map with {plotted_count} locations at {self.output_filepath}")

        except ImportError:
            self.logger.warning("folium not installed. Map generation skipped.")
        except Exception as e:
            self.logger.error(f"Error generating interactive map: {e}", exc_info=True)
