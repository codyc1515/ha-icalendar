# iCalendar API integration for Home Assistant
Generates an iCalendar (.ics) link that you can use to view your Home Assistant calendars in another app.

## Installation
### HACS (recommended)
1. [Install HACS](https://hacs.xyz/docs/setup/download), if you did not already
2. [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=codyc1515&repository=ha-icalendar&category=integration)
3. Press the Download button
4. Add the following to your configuration.yaml file:

   ```
   icalendar:
     secret: yourSuperSecret
   ```
4. Restart Home Assistant

### Manually
Copy all files in the *custom_components/icalendar* folder to your Home Assistant folder *config/custom_components/icalendar*.

## Getting started
In your preferred calendar application, input your iCalendar URL in the following format:

- Home Assistant URL - http://homeassistant.local:8123
- iCalendar API path - /api/ics/
- Calendar Entity Id - calendar.*entity_id*
- Secret parameter - ?s=*secret*

### Example

- http://*homeassistant.local:8123*/api/ics/calendar.*holidays*?s=*yourSuperSecret*

## Known issues
- Only supplies the first upcoming event.

## Future enhancements
Your support is welcomed.
