# Roadmap

Planned work on Event Radar, roughly in order. Each item links to its GitHub issue where one exists.

## Production reliability

- **Make the Axiom monitors catch a failing job or source** ([#675](https://github.com/allut/event-radar/issues/675)).
- **Keep an admin's switch-off of a failing source across deploys** ([#698](https://github.com/allut/event-radar/issues/698)). This is the first tunable value in runtime config ([#693](https://github.com/allut/event-radar/issues/693)).
- **Let admins fix a broken source or a bad prompt without a deploy**: scrape selectors ([#702](https://github.com/allut/event-radar/issues/702)), LLM prompts ([#700](https://github.com/allut/event-radar/issues/700)), the LLM provider chain ([#704](https://github.com/allut/event-radar/issues/704)) and ranking values ([#699](https://github.com/allut/event-radar/issues/699)). Each has a dry run ([#701](https://github.com/allut/event-radar/issues/701), [#703](https://github.com/allut/event-radar/issues/703), [#705](https://github.com/allut/event-radar/issues/705), [#706](https://github.com/allut/event-radar/issues/706)), and the repo keeps working defaults.

## Code health

- **Pin the `http_get()` and `http_post()` error contract in tests**, and stop building `HTTPStatusError` around `MagicMock` responses ([#676](https://github.com/allut/event-radar/issues/676)).
- **Have review read the callers of a shared helper whose contract changes** ([#677](https://github.com/allut/event-radar/issues/677)).
- **Sharpen the log-triage recipe** in `docs/observability.md` ([#678](https://github.com/allut/event-radar/issues/678)).
- **Scan for secrets in the pre-commit hook and CI** ([#670](https://github.com/allut/event-radar/issues/670)).
- **Keep real email addresses out of test and fixture files** with a guard test ([#671](https://github.com/allut/event-radar/issues/671)).
- **Keep the owner's name and personal email out of every tracked file** with a guard test ([#711](https://github.com/allut/event-radar/issues/711)).
- **Catch frontend tests that will fail once their hardcoded date passes** with a scheduled run that moves the clock forward ([#672](https://github.com/allut/event-radar/issues/672)).
- **Hide console output from passing frontend tests in CI logs** ([#673](https://github.com/allut/event-radar/issues/673)).
- **Match claims by the stored series key in dedup** ([#664](https://github.com/allut/event-radar/issues/664)).
- **Run the docs style check on any staged Markdown**, so the governed-doc list lives in one place ([#707](https://github.com/allut/event-radar/issues/707)).
- **Fail a governed doc that has no Documentation Map row** with a guard test ([#708](https://github.com/allut/event-radar/issues/708)).
- **Fail a backticked constant name in a doc that the code no longer defines** with a guard test ([#709](https://github.com/allut/event-radar/issues/709)).
- **Compare the live Axiom monitors before editing the Monitors spec** in `docs/observability.md` ([#710](https://github.com/allut/event-radar/issues/710)).
- **Fail the README tree check on a tracked top-level directory it doesn't list** ([#712](https://github.com/allut/event-radar/issues/712)).
- **Document claiming an issue, removing its roadmap bullet, and the README word budget** ([#713](https://github.com/allut/event-radar/issues/713)).
- **Run the frontend tests related to staged files in pre-commit** ([#715](https://github.com/allut/event-radar/issues/715)).
- **Say when a future decision takes effect** in ADRs and the glossary ([#716](https://github.com/allut/event-radar/issues/716)).
- **Document the paid-slots legal date rule** in `docs/frontend.md` ([#717](https://github.com/allut/event-radar/issues/717)).

## Features

- **"More like this" on the event detail page.**
- **More cities beyond Tallinn.**
- **Report follow-ups** deferred until there is volume data ([#121](https://github.com/allut/event-radar/issues/121)).

## Promotions go-live (deferred indefinitely)

Paid Sponsored slots are built. These steps take them live:

- **Supply the Operator details through runtime config** ([#693](https://github.com/allut/event-radar/issues/693)), so the repo holds no Operator PII. This takes the store ([#694](https://github.com/allut/event-radar/issues/694)), entering the details in the admin console ([#695](https://github.com/allut/event-radar/issues/695)), baking them into the legal pages ([#696](https://github.com/allut/event-radar/issues/696)) and naming the Operator on Stripe invoices ([#697](https://github.com/allut/event-radar/issues/697)). The two Operator steps below wait on these.
- **Run card checkout, invoices and refunds in Stripe test mode** ([#624](https://github.com/allut/event-radar/issues/624)).
- **Verify the Äriregister lookup against the real API** ([#623](https://github.com/allut/event-radar/issues/623)).
- **Name the Daily 5 Пятёрка дня throughout the Russian copy** ([#669](https://github.com/allut/event-radar/issues/669)), before the native-speaker review.
- **Get the Estonian and Russian copy reviewed by native speakers** ([#625](https://github.com/allut/event-radar/issues/625)).
- **Fill in the Operator details and get the Organizer terms legally reviewed** ([#622](https://github.com/allut/event-radar/issues/622)).
- **Add the Operator imprint and notice emails** ([#621](https://github.com/allut/event-radar/issues/621)).
- **Switch over:** deploy and enable the feature flags in order ([#626](https://github.com/allut/event-radar/issues/626)).
