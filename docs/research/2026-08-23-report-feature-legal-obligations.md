# Legal obligations for a "report this event" feature

**Date:** 2026-08-23
**Ticket:** https://github.com/allut/event-radar/issues/109 (research task)
**Parent wayfinder map:** https://github.com/allut/event-radar/issues/108 ("report an inappropriate event")

All claims below are cited to primary legal text, read directly from the official PDF/HTML publications at eur-lex.europa.eu (DSA: CELEX:32022R2065; GDPR: CELEX:32016R0679; SME Recommendation: CELEX:32003H0361), plus Estonia's official gazette (Riigi Teataja) and the Estonian Digital Services Coordinator's own site for the national layer.

---

## 1. DSA Article 16 — Notice and action mechanisms

Source: Regulation (EU) 2022/2065, consolidated text at
https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32022R2065 (Article 16 is in Chapter III, Section 2, "Additional provisions applicable to providers of hosting services, including online platforms").

### 1.1 Full text (verbatim)

> **Article 16 — Notice and action mechanisms**
>
> 1. Providers of hosting services shall put mechanisms in place to allow any individual or entity to notify them of the presence on their service of specific items of information that the individual or entity considers to be illegal content. Those mechanisms shall be easy to access and user-friendly, and shall allow for the submission of notices exclusively by electronic means.
>
> 2. The mechanisms referred to in paragraph 1 shall be such as to facilitate the submission of sufficiently precise and adequately substantiated notices. To that end, the providers of hosting services shall take the necessary measures to enable and to facilitate the submission of notices containing all of the following elements:
>    (a) a sufficiently substantiated explanation of the reasons why the individual or entity alleges the information in question to be illegal content;
>    (b) a clear indication of the exact electronic location of that information, such as the exact URL or URLs, and, where necessary, additional information enabling the identification of the illegal content adapted to the type of content and to the specific type of hosting service;
>    (c) the name and email address of the individual or entity submitting the notice, except in the case of information considered to involve one of the offences referred to in Articles 3 to 7 of Directive 2011/93/EU [child sexual abuse material];
>    (d) a statement confirming the bona fide belief of the individual or entity submitting the notice that the information and allegations contained therein are accurate and complete.
>
> 3. Notices referred to in this Article shall be considered to give rise to actual knowledge or awareness for the purposes of Article 6 in respect of the specific item of information concerned where they allow a diligent provider of hosting services to identify the illegality of the relevant activity or information without a detailed legal examination.
>
> 4. Where the notice contains the electronic contact information of the individual or entity that submitted it, the provider of hosting services shall, without undue delay, send a confirmation of receipt of the notice to that individual or entity.
>
> 5. The provider shall also, without undue delay, notify that individual or entity of its decision in respect of the information to which the notice relates, providing information on the possibilities for redress in respect of that decision.
>
> 6. Providers of hosting services shall process any notices that they receive under the mechanisms referred to in paragraph 1 and take their decisions in respect of the information to which the notices relate, in a timely, diligent, non-arbitrary and objective manner. Where they use automated means for that processing or decision-making, they shall include information on such use in the notification referred to in paragraph 5.

### 1.2 Does What's on Radar fall in scope?

**Which DSA category applies.** Article 3(g)(iii) defines a "hosting" service as "the storage of information provided by, and at the request of, a recipient of the service." What's on Radar stores organizer-submitted event listings (and republishes scraped listings) and makes them accessible to the public on a SEO-indexed site — this is squarely a hosting service, and specifically an **"online platform"** under Article 3, because it disseminates recipient-provided information *to the public* (as opposed to only back to the submitter). It is not a VLOP (Article 33 designation requires ≥45 million monthly EU users, published via a Commission decision) — that threshold is nowhere close to being met and is not a realistic near-term concern.

**Article 16 itself is NOT covered by any size exemption.** This is the load-bearing finding: Article 16 sits in **Section 2** ("Additional provisions applicable to providers of hosting services, **including online platforms**"), which carries no micro/small carve-out. The micro/small exemption in **Article 19** (see below) applies only to **Section 3** ("Additional provisions applicable to providers of online platforms" — Articles 19 onward: internal complaint-handling, out-of-court dispute settlement, trusted flaggers, etc.), *not* to Section 2. So even a genuinely micro-sized operator that is a hosting service is bound by Article 16's notice-and-action mechanism. This conclusion holds regardless of What's on Radar's actual size — no headcount/turnover fact would change it.

