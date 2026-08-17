import { CONTACT_EMAIL, CONTACT_MAILTO } from '../../constants';
import type { LegalDoc } from './types';

const AKI_URL = 'https://www.aki.ee';

const doc: LegalDoc = {
  title: 'Privaatsuspoliitika',
  lastUpdated: '2026-08-11',
  intro: [
    {
      kind: 'p',
      content: [
        'What’s on Radar ("meie", "meid", "teenus") on sündmuste avastamise teenus Tallinnas, Eestis. See poliitika selgitab, milliseid isikuandmeid me kogume, miks, kui kaua me neid säilitame, kellega jagame ning millised õigused sul on ELi isikuandmete kaitse üldmääruse (GDPR) alusel.',
      ],
    },
  ],
  sections: [
    {
      heading: '1. Kes vastutab sinu andmete eest (vastutav töötleja)',
      blocks: [
        {
          kind: 'p',
          content: [
            'Vastutav töötleja on Aleksei Lutkov, kes haldab What’s on Radarit füüsilisest isikust ettevõtjana Eestis. Privaatsusküsimuste või oma õiguste kasutamiseks võta ühendust ',
            { text: CONTACT_EMAIL, href: CONTACT_MAILTO },
            '.',
          ],
        },
      ],
    },
    {
      heading: '2. Mida me kogume',
      blocks: [
        {
          kind: 'ul',
          items: [
            ['Sinu e-posti aadress — sisened ühekordse "maagilise lingiga"; me ei kasuta paroole.'],
            ['Sinu eelistused — kasutajaliidese keel (eesti, inglise või vene) ja soovi korral sinu kodulinn.'],
            ['Sinu maitseprofiil — persoonad, mille valid tutvustuse käigus, mida kasutatakse sinu voo isikupärastamiseks.'],
            ['Sinu tegevus rakenduses — sündmused, mis sulle meeldivad, ei meeldi, mille lisad järjehoidjatesse, vaatad või mille piletilinke klikid. Neid signaale kasutame sinu "Päeva 5" järjestamiseks ja isikupärastamiseks.'],
            ['E-posti kokkuvõtte eelistus — kas oled tellinud igapäevase e-posti kokkuvõtte.'],
            ['Tehnilised andmed — sinu IP-aadress ja tavapärane päringuteave, mida töödeldakse ajutiselt turvalisuse, päringute piiramise ja väärkasutuse ennetamise ning lühiajaliste serverilogide jaoks.'],
          ],
        },
        {
          kind: 'p',
          content: [
            'Me ei kogu paroole, makseandmeid, täpset/GPS-asukohta ega eriliigilisi (tundlikke) andmeid, nagu tervis, usk või rahvus.',
          ],
        },
      ],
    },
    {
      heading: '3. Miks me andmeid töötleme ja meie õiguslik alus (GDPR art. 6)',
      blocks: [
        {
          kind: 'ul',
          items: [
            ['Teenuse osutamiseks — sisselogimine, sinu konto ja isikupärastatud voog: lepingu täitmine ja meie õigustatud huvi teenuse käitamisel (art. 6(1)(b),(f)).'],
            ['E-posti kokkuvõte — sinu nõusolek (art. 6(1)(a)); tellitav ja igal ajal tagasi võetav.'],
            ['Turvalisus, päringute piiramine, väärkasutuse ennetamine ja logimine — meie õigustatud huvi hoida teenus turvaline ja kättesaadav (art. 6(1)(f)).'],
            ['Koondatud, privaatsussõbralik analüütika — meie õigustatud huvi mõista üldist kasutust ja jõudlust (art. 6(1)(f)).'],
          ],
        },
      ],
    },
    {
      heading: '4. Küpsised, kohalik salvestusruum ja analüütika',
      blocks: [
        {
          kind: 'p',
          content: [
            'Kasutame üht rangelt vajalikku küpsist: allkirjastatud, httpOnly sessiooniküpsist, mis hoiab sind sisse logituna. Sellel pole reklaami- ega jälgimiseesmärki ja lehel töötavad skriptid ei saa seda lugeda. Kuna see on teenuse toimimiseks rangelt vajalik, ei ole küpsiste nõusolekuriba vaja. Sinu keelevalik ja tõeväärtuslipp "oled sisse logitud", mis ei sisalda mandaati, salvestatakse sinu brauseri kohalikku salvestusruumi. Meie kasutus- ja jõudlusanalüütika (Vercel Web Analytics ja Speed Insights) on küpsisevaba ja koondatud; lehe URL-id maskeeritakse enne analüütikapakkujani jõudmist, nii et ühtki sündmuse tunnust ega sessiooni mandaati ei saadeta kunagi.',
          ],
        },
      ],
    },
    {
      heading: '5. Kellega me andmeid jagame (volitatud töötlejad ja saajad)',
      blocks: [
        {
          kind: 'p',
          content: [
            'Me ei müü kunagi sinu andmeid ega jaga neid reklaamijatega. Kasutame väikest hulka teenusepakkujaid, kes töötlevad andmeid ainult meie juhiste alusel ja andmetöötluslepingute kohaselt:',
          ],
        },
        {
          kind: 'ul',
          items: [
            ['Neon — andmebaasi majutus (ELi piirkond, Frankfurt, Saksamaa).'],
            ['Render — taustarakenduse majutus.'],
            ['Vercel — esiliidese majutus ja ülalnimetatud küpsisevaba analüütika.'],
            ['Resend — sisselogimise ja kokkuvõtte e-kirjade edastamine.'],
          ],
        },
        {
          kind: 'p',
          content: [
            'Pakkujad, kes töötlevad ainult sündmuste andmeid, mitte kunagi sinu isikuandmeid: meie keelemudelite pakkujad (Groq, Cerebras, Mistral) klassifitseerivad avalikke sündmuste kirjeid; OpenStreetMap Nominatim geokodeerib sündmuste toimumiskohtade aadresse; cron-job.org pingib teenust, et hoida see ärkvel. Võime andmeid avaldada ka seaduses nõutud juhtudel.',
          ],
        },
      ],
    },
    {
      heading: '6. Rahvusvahelised edastused',
      blocks: [
        {
          kind: 'p',
          content: [
            'Sinu põhilised konto andmed säilitatakse ELis (Frankfurt, Saksamaa). Mõned pakkujad (nt Render, Vercel) asuvad USAs; kui isikuandmeid edastatakse väljapoole EMPd, kaitsevad neid Euroopa Komisjoni standardsed lepingutingimused ja pakkujate andmetöötlustingimused.',
          ],
        },
      ],
    },
    {
      heading: '7. Kui kaua me andmeid säilitame',
      blocks: [
        {
          kind: 'ul',
          items: [
            ['Sisselogimise (sessiooni) load: 2 päeva; need on allkirjastatud, mitte meie serveritesse salvestatud.'],
            ['Maagilise lingi load: 7 päeva, ühekordsed.'],
            ['Tehnilised/auditikirjed (töötlemata sissevõtu andmed, päringu-/töötluslogid): kuni 90 päeva.'],
            ['Voo hetktõmmised ja vahemällu salvestatud järjestusskoorid: kuni 30 päeva.'],
            ['Konto andmed (e-post, eelistused, maitseprofiil, tagasiside): säilitatakse konto aktiivsuse ajal ja kustutatakse taotluse alusel (vt allpool). Sündmuste kirjeid säilitame tähtajatult, kuid need on avalik sündmuste teave, mitte sinu isikuandmed.'],
          ],
        },
      ],
    },
    {
      heading: '8. Sinu õigused',
      blocks: [
        {
          kind: 'p',
          content: [
            'GDPR-i alusel on sul õigus: pääseda ligi oma andmetele; parandada ebatäpseid andmeid; kustutada oma andmed ("õigus olla unustatud"); piirata töötlemist või sellele vastu olla; andmete ülekantavus; ja võtta nõusolek igal ajal tagasi (see ei mõjuta juba tehtud töötlemist). Kokkuvõtte tellimuse saad tühistada igast kokkuvõtte e-kirjast või tellimuse tühistamise lehelt. Mis tahes õiguse kasutamiseks kirjuta ',
            { text: CONTACT_EMAIL, href: CONTACT_MAILTO },
            '; me vastame ühe kuu jooksul. Sul on ka õigus esitada kaebus oma järelevalveasutusele — Eestis on selleks Andmekaitse Inspektsioon, ',
            { text: AKI_URL, href: AKI_URL },
            '.',
          ],
        },
      ],
    },
    {
      heading: '9. Kuidas me sinu andmeid kaitseme',
      blocks: [
        {
          kind: 'p',
          content: [
            'Andmed on edastamisel krüpteeritud (HTTPS/TLS) ja salvestatud ELis majutatud andmebaasi. Maagilise lingi load on räsitud ja ühekordsed; sessiooniload on allkirjastatud ja tühistatavad. Järgime OWASP-i turvatavasid ja rakendame juurdepääsukontrolle. Kui andmetega seotud rikkumine tõenäoliselt ohustab sinu õigusi, teavitame järelevalveasutust 72 tunni jooksul ja vajaduse korral teavitame ka sind.',
          ],
        },
      ],
    },
    {
      heading: '10. Lapsed',
      blocks: [
        {
          kind: 'p',
          content: [
            'Teenus ei ole suunatud alla 13-aastastele lastele (digitaalse nõusoleku vanus Eestis). Me ei kogu teadlikult andmeid lastelt; kui arvad, et laps on meile andmeid esitanud, võta meiega ühendust ja me kustutame need.',
          ],
        },
      ],
    },
    {
      heading: '11. Selle poliitika muudatused',
      blocks: [
        {
          kind: 'p',
          content: [
            'Võime seda poliitikat uuendada; "Viimati uuendatud" kuupäev näitab praegust versiooni. Olulistest muudatustest anname märku rakenduses.',
          ],
        },
      ],
    },
    {
      heading: '12. Kontakt',
      blocks: [
        {
          kind: 'p',
          content: [
            'Küsimused või taotlused: ',
            { text: CONTACT_EMAIL, href: CONTACT_MAILTO },
            '.',
          ],
        },
      ],
    },
  ],
};

export default doc;
