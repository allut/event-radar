# Card-only Stripe checkout for Promotions; bank transfer goes through admin requests

Status: accepted

Self-serve Promotions are paid through Stripe Checkout with Stripe's
post-payment invoice, and only by card. Stripe's Pay by Bank doesn't reach
Estonian payers, so Swedbank, SEB and LHV bank links aren't offered. An
Organizer who wants to pay by bank transfer, or a buyer with an EU VAT
number, sends a Promotion request instead. An admin grants it into an
`unpaid` Promotion and invoices it off-platform. Decided in
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

## Consequences

- **Adding bank links later means a second provider beside Stripe, not a
  swap.** The `ER-` invoice series, the Stripe Customer mapping and the
  webhook stay.
- **Two invoice series exist:** `ER-` from Stripe, and `ER-M-` for
  off-platform admin invoices. The accountant confirms this under the legal
  prerequisites on the Promotions map.
- **The Stripe SDK bypasses `http_get()`.** `docs/conventions.md` lists the
  bypass: the SDK manages its own idempotency keys and retries.
