import { AKI_URL, CONTACT_EMAIL, CONTACT_MAILTO } from '../../constants/core';
import type { LegalDoc } from './types';

const doc: LegalDoc = {
  title: 'Privaatsuspoliitika',
  lastUpdated: '2026-10-17',
  lastUpdatedSlots: '2026-10-18',
  intro: [
    {
      kind: 'p',
      content: [
        'Event Radar ("meie", "meid", "teenus") on sündmuste avastamise teenus Tallinnas, Eestis. See poliitika selgitab, milliseid isikuandmeid me kogume, miks, kui kaua me neid säilitame, kellega jagame ning millised õigused sul on ELi isikuandmete kaitse üldmääruse (GDPR) alusel.',
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
            'Vastutav töötleja on Aleksei Lutkov, kes haldab Event Radarit füüsilisest isikust ettevõtjana Eestis. Privaatsusküsimuste või oma õiguste kasutamiseks võta ühendust ',
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
            ['Kui logid sisse Google’iga — sinu Google’i konto tunnus ning e-posti aadress ja kinnitusstaatus, mille Google edastab; me ei küsi ega saa kunagi sinu nime ega fotot.'],
            ['Tehnilised andmed — sinu IP-aadress ja tavapärane päringuteave, mida töödeldakse ajutiselt turvalisuse, päringute piiramise ja väärkasutuse ennetamise ning lühiajaliste serverilogide jaoks.'],
            {
              content: [
                'Sinu e-kirja reklaami nõusoleku kirje, kui lülitad selle sisse või välja: kas see on sees, millal sa selle andsid või tagasi võtsid, millise sõnastusega nõustusid, kus seda tegid (Seaded, e-kirja link või kokkuvõtte tellimuse tühistamine) ja sinu keel.',
              ],
              gate: 'slotsOn',
            },
            {
              content: [
                'Milline reklaam sinu Päeva 5 juurde igal päeval määrati: reklaam ja kuupäev. Kasutame seda, et reklaam püsiks päeva jooksul samana, et see puhkaks kolm päeva ja et saaksime lugeda, mitu inimest reklaamini jõudis.',
              ],
              gate: 'slotsOn',
            },
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
            ['E-posti kokkuvõte, 15. oktoobril 2026 või hiljem loodud kontode puhul — sinu nõusolek (art. 6(1)(a)); tellitav ja igal ajal tagasi võetav.'],
            ['E-posti kokkuvõte, enne 15. oktoobrit 2026 loodud kontode puhul — need kontod tellisid kokkuvõtte vaikimisi, seega tugineme oma õigustatud huvile hoida olemasolevaid kasutajaid kursis (art. 6(1)(f)) ning infoühiskonna teenuse seaduse § 103¹ erandile olemasolevate klientide puhul. Igas kokkuvõttes on loobumislink ja kokkuvõtte saab Seadetes igal ajal välja lülitada.'],
            {
              content: [
                'Reklaami näitamine Avastamises ja Päeva 5-s — reklaamikohad valitakse konteksti, mitte sinu huvide põhjal. Päeva 5 reklaamikoha jaoks salvestame iga kasutaja ja päeva kohta, milline reklaam sulle määrati, ning rakendame sinu enda välistusi (üritused, mis sulle ei meeldinud, mida raporteerisid, salvestasid või mis sulle meeldisid) ja kolmepäevast pausi, enne kui sama reklaam võib tagasi tulla. Meie õigustatud huvi on näidata korraldajate tasutud reklaami nii, et sa ei näe ürituse, mille oled juba tagasi lükanud, ega sama reklaami liiga tihti (art. 6(1)(f)).',
              ],
              gate: 'slotsOn',
            },
            {
              content: [
                'Reklaami mõõtmine — loeme, mitu korda iga reklaami on näidatud ja avatud, päevakogusummadena reklaami kohta, mis ei sisalda midagi sinu kohta. Meie õigustatud huvi on korraldajate tasutud reklaami edastamine ja selle kohta aruandmine (art. 6(1)(f)).',
              ],
              gate: 'slotsOn',
            },
            {
              content: [
                'Reklaam e-kirjas — sinu eraldi nõusolek (art. 6(1)(a); infoühiskonna teenuse seaduse § 103¹). Väljas, kuni sa selle sisse lülitad, ja tagasivõetav Seadetes või igast kirjast, kus reklaam on.',
              ],
              gate: 'slotsOn',
            },
            {
              content: [
                'Valime, millist reklaami sulle näidata, päeva ja saadaolevate reklaamide põhjal, mitte kunagi sinu tegevuse ega huvide põhjal.',
              ],
              gate: 'slotsOn',
            },
            ['Turvalisus, päringute piiramine, väärkasutuse ennetamine ja logimine — meie õigustatud huvi hoida teenus turvaline ja kättesaadav (art. 6(1)(f)).'],
          ],
        },
      ],
    },
    {
      heading: '4. Küpsised, kohalik salvestusruum ja seadmele juurdepääs',
      blocks: [
        {
          kind: 'p',
          content: [
            'Kasutame üht rangelt vajalikku küpsist: allkirjastatud, httpOnly sessiooniküpsist, mis hoiab sind sisse logituna. Sellel pole reklaami- ega jälgimiseesmärki ja lehel töötavad skriptid ei saa seda lugeda. Kuna see on teenuse toimimiseks rangelt vajalik, ei ole küpsiste nõusolekuriba vaja. Kui logid sisse Google’iga, paneme sisselogimise lõpuleviimise mõneks minutiks ka teise rangelt vajaliku küpsise — allkirjastatud, httpOnly, ühekordse olekuküpsise, mis kaitseb sisselogimist saidiülese võltsimise (CSRF) eest; see kustutatakse kohe pärast sisselogimise lõppu, olenemata tulemusest, ja ükski Google’i seatud küpsis ei puuduta kunagi meie saiti. Sinu keelevalik ja tõeväärtuslipp "oled sisse logitud", mis ei sisalda mandaati, salvestatakse sinu brauseri kohalikku salvestusruumi. Me ei kasuta analüütika- ega reklaamijälgijaid: ühtegi kolmanda osapoole analüütikaskripti ei laadita ning mõõtmiseks ei salvestata sinu seadmesse ega loeta sealt midagi. Kui oled sisse logitud, teatab rakendus meie enda serverile, milliseid üritusi vaatad ja milliste piletilinkidele klõpsad; see toidab sinu isikupärastatud „Päeva 5”, mille sisselogimisega tellisid, ning on selle funktsiooni jaoks rangelt vajalik.',
          ],
        },
        {
          kind: 'p',
          content: [
            'Me ei jälgi, kas sa meie e-kirju avad: kirjades pole jälgimispikslit ega linke, mis sind tuvastaksid. Kui järgid reklaami ürituse lehele, lisandub see külastus reklaami anonüümsele päevakogusummale. Seda ei seota sinu ega sinu e-posti aadressiga.',
          ],
          gate: 'slotsOn',
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
          gate: 'slotsOff',
        },
        {
          kind: 'p',
          content: [
            'Me ei müü kunagi sinu isikuandmeid ega jaga neid reklaamijatega. Korraldajad, kes reklaami eest maksavad, saavad ainult anonüümseid päevakogusummasid selle kohta, mitu korda reklaami näidati ja avati, mitte kunagi seda, kes seda nägi või sellele klõpsas. Kasutame väikest hulka teenusepakkujaid, kes töötlevad andmeid ainult meie juhiste alusel ja andmetöötluslepingute kohaselt:',
          ],
          gate: 'slotsOn',
        },
        {
          kind: 'ul',
          items: [
            ['Neon — andmebaasi majutus (ELi piirkond, Frankfurt, Saksamaa).'],
            ['Render — taustarakenduse majutus.'],
            ['Cloudflare — esiliidese majutus (Cloudflare Pages).'],
            ['Google — kui kasutad Google’iga sisselogimist, sinu sisselogimisidentiteedi kinnitamine. Sisselogimisel tegutseb Google kahes rollis: meie volitatud töötlejana loa väljastamisel ning iseseisvalt — oma identiteedipakkuja rollis, mitte meie juhiste alusel —, kui ta kinnitab, kes sa oled.'],
            ['Resend — sisselogimise ja kokkuvõtte e-kirjade edastamine.'],
          ],
        },
        {
          kind: 'p',
          content: [
            'Pakkujad, kes töötlevad ainult sündmuste andmeid, mitte kunagi sinu isikuandmeid: meie keelemudelite pakkujad (Groq, Cloudflare Workers AI, Mistral) klassifitseerivad avalikke sündmuste kirjeid; OpenStreetMap Nominatim geokodeerib sündmuste toimumiskohtade aadresse; cron-job.org pingib teenust, et hoida see ärkvel. Võime andmeid avaldada ka seaduses nõutud juhtudel.',
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
            'Sinu põhilised konto andmed säilitatakse ELis (Frankfurt, Saksamaa). Mõned pakkujad (nt Render, Cloudflare) asuvad USAs; kui isikuandmeid edastatakse väljapoole EMPd, kaitsevad neid Euroopa Komisjoni standardsed lepingutingimused ja pakkujate andmetöötlustingimused.',
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
            {
              content: [
                'E-kirja reklaami nõusoleku kirje: säilitatakse nii kaua, kui konto on olemas, ja kustutatakse koos sellega.',
              ],
              gate: 'slotsOn',
            },
            {
              content: [
                'Milline reklaam sinu Päeva 5 juurde igal päeval määrati: kuni 30 päeva.',
              ],
              gate: 'slotsOn',
            },
            {
              content: [
                'Anonüümsed reklaami päevakogusummad: säilitatakse tähtajatult. Need ei sisalda isikuandmeid.',
              ],
              gate: 'slotsOn',
            },
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
        {
          kind: 'p',
          content: [
            'E-kirja reklaami nõusoleku saad igal ajal tagasi võtta Seadetes või ilma sisse logimata lingiga „Ära näita reklaame e-kirjas” igas kirjas, kus reklaam on. Kokkuvõtte tellimuse tühistamine võtab selle samuti tagasi; kui tellid hiljem uuesti, jääb reklaam väljas, kuni lülitad selle Seadetes ise sisse.',
          ],
          gate: 'slotsOn',
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