**What the size exemption DOES affect (Article 19, verbatim):**

> **Article 19 — Exclusion for micro and small enterprises**
>
> 1. This Section, with the exception of Article 24(3) thereof, shall not apply to providers of online platforms that qualify as micro or small enterprises as defined in Recommendation 2003/361/EC. [...12-month grace period after losing that status is also excluded, except for VLOPs.]
> 2. By derogation from paragraph 1 of this Article, this Section shall apply to providers of online platforms that have been designated as very large online platforms in accordance with Article 33, irrespective of whether they qualify as micro or small enterprises.

If What's on Radar qualifies as a micro/small enterprise (Recommendation 2003/361/EC, Annex Article 2, verbatim from https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32003H0361 — an enterprise must meet the headcount test **and** at least one financial test):
- **Small**: fewer than 50 employees, AND annual turnover ≤ €10 million or balance sheet total ≤ €10 million.
- **Micro**: fewer than 10 employees, AND annual turnover ≤ €2 million or balance sheet total ≤ €2 million.

If small/micro, What's on Radar is **exempt from Article 20** (the internal complaint-handling system that lets a reporter or affected recipient appeal a decision — 6-month window, free, electronic) and from other Section 3 obligations (out-of-court dispute settlement designation, trusted-flagger prioritization, etc.), but it still owes the notice-and-action mechanism of Article 16, the confirmation-of-receipt (16(4)), and the decision notification (16(5)).

**NEEDS DEVELOPER INPUT:** I do not have What's on Radar's EU headcount or annual turnover/balance-sheet figures. Given the product description ("soft launch," small team, single-process MVP on Render free tier), it is highly plausible the company qualifies as micro or small — but this is a factual question for the business, not a legal one, and determines whether Article 20's internal-appeal system is legally mandatory or optional. **Flag: confirm headcount/turnover before deciding whether to build an internal-appeal/complaint-handling flow, or build it anyway as good practice regardless of exemption.**

### 1.3 What a compliant mechanism must DO

- **Intake (Art. 16(2))**: the submission form must let the reporter provide — (a) a substantiated explanation of why the content is alleged illegal, (b) the exact location of the content (event URL/ID is sufficient — no need for line/pixel precision), (c) the reporter's name and email, *unless* the report concerns CSAM-related offences (Directive 2011/93/EU, in which case anonymous reporting must be allowed), and (d) a bona-fide/accuracy attestation (a checkbox-level statement is generally regarded as sufficient).
- **Confirmation of receipt (Art. 16(4))**: required, "without undue delay," but *only* if the notice included the reporter's electronic contact info (i.e., always, in practice, since (c) requires an email except for the CSAM exception).
- **Decision notice (Art. 16(5))**: the platform must, without undue delay, tell the reporter what decision it made about the reported content and inform them of "possibilities for redress" — this cross-references **Article 17 (Statement of reasons)**, quoted below, which sets the *content* standard for that decision notice whenever the decision imposes a restriction (removal, visibility restriction, demotion, account/payment suspension) on the *reported party* (the organizer/submitter), not the reporter.
- **Processing standard (Art. 16(6))**: "timely, diligent, non-arbitrary and objective" — if automated means are used to process/decide, that must be disclosed in the 16(5) notice.

### 1.4 Article 17 — Statement of reasons (cross-referenced from 16(5))

