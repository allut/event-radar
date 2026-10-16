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
- **The overhead is small but real.** It is €200 to found, then about €115 a
  year (up to €125 at the revenue cap): self-kept books in e-arveldaja, an
  accountant for the annual report, and the VAT below. Anything paid out owes
  22/78. Running costs are about €125 a year, so deductibility hardly
  mattered.
- **The OÜ is a limited VAT payer from its first foreign vendor bill**
  (KMS § 21(1)). It self-assesses 24% on the Cloudflare, Render and Stripe
  Invoicing bills with no deduction, about €30 a year, and files a KMD for
  each month with such bills. Promotions still carry no VAT. Found in
  [limited VAT payer status](https://github.com/allut/event-radar/issues/591).
- **Switching later is expensive.** A new legal person means a new Stripe
  account, new Terms and Organizer terms, a new Privacy notice controller and
  a new invoice series. So the switch from the owner, who runs Event Radar as
  a private individual today, happens once, before launch: an emailed notice
  about 14 days ahead, then every document, Stripe, vendor billing and the .ee
  registrant moved together.
- **Each product gets its own Stripe account** under the OÜ, and its own
  invoice series. Event Radar keeps `ER-` and `ER-M-`.
