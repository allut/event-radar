import { ROUTES } from '../../constants/routes';
import { ORGANIZER_TERMS_IS_DRAFT } from '../../constants/operator';
import { CONTACT_EMAIL, CONTACT_MAILTO } from '../../constants/core';
import { ORGANIZER_TERMS_VERSION } from '../../_generated/sharedConstants';
import type { LegalDoc } from './types';

const doc: LegalDoc = {
  title: 'Korraldaja tingimused',
  lastUpdated: '2026-10-18',
  draft: ORGANIZER_TERMS_IS_DRAFT,
  intro: [
    {
      kind: 'p',
      content: [
        'Need tingimused kehtivad, kui ostad või taotled Event Radaris reklaamiperioodi. Need kehtivad koos kasutustingimuste ja privaatsuspoliitikaga. Nende osaks on viitamise teel leht ',
        { text: 'Kuidas tulemused järjestatakse', to: ROUTES.ranking },
        ', ehk järjestuse avalikustamine.',
      ],
    },
    {
      kind: 'p',
      content: [
        `Versioon ${ORGANIZER_TERMS_VERSION}, kehtib alates `,
        { operator: 'dateInForce' },
        '. Kui need tingimused vastu võtad, salvestame versiooni ja aja.',
      ],
    },
  ],
  sections: [
    {
      id: 'operator',
      heading: '1. Kes me oleme',
      blocks: [
        {
          kind: 'p',
          content: [
            'Event Radarit haldab ',
            { operator: 'name' },
            ' OÜ, registrikood ',
            { operator: 'registryCode' },
            ', asukoht ',
            { operator: 'seat' },
            ', käibemaksukohustuslase number ',
            { operator: 'vatNumber' },
            ' („operaator”, „meie”). Kontakt: ',
            { text: CONTACT_EMAIL, href: CONTACT_MAILTO },
            '.',
          ],
        },
        {
          kind: 'p',
          content: [
            '„Sina” on ettevõte või mittetulundusühing, kes reklaamiperioodi ostab või taotleb. „Reklaamiperiood” on Tallinna aja järgi täispäevade aken, mille jooksul üks sinu oma üritus võib täita reklaamikohti. „Reklaamikoht” on märgistatud koht tulemuste kõrval Avastamises, Päeva 5-s või hommikuses e-kirjas.',
          ],
        },
      ],
    },
    {
      id: 'promotion',
      heading: '2. Mis on reklaamiperiood',
      blocks: [
        {
          kind: 'ul',
          items: [
            [
              'See kestab 3 kuni 14 täispäeva Tallinna aja järgi, esimene ja viimane päev kaasa arvatud. See algab kõige varem homme ja lõpeb hiljemalt sinu ürituse viimasel päeval.',
            ],
            [
              'See hõlmab ühte üritust, mis on sinu oma: sa esitasid selle või oled selle enda omaks nõudnud ja nõue on kinnitatud.',
            ],
            [
              'Korraga on elus kuni 5 reklaamiperioodi ja iga elus reklaamiperiood saab võrdse osa reklaamikohtadest. Reklaamiperiood hoiab oma päevi alates hetkest, mil see on antud või makstud.',
            ],
            [
              'Reklaamikoht näitab sinu üritust tavalise ürituse kaardina, millel on märge „Reklaam” ja maksnud ettevõtte juriidiline nimi. Nimi salvestatakse müügi hetkel ja see ei muutu, kui sa hiljem oma profiili ümber nimetad.',
            ],
            [
              'Reklaamiperiood on nähtav ainult siis, kui üritus on avalik, ei ole lõppenud, on algne kuulutus ja on endiselt sinu oma ning selle sisu vastab allolevale sisupoliitikale. Kui miski neist lakkab kehtimast, jääb reklaamiperiood iseenesest pausile ja jätkub, kui see taas kehtib.',
            ],
          ],
        },
        {
          kind: 'p',
          content: [
            'Midagi ei garanteerita: ei näitamisi, klõpse, piletimüüki ega muud tulemust. Reklaamikoht võib jääda tühjaks või olla jagatud teiste reklaamiperioodidega ja vaataja võib selle enda eest eemal hoida: üritust, mis vaatajale ei meeldinud, mida ta raporteeris, salvestas või mis talle meeldis, ei näidata talle reklaamina.',
          ],
        },
      ],
    },
    {
      id: 'ranking',
      heading: '3. Tasuline koht ei mõjuta kunagi järjestust',
      blocks: [
        {
          kind: 'p',
          content: [
            'Reklaamiperiood ostab ainult reklaamikohti. See ei muuda kunagi sinu ürituse kohta Avastamises, Päeva 5-s ega hommikuses e-kirjas ja keegi ei saa maksta orgaanilise järjekorra muutmise eest. Peamised järjestust määravad parameetrid ja nende suhteline tähtsus on lehel ',
            { text: 'Kuidas tulemused järjestatakse', to: ROUTES.ranking },
            '. Reklaamikohad valitakse konteksti (lehe, päeva ja vaataja aktiivsete filtrite) järgi, mitte kunagi vaataja huvide põhjal.',
          ],
        },
      ],
    },
    {
      id: 'price',
      heading: '4. Kes võib osta ja hind',
      blocks: [
        {
          kind: 'ul',
          items: [
            [
              'Reklaamiperioode müüakse ainult Eestis registreeritud ettevõtetele ja mittetulundusühingutele ning sa pead esitama oma Eesti registrikoodi.',
            ],
            [
              'Ostad ainult oma ettevõtte või ühingu jaoks, mitte kunagi kellegi teise eest. Ostes kinnitad, et registrikood kuulub sinu enda ettevõttele või ühingule ja et sul on õigus selle nimel tegutseda. Selle juriidiline nimi on näha reklaamiperioodil ja arvel.',
            ],
            [
              'Hind on 5 € päevas pluss käibemaks kehtiva määra järgi (24% korral 6,20 € päevas). Näiteks 7 päeva maksavad 35 € pluss 8,40 € käibemaksu, kokku 43,40 €.',
            ],
            [
              'Müügi ajal kehtinud hind ja käibemaksumäär salvestatakse sinu reklaamiperioodiga. Hilisem hinnamuutus kehtib ainult pärast selle jõustumist müüdud reklaamiperioodidele.',
            ],
            [
              'Võime anda reklaamiperioodi tasuta oma äranägemise järgi. Tasuta reklaamiperiood järgib kõiges muus neid tingimusi ega anna õigust teisele.',
            ],
          ],
        },
      ],
    },
    {
      id: 'buying',
      heading: '5. Kuidas osta',
      blocks: [
        {
          kind: 'p',
          content: [
            "Kaardiga. Sisestad oma registrikoodi, sinu juriidiline nimi täidetakse Eesti äriregistri põhjal, kinnitad, et ettevõte või ühing on sinu oma ja et sinu üritus vastab sisupoliitikale, nõustud nende tingimustega ja maksad Stripe'i kaudu. Kui oled makselehel, hoiame valitud päevi 30 minutit. Kui makse jõuab kohale pärast hoiu lõppu, tagastame selle automaatselt täies mahus ja teavitame sind e-kirjaga.",
          ],
        },
        {
          kind: 'p',
          content: [
            'Pangaülekandega, taotluse kaudu. Saadad reklaamitaotluse oma kuupäevade, juriidilise nime, registrikoodi, arveldus-e-posti ja valikulise märkusega, kinnitad, et ettevõte või ühing on sinu oma, ning nõustud nende tingimustega. Taotlus ei ole pakkumine, mille me peaksime vastu võtma. Võime selle rahuldada, rahuldada sinuga kokku lepitud muudel kuupäevadel või tagasi lükata koos põhjusega. Kui rahuldame, esitame sulle arve ja sa maksad pangaülekandega. Reklaamiperiood, mis on algamispäeva alguseks veel tasumata, tühistatakse ja selle päevad vabastatakse.',
          ],
        },
        {
          kind: 'p',
          content: [
            'Kaardimakse pole saadaval ürituse puhul, mis vajab sisu ülevaatust. Sellise ürituse jaoks saab esitada taotluse.',
          ],
        },
      ],
    },
    {
      id: 'invoices',
      heading: '6. Arved',
      blocks: [
        {
          kind: 'p',
          content: [
            'Esitame käibemaksuarve ER- seerias (ER-M- käsitsi väljastatud arvete puhul), millel on meie KMKR number, sinu registrikood, üritus ja reklaamiperioodi aken. Stripe saadab kaardiarved sinu arveldus-e-postile ja saad need avada oma reklaamiperioodide loendist.',
          ],
        },
      ],
    },
    {
      id: 'no-cancel',
      heading: '7. Makstud reklaamiperioodi ei saa sina tühistada',
      blocks: [
        {
          kind: 'p',
          content: [
            'Kui reklaamiperiood on makstud või tasuta antud, ei saa sina seda tühistada, sest selle päevad on broneeritud viie piirarvu vastu ega ole edasi müüdavad. See ei piira punktis 9 sätestatud tagasimakseid ega õigusi, mis seadus sulle annab.',
          ],
        },
      ],
    },
    {
      id: 'reasons',
      heading: '8. Millal võime tagasi lükata, enneaegselt lõpetada või tühistada',
      blocks: [
        {
          kind: 'p',
          content: [
            'Esitame sulle e-kirjaga sinu keeles põhjendused alati, kui lükkame taotluse tagasi, lõpetame reklaamiperioodi enneaegselt või tühistame selle. Alused on:',
          ],
        },
        {
          kind: 'ul',
          items: [
            [
              'Taotluse tagasilükkamine: üritus ei sobi (ei ole sinu oma, on lõppenud, kuupäevad on reeglitest väljas või päevad on täis); üritus vajab sisu ülevaatust ja ei läbi seda; me ei saa ettevõtet kinnitada; või muu põhjus, mille me esitame.',
            ],
            [
              'Enneaegne lõpetamine: sinu üritus tühistatakse või võetakse tagasi või sinu õigus üritusele tühistatakse (see juhtub automaatselt); sisu rikub sisupoliitikat; sa rikud neid tingimusi; me võtame funktsiooni kõigi jaoks kasutusest; seadus või ametiasutus nõuab seda; või muu põhjus, mille me kirjalikult esitame.',
            ],
            [
              'Tühistamine: makse pole algamispäevaks kohale jõudnud või kaardimakse leht jäi pooleli või aegus. Pooleli jäänud makselehe kohta e-kirja ei saada.',
            ],
          ],
        },
        {
          kind: 'p',
          content: ['Otsuse vaidlustamiseks võid vastata kontaktaadressile; vt punkt 14.'],
        },
      ],
    },
    {
      id: 'refunds',
      heading: '9. Tagasimaksed',
      blocks: [
        {
          kind: 'ul',
          items: [
            [
              'Kui reklaamiperiood peatub meie süül, tagastame kasutamata täispäevad. Päevad, mil reklaamiperiood oli pausil ilma sinu süüta (näiteks kuna duplikaatkuulutus võitis dubleerimise või sisu märgistus osutus valeks), loetakse kasutamata päevadeks.',
            ],
            [
              'Kui võtame funktsiooni kasutusest (lõpetamise põhjus „funktsioon kasutusest võetud”), tagastame kasutamata päevad täies mahus.',
            ],
            [
              'Kui sinu üritus tühistatakse või võetakse tagasi, reklaamiperiood lõpeb. Kasutamata päevad tagastame oma äranägemise järgi; selleks sul õigust ei ole.',
            ],
            [
              'Sisutest: kui sisu oli makse vastuvõtmise ajal juba piiratud, tagastame kasutamata päevad. Kui see muutus rikkumiseks pärast maksmist, siis mitte. Otsustame seda kirje põhjal, mida me hoiame selle kohta, mida reklaamiperiood näitas. Võime keelduda tagasimaksest, kui sisu kinnitus oli teadlikult vale.',
            ],
            [
              'Kui nimetatud ettevõte või ühing ei ole sinu oma, lõpetame reklaamiperioodi ja tagasimakset ei tee.',
            ],
            [
              'Möödunud päevi ei tagastata ja vähest näitamist ei loeta kunagi tagasimakse aluseks.',
            ],
          ],
        },
        {
          kind: 'p',
          content: [
            'Tagasimakse on kasutamata päevad pluss pausil olnud päevad, korrutatud päevahinnaga, mida sa maksid. Kaardimaksed tagastatakse kaardile kreeditarvega, mis tühistab käibemaksu. Pangaülekandega tehtud maksed tagastatakse pangaülekandega. Tasuta reklaamiperioodil pole midagi tagastada.',
          ],
        },
      ],
    },
    {
      id: 'content-policy',
      heading: '10. Reklaami sisupoliitika',
      blocks: [
        {
          kind: 'p',
          content: [
            'Sinu üritus ei tohi olla ükski neist viiest liigist, v.a juhul, kui oleme selle üle vaadanud ja sellele reklaamiperioodile kirjalikult kinnitanud:',
          ],
        },
        {
          kind: 'ul',
          items: [
            ['Tubakas: tubaka, aurustamise või vesipiibu keskne üritus.'],
            [
              'Hasartmäng: näiteks pokkeriõhtud, kasiinoõhtud ja kihlveoettevõtete üritused.',
            ],
            [
              'Alkohol: üritused, kus alkohol on peamine tõmbenumber või alkoholimark on pealkirjas või ürituse esitleja, nt viskidegusteerimine või „Brand X Night”. Kontsert baaris siia ei kuulu.',
            ],
            [
              'Poliitiline: erakonna, kandidaadi või kampaania poolt või heaks korraldatud üritus või üritus, mis puudutab hääletust, rahvahääletust või eelnõu.',
            ],
            ['Relvad: relvade või pürotehnika müük. Ilutulestikushow on lubatud.'],
          ],
        },
        {
          kind: 'p',
          content: [
            'Lisaks ei tohi reklaamiperioodi sisu olla eksitav, diskrimineeriv ega muul viisil reklaamiseadust rikkuv.',
          ],
        },
        {
          kind: 'p',
          content: [
            'Piiratud üritus võib Event Radaris siiski olla loetletud ja seda järjestatakse nagu tavaliselt, kuid seda ei reklaamita ilma meie ülevaatuseta ja võime tagasi lükata koos põhjendusega. Võime reklaamiperioodi igal ajal peatada või lõpetada koos põhjenduste esitamisega; tagasimaksed järgivad punkti 9. Kaardiga makstes kinnitad, et sinu üritus vastab sellele poliitikale, ja salvestame kinnituse koos aja ja poliitika versiooniga. Hoiame kirjet selle kohta, mida iga reklaamiperiood näitas: pealkiri, kirjelduse väljavõte, pilt, toimumiskoht, kuupäevad, hind ja märge, tehtud makse või andmise ajal ja uuesti iga muutmise korral. Lugeja teade sinu ürituse kohta ei peata reklaamiperioodi automaatselt; vaatame selle üle.',
          ],
        },
      ],
    },
    {
      id: 'data',
      heading: '11. Andmed, mida sa saad',
      blocks: [
        {
          kind: 'p',
          content: [
            'Iga reklaamiperioodi kohta näitab sinu reklaamiperioodide leht päevapõhist tabelit: kas see oli näidatud või pausil (ja miks), mitu korda seda näidati Avastamises, paigutati Päeva 5-sse, saadeti hommikuses e-kirjas ja avati, ning üks arv selle kohta, mitmele erinevale inimesele see Päeva 5-s kogu aknas paigutati. Tabel hõlmab täispäevi ja uuendatakse iga päev.',
          ],
        },
        {
          kind: 'ul',
          items: [
            [
              '„Näidatud” ja „paigutatud” ei ole „nähtud”. Tuntud robotid on välja jäetud. Me ei garanteeri ühtegi arvu.',
            ],
            [
              'Need on anonüümsed kogusummad. Sa ei saa vaatajate identiteete ega vaatajapõhiseid andmeid ega arve teiste korraldajate reklaamiperioodide kohta.',
            ],
            [
              'Sul säilib juurdepääs ostetud reklaamiperioodi aruandele ka siis, kui sinu õigus üritusele hiljem lõpeb.',
            ],
          ],
        },
        {
          kind: 'p',
          content: [
            'Mida me reklaamiperioodi kohta hoiame: äriandmed (sinu juriidiline nimi, registrikood, arveldus-e-post, hind, käibemaksumäär, arve, kuupäevad, nende tingimuste ja sisupoliitika versioonid, millega nõustusid), punktis 10 nimetatud sisukirje ja päevakogusummad. Kolmandad osapooled, kes seda töötlevad: Stripe (kaardimaksed ja arved), Resend (e-post), meie majutuspakkujad (Render, Cloudflare, Neon) ja Eesti äriregister (nime päring). Isikuandmeid käsitleb ',
            { text: 'privaatsuspoliitika', to: ROUTES.privacy },
            '.',
          ],
        },
      ],
    },
    {
      id: 'liability',
      heading: '12. Vastutus',
      blocks: [
        {
          kind: 'p',
          content: [
            'Seadusega lubatud ulatuses on meie vastutus sinu ees reklaamiperioodi eest piiratud hinnaga, mille sa selle eest maksid, välja arvatud tahtlus või raske hooletus. Me ei garanteeri katkematut teenust. ',
            { operator: 'liabilityCounsel' },
          ],
        },
      ],
    },
    {
      id: 'changes',
      heading: '13. Nende tingimuste muudatused',
      blocks: [
        {
          kind: 'p',
          content: [
            'Teavitame sind 15 päeva ette iga sisulisest muudatusest nendes tingimustes või lehel Kuidas tulemused järjestatakse, e-kirjaga igale korraldajakontole kuuluvale aadressile, koos kuupäevastatud märkega „mis muutus” selle lehe ülaosas. Parandused, mis ei muuda ühtki õigust ega kohustust, ei vaja teavitust. Juba makstud reklaamiperiood kehtib edasi tingimustel, mille alusel see osteti.',
          ],
        },
        {
          kind: 'p',
          content: [
            'Versiooniajalugu: 1 — ',
            { operator: 'dateInForce' },
            ' — esimene versioon.',
          ],
        },
      ],
    },
    {
      id: 'law',
      heading: '14. Kaebused, kohaldatav õigus ja vaidlused',
      blocks: [
        {
          kind: 'p',
          content: [
            'Kaebused: kirjuta aadressile ',
            { text: CONTACT_EMAIL, href: CONTACT_MAILTO },
            '. Vastame ',
            { operator: 'complaintReplyDays' },
            ' tööpäeva jooksul koos põhjendustega. Kui me vaidlust lahendada ei suuda, võid pöörduda ühe nende vahendajate poole: ',
            { operator: 'mediator1' },
            ', ',
            { operator: 'mediator2' },
            '.',
          ],
        },
        {
          kind: 'p',
          content: [
            'Nende tingimuste suhtes kohaldatakse Eesti õigust. Vaidlused lahendab ',
            { operator: 'court' },
            ', piiramata õigusi, mille seadus sulle annab.',
          ],
        },
      ],
    },
  ],
};

export default doc;
