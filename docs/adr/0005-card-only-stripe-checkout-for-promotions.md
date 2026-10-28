# Card-only Stripe checkout for Promotions; bank transfer goes through admin requests

Status: accepted (amended: EU VAT-number buyers dropped from the request path;
Organizers buy only as their own business)

Self-serve Promotions are paid through Stripe Checkout with Stripe's
post-payment invoice, and only by card. Stripe's Pay by Bank doesn't reach
Estonian payers, so Swedbank, SEB and LHV bank links aren't offered. An
Organizer who wants to pay by bank transfer sends a Promotion request
instead. An admin grants it into an `unpaid` Promotion and invoices it
off-platform. Buyers with an EU VAT number are out of scope on the request
path: Promotions are sold to Estonian-registered businesses only, so no
reverse-charge invoice is issued (amended per
[accounting and operator setup](https://github.com/allut/event-radar/issues/583)).
An Organizer buys only as its own business, never for another one, and attests
on both paths that the registry code is its own. Nothing checks that claim:
the attestation makes a false one a recorded breach of the Organizer terms.
Decided in
[self-serve checkout and invoicing](https://github.com/allut/event-radar/issues/578).
The provider research is in
[payment and invoicing providers](https://github.com/allut/event-radar/issues/577).

A Checkout reuses the `unpaid` Promotion as its hold on cap days. Paying
moves it to `paid`, and an abandoned checkout is voided quietly. Void stays
final: a payment that arrives after the void is refunded in full, never
reinstated.

## Considered options

- **Montonio for bank links, plus Merit Aktiva or an invoice generator we
  build ourselves.** Rejected for launch. It costs €12–15 a month at a
  volume of a few dozen sales, needs a second integration and an invoice
  series we run ourselves, and FIE eligibility is unconfirmed. Its main
  benefit, bank transfer, is already covered by the admin request path.
- **Holding cap days on the Promotion request, or on a separate hold
  record.** Rejected. A request holding days would break *Promotion request*
  in `CONTEXT.md`. `unpaid` already holds days, never goes live and has a
  void path.
- **Buying on behalf of another business (agencies, a venue paying for a
  promoter).** Rejected. It would need a separate advertiser party beside the
  Organizer, and nothing sold so far calls for one.
- **Locking each registry code to the first Organizer that pays under it.**
  Rejected. A company with two staff accounts lands in review, and an
  impersonator who pays first keeps the code.
- **Checking the Organizer against the e-Business Register's board members.**
  Rejected for now. It needs a verified personal identity (Smart-ID or eID)
  that Organizer accounts don't have.

## Consequences

- **Adding bank links later means a second provider beside Stripe, not a
  swap.** The `ER-` invoice series, the Stripe Customer mapping and the
  webhook stay.
- **Two invoice series exist:** `ER-` from Stripe, and `ER-M-` for
  off-platform admin invoices. The accountant confirms this under the legal
  prerequisites on the Promotions map.
- **The Stripe SDK bypasses `http_get()`.** `docs/conventions.md` lists the
  bypass: the SDK manages its own idempotency keys and retries.
