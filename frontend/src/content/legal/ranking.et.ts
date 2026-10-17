import type { LegalDoc } from './types';

const doc: LegalDoc = {
  title: 'Kuidas tulemused järjestatakse',
  lastUpdated: '2026-10-17',
  intro: [
    {
      kind: 'p',
      content: [
        'Siin on selgitatud, milliseid üritusi Event Radar näitab ja mis nende järjekorda peamiselt mõjutab. Signaalid on toodud tähtsuse järjekorras. Täpseid kaalusid me ei avalda.',
      ],
    },
  ],
  sections: [
    {
      id: 'eligible',
      heading: 'Milliseid üritusi näitame',
      blocks: [
        {
          kind: 'p',
          content: [
            'Ainult avaldatud üritused, mis pole veel lõppenud, Tallinnas ja selle ümbruses. Kui mitu saiti pakub sama üritust, näitame üht kuulutust.',
          ],
        },
        {
          kind: 'p',
          content: [
            'Välja jätame kuulutused, mis jäävad alla meie kvaliteedilati, ebasündsa sisu ning asjad, mis ei ole üritused, näiteks kinkekaardid, kaubad ja veebiseminarid.',
          ],
        },
      ],
    },
    {
      id: 'relevance',
      heading: 'Avastamise "Asjakohasus"',
      blocks: [
        {
          kind: 'p',
          content: ['Sisse logituna, tähtsamast vähemtähtsani:'],
        },
        {
          kind: 'ol',
          items: [
            ['Sinu maitse, ehk kategooriad ja meeleolud, mille valisid.'],
            ['Kui varsti üritus algab ning sinu meeldimised ja mittemeeldimised. Need on võrdse kaaluga.'],
            ['Kuulutuse kvaliteet.'],
            ['Tallinna kesklinna üritused tõusevad veidi kõrgemale.'],
          ],
        },
        {
          kind: 'p',
          content: ['Sisse logimata, tähtsamast vähemtähtsani:'],
        },
        {
          kind: 'ol',
          items: [
            ['Kui varsti üritus algab.'],
            ['Kuulutuse kvaliteet.'],
            ['Tallinna kesklinna üritused tõusevad veidi kõrgemale.'],
          ],
        },
      ],
    },
    {
      id: 'sorts',
      heading: 'Muud sortimised',
      blocks: [
        {
          kind: 'ul',
          items: [
            ['Kuupäev: esimesena see, mis algab kõige varem.'],
            ['Hind: esimesena odavaim, tasuta üritused kõige ees.'],
            ['Kvaliteet: esimesena kõige täielikumad kuulutused.'],
          ],
        },
      ],
    },
    {
      id: 'daily-5',
      heading: 'Päeva 5 ja hommikune e-kiri',
      blocks: [
        {
          kind: 'p',
          content: [
            'Sinu Päeva 5 ja hommikune e-kiri kasutavad samu signaale nagu sisse logitud asjakohasus, lisaks mõned reeglid:',
          ],
        },
        {
          kind: 'ul',
          items: [
            ['Segame kategooriaid, et üks üritusetüüp ei võtaks kõike üle.'],
            ['Korduvat ürituste sarja ei näita me mõne päeva jooksul uuesti.'],
            ['Ürituse, mis sulle ei meeldi, jätame välja koos selle duplikaatidega.'],
          ],
        },
      ],
    },
    {
      id: 'organizers',
      heading: 'Korraldajatele',
      blocks: [
        {
          kind: 'p',
          content: [
            'Täielikum kuulutus saab parema koha: täpsed andmed, pildid ja kirjeldus. Orgaanilist järjekorda ei saa keegi raha eest muuta.',
          ],
        },
      ],
    },
  ],
};

export default doc;