> **Article 17(1)**: Providers of hosting services shall provide a clear and specific statement of reasons to any affected recipients of the service for any of the following restrictions imposed on the ground that the information provided by the recipient of the service is illegal content or incompatible with their terms and conditions: (a) restrictions of visibility (removal, disabling access, demotion); (b) suspension/termination/restriction of monetary payments; (c) suspension/termination of the service; (d) suspension/termination of the account.
>
> **17(2)**: applies only where contact details of the *affected recipient* (i.e. the organizer whose listing was actioned) are known; applies from the moment the restriction is imposed; does not apply to deceptive high-volume commercial content.
>
> **17(3)**: the statement must contain — what the decision entails and its scope/duration; the facts/circumstances relied on, including **whether the decision was based on a notice under Article 16 and, "where strictly necessary, the identity of the notifier"**; whether automated means were used; the legal ground (if illegal-content ground) or the contractual ground (T&Cs) relied on and why; and redress options (internal complaint-handling, out-of-court dispute settlement, judicial redress).
>
> **17(4)**: must be clear, easily comprehensible, and as precise/specific as reasonably possible.

Note the important nuance in 17(3)(b): the platform *may* have to disclose the reporter's identity to the organizer as part of the statement of reasons, but only "where strictly necessary" — this is a narrow exception, not a default, and should be read alongside the GDPR analysis in Section 3 below (Article 15(4)) which is the general mechanism protecting reporter identity from disclosure. Article 17(3)(b) is the DSA-side counterpart: it authorizes identity disclosure only when strictly necessary to justify the decision, not as a routine matter.

---

## 2. Estonian national implementation

