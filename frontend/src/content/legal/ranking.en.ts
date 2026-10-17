import type { LegalDoc } from './types';

const doc: LegalDoc = {
  title: 'How results are ordered',
  lastUpdated: '2026-10-17',
  intro: [
    {
      kind: 'p',
      content: [
        'This page explains which events Event Radar can show and the main things that decide their order. It names the signals from most to least important. It does not give the exact weights.',
      ],
    },
  ],
  sections: [
    {
      id: 'eligible',
      heading: 'Which events we show',
      blocks: [
        {
          kind: 'p',
          content: [
            'Only published events that have not ended, in and around Tallinn. When several sites list the same event, we show one listing.',
          ],
        },
        {
          kind: 'p',
          content: [
            'We leave out listings below our quality bar, explicit content, and things that are not events, such as gift cards, merchandise and webinars.',
          ],
        },
      ],
    },
    {
      id: 'relevance',
      heading: 'Explore "Relevance"',
      blocks: [
        {
          kind: 'p',
          content: ['When you are signed in, from most to least important:'],
        },
        {
          kind: 'ol',
          items: [
            ['Your tastes, the categories and moods you chose.'],
            ['How soon the event starts, and your likes and dislikes. These count equally.'],
            ['Listing quality.'],
            ['Events in central Tallinn rank slightly higher.'],
          ],
        },
        {
          kind: 'p',
          content: ['When you are signed out, from most to least important:'],
        },
        {
          kind: 'ol',
          items: [
            ['How soon the event starts.'],
            ['Listing quality.'],
            ['Events in central Tallinn rank slightly higher.'],
          ],
        },
      ],
    },
    {
      id: 'sorts',
      heading: 'The other sorts',
      blocks: [
        {
          kind: 'ul',
          items: [
            ['Date: the soonest start first.'],
            ['Price: the cheapest first, free events at the top.'],
            ['Quality: the most complete listings first.'],
          ],
        },
      ],
    },
    {
      id: 'daily-5',
      heading: 'Daily 5 and the morning email',
      blocks: [
        {
          kind: 'p',
          content: [
            'Your Daily 5 and the morning email use the same signals as signed-in Relevance, with a few extra rules:',
          ],
        },
        {
          kind: 'ul',
          items: [
            ['We mix categories so one kind of event does not take over.'],
            ['A recurring series does not come back for a few days.'],
            ['An event you dislike is left out, along with its duplicates.'],
          ],
        },
      ],
    },
    {
      id: 'organizers',
      heading: 'For organizers',
      blocks: [
        {
          kind: 'p',
          content: [
            'A more complete listing ranks better: full details, images and a description. Nobody can pay to change the organic order.',
          ],
        },
      ],
    },
  ],
};

export default doc;
