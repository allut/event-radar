import { ROUTES } from '../../constants/routes';
import { RANKING_PAID_SLOTS_ID } from '../../constants/sponsored';
import type { LegalDoc } from './types';

const doc: LegalDoc = {
  title: 'Kuidas tulemused järjestatakse',
  lastUpdated: '2026-10-17',
  lastUpdatedSlots: '2026-10-18',
  intro: [
    {
      kind: 'p',
      content: [
        'Siin on selgitatud, milliseid üritusi Event Radar näitab ja mis nende järjekorda peamiselt mõjutab. Signaalid on toodud tähtsuse järjekorras. Täpseid kaalusid me ei avalda.',
      ],
    },
    {
      kind: 'p',
      content: [
        'Samuti selgitab see leht, kuidas tasuline reklaam tulemuste kõrval asub, neid muutmata.',
      ],
      gate: 'slotsOn',
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
      id: RANKING_PAID_SLOTS_ID,
      heading: 'Reklaam',
      gate: 'slotsOn',
      blocks: [
        {
          kind: 'p',
          content: [
            'Korraldajad saavad maksta koha eest tulemuste kõrval. Me nimetame seda reklaamikohaks. Reklaamikoht on tavaline ürituse kaart, millel on märge „Reklaam” ja selle eest maksnud ettevõtte nimi. See ei ole üks tulemustest: sel pole kohta järjestuses ja ükski tulemus ei jää selle pärast välja.',
          ],
        },
        {
          kind: 'p',
          content: ['Kus reklaamikoht võib olla:'],
        },
        {
          kind: 'ul',
          items: [
            [
              'Avasta: kuni üks, ainult esimesel lehel, neljanda kaardi kohal. See on olemas ainult siis, kui lehel on vähemalt kuus tulemust.',
            ],
            [
              'Päeva 5: kuni üks eraldi kaart sinu viie valiku järel, mida ei nummerdata kuuendaks valikuks. See on olemas ainult siis, kui sul on täis viis valikut.',
            ],
            [
              "Hommikune e-kiri: kuni üks, sinu valikute all, ja ainult siis, kui oled Seadetes sisse lülitanud valiku „Näita mu Daily Five'i kirjas reklaami”. See on väljas, kuni sa selle ise sisse lülitad.",
            ],
          ],
        },
        {
          kind: 'p',
          content: [
            'Kuidas reklaamikoht valitakse: konteksti järgi ehk lehe, päeva ja Avastamises sinu aktiivsete filtrite ja otsingu järgi. Seda ei valita kunagi sinu huvide, maitse, meeldimiste ega tegevuse põhjal. Kui filtrid või otsing on sees, võib koha täita ainult üritus, mis vastab neile kõigile. Sinu enda signaalid saavad reklaami sinu eest ainult eemal hoida: üritust, mis sulle ei meeldinud, mida sa raporteerisid, salvestasid või mis sulle meeldis, ning üritust, mis on juba sinu ekraanil, sulle ei reklaamita. Kui miski ei sobi, jääb koht tühjaks ja selle asemele ei panda midagi. Iga kehtiv reklaam maksab sama ja saab võrdse osa.',
          ],
        },
        {
          kind: 'p',
          content: ['Mida reklaam ei tee:'],
        },
        {
          kind: 'ul',
          items: [
            [
              'See ei muuda tulemuste järjekorda. Avasta, Päeva 5 ja hommikune e-kiri järjestatakse täpselt nii, nagu need oleks ilma reklaamita.',
            ],
            ['See ei asenda ühtki sinu viiest valikust.'],
            [
              'Reklaami nägemine või avamine ei muuda sinu maitseprofiili ega järjestust. Kui vajutad reklaamile „Ei meeldi”, jäetakse see üritus sinu tulemustest välja nagu iga teine mittemeeldinud üritus.',
            ],
          ],
        },
        {
          kind: 'p',
          content: [
            'Igal reklaamil on nupp „Miks?”, mis selgitab ühe lausega, miks sa seda näed.',
          ],
        },
        {
          kind: 'p',
          content: [
            'Loeme, mitu korda iga reklaami on näidatud ja avatud, ainult anonüümsete päevakogusummadena, mis ei sisalda midagi sinu kohta. Reklaami tellija ei saa sinu kohta mingeid andmeid. Üksikasjad on ',
            { text: 'privaatsuspoliitikas', to: ROUTES.privacy },
            '.',
          ],
        },
        {
          kind: 'p',
          content: [
            'Hommikuses e-kirjas saad reklaami ühe klõpsuga välja lülitada lingiga „Ära näita reklaame e-kirjas” või Seadetes.',
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
          gate: 'slotsOff',
        },
        {
          kind: 'p',
          content: [
            'Täielikum kuulutus saab parema koha: täpsed andmed, pildid ja kirjeldus. Orgaanilist järjekorda ei saa keegi raha eest muuta. Maksmisega saab osta ainult märgistatud reklaamikoha, nagu on kirjeldatud eespool jaotises Reklaam.',
          ],
          gate: 'slotsOn',
        },
      ],
    },
  ],
};

export default doc;
