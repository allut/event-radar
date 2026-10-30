import { CONTACT_EMAIL, CONTACT_MAILTO } from '../../constants/core';
import { ROUTES } from '../../constants/routes';
import { SPONSORED_RANKING_TARGET } from '../../constants/sponsored';
import type { FaqDoc } from './types';

const doc: FaqDoc = {
  lastUpdated: '2026-10-18',
  seoTitle: 'Frequently asked questions',
  metaDescription:
    "How Event Radar works: where Tallinn's events come from, how your Daily 5 is picked, the morning email, your data, and how organizers list or claim events.",
  title: 'Frequently asked questions',
  lede: 'How Event Radar works, for people looking for something to do and for the organizers behind the events.',
  jumpNavLabel: 'On this page',
  answerLinkLabel: 'Link to this answer',
  sections: [
    {
      id: 'about',
      heading: 'About Event Radar',
      items: [
        {
          id: 'what-is-event-radar',
          question: 'What is Event Radar?',
          answer: [
            {
              kind: 'p',
              content: [
                'Event Radar is a guide to events in Tallinn. Every morning it picks five events for you based on what you like: your Daily 5. You can also browse every upcoming event in Explore.',
              ],
            },
          ],
        },
        {
          id: 'is-it-free',
          question: 'Is it free?',
          answer: [
            {
              kind: 'p',
              content: [
                "Yes, for event-goers and for organizers. There's no fee, and nobody can pay to be shown higher.",
              ],
              gate: 'slotsOff',
            },
            {
              kind: 'p',
              content: [
                'Yes. Event Radar is free for event-goers, and listing events is free for organizers. Organizers can pay for a labelled ad spot, but nobody can pay to move up the regular results or your Daily 5. ',
                { text: 'How ads work', to: SPONSORED_RANKING_TARGET },
              ],
              gate: 'slotsOn',
            },
          ],
        },
        {
          id: 'where-events-come-from',
          question: 'Where do the events come from?',
          answer: [
            {
              kind: 'p',
              content: [
                'From ticket sites such as Fienta and Piletilevi, from museums and concert halls, and from organizers who list their own events. We use AI to sort each event into categories and to spot when several sites list the same event, so it appears only once.',
              ],
            },
          ],
        },
        {
          id: 'only-tallinn',
          question: 'Is it only Tallinn?',
          answer: [{ kind: 'p', content: ['Yes, for now: Tallinn and the area around it.'] }],
        },
        {
          id: 'languages',
          question: 'Which languages does it support?',
          answer: [
            { kind: 'p', content: ['The site works in Estonian, English and Russian.'] },
            {
              kind: 'p',
              content: [
                `An event's title and description appear in your language when the organizer or ticket site publishes that version. We don't machine-translate them. If your language is missing, you see the English version, or else the original. The short "Why go" notes are written by AI in all three languages.`,
              ],
            },
          ],
        },
      ],
    },
    {
      id: 'event-goers',
      heading: 'For event-goers',
      items: [
        {
          id: 'need-an-account',
          question: 'Do I need an account?',
          answer: [
            {
              kind: 'p',
              content: [
                'Not to browse Explore or open an event. You need one for your Daily 5, to like, dislike or bookmark events, for the morning email, and to report a listing.',
              ],
            },
          ],
        },
        {
          id: 'sign-in',
          question: 'How do I sign in? Why is there no password?',
          answer: [
            {
              kind: 'p',
              content: [
                "Enter your email address and we'll send you a sign-in link. It works once and expires after 15 minutes. You can also sign in with Google. With no password, there's nothing to forget or to leak. You stay signed in for 2 days, then sign in again.",
              ],
            },
          ],
        },
        {
          id: 'daily-5',
          question: 'How is my Daily 5 picked?',
          answer: [
            {
              kind: 'p',
              content: [
                "From the tastes you chose when you signed up, your likes and dislikes, how good the listing looks and how soon the event is. We mix categories so one kind of event doesn't take over.",
              ],
            },
            {
              kind: 'p',
              content: [
                "AI sorts every event into categories and moods, which is how events are matched to your tastes. Your first Daily 5 is ready as soon as you've picked your tastes, and a new one is ready early each morning.",
              ],
            },
            {
              kind: 'p',
              content: [{ text: 'How results are ordered', to: ROUTES.ranking }],
            },
          ],
        },
        {
          id: 'email',
          question: 'When does the email arrive, and how do I stop it?',
          answer: [
            {
              kind: 'p',
              content: [
                "In the morning, with that day's Daily 5. On a day with no picks for you, no email is sent. The email is switched on when you create your account. To stop it, use the unsubscribe link in any email (or your mail app's unsubscribe button), or turn it off in Settings. You can turn it back on in Settings at any time.",
              ],
            },
          ],
        },
        {
          id: 'paid-on-event-radar',
          question: 'Are there ads on Event Radar?',
          gate: 'slotsOn',
          answer: [
            {
              kind: 'p',
              content: [
                'Organizers can pay for a labelled spot next to the results: at most one card on the first page of Explore, and at most one separate card after your Daily 5. It is marked "Ad" and names the business that paid. When nothing fits, the spot stays empty and nothing takes its place.',
              ],
            },
            {
              kind: 'p',
              content: [{ text: 'How ads work', to: SPONSORED_RANKING_TARGET }],
            },
          ],
        },
        {
          id: 'paid-change-results',
          question: 'Do ads change my results or my Daily 5?',
          gate: 'slotsOn',
          answer: [
            {
              kind: 'p',
              content: [
                'No. Results and your five picks are ranked exactly as they would be without ads. An ad never takes a place in the order and never replaces one of your five. Paying cannot move an event up.',
              ],
            },
          ],
        },
        {
          id: 'paid-chosen',
          question: 'Are ads picked from my interests?',
          gate: 'slotsOn',
          answer: [
            {
              kind: 'p',
              content: [
                'No. An ad is chosen by context: the page, the day and, on Explore, the filters and search you set. Your tastes, likes and history are not used to pick it. They are used only to keep ads away: an event you disliked, reported, saved or liked is never advertised to you. Press "Why?" on any ad to see its one-line explanation.',
              ],
            },
          ],
        },
        {
          id: 'paid-in-email',
          question: 'Do I get ads in the morning email?',
          gate: 'slotsOn',
          answer: [
            {
              kind: 'p',
              content: [
                'Only if you ask. Ads in the email are off by default. You can switch them on in Settings, under the email setting, with "Include ads in my Daily Five email". Then the email may carry at most one paid event below your picks, marked "Ad". It is never mentioned in the subject.',
              ],
            },
            {
              kind: 'p',
              content: [
                'To stop, use "Stop ads in this email" in any email that carries one, or turn the setting off in Settings. Unsubscribing from the email also turns ads off, and they stay off if you subscribe again.',
              ],
            },
          ],
        },
        {
          id: 'paid-data',
          question: 'What do you record about ads?',
          gate: 'slotsOn',
          answer: [
            {
              kind: 'p',
              content: [
                'Anonymous daily totals for each ad: how often it was shown and how often it was opened. They contain nothing about you, and we do not track whether you open our emails. Advertisers get only these totals, never who saw or clicked an ad. Known bots are not counted. If you turn on ads in the email, we also keep a record of when you did and what you agreed to. The ',
                { text: 'Privacy Policy', to: ROUTES.privacy },
                ' has the details.',
              ],
            },
          ],
        },
        {
          id: 'like-dislike-bookmark',
          question: 'What do like, dislike and bookmark do?',
          answer: [
            {
              kind: 'p',
              content: [
                'An event can have only one of the three at a time. Choosing another replaces it.',
              ],
            },
            {
              kind: 'ul',
              items: [
                ['Like: that event, and others in the same categories, rank higher for you.'],
                [
                  "Dislike: the event disappears from your Daily 5 and from For you in Explore. For you also stops showing other events in that event's categories. It's still listed under All events.",
                ],
                ['Bookmark: keeps the event for later.'],
              ],
            },
            {
              kind: 'p',
              content: ['Saved has a tab for each: Bookmarked, Liked and Disliked.'],
            },
          ],
        },
        {
          id: 'change-tastes',
          question: 'Can I change my tastes later?',
          answer: [
            {
              kind: 'p',
              content: ['Yes. In Settings, choose Change persona and pick up to 3 tastes again.'],
            },
          ],
        },
        {
          id: 'event-missing',
          question: "Why isn't an event I know about listed?",
          answer: [
            {
              kind: 'p',
              content: [
                "We collect events from ticket sites, museums and concert halls, and from organizers who add their own. Some events aren't published anywhere we read, or take place outside Tallinn. If you know one we've missed, ",
                { text: 'tell us', to: ROUTES.contact },
                ". If it's your event, you can ",
                { text: 'list it yourself', to: ROUTES.organizerLogin },
                '.',
              ],
            },
          ],
        },
        {
          id: 'report-listing',
          question: "A listing is wrong or shouldn't be here. What do I do?",
          answer: [
            {
              kind: 'p',
              content: [
                "Open the event, choose Report event from its menu and pick a reason. You need to be signed in to report. We'll email you once we've dealt with it. Not signed in? ",
                { text: 'Write to us', to: ROUTES.contact },
                ' instead.',
              ],
            },
          ],
        },
        {
          id: 'data-and-tracking',
          question: 'What data do you keep? Do you track me?',
          answer: [
            {
              kind: 'p',
              content: [
                "We keep your email address, your language, the tastes you picked, your morning-email setting, and what you do on the site: likes, dislikes, bookmarks, the events you open and the ticket links you click. That's what your Daily 5 is built from.",
              ],
            },
            {
              kind: 'p',
              content: [
                'We set one cookie, to keep you signed in, and we run no analytics or advertising trackers. The ',
                { text: 'Privacy Policy', to: ROUTES.privacy },
                ' has the full list.',
              ],
            },
          ],
        },
        {
          id: 'delete-account',
          question: 'How do I delete my account?',
          answer: [
            {
              kind: 'p',
              content: [
                'Email us at ',
                { text: CONTACT_EMAIL, href: CONTACT_MAILTO },
                " and we'll delete it. The ",
                { text: 'Privacy Policy', to: ROUTES.privacy },
                ' explains your other rights.',
              ],
            },
          ],
        },
      ],
    },
    {
      id: 'organizers',
      heading: 'For organizers',
      items: [
        {
          id: 'list-my-event',
          question: 'How do I list my event? Does it cost anything?',
          answer: [
            {
              kind: 'p',
              content: [
                "It's free. Sign in to the ",
                { text: 'organizer portal', to: ROUTES.organizerLogin },
                ' with an email link or Google, then fill in the event form.',
              ],
            },
          ],
        },
        {
          id: 'first-event-not-live',
          question: "Why isn't my first event live yet?",
          answer: [
            {
              kind: 'p',
              content: [
                "A person reviews each new organizer's first event. Once it's approved, it goes live along with any others you've submitted. After that, your events go live within seconds, as long as they pass our automatic checks. You can see each event's status on your dashboard. We don't send an email when it's approved.",
              ],
            },
          ],
        },
        {
          id: 'organizer-languages',
          question: 'Which languages should I write in?',
          answer: [
            {
              kind: 'p',
              content: [
                "Only the Estonian title is required. You can also add English and Russian titles and descriptions, and readers of those languages will see them. A reader whose language you haven't filled in sees English, or Estonian if there's no English.",
              ],
            },
          ],
        },
        {
          id: 'claim-event',
          question: 'My event is already on Event Radar. Can I take it over?',
          answer: [
            {
              kind: 'p',
              content: [
                "Yes, by claiming it. Open the event and choose Claim this event, or search for it from your organizer dashboard. Then prove it's yours: with a code in your ticket listing, a record on your website's domain, or your email address, or by sending a short note that we review. The claim screen shows which ways work for your event. An unfinished claim expires after 7 days, or after 30 days if it's waiting for our review.",
              ],
            },
          ],
        },
        {
          id: 'claimed-edits',
          question: 'After I claim it, will my edits get overwritten?',
          answer: [
            {
              kind: 'p',
              content: [
                "No. Our overnight update skips the text you've edited, and never changes the image, dates, link or categories you set. Two things still follow the source: the venue and address, and the price, which always matches the ticket page. If the price changes, the edit screen tells you. Languages you haven't written yet are filled in from the source when it has them.",
              ],
            },
          ],
        },
      ],
    },
  ],
  contact: {
    heading: 'Still have a question?',
    body: 'Write to us and a person will reply by email.',
    cta: 'Contact us',
  },
};

export default doc;
