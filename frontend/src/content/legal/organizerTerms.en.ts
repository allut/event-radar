import { ROUTES } from '../../constants/routes';
import { ORGANIZER_TERMS_IS_DRAFT } from '../../constants/operator';
import { CONTACT_EMAIL, CONTACT_MAILTO } from '../../constants/core';
import { ORGANIZER_TERMS_VERSION } from '../../_generated/sharedConstants';
import type { LegalDoc } from './types';

const doc: LegalDoc = {
  title: 'Organizer terms',
  lastUpdated: '2026-10-18',
  draft: ORGANIZER_TERMS_IS_DRAFT,
  intro: [
    {
      kind: 'p',
      content: [
        'These terms apply when you buy or request a Promotion on Event Radar. They sit alongside the Terms of Service and the Privacy Policy. They include ',
        { text: 'How results are ordered', to: ROUTES.ranking },
        ', the Ranking disclosure, by reference.',
      ],
    },
    {
      kind: 'p',
      content: [
        `Version ${ORGANIZER_TERMS_VERSION}, in force from `,
        { operator: 'dateInForce' },
        '. When you accept these terms we record the version and the time.',
      ],
    },
  ],
  sections: [
    {
      id: 'operator',
      heading: '1. Who we are',
      blocks: [
        {
          kind: 'p',
          content: [
            'Event Radar is operated by ',
            { operator: 'name' },
            ' OÜ, registry code ',
            { operator: 'registryCode' },
            ', seat ',
            { operator: 'seat' },
            ', VAT number ',
            { operator: 'vatNumber' },
            ' (the "Operator", "we"). Contact: ',
            { text: CONTACT_EMAIL, href: CONTACT_MAILTO },
            '.',
          ],
        },
        {
          kind: 'p',
          content: [
            '"You" means the business or non-profit that buys or requests a Promotion. A "Promotion" is a window of whole Tallinn days during which one event you own may fill Sponsored slots. A "Sponsored slot" is a labelled position beside the results on Explore, the Daily 5 or the morning email.',
          ],
        },
      ],
    },
    {
      id: 'promotion',
      heading: '2. What a Promotion is',
      blocks: [
        {
          kind: 'ul',
          items: [
            [
              'It lasts 3 to 14 whole Tallinn days, first and last included. It starts tomorrow at the earliest and ends no later than the last day of your event.',
            ],
            [
              'It covers one event that you own: you submitted it, or you hold an approved claim on it.',
            ],
            [
              'At most 5 Promotions are live at the same time, and each live Promotion gets an equal share of the slots. A Promotion holds its days from the moment it is granted or paid.',
            ],
            [
              'The slot shows your event as a normal event card captioned "Ad", with the legal name of the business that paid. The name is recorded at sale and does not change if you later rename your profile.',
            ],
            [
              'A Promotion shows only while its event is public, not ended, the original listing and still yours, and its content meets the content policy below. If one of these stops being true, the Promotion pauses and resumes by itself once it is true again.',
            ],
          ],
        },
        {
          kind: 'p',
          content: [
            'Nothing is guaranteed: not impressions, clicks, ticket sales or any other result. A slot may stay empty or be shared with other Promotions, and viewers can hide it from themselves: an event a viewer disliked, reported, saved or liked is never shown to that viewer as an ad.',
          ],
        },
      ],
    },
    {
      id: 'ranking',
      heading: '3. Paid placement never affects ranking',
      blocks: [
        {
          kind: 'p',
          content: [
            'A Promotion buys Sponsored slots only. It never changes where your event ranks in Explore, the Daily 5 or the morning email, and nobody can pay to change the organic order. The main parameters that decide the order, and their relative importance, are in ',
            { text: 'How results are ordered', to: ROUTES.ranking },
            ". Slots are chosen by context (the page, the day and the viewer's active filters), never by a viewer's interests.",
          ],
        },
      ],
    },
    {
      id: 'price',
      heading: '4. Who can buy, and the price',
      blocks: [
        {
          kind: 'ul',
          items: [
            [
              'Promotions are sold only to businesses and non-profits registered in Estonia, and you must give your Estonian registry code.',
            ],
            [
              'The price is €5 per day plus VAT at the applicable rate (at 24%, €6.20 per day). For example, 7 days cost €35 plus €8.40 VAT, €43.40 in total.',
            ],
            [
              'The price and VAT rate in force at the time of sale are recorded with your Promotion. A later price change applies only to Promotions sold after it takes effect.',
            ],
            [
              'We may grant a Promotion free of charge at our discretion. A complimentary Promotion follows these terms in every other way and gives no right to another one.',
            ],
          ],
        },
      ],
    },
    {
      id: 'buying',
      heading: '5. How to buy',
      blocks: [
        {
          kind: 'p',
          content: [
            'By card. You enter your registry code, your legal name is filled in from the Estonian business register, you confirm that your event meets the content policy and accept these terms, and you pay through Stripe. While you are in checkout we hold the days you chose for 30 minutes. If a payment arrives after the hold has lapsed, we refund it in full automatically and tell you by email.',
          ],
        },
        {
          kind: 'p',
          content: [
            'By bank transfer, through a request. You send a Promotion request with your dates, legal name, registry code, billing email and an optional note, and you accept these terms. A request is not an offer that we must accept. We may grant it, grant it on other dates agreed with you, or decline it with a reason. If we grant it, we invoice you and you pay by bank transfer. A Promotion that is still unpaid when its start date begins is voided and its days are released.',
          ],
        },
        {
          kind: 'p',
          content: [
            'Card checkout is not available for an event that needs a content review. Such an event can be requested instead.',
          ],
        },
      ],
    },
    {
      id: 'invoices',
      heading: '6. Invoices',
      blocks: [
        {
          kind: 'p',
          content: [
            'We issue a VAT invoice in the ER- series (ER-M- for invoices we issue by hand) with our VAT number, your registry code, the event and the Promotion window. Stripe emails card invoices to your billing email, and you can open them from your Promotions list.',
          ],
        },
      ],
    },
    {
      id: 'no-cancel',
      heading: '7. A paid Promotion cannot be cancelled by you',
      blocks: [
        {
          kind: 'p',
          content: [
            'Once a Promotion is paid, or granted free of charge, you cannot cancel it, because its days are reserved against the limit of five and cannot be resold. This does not limit the refunds in section 9 or any right that the law gives you.',
          ],
        },
      ],
    },
    {
      id: 'reasons',
      heading: '8. When we may decline, end early or void',
      blocks: [
        {
          kind: 'p',
          content: [
            'We give you a statement of reasons by email, in your language, whenever we decline a request, end a Promotion early or void it. The grounds are:',
          ],
        },
        {
          kind: 'ul',
          items: [
            [
              'Declining a request: the event is not eligible (not yours, ended, dates outside the rules, or the days are full); the event needs a content review and fails it; we cannot verify the business; or another reason that we state.',
            ],
            [
              'Ending early: your event is cancelled or retracted, or your claim is revoked (this happens automatically); the content breaches the content policy; you breach these terms; we withdraw the feature for everyone; a law or authority requires it; or another reason that we state in writing.',
            ],
            [
              'Voiding: payment has not arrived by the start date, or a card checkout was abandoned or expired. We do not email you about an abandoned checkout.',
            ],
          ],
        },
        {
          kind: 'p',
          content: [
            'You may reply to the contact address to contest a decision; see section 14.',
          ],
        },
      ],
    },
    {
      id: 'refunds',
      heading: '9. Refunds',
      blocks: [
        {
          kind: 'ul',
          items: [
            [
              'If a Promotion stops through our fault, we refund the unused whole days. Days a Promotion was paused through no fault of yours (for example because a duplicate listing won the dedup, or a content flag turned out to be wrong) count as unused.',
            ],
            [
              'If we withdraw the feature (end reason "feature withdrawn"), we refund the unused days in full.',
            ],
            [
              'If your event is cancelled or retracted, the Promotion ends. We refund the unused days at our discretion; you have no right to it.',
            ],
            [
              'Content test: if the content was already restricted when we accepted payment, we refund the unused days. If it changed into breach after payment, we do not. We decide this against the record we keep of what the Promotion displayed. We may refuse a refund where the content attestation was knowingly false.',
            ],
            [
              'Days that have run are not refunded, and low delivery is never a ground for a refund.',
            ],
          ],
        },
        {
          kind: 'p',
          content: [
            'The refund is the unused days plus paused days, multiplied by the price per day that you paid. Card payments are refunded to the card with a credit note that reverses the VAT. Refunds for bank-transfer payments are paid back by bank transfer. A complimentary Promotion has nothing to refund.',
          ],
        },
      ],
    },
    {
      id: 'content-policy',
      heading: '10. Promotion content policy',
      blocks: [
        {
          kind: 'p',
          content: [
            'Your event must not be one of these five kinds, unless we have reviewed it and cleared it in writing for this Promotion:',
          ],
        },
        {
          kind: 'ul',
          items: [
            ['Tobacco: events led by tobacco, vaping or hookah.'],
            [
              'Gambling: for example poker nights, casino evenings and events of betting brands.',
            ],
            [
              'Alcohol: events where alcohol is the main attraction or an alcohol brand is in the title or presents the event, such as a whisky tasting or "Brand X Night". A concert in a bar is not covered.',
            ],
            [
              'Political: events by or for a party, a candidate or a campaign, or about a vote, referendum or bill.',
            ],
            [
              'Weapons: sales of weapons or pyrotechnics. A fireworks show is fine.',
            ],
          ],
        },
        {
          kind: 'p',
          content: [
            'In addition, the content of a Promotion must not be misleading, discriminatory or otherwise breach the Advertising Act.',
          ],
        },
        {
          kind: 'p',
          content: [
            "A restricted event may still be listed on Event Radar and is ranked as usual, but it is not promoted without our review, and we may decline with a stated reason. We may pause or end a Promotion at any time with a statement of reasons; refunds follow section 9. When you pay by card you attest that your event meets this policy, and we store the attestation with the time and the policy version. We keep a record of what each Promotion displayed: the title, the description excerpt, the image, the venue, the dates, the price and the label, taken at payment or grant and again at each edit. A reader's report about your event does not pause a Promotion by itself; we review it.",
          ],
        },
      ],
    },
    {
      id: 'data',
      heading: '11. The data you get',
      blocks: [
        {
          kind: 'p',
          content: [
            'For each Promotion, your Promotions page shows a table per day: whether it was shown or paused (and why), how many times it was shown on Explore, placed in the Daily 5, sent in the morning email and opened, plus one figure for how many different people it was placed for in the Daily 5 across the whole window. The table covers complete days and is updated daily.',
          ],
        },
        {
          kind: 'ul',
          items: [
            [
              '"Shown" and "placed" are not "seen". Known bots are excluded. We do not guarantee any figure.',
            ],
            [
              "These are anonymous totals. You get no viewer identities and no per-viewer data, and no figures about other organizers' Promotions.",
            ],
            [
              'You keep access to the report of a Promotion you bought even if your ownership of the event later lapses.',
            ],
          ],
        },
        {
          kind: 'p',
          content: [
            'What we hold about a Promotion: the commercial record (your legal name, registry code, billing email, price, VAT rate, invoice, dates, the versions of these terms and the content policy that you accepted), the content record in section 10 and the daily totals. Third parties that handle it: Stripe (card payments and invoices), Resend (email), our hosting providers (Render, Cloudflare, Neon) and the Estonian business register (name lookup). The ',
            { text: 'Privacy Policy', to: ROUTES.privacy },
            ' covers personal data.',
          ],
        },
      ],
    },
    {
      id: 'liability',
      heading: '12. Liability',
      blocks: [
        {
          kind: 'p',
          content: [
            'To the extent the law allows, our liability to you for a Promotion is limited to the price you paid for it, except for intent or gross negligence. We do not guarantee uninterrupted service. ',
            { operator: 'liabilityCounsel' },
          ],
        },
      ],
    },
    {
      id: 'changes',
      heading: '13. Changes to these terms',
      blocks: [
        {
          kind: 'p',
          content: [
            'We give you 15 days\' notice of any substantive change to these terms or to How results are ordered, by email to the address of every organizer account, together with a dated "what changed" note at the top of this page. Corrections that change no right or duty need no notice. A Promotion you have already paid for keeps running on the terms it was bought under.',
          ],
        },
        {
          kind: 'p',
          content: [
            'Version history: 1 — ',
            { operator: 'dateInForce' },
            ' — first version.',
          ],
        },
      ],
    },
    {
      id: 'law',
      heading: '14. Complaints, governing law and disputes',
      blocks: [
        {
          kind: 'p',
          content: [
            'Complaints: write to ',
            { text: CONTACT_EMAIL, href: CONTACT_MAILTO },
            '. We answer within ',
            { operator: 'complaintReplyDays' },
            ' working days, with reasons. If we cannot settle a dispute, you may turn to one of these mediators: ',
            { operator: 'mediator1' },
            ', ',
            { operator: 'mediator2' },
            '.',
          ],
        },
        {
          kind: 'p',
          content: [
            'These terms are governed by the laws of Estonia. Disputes go to ',
            { operator: 'court' },
            ', without prejudice to any right that the law gives you.',
          ],
        },
      ],
    },
  ],
};

export default doc;
