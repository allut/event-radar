import { CONTACT_EMAIL, CONTACT_MAILTO, ROUTES } from '../../constants';
import type { FaqDoc } from './types';

const doc: FaqDoc = {
  lastUpdated: '2026-10-06',
  seoTitle: 'Korduma kippuvad küsimused',
  metaDescription:
    'Kuidas Event Radar töötab: kust Tallinna üritused pärinevad, kuidas valitakse Päeva 5, hommikune e-kiri, sinu andmed ja kuidas korraldajad üritusi lisavad.',
  title: 'Korduma kippuvad küsimused',
  lede: 'Kuidas Event Radar töötab — neile, kes otsivad, mida teha, ja korraldajatele, kes üritusi korraldavad.',
  jumpNavLabel: 'Sellel lehel',
  answerLinkLabel: 'Link sellele vastusele',
  sections: [
    {
      id: 'about',
      heading: 'Event Radarist',
      items: [
        {
          id: 'what-is-event-radar',
          question: 'Mis on Event Radar?',
          answer: [
            {
              kind: 'p',
              content: [
                'Event Radar on Tallinna ürituste teejuht. Igal hommikul valib see sulle sinu maitse järgi viis üritust — sinu Päeva 5. Lisaks saad Avasta lehel sirvida kõiki tulevasi üritusi.',
              ],
            },
          ],
        },
        {
          id: 'is-it-free',
          question: 'Kas see on tasuta?',
          answer: [
            {
              kind: 'p',
              content: [
                'Jah, nii üritustel käijatele kui ka korraldajatele. Tasu pole ja keegi ei saa maksta, et teda kõrgemal näidataks.',
              ],
            },
          ],
        },
        {
          id: 'where-events-come-from',
          question: 'Kust üritused pärit on?',
          answer: [
            {
              kind: 'p',
              content: [
                'Piletimüügisaitidelt, nagu Fienta ja Piletilevi, muuseumidelt ja kontserdisaalidelt ning korraldajatelt, kes lisavad oma üritused ise. Kasutame tehisintellekti, et jagada iga üritus kategooriatesse ja märgata, kui sama üritus on mitmel saidil, nii et see ilmub ainult korra.',
              ],
            },
          ],
        },
        {
          id: 'only-tallinn',
          question: 'Kas ainult Tallinn?',
          answer: [{ kind: 'p', content: ['Jah, praegu: Tallinn ja selle ümbrus.'] }],
        },
        {
          id: 'languages',
          question: 'Mis keeltes Event Radar on?',
          answer: [
            { kind: 'p', content: ['Sait töötab eesti, inglise ja vene keeles.'] },
            {
              kind: 'p',
              content: [
                'Ürituse pealkiri ja kirjeldus on sinu keeles siis, kui korraldaja või piletisait selle keeleversiooni avaldab. Me ei tõlgi neid masintõlkega. Kui sinu keel puudub, näed ingliskeelset versiooni või selle puudumisel originaali. Lühikesed „Miks minna“ märkused kirjutab tehisintellekt kõigis kolmes keeles.',
              ],
            },
          ],
        },
      ],
    },
    {
      id: 'event-goers',
      heading: 'Üritustel käijatele',
      items: [
        {
          id: 'need-an-account',
          question: 'Kas mul on kontot vaja?',
          answer: [
            {
              kind: 'p',
              content: [
                'Avasta lehe sirvimiseks ja ürituse avamiseks mitte. Kontot on vaja Päeva 5 jaoks, üritustele „Meeldib“, „Ei meeldi“ või järjehoidja lisamiseks, hommikuse e-kirja jaoks ja kuulutusest teatamiseks.',
              ],
            },
          ],
        },
        {
          id: 'sign-in',
          question: 'Kuidas sisse logida? Miks parooli pole?',
          answer: [
            {
              kind: 'p',
              content: [
                "Sisesta oma e-posti aadress ja saadame sulle sisselogimislingi. See töötab ühe korra ja aegub 15 minuti pärast. Võid sisse logida ka Google'iga. Kui parooli pole, pole midagi unustada ega lekkida. Jääd sisse 2 päevaks, seejärel logi uuesti sisse.",
              ],
            },
          ],
        },
        {
          id: 'daily-5',
          question: 'Kuidas minu Päeva 5 valitakse?',
          answer: [
            {
              kind: 'p',
              content: [
                'Selle järgi, milliseid eelistusi registreerumisel valisid, mis sulle meeldib ja mis mitte, kui hea kuulutus paistab ja kui varsti üritus toimub. Segame kategooriaid, et üks üritusetüüp ei võtaks kõike üle.',
              ],
            },
            {
              kind: 'p',
              content: [
                'Tehisintellekt jagab iga ürituse kategooriatesse ja meeleoludesse — nii leitakse sinu eelistustele sobivad üritused. Sinu esimene Päeva 5 on valmis kohe, kui oled eelistused valinud, ja uus valmib iga päev varahommikul.',
              ],
            },
          ],
        },
        {
          id: 'email',
          question: 'Millal e-kiri saabub ja kuidas sellest loobuda?',
          answer: [
            {
              kind: 'p',
              content: [
                'Hommikul, koos selle päeva Päeva 5-ga. Kui sulle sel päeval valikuid pole, e-kirja ei saadeta. E-kiri on konto loomisel sisse lülitatud. Loobumiseks kasuta mis tahes e-kirjas olevat loobumislinki (või oma e-postirakenduse loobumisnuppu) või lülita see Seadetes välja. Seadetes saad selle igal ajal uuesti sisse lülitada.',
              ],
            },
          ],
        },
        {
          id: 'like-dislike-bookmark',
          question: 'Mida teevad „Meeldib“, „Ei meeldi“ ja „Järjehoidja“?',
          answer: [
            {
              kind: 'p',
              content: ['Ühel üritusel saab korraga olla neist ainult üks. Uus valik asendab eelmise.'],
            },
            {
              kind: 'ul',
              items: [
                [
                  '„Meeldib“: see üritus ja teised samade kategooriate üritused tõusevad sinu jaoks kõrgemale.',
                ],
                [
                  '„Ei meeldi“: üritus kaob sinu Päeva 5-st ja Avasta lehe vaatest „Sinu jaoks“. „Sinu jaoks“ lõpetab ka teiste samadesse kategooriatesse kuuluvate ürituste näitamise. Vaates „Kõik sündmused“ on see endiselt olemas.',
                ],
                ['„Järjehoidja“: hoiab ürituse hilisemaks alles.'],
              ],
            },
            {
              kind: 'p',
              content: [
                'Salvestatud lehel on igaühe jaoks oma vahekaart: Järjehoidjad, Meeldivad ja Ei meeldi.',
              ],
            },
          ],
        },
        {
          id: 'change-tastes',
          question: 'Kas saan oma eelistusi hiljem muuta?',
          answer: [
            {
              kind: 'p',
              content: ['Jah. Vali Seadetes „Muuda persooni“ ja vali uuesti kuni 3 eelistust.'],
            },
          ],
        },
        {
          id: 'event-missing',
          question: 'Miks mulle teadaolevat üritust siin pole?',
          answer: [
            {
              kind: 'p',
              content: [
                'Kogume üritusi piletisaitidelt, muuseumidelt ja kontserdisaalidelt ning korraldajatelt, kes lisavad oma üritused ise. Mõnda üritust ei avaldata kusagil, kust me loeme, või toimub see väljaspool Tallinna. Kui tead üritust, mis meil puudu on, ',
                { text: 'anna meile teada', to: ROUTES.contact },
                '. Kui see on sinu üritus, saad selle ',
                { text: 'ise lisada', to: ROUTES.organizerLogin },
                '.',
              ],
            },
          ],
        },
        {
          id: 'report-listing',
          question: 'Kuulutus on vale või ei kuulu siia. Mida teha?',
          answer: [
            {
              kind: 'p',
              content: [
                'Ava üritus, vali selle menüüst „Teata üritusest“ ja vali põhjus. Teatamiseks pead olema sisse logitud. Saadame sulle e-kirja, kui oleme asjaga tegelenud. Pole sisse logitud? ',
                { text: 'Kirjuta meile', to: ROUTES.contact },
                '.',
              ],
            },
          ],
        },
        {
          id: 'data-and-tracking',
          question: 'Milliseid andmeid te hoiate? Kas te jälgite mind?',
          answer: [
            {
              kind: 'p',
              content: [
                'Hoiame sinu e-posti aadressi, keelt, valitud eelistusi, hommikuse e-kirja seadet ja seda, mida saidil teed: meeldimisi, mittemeeldimisi, järjehoidjaid, avatud üritusi ja klõpsatud piletilinke. Nende põhjal koostataksegi sinu Päeva 5.',
              ],
            },
            {
              kind: 'p',
              content: [
                'Kasutame ühte küpsist, et hoida sind sisselogituna. Meie analüütika töötab ilma küpsisteta ja lehtede aadressid maskeeritakse enne saatmist. Täielik loetelu on ',
                { text: 'privaatsuspoliitikas', to: ROUTES.privacy },
                '.',
              ],
            },
          ],
        },
        {
          id: 'delete-account',
          question: 'Kuidas oma konto kustutada?',
          answer: [
            {
              kind: 'p',
              content: [
                'Kirjuta meile aadressil ',
                { text: CONTACT_EMAIL, href: CONTACT_MAILTO },
                ' ja kustutame selle. Sinu muud õigused on kirjas ',
                { text: 'privaatsuspoliitikas', to: ROUTES.privacy },
                '.',
              ],
            },
          ],
        },
      ],
    },
    {
      id: 'organizers',
      heading: 'Korraldajatele',
      items: [
        {
          id: 'list-my-event',
          question: 'Kuidas oma üritust lisada? Kas see maksab midagi?',
          answer: [
            {
              kind: 'p',
              content: [
                'See on tasuta. Logi ',
                { text: 'korraldaja portaali', to: ROUTES.organizerLogin },
                " sisse e-posti lingi või Google'iga ja täida ürituse vorm.",
              ],
            },
          ],
        },
        {
          id: 'first-event-not-live',
          question: 'Miks mu esimene üritus pole veel avaldatud?',
          answer: [
            {
              kind: 'p',
              content: [
                'Iga uue korraldaja esimese ürituse vaatab üle inimene. Kui see on heaks kiidetud, avaldatakse see koos teiste juba esitatud üritustega. Edaspidi jõuavad sinu üritused avalikuks mõne sekundiga, kui need läbivad meie automaatsed kontrollid. Iga ürituse olekut näed oma töölaualt. Heakskiidu kohta e-kirja ei saadeta.',
              ],
            },
          ],
        },
        {
          id: 'organizer-languages',
          question: 'Mis keeles peaksin kirjutama?',
          answer: [
            {
              kind: 'p',
              content: [
                'Kohustuslik on ainult eestikeelne pealkiri. Võid lisada ka inglis- ja venekeelse pealkirja ja kirjelduse, ning nende keelte lugejad näevad neid. Lugeja, kelle keelt sa pole täitnud, näeb ingliskeelset teksti või selle puudumisel eestikeelset.',
              ],
            },
          ],
        },
        {
          id: 'claim-event',
          question: 'Minu üritus on juba Event Radaris. Kas saan selle üle võtta?',
          answer: [
            {
              kind: 'p',
              content: [
                'Jah, nõudes selle enda omaks. Ava üritus ja vali „Nõua see üritus enda omaks“ või otsi seda oma töölaualt. Seejärel tõesta, et üritus on sinu: koodiga oma piletikuulutuses, kirjega oma veebisaidi domeenil või oma e-posti aadressiga või saada lühike selgitus, mille me üle vaatame. Nõude vaade näitab, millised viisid sinu ürituse puhul sobivad. Lõpetamata nõue aegub 7 päeva pärast või 30 päeva pärast, kui see ootab meie ülevaatust.',
              ],
            },
          ],
        },
        {
          id: 'claimed-edits',
          question: 'Kas pärast ülevõtmist kirjutatakse minu muudatused üle?',
          answer: [
            {
              kind: 'p',
              content: [
                'Ei. Meie öine uuendus jätab sinu muudetud teksti puutumata ega muuda kunagi sinu määratud pilti, kuupäevi, linki ega kategooriaid. Kaks asja järgivad endiselt allikat: toimumiskoht ja aadress ning hind, mis vastab alati piletilehele. Kui hind muutub, näitab muutmisvaade seda sulle. Keeled, milles sa pole veel kirjutanud, täidetakse allikast, kui seal need olemas on.',
              ],
            },
          ],
        },
      ],
    },
  ],
  contact: {
    heading: 'Kas jäi küsimus vastuseta?',
    body: 'Kirjuta meile ja inimene vastab sulle e-kirjaga.',
    cta: 'Võta ühendust',
  },
};

export default doc;
