# Roadmap

Planned work on Event Radar, roughly in order. Each item links to its GitHub issue where one exists.

## Promotions go-live

Paid Sponsored slots are built. These steps take them live:

- **Run card checkout, invoices and refunds in Stripe test mode** ([#624](https://github.com/allut/event-radar/issues/624)).
- **Verify the Äriregister lookup against the real API** ([#623](https://github.com/allut/event-radar/issues/623)).
- **Get the Estonian and Russian copy reviewed by native speakers** ([#625](https://github.com/allut/event-radar/issues/625)).
- **Fill in the Operator details and get the Organizer terms legally reviewed** ([#622](https://github.com/allut/event-radar/issues/622)).
- **Add the Operator imprint and notice emails** ([#621](https://github.com/allut/event-radar/issues/621)).
- **Switch over:** deploy and enable the feature flags in order ([#626](https://github.com/allut/event-radar/issues/626)).

## Code health

- **Split oversized source files by area**, with a 700-line regrowth guard ([#668](https://github.com/allut/event-radar/issues/668)).
- **Match claims by the stored series key in dedup** ([#664](https://github.com/allut/event-radar/issues/664)).
- **Load LLM prompts, scrape selectors and ranking weights from runtime config**, so operators can tune them without a deploy. The repo keeps working defaults.

## Features

- **"More like this" on the event detail page.**
- **More cities beyond Tallinn.**
- **Report follow-ups** deferred until there is volume data ([#121](https://github.com/allut/event-radar/issues/121)).
