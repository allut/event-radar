# Event Radar is operated by a general-purpose OÜ

Status: accepted

The Operator of Event Radar is a private limited company (OÜ), founded as a
general-purpose company for any of the owner's products that get monetised,
not one named after Event Radar. It runs all of Event Radar: it sells
Promotions, issues the invoices, holds Event Radar's Stripe account, controls
personal data, and is the party to the Terms and the Organizer terms. It must
exist before `PROMOTIONS_OFFER_ENABLED` is turned on, because a Promotion
granted from a request is a sale too. Decided in
[choose the legal form](https://github.com/allut/event-radar/issues/590), from
the facts in
[legal form options](https://github.com/allut/event-radar/issues/589).

## Considered options

- **The LHV Entrepreneur account (ettevõtluskonto).** Rejected. It is free
  and roughly as cheap as the OÜ for the owner, but every Estonian company or
  MTÜ buying a service from it owes an extra 22/78 income tax (TuMS § 34 p 13,
  § 51): €9.87 on a €35 Promotion. It falls on exactly the businesses we sell
  to, and the seller must tell each buyer about it. It also can never register
  for VAT, and its holder is personally liable.
- **An FIE.** Rejected. The owner's salary covers the social-tax floor, but
  income tax plus 33% social tax still takes about 41% of profit, against 22%
  on an OÜ dividend. Its only saving is the annual report, and its liability
  is unlimited.

## Consequences

- **Liability stops at the company**, for GDPR, Organizer refund and contract
  claims, except for a board member's breach of duty. Products under the same
  OÜ share that liability. A product that grows risky can move into its own
  company later.
- **The overhead is small but real.** It is €200 to found, then about €85 a
  year: self-kept books in e-arveldaja and an accountant for the annual
  report. The VAT on its own costs is deductible (below). Anything paid out
  owes 22/78. Running costs are about €125 a year, so deductibility hardly
  mattered.
- **The OÜ registers fully for VAT** (KMS § 20(2)), applying at founding.
  The VAT number gates `PROMOTIONS_OFFER_ENABLED`; there is no launch as a
  limited VAT payer. Promotions are sold at €5/day + VAT at the applicable
  rate (€6.20 at 24%), so the Operator keeps €5 whatever the rate, and Stripe
  adds one manual 24% Tax Rate. It deducts the VAT on vendor bills and
  Estonian purchases and files one KMD a month; KMD INF never triggers on
  sales, which stay under €1,000 per buyer a month. Organizers without a VAT
  number, about half of buyers by count, pay 24% more. The registration
  covers the legal person, so every product the OÜ sells charges VAT.
  Staying a limited VAT payer (§ 21(1)) at €5 with no VAT was rejected,
  though it cost the Operator only about €80 a year more. Decided in
  [limited or full VAT registration](https://github.com/allut/event-radar/issues/596),
  from [limited VAT payer status](https://github.com/allut/event-radar/issues/591)
  and [share of Organizers that are VAT-registered](https://github.com/allut/event-radar/issues/595).
- **Switching later is expensive.** A new legal person means a new Stripe
  account, new Terms and Organizer terms, a new Privacy notice controller and
  a new invoice series. So the switch from the owner, who runs Event Radar as
  a private individual today, happens once, before launch: an emailed notice
  about 14 days ahead, then every document, Stripe, vendor billing and the .ee
  registrant moved together.
- **Each product gets its own Stripe account** under the OÜ, and its own
  invoice series. Event Radar keeps `ER-` and `ER-M-`.
