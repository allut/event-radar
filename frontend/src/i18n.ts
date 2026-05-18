import { LOCALES, PERSONAS } from './constants';

type Locale = 'en' | 'et' | 'ru';

// ---------------------------------------------------------------------------
// Persona multilingual data
// English strings are the single source of truth in constants.ts PERSONAS.
// Only non-English translations live here.
// ---------------------------------------------------------------------------
type PersonaLocale = { name: string; vibe: string };
const PERSONA_TRANSLATIONS: Record<string, Partial<Record<'et' | 'ru', PersonaLocale>>> = {
  underground_clubber: {
    et: { name: 'Klubikülastaja', vibe: 'Hilisöised reivid, techno, keldribaarid' },
    ru: { name: 'Клабер', vibe: 'Ночные рейвы, техно, подвальные бары' },
  },
  networking_pro: {
    et: { name: 'Võrgustikuproff', vibe: 'Idufirmade üritused, pitching, professionaalsed kohtumised' },
    ru: { name: 'Нетворкинг Про', vibe: 'Стартап-события, питчинги, профессиональные встречи' },
  },
  weekend_hobbyist: {
    et: { name: 'Nädalavahetuse Harrastaja', vibe: 'Töötoad, välistegevused, käsitööturgud' },
    ru: { name: 'Хоббист выходного дня', vibe: 'Мастер-классы, активный отдых, ярмарки' },
  },
  culture_buff: {
    et: { name: 'Kultuurihuviline', vibe: 'Muuseumid, teater, klassikalised kontserdid, kunstiavamised' },
    ru: { name: 'Ценитель культуры', vibe: 'Музеи, театр, классические концерты, арт-открытия' },
  },
  family_explorer: {
    et: { name: 'Perepuhkuse Harrastaja', vibe: 'Peresõbralik, loodusretked, nädalavahetuse väljasõidud' },
    ru: { name: 'Семейный исследователь', vibe: 'Семейный отдых, прогулки на природе, вылазки на выходных' },
  },
};

function _enPersona(slug: string): PersonaLocale {
  const p = PERSONAS.find((x) => x.slug === slug);
  return { name: p?.name ?? slug, vibe: p?.vibe ?? '' };
}

export function personaName(slug: string, locale: string): string {
  if (locale === 'en') return _enPersona(slug).name;
  return PERSONA_TRANSLATIONS[slug]?.[locale as 'et' | 'ru']?.name ?? _enPersona(slug).name;
}

export function personaVibe(slug: string, locale: string): string {
  if (locale === 'en') return _enPersona(slug).vibe;
  return PERSONA_TRANSLATIONS[slug]?.[locale as 'et' | 'ru']?.vibe ?? _enPersona(slug).vibe;
}

