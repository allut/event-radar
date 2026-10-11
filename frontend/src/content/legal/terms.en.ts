import { CONTACT_EMAIL, CONTACT_MAILTO, ODR_URL } from '../../constants/core';
import type { LegalDoc } from './types';

const doc: LegalDoc = {
  title: 'Terms of Service',
  lastUpdated: '2026-09-13',
  intro: [],
  sections: [
    {
      heading: '1. Acceptance',
      blocks: [
        {
          kind: 'p',
          content: [
            'By using Event Radar (the "Service") you agree to these Terms. If you do not agree, please do not use the Service.',
          ],
        },
      ],
    },
    {
      heading: '2. The Service',
      blocks: [
        {
          kind: 'p',
          content: [
            'Event Radar is a free service that discovers, deduplicates and personalises public events in Tallinn, Estonia, including a curated "Daily 5" feed and an optional email digest. We aggregate event information from third-party sources; we do not organise, host, or sell tickets to events.',
          ],
        },
      ],
    },
    {
      heading: '3. Eligibility and your account',
      blocks: [
        {
          kind: 'p',
          content: [
            'You must be at least 13 years old to use the Service. You sign in with a one-time link sent to your email; you are responsible for the security of your email inbox and for activity under your account. One account per person.',
          ],
        },
      ],
    },
    {
      heading: '4. Acceptable use',
      blocks: [
        {
          kind: 'p',
          content: [
            'You agree not to: use the Service unlawfully; scrape, harvest, or access it by automated means beyond normal personal use; interfere with or attempt to breach its security or infrastructure; overload or disrupt it; or misuse another person’s account. We may suspend access for breach.',
          ],
        },
      ],
    },
    {
      heading: '5. Third-party events and content — important',
      blocks: [
        {
          kind: 'p',
          content: [
            'Event details (times, prices, venues, availability, images and descriptions) are aggregated from third-party sources and may be inaccurate, incomplete, or out of date. Always confirm details with the official organiser or ticket seller before you rely on them or attend. We are not a party to any transaction between you and an organiser, venue or ticket seller, and are not responsible for third-party events, content, websites, or dealings. External links are provided for convenience only.',
          ],
        },
      ],
    },
    {
      heading: '6. Intellectual property',
      blocks: [
        {
          kind: 'p',
          content: [
            'The Service’s software, design, branding and compilation are ours or our licensors’. Event data belongs to its respective sources. By submitting feedback signals (likes, dislikes, bookmarks) you grant us a licence to use them to operate and improve the Service.',
          ],
        },
      ],
    },
    {
      heading: '7. No warranty',
      blocks: [
        {
          kind: 'p',
          content: [
            'The Service is provided "as is" and "as available", without warranties of any kind, express or implied, including as to accuracy, completeness, availability, or fitness for a particular purpose. We do not guarantee uninterrupted or error-free operation.',
          ],
        },
      ],
    },
    {
      heading: '8. Limitation of liability',
      blocks: [
        {
          kind: 'p',
          content: [
            'To the maximum extent permitted by law, we are not liable for any indirect, incidental, special or consequential damages, or for loss arising from your reliance on event information or from third-party events. Nothing in these Terms excludes or limits liability that cannot be excluded or limited under applicable law, including your mandatory rights as a consumer under EU and Estonian law, which are unaffected.',
          ],
        },
      ],
    },
    {
      heading: '9. Suspension and termination',
      blocks: [
        {
          kind: 'p',
          content: [
            'We may suspend or terminate access for breach of these Terms or to protect the Service. You may stop using the Service and request deletion of your account at any time (',
            { text: CONTACT_EMAIL, href: CONTACT_MAILTO },
            ').',
          ],
        },
      ],
    },
    {
      heading: '10. Changes',
      blocks: [
        {
          kind: 'p',
          content: [
            'We may change the Service or these Terms; the "Last updated" date shows the current version. Continued use after a change means you accept the updated Terms.',
          ],
        },
      ],
    },
    {
      heading: '11. Governing law and disputes',
      blocks: [
        {
          kind: 'p',
          content: [
            'These Terms are governed by the laws of Estonia. Disputes are subject to the competent Estonian courts, without prejudice to any mandatory consumer-protection rights or to your right to bring proceedings in your country of residence. EU consumers may also use the European Commission’s Online Dispute Resolution platform (',
            { text: ODR_URL, href: ODR_URL },
            ').',
          ],
        },
      ],
    },
    {
      heading: '12. Contact',
      blocks: [
        {
          kind: 'p',
          content: [{ text: CONTACT_EMAIL, href: CONTACT_MAILTO }, '.'],
        },
      ],
    },
  ],
};

export default doc;
