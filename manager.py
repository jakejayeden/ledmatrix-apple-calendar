"""Apple Calendar (iCalendar/ICS) plugin for LEDMatrix.

Fetches a published Apple/iCloud calendar feed and renders upcoming events on
small LED matrices such as 128x32 panels.
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

import requests
from dateutil.rrule import rrulestr
from icalendar import Calendar
from PIL import Image, ImageDraw, ImageFont

from src.plugin_system.base_plugin import BasePlugin, VegasDisplayMode


class AppleCalendarPlugin(BasePlugin):
    """Display upcoming events from an Apple/iCloud published ICS feed."""

    DEFAULT_HEADER_COLOR = "#149FD9"

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        self.events: List[Dict[str, Any]] = []
        self.current_event_index = 0
        self.last_fetch = 0.0
        self.last_rotation = time.time()
        self._read_settings(config)
        self._load_fonts()

    @staticmethod
    def _parse_hex_color(value: Any, fallback=(20, 159, 217)):
        """Convert #RRGGBB (or RRGGBB) to an RGB tuple."""
        if not isinstance(value, str):
            return fallback
        hex_value = value.strip().lstrip("#")
        if len(hex_value) != 6:
            return fallback
        try:
            return tuple(int(hex_value[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            return fallback

    def _read_settings(self, config: Dict[str, Any]) -> None:
        self.calendar_url = (config.get("calendar_url") or "").strip()
        self.max_events = int(config.get("max_events", 5))
        self.show_all_day = bool(config.get("show_all_day_events", True))
        self.update_interval = float(config.get("update_interval", 900))
        self.rotation_interval = float(config.get("event_rotation_interval", 10))
        self.lookahead_days = int(config.get("lookahead_days", 30))
        self.request_timeout = float(config.get("request_timeout", 15))
        self.timezone_name = config.get("timezone", "Europe/London")
        self.header_color_hex = config.get("header_color", self.DEFAULT_HEADER_COLOR)
        self.header_color = self._parse_hex_color(self.header_color_hex)
        try:
            self.local_tz = ZoneInfo(self.timezone_name)
        except Exception:
            self.logger.warning("Invalid timezone %s; falling back to UTC", self.timezone_name)
            self.local_tz = timezone.utc

    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        super().on_config_change(new_config)
        self._read_settings(self.config)
        self.last_fetch = 0.0
        self.last_rotation = time.time()
        self._load_fonts()

    def _load_fonts(self) -> None:
        self.header_font = ImageFont.load_default()
        self.title_font = ImageFont.load_default()
        try:
            fm = getattr(self.plugin_manager, "font_manager", None)
            if fm:
                fm.register_manager_font(
                    manager_id=self.plugin_id,
                    element_key=f"{self.plugin_id}.header",
                    family="four_by_six",
                    size_px=8,
                    color=self.header_color,
                )
                fm.register_manager_font(
                    manager_id=self.plugin_id,
                    element_key=f"{self.plugin_id}.title",
                    family="press_start",
                    size_px=8,
                    color=(255, 255, 255),
                )
        except Exception as exc:
            self.logger.debug("Could not register fonts: %s", exc)

    def _normalise_dt(self, value: Any) -> datetime:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=self.local_tz)
            return value.astimezone(self.local_tz)
        return datetime(value.year, value.month, value.day, tzinfo=self.local_tz)

    def _expand_event(self, component, window_start: datetime,
                      window_end: datetime) -> List[Dict[str, Any]]:
        dtstart_raw = component.decoded("DTSTART")
        all_day = not isinstance(dtstart_raw, datetime)
        if all_day and not self.show_all_day:
            return []

        start = self._normalise_dt(dtstart_raw)
        dtend_prop = component.get("DTEND")
        if dtend_prop:
            end = self._normalise_dt(dtend_prop.dt)
        else:
            end = start + (timedelta(days=1) if all_day else timedelta(hours=1))

        title = str(component.get("SUMMARY", "Untitled event"))
        uid = str(component.get("UID", ""))
        duration = max(end - start, timedelta(0))

        recurrence = component.get("RRULE")
        starts = [start]
        if recurrence:
            try:
                rule_text = recurrence.to_ical().decode("utf-8")
                rule = rrulestr(rule_text, dtstart=start)
                starts = list(rule.between(window_start - duration, window_end, inc=True))
            except Exception as exc:
                self.logger.warning("Could not expand recurring event %s: %s", title, exc)
                starts = [start]

        rdates = component.get("RDATE")
        if rdates:
            if not isinstance(rdates, list):
                rdates = [rdates]
            for rdate in rdates:
                for item in rdate.dts:
                    starts.append(self._normalise_dt(item.dt))

        excluded = set()
        exdates = component.get("EXDATE")
        if exdates:
            if not isinstance(exdates, list):
                exdates = [exdates]
            for exdate in exdates:
                for item in exdate.dts:
                    excluded.add(self._normalise_dt(item.dt))

        result = []
        seen = set()
        for occurrence_start in starts:
            occurrence_start = self._normalise_dt(occurrence_start)
            if occurrence_start in excluded or occurrence_start in seen:
                continue
            seen.add(occurrence_start)
            occurrence_end = occurrence_start + duration
            if occurrence_end < window_start or occurrence_start > window_end:
                continue
            result.append({
                "uid": uid,
                "title": title,
                "start": occurrence_start,
                "end": occurrence_end,
                "all_day": all_day,
            })
        return result

    def _fetch_events(self) -> None:
        if not self.calendar_url:
            self.logger.warning("Apple Calendar URL is not configured")
            self.events = []
            return

        now = datetime.now(self.local_tz)
        window_end = now + timedelta(days=self.lookahead_days)
        fetch_url = self.calendar_url
        if fetch_url.lower().startswith("webcal://"):
            fetch_url = "https://" + fetch_url[len("webcal://"):]

        response = requests.get(
            fetch_url,
            timeout=self.request_timeout,
            headers={"User-Agent": "LEDMatrix-Apple-Calendar/1.0"},
        )
        response.raise_for_status()
        calendar = Calendar.from_ical(response.content)

        events: List[Dict[str, Any]] = []
        for component in calendar.walk("VEVENT"):
            try:
                events.extend(self._expand_event(component, now, window_end))
            except Exception as exc:
                self.logger.warning("Skipping malformed calendar event: %s", exc)

        events = [event for event in events if event["end"] >= now]
        events.sort(key=lambda event: event["start"])
        self.events = events[: self.max_events]
        self.current_event_index = min(
            self.current_event_index, max(len(self.events) - 1, 0)
        )

    def update(self) -> None:
        """Refresh calendar data when the plugin scheduler calls update()."""
        now = time.time()
        if now - self.last_fetch >= self.update_interval:
            try:
                self._fetch_events()
                self.last_fetch = now
            except Exception as exc:
                self.logger.error("Failed to refresh Apple Calendar feed: %s", exc)
                self.last_fetch = now

    def _wrap_title(self, draw: ImageDraw.ImageDraw, text: str,
                    width: int, max_lines: int = 2) -> List[str]:
        words = text.split()
        lines: List[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if draw.textbbox((0, 0), candidate, font=self.title_font)[2] <= width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
                if len(lines) >= max_lines:
                    break
        if current and len(lines) < max_lines:
            lines.append(current)
        if len(lines) == max_lines and lines:
            while (draw.textbbox((0, 0), lines[-1], font=self.title_font)[2] > width
                   and len(lines[-1]) > 1):
                lines[-1] = lines[-1][:-1]
        return lines[:max_lines]

    def display(self, force_clear: bool = False) -> None:
        width = getattr(self.display_manager, "width", 128)
        height = getattr(self.display_manager, "height", 32)
        image = Image.new("RGB", (width, height), (0, 0, 0))
        draw = ImageDraw.Draw(image)

        if not self.calendar_url:
            draw.text((1, 2), "Apple Calendar", font=self.header_font,
                      fill=self.header_color)
            draw.text((1, 15), "Set calendar URL", font=self.title_font,
                      fill=(255, 255, 255))
        elif not self.events:
            draw.text((1, 2), "APPLE CAL", font=self.header_font,
                      fill=self.header_color)
            draw.text((1, 15), "No upcoming events", font=self.title_font,
                      fill=(220, 220, 220))
        else:
            current_time = time.time()
            if current_time - self.last_rotation >= self.rotation_interval:
                self.current_event_index = (self.current_event_index + 1) % len(self.events)
                self.last_rotation = current_time

            if self.current_event_index >= len(self.events):
                self.current_event_index = 0

            event = self.events[self.current_event_index]
            start = event["start"].astimezone(self.local_tz)
            if event["all_day"]:
                header = start.strftime("%a %d %b").upper() + "  ALL DAY"
            else:
                header = start.strftime("%a %d %b  %H:%M").upper()
            draw.text((1, 1), header, font=self.header_font,
                      fill=self.header_color)
            lines = self._wrap_title(
                draw, event["title"], max(width - 2, 8), max_lines=2
            )
            y = 13
            for line in lines:
                draw.text((1, y), line, font=self.title_font,
                          fill=(255, 255, 255))
                y += 9

        self.display_manager.image = image
        self.display_manager.update_display()

    def get_vegas_display_mode(self):
        return VegasDisplayMode.CONTENT

    def get_vegas_content_type(self) -> str:
        return "calendar"

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        info.update({
            "name": "Apple Calendar",
            "events_loaded": len(self.events),
            "configured": bool(self.calendar_url),
            "timezone": self.timezone_name,
            "header_color": self.header_color_hex,
        })
        return info
