# iCalendar API integration for Home Assistant
Generates an iCalendar (.ics) link that you can use to view your Home Assistant calendars in another app.

## Installation
### HACS (recommended)
1. [Install HACS](https://hacs.xyz/docs/setup/download), if you did not already.
2. [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=chris-y&repository=ha-icalendar&category=integration)
3. Press the Download button.
4. Restart Home Assistant.

### Manually
Copy all files in the `custom_components/icalendar` folder to your Home Assistant folder `config/custom_components/icalendar`.

## Setup
1. Go to **Settings > Devices & Services > Integrations**.
2. Add **iCalendar API**.
3. Choose **Include selected calendars** or **Exclude selected calendars**.
4. Select the `calendar.*` entities to include or exclude.

Each config entry provides one URL combining events from all matching calendars. Include requires at least one calendar. Exclude with no calendars selected exports all calendars. Exclude mode automatically includes newly added calendars. Existing single-calendar feeds keep their URLs and behave as include selections.

## URL format
The feed URL is now tied to the config entry ID:

- `/api/ics/<entry_id>/<secret>`

In the integration reconfigure/options UI, both local and external URL variants are shown (if configured in Home Assistant). Secret rotation is available from reconfigure.

## Additional configuration
For feeds resolving to one calendar, calendar color is taken from Home Assistant's calendar entity UI settings. Combined feeds omit calendar-level color.
Set it in the calendar entity settings. CSS3 color names are emitted as `COLOR`; hex colors use the `X-APPLE-CALENDAR-COLOR` extension (client support varies).

## Apple Calendar locations
Apple Calendar's enhanced location field needs coordinates; Home Assistant's `calendar.get_events` normally supplies only an address. Configure **Address lookup URL** in the feed settings with a Nominatim-compatible search endpoint (for example, your own `https://geocoder.example/search`) to resolve text such as `199 Clarence Street, Riccarton`. Leave the setting empty to disable lookup. Include the city and country in addresses when possible to avoid ambiguity.

Resolved events retain their original `LOCATION` and also include standard `GEO` and Apple's `X-APPLE-STRUCTURED-LOCATION`, with the address, title, and a 100-metre radius. These provide coordinates for supported clients' maps and directions. Apple Calendar's actual presentation depends on the client; this has not been verified in the Apple Calendar UI.

- Location text is sent to the configured provider. Choose a provider appropriate for the privacy of your calendars.
- Lookups happen on subscription refresh, with at most one new request every 15 seconds across all feeds and a three-second timeout. Additional addresses resolve on later refreshes; cached addresses are available immediately.
- Successful lookups are cached for 90 days across restarts; missing or ambiguous results for seven days. Provider errors back off for a minute. Unresolved locations remain plain text and do not prevent the feed from loading.
- The shared cache holds up to 2,000 lookups, keyed by a hash of endpoint and address. Changing the provider uses separate cached results. Disabling lookup stops emitting enhanced metadata for that feed.

**Public Nominatim service:** deliberately review the [usage policy](https://operations.osmfoundation.org/policies/nominatim/) before choosing `https://nominatim.openstreetmap.org/search`. It prohibits confidential/personal data submissions and imposes application-wide limits, identification, caching, and attribution requirements. Regular requests are restricted to four per minute, and distributed bulk use is prohibited. The limiter here is per Home Assistant instance, so it cannot enforce limits across multiple installations; use a private or suitable hosted provider for broader deployment. OpenStreetMap geocoding data is © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), available under the ODbL.

## Configuration parameters
- Setup:
  - `selection_mode`: `include` or `exclude`.
  - `calendar_entity_ids`: Calendars to include or exclude.
- Reconfigure:
  - `selection_mode` and `calendar_entity_ids`: Change the selection without changing the URL.
  - `secret`: Optional new secret (minimum 20 ASCII letters, digits, underscores, or hyphens). Leave blank to keep current secret.
- Options:
  - Change the calendar selection, view feed URLs, and optionally rotate the secret.

## Installation parameters
- Home Assistant `internal_url` and/or `external_url` should be configured to display full feed URLs in UI.
- Calendar selection requires registered entities; integration startup does not wait for source calendars.

## Supported functionality
- Provides a secure iCalendar feed endpoint:
  - `GET /api/ics/<config_entry_id>/<secret>`
- Exports calendar events from all matching Home Assistant calendar entities.
- Emits calendar-level `COLOR` from Home Assistant calendar UI color settings when available.

## Data update behavior
- Setup restores locally saved events without fetching or waiting for source calendars.
- Feed requests fetch calendars concurrently via `calendar.get_events`, with a 15-second timeout per source.
- Successful results (including empty calendars) are saved per entry and source. Missing, unavailable, failing, or timed-out sources use their last saved events. Cached events can be stale and retain the window from the last successful fetch.
- If any selected source has no successful snapshot yet, its feed returns HTTP 503 so subscribers do not interpret missing events as deletions. Other feed entries remain independent.
- Exclude mode retains previously cached sources during startup even before their entities appear. Remove unwanted sources by excluding them; deleting an entry removes its saved events.
- Time window returned is 4 weeks of history and 52 weeks in the future.

## Use cases
- Subscribe to Home Assistant calendars from external calendar clients that support ICS URLs.
- Share read-only calendar timelines using per-entry secrets.

## Example
- `https://home.example.com/api/ics/01ABCDEF1234567890/your_long_secret`

## Known limitations
- Feed security is URL-secret based; URLs should be treated as credentials.
- Event IDs are stable for unchanged occurrences and scoped to their source calendar. Without a source UID, identity uses the summary and start time; edits to these fields change the ID. Indistinguishable events from the same source cannot be distinguished.
- Calendar data is read at request time; response latency depends on calendar backend responsiveness.

## Troubleshooting
- `401 Unauthorized`: URL secret does not match the config entry secret.
- `403 Forbidden`: Invalid path/secret format or non-calendar entity.
- `404 Not Found`: Entry ID does not exist.
- `503 Service Unavailable`: Entry is unloaded, or a source is unavailable with no cached results. Empty calendars return a valid feed.
- If UI does not show full feed URLs, set `internal_url` / `external_url` in Home Assistant network settings.

## Removal instructions
1. Go to **Settings > Devices & Services > Integrations**.
2. Open **iCalendar API**.
3. Delete the config entry.
4. Update/remove ICS subscriptions that used that entry URL.

## Security notes
- Secret checks use constant-time comparison.
- iCalendar output now escapes reserved characters and folds long lines to improve parser safety and compatibility.

## Development tests
Run `python -m pip install -r requirements-test.txt`, then `python -m pytest`.
Tests use small Home Assistant boundary doubles and the real pinned ICS library; they do not replace testing in a running Home Assistant instance.