// ---------------------------------------------------------------------------
// Flat UI string translations
// ---------------------------------------------------------------------------
const TRANSLATIONS: Record<Locale, Record<string, string>> = {
  en: {
    // ── Brand / shared ──────────────────────────────────────────────────
    brand: 'Event Radar',
    settings_link: 'Settings',
    back_to_feed: '← Feed',
    back: '← Back',
    sign_out: 'Sign out',
    loading: 'Loading…',
    saved: 'Saved.',
    save_failed: 'Save failed.',
    generic_error: 'Something went wrong. Please try again.',

    // ── Login ────────────────────────────────────────────────────────────
    tagline: 'Your daily five events in Tallinn.',
    email_label: 'Email address',
    email_placeholder: 'you@example.com',
    send_link: 'Send me a link →',
    sending: 'Sending…',
    check_inbox: 'Check your inbox at',
    link_expires: 'The link expires in {minutes} minutes.',
    use_different: 'Use a different address',
    no_password: 'No password. No tracking. Just events.',

    // ── Auth verify ──────────────────────────────────────────────────────
    verifying: 'Verifying your sign-in link…',
    signed_in: 'Signed in! Redirecting…',
    no_token: 'No sign-in token found in the URL. Please request a new link.',
    verify_failed: 'Verification failed. The link may have expired.',
    request_new_link: 'Request a new link →',

    // ── Onboarding ───────────────────────────────────────────────────────
    onboarding_heading: "What's your vibe?",
    onboarding_sub: 'Pick one primary persona. Optionally add a secondary to widen your feed.',
    persona_blending: 'Blending {primary} with {secondary}',
    lets_go: "Let's go →",
    saving: 'Saving…',

    // ── Feed ─────────────────────────────────────────────────────────────
    daily_five: 'Your Daily Five',
    curated_at: 'Curated at {time}',
    feed_empty_title: 'Your feed is being prepared…',
    feed_empty_msg: "We're scanning Tallinn's event landscape. Your personalized Daily Five will be ready by 06:00 tomorrow morning.",
    feed_empty_hint: 'In the meantime, new events are being classified and ranked for you.',
    feed_error: 'Failed to load your feed. Please refresh.',

    // ── Event card / detail ──────────────────────────────────────────────
    why_go: 'Why go',
    tickets: 'Tickets →',
    get_tickets: 'Get tickets →',
    signal_like: 'Like',
    signal_dislike: 'Dislike',
    signal_bookmark: 'Bookmark',
    loading_event: 'Loading event…',
    event_not_found: 'Event not found or unavailable.',
    back_to_feed_link: '← Back to feed',
    ends_at: 'ends {time}',
    view_on_map: 'View on map →',

    // ── PersonaCard ──────────────────────────────────────────────────────────
    persona_btn_deselect: 'Deselect',
    persona_btn_set_primary: 'Set as primary',
    persona_btn_set_secondary: 'Set as secondary',
    persona_btn_add_secondary: '+ 2nd',
    persona_btn_remove_secondary: 'Remove secondary',
    persona_badge_secondary_label: 'Secondary — click to remove',
    persona_badge_secondary_text: '2nd ×',

    // ── Settings ─────────────────────────────────────────────────────────
    section_account: 'Account',
    section_language: 'Language',
    section_persona: 'Persona',
    section_digest: 'Email digest',
    digest_label: 'Daily Five digest',
    digest_desc: 'Receive your Daily Five by email each morning.',
    digest_off: 'Email digest is off. You can re-enable it any time.',
    digest_subscribe: 'Subscribe to email digest',
    digest_unsubscribe: 'Unsubscribe from email digest',
    persona_primary: 'Primary',
    persona_secondary: 'Secondary',
    change_persona: 'Change persona →',
    no_persona: 'No persona selected.',
    settings_error: 'Failed to load settings. Please refresh.',

    // ── 404 / error boundary ─────────────────────────────────────────────
    not_found_title: 'Page not found',
    not_found_msg: "The page you're looking for doesn't exist.",
    not_found_back: '← Back to feed',
    error_boundary_title: 'Something went wrong',
    error_boundary_msg: 'An unexpected error occurred. Try refreshing the page.',
    error_boundary_reload: 'Reload page',
  },

  et: {
    brand: 'Event Radar',
    settings_link: 'Seaded',
    back_to_feed: '← Voog',
    back: '← Tagasi',
    sign_out: 'Logi välja',
    loading: 'Laaditakse…',
    saved: 'Salvestatud.',
    save_failed: 'Salvestamine ebaõnnestus.',
    generic_error: 'Midagi läks valesti. Palun proovi uuesti.',

    tagline: 'Sinu viis igapäevast sündmust Tallinnas.',
    email_label: 'E-posti aadress',
    email_placeholder: 'sina@example.ee',
    send_link: 'Saada mulle link →',
    sending: 'Saatmine…',
    check_inbox: 'Kontrolli oma postkasti:',
    link_expires: 'Link aegub {minutes} minuti pärast.',
    use_different: 'Kasuta teist aadressi',
    no_password: 'Pole parooli. Pole jälgimist. Ainult sündmused.',

    verifying: 'Sisselogimislinki kontrollitakse…',
    signed_in: 'Sisse logitud! Suunatakse ümber…',
    no_token: 'URL-is ei leitud sisselogimise tokenit. Palun taotle uus link.',
    verify_failed: 'Kontrollimine ebaõnnestus. Link võib olla aegunud.',
    request_new_link: 'Taotle uus link →',

    onboarding_heading: 'Milline on sinu tuju?',
    onboarding_sub: 'Vali üks peamine persoon. Soovi korral lisa teisejärguline, et oma voogu laiendada.',
    persona_blending: '{primary} ja {secondary} segu',
    lets_go: 'Edasi →',
    saving: 'Salvestamine…',

    daily_five: 'Sinu Päevane Viisik',
    curated_at: 'Koostatud kell {time}',
    feed_empty_title: 'Sinu voog koostatakse…',
    feed_empty_msg: 'Skannime Tallinna sündmuste maastikku. Sinu isikupärastatud Päevane Viisik on valmis homme hommikuks kell 06:00.',
    feed_empty_hint: 'Seniks klassifitseeritakse ja järjestatakse sinu jaoks uusi sündmusi.',
    feed_error: 'Voo laadimine ebaõnnestus. Palun värskenda.',

    why_go: 'Miks minna',
    tickets: 'Piletid →',
    get_tickets: 'Hangi piletid →',
    signal_like: 'Meeldib',
    signal_dislike: 'Ei meeldi',
    signal_bookmark: 'Järjehoidja',
    loading_event: 'Sündmust laaditakse…',
    event_not_found: 'Sündmust ei leitud või see pole saadaval.',
    back_to_feed_link: '← Tagasi voolu',
    ends_at: 'lõpeb {time}',
    view_on_map: 'Vaata kaardil →',

    persona_btn_deselect: 'Tühista',
    persona_btn_set_primary: 'Määra peamiseks',
    persona_btn_set_secondary: 'Määra teisejärguliseks',
    persona_btn_add_secondary: '+ 2nda',
    persona_btn_remove_secondary: 'Eemalda teisejärguline',
    persona_badge_secondary_label: 'Teisejärguline — kliki eemaldamiseks',
    persona_badge_secondary_text: '2nda ×',

    section_account: 'Konto',
    section_language: 'Keel',
    section_persona: 'Persoon',
    section_digest: 'E-posti uudiskiri',
    digest_label: 'Päevase Viisiku kokkuvõte',
    digest_desc: 'Saa oma Päevane Viisik iga hommik e-postiga.',
    digest_off: 'E-posti uudiskiri on välja lülitatud. Saad selle igal ajal uuesti sisse lülitada.',
    digest_subscribe: 'Telli e-posti uudiskiri',
    digest_unsubscribe: 'Tühista e-posti uudiskiri',
    persona_primary: 'Peamine',
    persona_secondary: 'Teisejärguline',
    change_persona: 'Muuda persooni →',
    no_persona: 'Ühtegi persooni pole valitud.',
    settings_error: 'Seadete laadimine ebaõnnestus. Palun värskenda.',

    not_found_title: 'Lehte ei leitud',
    not_found_msg: 'Otsitavat lehte ei ole olemas.',
    not_found_back: '← Tagasi voolu',
    error_boundary_title: 'Midagi läks valesti',
    error_boundary_msg: 'Tekkis ootamatu viga. Proovi lehte uuesti laadida.',
    error_boundary_reload: 'Laadi leht uuesti',
  },

  ru: {
    brand: 'Event Radar',
    settings_link: 'Настройки',
    back_to_feed: '← Лента',
    back: '← Назад',
    sign_out: 'Выйти',
    loading: 'Загрузка…',
    saved: 'Сохранено.',
    save_failed: 'Ошибка сохранения.',
    generic_error: 'Что-то пошло не так. Попробуйте снова.',

    tagline: 'Пять ваших ежедневных событий в Таллине.',
    email_label: 'Электронная почта',
    email_placeholder: 'вы@example.ee',
    send_link: 'Отправить ссылку →',
    sending: 'Отправка…',
    check_inbox: 'Проверьте почту:',
    link_expires: 'Ссылка истекает через {minutes} минут.',
    use_different: 'Использовать другой адрес',
    no_password: 'Без пароля. Без слежки. Только события.',

    verifying: 'Проверяем вашу ссылку для входа…',
    signed_in: 'Вы вошли! Перенаправление…',
    no_token: 'В URL не найден токен. Пожалуйста, запросите новую ссылку.',
    verify_failed: 'Проверка не удалась. Срок действия ссылки мог истечь.',
    request_new_link: 'Запросить новую ссылку →',

    onboarding_heading: 'Каков ваш вайб?',
    onboarding_sub: 'Выберите основную персону. Дополнительно добавьте вторичную для расширения ленты.',
    persona_blending: 'Смешивание {primary} с {secondary}',
    lets_go: 'Поехали →',
    saving: 'Сохранение…',

    daily_five: 'Ваша ежедневная пятёрка',
    curated_at: 'Составлено в {time}',
    feed_empty_title: 'Ваша лента готовится…',
    feed_empty_msg: 'Сканируем события Таллина. Ваша персональная пятёрка будет готова к 06:00 завтра утром.',
    feed_empty_hint: 'Тем временем новые события классифицируются и ранжируются для вас.',
    feed_error: 'Не удалось загрузить ленту. Обновите страницу.',

    why_go: 'Почему стоит пойти',
    tickets: 'Билеты →',
    get_tickets: 'Получить билеты →',
    signal_like: 'Нравится',
    signal_dislike: 'Не нравится',
    signal_bookmark: 'Закладка',
    loading_event: 'Загрузка события…',
    event_not_found: 'Событие не найдено или недоступно.',
    back_to_feed_link: '← Назад к ленте',
    ends_at: 'заканчивается {time}',
    view_on_map: 'Посмотреть на карте →',

    persona_btn_deselect: 'Отменить',
    persona_btn_set_primary: 'Сделать основной',
    persona_btn_set_secondary: 'Назначить вторичной',
    persona_btn_add_secondary: '+ 2-я',
    persona_btn_remove_secondary: 'Удалить вторичную',
    persona_badge_secondary_label: 'Вторичная — нажмите для удаления',
    persona_badge_secondary_text: '2-я ×',

    section_account: 'Аккаунт',
    section_language: 'Язык',
    section_persona: 'Персона',
    section_digest: 'Почтовая рассылка',
    digest_label: 'Дайджест пятёрки',
    digest_desc: 'Получайте вашу пятёрку по электронной почте каждое утро.',
    digest_off: 'Рассылка отключена. Вы можете включить её в любое время.',
    digest_subscribe: 'Подписаться на рассылку',
    digest_unsubscribe: 'Отписаться от рассылки',
    persona_primary: 'Основная',
    persona_secondary: 'Дополнительная',
    change_persona: 'Изменить персону →',
    no_persona: 'Персона не выбрана.',
    settings_error: 'Не удалось загрузить настройки. Обновите страницу.',

    not_found_title: 'Страница не найдена',
    not_found_msg: 'Запрашиваемая страница не существует.',
    not_found_back: '← Назад к ленте',
    error_boundary_title: 'Что-то пошло не так',
    error_boundary_msg: 'Произошла непредвиденная ошибка. Попробуйте обновить страницу.',
    error_boundary_reload: 'Обновить страницу',
  },
};

export function t(key: string, locale: string): string {
  const loc = (locale as Locale) in TRANSLATIONS ? (locale as Locale) : LOCALES[0].code;
  return TRANSLATIONS[loc][key] ?? TRANSLATIONS.en[key] ?? key;
}

export function ti(key: string, locale: string, vars: Record<string, string>): string {
  let str = t(key, locale);
  for (const [k, v] of Object.entries(vars)) {
    str = str.replaceAll(`{${k}}`, v);
  }
  return str;
}