- **Digital Services Coordinator**: confirmed to be **Tarbijakaitse ja Tehnilise Järelevalve Amet (TTJA)** — the Consumer Protection and Technical Regulatory Authority. Confirmed via TTJA's own site (https://ttja.ee/ariklient/ettevotlus/tarbijakaitsenouded-tegevusalale/digiteenused — "TTJA is an independent digital services coordinator under Regulation (EU) 2022/2065" and carries out national supervision of compliance with that Regulation) and cross-checked against the EDRi Digital Services Coordinators database (https://dscdb.edri.org/en/DigitalServicesCoordinators/Estonia).
- **Implementing act**: Estonia designated TTJA via an amendment to the **Infoühiskonna teenuse seadus** (Information Society Services Act, "InfoTS"). Per Riigi Teataja search results, the amending act is *"Infoühiskonna teenuse seaduse ja karistusseadustiku muutmise seadus"*, adopted 4 June 2024, published as RT I, 04.07.2024, 3 (https://www.riigiteataja.ee/akt/104072024003); the consolidated current text of the base act is at https://www.riigiteataja.ee/akt/104072024024. **Caveat**: Riigi Teataja serves its legislative text through a JavaScript single-page app that this research could not scrape into plain text (repeated fetch attempts returned only the unrendered app shell), so I was not able to quote the Estonian statutory text verbatim — the citations above are the official act identifiers for a developer/legal reviewer to pull up directly in a browser and verify.
- **National-level obligations beyond the DSA baseline found so far**: TTJA's guidance page states that hosting/storage providers ("teabe talletajad") must notify the **Politsei- ja Piirivalveamet** (Police and Border Guard Board, PPA) — not TTJA — of suspected criminal activity discovered through content, which is Estonia's designation of the competent authority for **DSA Article 18** ("Notification of suspicions of criminal offences"), not an addition to Article 16 itself. I found no Estonian-law addition that changes what an Article 16 notice mechanism must look like beyond the Regulation's own text — treat this as **no additional obligation found**, not as a guarantee none exists; a full read of the consolidated InfoTS text (once accessible) would be needed to close this out with certainty.

---

## 3. GDPR — retaining reporter identity

Source: Regulation (EU) 2016/679, https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32016R0679

### 3.1 Lawful basis (Article 6(1))

Verbatim:
> (c) "processing is necessary for compliance with a legal obligation to which the controller is subject";
> (f) "processing is necessary for the purposes of the legitimate interests pursued by the controller or by a third party, except where such interests are overridden by the interests or fundamental rights and freedoms of the data subject which require protection of personal data, in particular where the data subject is a child."

Both are plausible, and they are not mutually exclusive — a controller can rely on either depending on framing:
- **6(1)(c)** fits cleanly for the *minimum* elements the DSA itself compels a hosting provider to collect/retain per Article 16(2)(c) (reporter name+email) and to be able to substantiate a 16(6) "diligent, non-arbitrary, objective" decision — the DSA is EU law that creates the "legal obligation."
- **6(1)(f)** (legitimate interests) is the more natural basis for anything beyond the DSA's bare minimum — e.g., retaining the report content/history to detect abusive/bad-faith reporting patterns, or to defend the platform if a decision is disputed. This requires the standard legitimate-interests balancing test against the reporter's own rights.

**Recommendation for the design doc**: cite 6(1)(c) for the DSA-mandated fields and 6(1)(f) for anything retained beyond that floor (e.g., IP address, free-text report detail, moderation notes) — don't conflate the two into a single blanket basis.

### 3.2 Retention period (Article 5(1)(e))

Verbatim: personal data shall be "kept in a form which permits identification of data subjects for no longer than is necessary for the purposes for which the personal data are processed... ('storage limitation')."

GDPR sets **no fixed number of days/months** — any retention period the design settles on must be justified against actual purpose, not picked arbitrarily. Recital 39 (general storage-limitation principle) reinforces this: "personal data should be kept for no longer than is necessary." Factors that would justify a longer window here specifically: the DSA's own evidentiary chain (an organizer could dispute a decision via Article 20 internal complaint-handling — six months minimum per Article 20(1) — or via out-of-court dispute settlement or judicial redress, which can run longer), and any internal need to detect repeat/abusive reporters. **Do not hardcode an arbitrary retention figure without documenting which of these purposes it maps to.**

### 3.3 Does the reported organizer have a right to see the reporter's identity? (Article 15)

Verbatim, Article 15 ("Right of access by the data subject"):
> 1. The data subject shall have the right to obtain from the controller confirmation as to whether or not personal data concerning him or her are being processed, and, where that is the case, access to the personal data and [listed categories: purposes, categories of data, recipients, retention period/criteria, rights to rectification/erasure/restriction/objection, right to complain to a supervisory authority, source of data if not collected from the subject, existence of automated decision-making].
> 3. The controller shall provide a copy of the personal data undergoing processing. [...]
> **4. The right to obtain a copy referred to in paragraph 3 shall not adversely affect the rights and freedoms of others.**

Article 15(4) is the key mechanism: an organizer who is the subject of an access request about *their own* data does not get to use that request to extract the *reporter's* personal data, because the reporter's identity is "the rights and freedoms of others" relative to the organizer's SAR. **Recital 63** (same Regulation) confirms and contextualizes this: "[The right of access] should not adversely affect the rights or freedoms of others... the result of those considerations should not be a refusal to provide all information to the data subject" — i.e. the correct operational response is to **redact/withhold the reporter-identifying fields while still fulfilling the rest of the organizer's own access request**, not to refuse the whole request.

Note this is a general GDPR mechanism protecting *any* third party's data appearing in a SAR response, not something specific to content moderation — but it is exactly the tool that lets the platform decline to hand the organizer the name/email of whoever reported their event, while still answering the SAR about the organizer's own account/listing data. This dovetails with DSA Article 17(3)(b) above, which independently limits disclosure of the notifier's identity in the *statement of reasons* to cases where it is "strictly necessary."

---

## 4. Does DSA/GDPR mandate specific report-reason categories?

**Yes, indirectly, via Article 16(2)(a).** The notice mechanism must let the reporter provide "a sufficiently substantiated explanation of the reasons why the individual or entity alleges the information in question to be **illegal content**" — the Article is scoped to illegal-content notices specifically (the section header context and Art. 16(1) both say "considers to be illegal content"). The Article does **not** literally say "the taxonomy must have a checkbox labelled 'illegal' distinct from 'violates house rules'" — but it does functionally force the distinction, for two reasons:

1. **16(3)**: a notice only triggers "actual knowledge" (the liability-relevant trigger under Article 6's hosting-provider liability shield) if it's about *illegal* content specifically, identifiable "without a detailed legal examination" — a report that just says "this event is boring/mis-categorized" would not carry that legal weight, so the platform needs to be able to tell which reports are illegal-content claims (with Article 16's procedural guarantees attached) versus which are simple T&Cs/house-rules complaints (which get lighter-touch, self-determined handling, not Article 16's guarantees).
2. **Article 17(1)** distinguishes, for the *decision notice*, whether a restriction was imposed "on the ground that the information... is illegal content **or** incompatible with their terms and conditions" — and 17(3)(d)/(e) require *different* content in the statement of reasons depending on which ground applies (legal-ground explanation vs. contractual-ground explanation). The platform cannot produce a compliant Article 17 statement of reasons without first knowing, at intake, which ground the reporter (or the platform's own subsequent classification) is invoking.

So: **the taxonomy should offer an explicit "this is illegal content" path (with the DSA's required substantiation fields) as functionally distinct from a general "violates our content guidelines / house rules" path**, even though no single sentence in the DSA literally commands a UI checkbox to that effect. GDPR does not touch report-reason taxonomy at all — no requirement found there.

---

## What this forces on the design

**(a) Acknowledgment-on-submit — required, conditionally.** DSA Article 16(4): if the report includes the reporter's electronic contact information (which it will in nearly all cases, since Article 16(2)(c) requires name+email except for CSAM-category reports), the platform must send a confirmation of receipt "without undue delay." Build this as a synchronous or near-immediate response (an on-screen confirmation plus a receipt email is the safest reading of "without undue delay").

**(b) Outcome/decision notification back to the reporter — required.** DSA Article 16(5): the platform must, without undue delay, notify the reporter of its decision on the reported content and tell them about possibilities for redress. If small/micro (NEEDS DEVELOPER INPUT — headcount/turnover unconfirmed), an internal appeal system (Article 20) is not mandatory, but the decision notice and redress information still are. Separately, if the decision *restricts* the organizer's content/account (Article 17), the organizer gets their own statement of reasons — a different notification, to a different party, with more content (facts relied on, legal vs. contractual ground, and only "where strictly necessary" the reporter's identity).

**(c) Report reason taxonomy — must distinguish "illegal content" from "violates house rules/guidelines."** This isn't cosmetic: it determines (i) whether Article 16's full procedural machinery (substantiation fields, actual-knowledge trigger, Article 17 legal-ground statement) applies to a given report, versus a lighter-touch T&Cs-violation flow, and (ii) what the resulting decision notice must say. Concretely: the "illegal content" path should collect a substantiated explanation of the alleged illegality (16(2)(a)) plus the exact content location (16(2)(b), i.e. event ID/URL — already implicit in a "report this event" UI) plus a bona-fide/accuracy attestation checkbox (16(2)(d)); a non-illegal "house rules" report can be lighter-weight.

**(d) Reporter-identity retention and organizer-access-request handling.**
- Retain reporter name/email under GDPR Article 6(1)(c) (DSA-mandated minimum) and/or 6(1)(f) (legitimate interests, for anything beyond that floor, e.g. abuse-pattern detection) — don't use a single blanket basis for both.
- No fixed retention period exists in law (Article 5(1)(e)); tie whatever period is chosen explicitly to a stated purpose (dispute/appeal window — at least the Article 20 six-month floor if that Section applies; general storage-limitation principle otherwise) rather than picking an arbitrary number.
- When an organizer submits a GDPR Article 15 access request about their own account/listing, the reporter's identity must be **redacted, not used to refuse the whole request** (Article 15(4), reinforced by Recital 63) — build the SAR-fulfillment logic to filter out third-party-identifying fields rather than blanket-denying or blanket-granting.
- Disclosing the reporter's identity to the organizer as part of a DSA Article 17 statement of reasons is permitted only "where strictly necessary" (Article 17(3)(b)) — treat this as a narrow, actively-decided exception, not a default field in the notice template.

**NEEDS DEVELOPER INPUT flags, consolidated:**
1. EU headcount and annual turnover/balance-sheet figures — determines whether Article 19's micro/small exclusion applies, which in turn determines whether Article 20's internal complaint-handling system (6-month appeal window, free, electronic) is legally mandatory or optional-but-recommended.
2. Full verbatim text of the Estonian Infoühiskonna teenuse seadus could not be scraped (JS-rendered site) — the act identifiers are cited above for direct verification; no additional Article-16-specific national obligation was found, but this should be treated as "not found" rather than "confirmed absent."
