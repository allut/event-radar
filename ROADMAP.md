# Roadmap

Planned work on Event Radar, roughly in order. Each item links to its GitHub issue where one exists.

## Production reliability

- **Make the Axiom monitors catch a failing job or source** ([#675](https://github.com/allut/event-radar/issues/675)).

## Code health

- **Pin the `http_get()` and `http_post()` error contract in tests**, and stop building `HTTPStatusError` around `MagicMock` responses ([#676](https://github.com/allut/event-radar/issues/676)).
- **Have review read the callers of a shared helper whose contract changes** ([#677](https://github.com/allut/event-radar/issues/677)).
- **Sharpen the log-triage recipe** in `docs/observability.md` ([#678](https://github.com/allut/event-radar/issues/678)).
- **Scan for secrets in the pre-commit hook and CI** ([#670](https://github.com/allut/event-radar/issues/670)).
- **Keep real email addresses out of test and fixture files** with a guard test ([#671](https://github.com/allut/event-radar/issues/671)).
- **Catch frontend tests that will fail once their hardcoded date passes** with a scheduled run that moves the clock forward ([#672](https://github.com/allut/event-radar/issues/672)).
- **Hide console output from passing frontend tests in CI logs** ([#673](https://github.com/allut/event-radar/issues/673)).
- **Match claims by the stored series key in dedup** ([#664](https://github.com/allut/event-radar/issues/664)).
- **Remove the owner's name and email from the README, constants and tests** ([#686](https://github.com/allut/event-radar/issues/686)).

## Features

- **"More like this" on the event detail page.**
- **More cities beyond Tallinn.**
- **Report follow-ups** deferred until there is volume data ([#121](https://github.com/allut/event-radar/issues/121)).

## Promotions go-live (deferred indefinitely)

Paid Sponsored slots are built. These steps take them live:

- **Load the Operator details, LLM prompts, scrape selectors and ranking weights from runtime config** ([#679](https://github.com/allut/event-radar/issues/679)), so admins can tune them without a deploy and the repo holds no Operator PII. The Operator details come first, since the two Operator steps below wait on them. For everything else, the repo keeps working defaults.
- **Run card checkout, invoices and refunds in Stripe test mode** ([#624](https://github.com/allut/event-radar/issues/624)).
- **Verify the Äriregister lookup against the real API** ([#623](https://github.com/allut/event-radar/issues/623)).
- **Name the Daily 5 Пятёрка дня throughout the Russian copy** ([#669](https://github.com/allut/event-radar/issues/669)), before the native-speaker review.
- **Get the Estonian and Russian copy reviewed by native speakers** ([#625](https://github.com/allut/event-radar/issues/625)).
- **Fill in the Operator details and get the Organizer terms legally reviewed** ([#622](https://github.com/allut/event-radar/issues/622)).
- **Add the Operator imprint and notice emails** ([#621](https://github.com/allut/event-radar/issues/621)).
- **Switch over:** deploy and enable the feature flags in order ([#626](https://github.com/allut/event-radar/issues/626)).
