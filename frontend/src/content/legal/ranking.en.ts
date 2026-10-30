import { ROUTES } from '../../constants/routes';
import { RANKING_PAID_SLOTS_ID } from '../../constants/sponsored';
import type { LegalDoc } from './types';

const doc: LegalDoc = {
  title: 'How results are ordered',
  lastUpdated: '2026-10-17',
  lastUpdatedSlots: '2026-10-18',
  intro: [
    {
      kind: 'p',
      content: [
        'This page explains which events Event Radar can show and the main things that decide their order. It names the signals from most to least important. It does not give the exact weights.',
      ],
    },
    {
      kind: 'p',
      content: [
        'It also explains how paid ads fit around the results without changing them.',
      ],
      gate: 'slotsOn',
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
      id: RANKING_PAID_SLOTS_ID,
      heading: 'Ads',
      gate: 'slotsOn',
      blocks: [
        {
          kind: 'p',
          content: [
            'Organizers can pay for a spot beside the results. We call it a Sponsored slot. A slot is a normal event card with a caption that reads "Ad" and names the business that paid. It is not one of the results: it takes no place in the order, and no result is dropped to make room for it.',
          ],
        },
        {
          kind: 'p',
          content: ['Where a slot can appear:'],
        },
        {
          kind: 'ul',
          items: [
            [
              'Explore: at most one, on the first page only, in the position of the fourth card. It appears only when the page has at least six results.',
            ],
            [
              'Daily 5: at most one separate card after your five, never numbered as a sixth pick. It appears only when you have a full five.',
            ],
            [
              'The morning email: at most one, below your picks, and only if you switched on "Include ads in my Daily Five email" in Settings. It is off unless you turn it on.',
            ],
          ],
        },
        {
          kind: 'p',
          content: [
            'How a slot is chosen: by context, meaning the page, the day and, on Explore, the filters and search you have active. It is never chosen from your interests, tastes, likes or history. When filters or a search are active, only an event that matches all of them can fill the slot. Your own signals can only keep an ad away from you: we never advertise an event you disliked, reported, saved or liked, or one that is already on your screen. If nothing qualifies, the slot stays empty and nothing takes its place. Every live ad costs the same and gets an equal share.',
          ],
        },
        {
          kind: 'p',
          content: ['What ads never do:'],
        },
        {
          kind: 'ul',
          items: [
            [
              'They never change the order of results. Explore, Daily 5 and the morning email are ranked exactly as they would be with no ads.',
            ],
            ['They never replace one of your five.'],
            [
              'Seeing or opening an ad does not change your taste profile or your ranking. If you press "Dislike" on an ad, that event is left out of your results like any other disliked event.',
            ],
          ],
        },
        {
          kind: 'p',
          content: [
            'Every ad has a "Why?" button that explains in one sentence why you are seeing it.',
          ],
        },
        {
          kind: 'p',
          content: [
            'We count how often each ad was shown and opened, only as anonymous daily totals that contain nothing about you. Advertisers never receive data about you. The ',
            { text: 'Privacy Policy', to: ROUTES.privacy },
            ' has the details.',
          ],
        },
        {
          kind: 'p',
          content: [
            'In the morning email you can switch ads off with one click on "Stop ads in this email", or in Settings.',
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
          gate: 'slotsOff',
        },
        {
          kind: 'p',
          content: [
            'A more complete listing ranks better: full details, images and a description. Nobody can pay to change the organic order. Payment buys a labelled slot only, as described under Ads above.',
          ],
          gate: 'slotsOn',
        },
      ],
    },
  ],
};

export default doc;
