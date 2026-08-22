import { CONTACT_EMAIL, CONTACT_MAILTO } from '../../constants';
import type { LegalDoc } from './types';

const AKI_URL = 'https://www.aki.ee';

const doc: LegalDoc = {
  title: 'Privacy Policy',
  lastUpdated: '2026-08-11',
  intro: [
    {
      kind: 'p',
      content: [
        'What’s on Radar ("we", "us", "the Service") is an event-discovery service for Tallinn, Estonia. This policy explains what personal data we collect, why, how long we keep it, who we share it with, and the rights you have under the EU General Data Protection Regulation (GDPR).',
      ],
    },
  ],
  sections: [
    {
      heading: '1. Who is responsible for your data (Controller)',
      blocks: [
        {
          kind: 'p',
          content: [
            'The data controller is Aleksei Lutkov, operating What’s on Radar as a sole trader in Estonia. For any privacy question or to exercise your rights, contact ',
            { text: CONTACT_EMAIL, href: CONTACT_MAILTO },
            '.',
          ],
        },
      ],
    },
    {
      heading: '2. What we collect',
      blocks: [
        {
          kind: 'ul',
          items: [
            ['Your email address — you sign in with a one-time "magic link"; we use no passwords.'],
            ['Your preferences — interface language (Estonian, English or Russian) and, optionally, your home city.'],
            ['Your taste profile — the personas you pick during onboarding, used to personalise your feed.'],
            ['Your activity in the app — the events you like, dislike, bookmark, view, or whose ticket links you click. We use these signals to rank and personalise your "Daily 5".'],
            ['Email digest preference — whether you have opted in to the daily email digest.'],
            ['Technical data — your IP address and standard request information, processed transiently for security, rate-limiting and abuse prevention, and short-lived server logs.'],
          ],
        },
        {
          kind: 'p',
          content: [
            'We do not collect passwords, payment data, precise/GPS location, or special-category (sensitive) data such as health, religion or ethnicity.',
          ],
        },
      ],
    },
    {
      heading: '3. Why we process it, and our legal basis (GDPR Art. 6)',
      blocks: [
        {
          kind: 'ul',
          items: [
            ['To provide the Service — sign-in, your account, and the personalised feed: performance of a contract and our legitimate interest in operating the Service (Art. 6(1)(b),(f)).'],
            ['The email digest — your consent (Art. 6(1)(a)); opt-in, and withdrawable at any time.'],
            ['Security, rate-limiting, abuse prevention and logging — our legitimate interest in keeping the Service safe and available (Art. 6(1)(f)).'],
            ['Aggregate, privacy-friendly analytics — our legitimate interest in understanding overall usage and performance (Art. 6(1)(f)).'],
          ],
        },
      ],
    },
    {
      heading: '4. Cookies, local storage and analytics',
      blocks: [
        {
          kind: 'p',
          content: [
            'We use one strictly-necessary cookie: a signed, httpOnly session cookie that keeps you signed in. It carries no advertising or tracking purpose and cannot be read by scripts running on the page. Because it is strictly necessary for the Service to function, no cookie-consent banner is required. Your language choice, and a boolean "you’re signed in" flag that carries no credential, are stored in your browser’s local storage. Our usage and performance analytics (Vercel Web Analytics, Speed Insights, and Google Analytics) are cookieless and aggregated; page URLs are masked before they reach any analytics provider, so no event identifier or session credential is ever sent, and Google Analytics is configured to never set a persistent identifier cookie.',
          ],
        },
      ],
    },
    {
      heading: '5. Who we share data with (processors and recipients)',
      blocks: [
        {
          kind: 'p',
          content: [
            'We never sell your data or share it with advertisers. We use a small set of service providers who process data only on our instructions, under data-processing agreements:',
          ],
        },
        {
          kind: 'ul',
          items: [
            ['Neon — database hosting (EU region, Frankfurt, Germany).'],
            ['Render — backend application hosting.'],
            ['Vercel — frontend hosting and the cookieless Vercel analytics above.'],
            ['Google — the cookieless Google Analytics above.'],
            ['Resend — delivery of sign-in and digest emails.'],
          ],
        },
        {
          kind: 'p',
          content: [
            'Providers that process event data only, never your personal data: our language-model providers (Groq, Cerebras, Mistral) classify public event listings; OpenStreetMap Nominatim geocodes event venue addresses; cron-job.org pings the Service to keep it awake. We may also disclose data where required by law.',
          ],
        },
      ],
    },
    {
      heading: '6. International transfers',
      blocks: [
        {
          kind: 'p',
          content: [
            'Your core account data is stored in the EU (Frankfurt, Germany). Some providers (e.g. Render, Vercel) are US-based; where personal data is transferred outside the EEA, it is protected by the European Commission’s Standard Contractual Clauses and the providers’ data-processing terms.',
          ],
        },
      ],
    },
    {
      heading: '7. How long we keep it',
      blocks: [
        {
          kind: 'ul',
          items: [
            ['Sign-in (session) tokens: 2 days; they are signed, not stored on our servers.'],
            ['Magic-link tokens: 7 days, single-use.'],
            ['Technical/audit records (raw ingest data, request/processing logs): up to 90 days.'],
            ['Feed snapshots and cached ranking scores: up to 30 days.'],
            ['Account data (email, preferences, taste profile, feedback): kept while your account is active, and deleted on request (see below). We keep event listings indefinitely, but these are public event information, not personal data about you.'],
          ],
        },
      ],
    },
    {
      heading: '8. Your rights',
      blocks: [
        {
          kind: 'p',
          content: [
            'Under the GDPR you have the right to: access your data; rectify inaccurate data; erase your data ("right to be forgotten"); restrict or object to processing; data portability; and to withdraw consent at any time (this does not affect processing already carried out). You can unsubscribe from the digest from any digest email or from the unsubscribe page. To exercise any right, email ',
            { text: CONTACT_EMAIL, href: CONTACT_MAILTO },
            '; we respond within one month. You also have the right to lodge a complaint with your supervisory authority — in Estonia, the Andmekaitse Inspektsioon (Estonian Data Protection Inspectorate), ',
            { text: AKI_URL, href: AKI_URL },
            '.',
          ],
        },
      ],
    },
    {
      heading: '9. How we protect your data',
      blocks: [
        {
          kind: 'p',
          content: [
            'Data is encrypted in transit (HTTPS/TLS) and stored in an EU-hosted database. Magic-link tokens are hashed and single-use; session tokens are signed and can be revoked. We follow OWASP security practices and apply access controls. If a data breach is likely to risk your rights, we will notify the supervisory authority within 72 hours and, where required, inform you.',
          ],
        },
      ],
    },
    {
      heading: '10. Children',
      blocks: [
        {
          kind: 'p',
          content: [
            'The Service is not directed at children under 13 (the age of digital consent in Estonia). We do not knowingly collect data from children; if you believe a child has provided us data, contact us and we will delete it.',
          ],
        },
      ],
    },
    {
      heading: '11. Changes to this policy',
      blocks: [
        {
          kind: 'p',
          content: [
            'We may update this policy; the "Last updated" date shows the current version. Material changes will be signalled in the app.',
          ],
        },
      ],
    },
    {
      heading: '12. Contact',
      blocks: [
        {
          kind: 'p',
          content: [
            'Questions or requests: ',
            { text: CONTACT_EMAIL, href: CONTACT_MAILTO },
            '.',
          ],
        },
      ],
    },
  ],
};

export default doc;
