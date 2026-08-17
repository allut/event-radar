import { CONTACT_EMAIL, CONTACT_MAILTO } from '../../constants';
import type { LegalDoc } from './types';

const ODR_URL = 'https://ec.europa.eu/consumers/odr';

const doc: LegalDoc = {
  title: 'Kasutustingimused',
  lastUpdated: '2026-07-24',
  intro: [],
  sections: [
    {
      heading: '1. Nõustumine',
      blocks: [
        {
          kind: 'p',
          content: [
            'What’s on Radarit ("teenus") kasutades nõustud nende tingimustega. Kui sa ei nõustu, palun ära kasuta teenust.',
          ],
        },
      ],
    },
    {
      heading: '2. Teenus',
      blocks: [
        {
          kind: 'p',
          content: [
            'What’s on Radar on tasuta teenus, mis avastab, dubleeringutest puhastab ja isikupärastab avalikke sündmusi Tallinnas, Eestis, sealhulgas kureeritud "Päeva 5" voog ja valikuline e-posti kokkuvõte. Me koondame sündmuste teavet kolmandate osapoolte allikatest; me ei korralda, majuta ega müü sündmustele pileteid.',
          ],
        },
      ],
    },
    {
      heading: '3. Sobivus ja sinu konto',
      blocks: [
        {
          kind: 'p',
          content: [
            'Teenuse kasutamiseks pead olema vähemalt 13-aastane. Sisened ühekordse lingiga, mis saadetakse sinu e-postile; sa vastutad oma e-posti postkasti turvalisuse ja oma kontol toimuva tegevuse eest. Üks konto isiku kohta.',
          ],
        },
      ],
    },
    {
      heading: '4. Lubatud kasutamine',
      blocks: [
        {
          kind: 'p',
          content: [
            'Sa nõustud mitte: kasutama teenust ebaseaduslikult; kraapima, koguma ega sellele automaatsete vahenditega juurde pääsema väljaspool tavapärast isiklikku kasutust; sekkuma või püüdma rikkuda selle turvalisust või taristut; seda üle koormama või häirima; ega väärkasutama teise isiku kontot. Rikkumise korral võime juurdepääsu peatada.',
          ],
        },
      ],
    },
    {
      heading: '5. Kolmandate osapoolte sündmused ja sisu — oluline',
      blocks: [
        {
          kind: 'p',
          content: [
            'Sündmuste üksikasjad (kellaajad, hinnad, toimumiskohad, saadavus, pildid ja kirjeldused) koondatakse kolmandate osapoolte allikatest ning need võivad olla ebatäpsed, mittetäielikud või aegunud. Kontrolli üksikasju alati ametliku korraldaja või piletimüüjaga, enne kui neile tugined või sündmusele lähed. Me ei ole osapooleks üheski tehingus sinu ja korraldaja, toimumiskoha või piletimüüja vahel ega vastuta kolmandate osapoolte sündmuste, sisu, veebisaitide ega tehingute eest. Välised lingid on esitatud üksnes mugavuse huvides.',
          ],
        },
      ],
    },
    {
      heading: '6. Intellektuaalomand',
      blocks: [
        {
          kind: 'p',
          content: [
            'Teenuse tarkvara, disain, bränd ja koostis kuuluvad meile või meie litsentsiandjatele. Sündmuste andmed kuuluvad nende vastavatele allikatele. Esitades tagasisidesignaale (meeldimised, mittemeeldimised, järjehoidjad), annad meile litsentsi kasutada neid teenuse käitamiseks ja parandamiseks.',
          ],
        },
      ],
    },
    {
      heading: '7. Garantii puudumine',
      blocks: [
        {
          kind: 'p',
          content: [
            'Teenust pakutakse "nagu on" ja "nagu saadaval", ilma igasuguse otsese või kaudse garantiita, sealhulgas täpsuse, täielikkuse, kättesaadavuse või konkreetseks otstarbeks sobivuse osas. Me ei garanteeri katkematut ega veatut tööd.',
          ],
        },
      ],
    },
    {
      heading: '8. Vastutuse piiramine',
      blocks: [
        {
          kind: 'p',
          content: [
            'Seadusega lubatud maksimaalses ulatuses ei vastuta me kaudsete, juhuslike, eriliste ega tulenevate kahjude eest ega kahju eest, mis tuleneb sinu tuginemisest sündmuste teabele või kolmandate osapoolte sündmustele. Miski nendes tingimustes ei välista ega piira vastutust, mida kohaldatava õiguse kohaselt ei saa välistada ega piirata, sealhulgas sinu kohustuslikke tarbijaõigusi ELi ja Eesti õiguse alusel, mis jäävad mõjutamata.',
          ],
        },
      ],
    },
    {
      heading: '9. Peatamine ja lõpetamine',
      blocks: [
        {
          kind: 'p',
          content: [
            'Võime juurdepääsu peatada või lõpetada nende tingimuste rikkumise korral või teenuse kaitsmiseks. Sa võid teenuse kasutamise igal ajal lõpetada ja taotleda oma konto kustutamist (',
            { text: CONTACT_EMAIL, href: CONTACT_MAILTO },
            ').',
          ],
        },
      ],
    },
    {
      heading: '10. Muudatused',
      blocks: [
        {
          kind: 'p',
          content: [
            'Võime muuta teenust või neid tingimusi; "Viimati uuendatud" kuupäev näitab praegust versiooni. Kasutamise jätkamine pärast muudatust tähendab, et nõustud uuendatud tingimustega.',
          ],
        },
      ],
    },
    {
      heading: '11. Kohaldatav õigus ja vaidlused',
      blocks: [
        {
          kind: 'p',
          content: [
            'Neid tingimusi reguleerib Eesti õigus. Vaidlused kuuluvad pädevate Eesti kohtute pädevusse, ilma et see piiraks kohustuslikke tarbijakaitseõigusi või sinu õigust algatada menetlus oma elukohariigis. ELi tarbijad võivad kasutada ka Euroopa Komisjoni veebipõhise vaidluste lahendamise platvormi (',
            { text: ODR_URL, href: ODR_URL },
            ').',
          ],
        },
      ],
    },
    {
      heading: '12. Kontakt',
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
