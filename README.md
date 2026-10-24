# LEDMatrix Apple Calendar

Display upcoming events from a shared/published Apple iCloud Calendar on a ChuckBuilds LEDMatrix panel. The defaults are designed for a 128x32 display.

## Features

- Reads Apple/iCloud published iCalendar (`.ics`) feeds
- Timed and all-day events
- Recurring events and EXDATE exclusions
- Configurable event rotation
- Configurable look-ahead window and refresh interval
- Timezone-aware display (defaults to `Europe/London`)
- Keeps the last successful event list if a refresh fails
- 128x32-friendly two-line layout

## Apple Calendar setup

Apple Calendar must expose the calendar as a published iCalendar feed. In iCloud Calendar, publish/share the calendar and copy its calendar subscription URL. Depending on where you copy it from, the URL may begin with `webcal://` or `https://`.

**Treat the calendar URL like a password.** Anyone who has a published calendar URL may be able to read its events. Do not commit your real URL to GitHub, paste it into issues, or include it in screenshots.

## LEDMatrix installation

Install this repository as a third-party LEDMatrix plugin using the plugin repository/install workflow in your LEDMatrix web UI. The plugin entry point is `manager.py` and its class is `AppleCalendarPlugin`.

Dependencies are listed in `requirements.txt`:

```text
requests
icalendar
python-dateutil
```

## Configuration

Open the Apple Calendar plugin settings in LEDMatrix and set:

- **Apple Calendar ICS URL**: your private published iCloud calendar URL
- **Timezone**: normally `Europe/London` for the UK
- **Maximum events**: how many upcoming events to rotate through
- **Show all-day events**: include/exclude all-day entries
- **Look ahead**: how many days into the future to parse recurring events
- **Refresh interval**: default 900 seconds (15 minutes)
- **Event rotation interval**: default 10 seconds

No real calendar URL is stored in this repository.

## 128x32 display

A timed event is rendered approximately as:

```text
SAT 24 OCT  18:30
Dinner at Mum's
```

An all-day event uses `ALL DAY` in the header. Upcoming events rotate automatically.

## Privacy

The plugin performs read-only HTTP(S) requests to the calendar feed. It does not use an Apple ID password, iCloud password, or app-specific password.

If you accidentally publish your calendar URL publicly, stop publishing/re-publish the calendar in iCloud so the old URL is no longer usable.

## Compatibility

Initial release targets LEDMatrix `>=3.3.0`.

## License

No license has been selected yet. Add one before redistributing the project if needed.
