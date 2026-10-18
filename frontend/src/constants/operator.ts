// Operator identity for the legal pages (spec #597, #613). Each field is `null`
// until the Operator supplies it at the switchover; a `null` field renders as a
// visible highlighted placeholder in the copy. Fill the value here, once, and
// every legal page picks it up. Any string, even '', counts as filled.

export type OperatorField =
  | 'name' // company name WITHOUT the legal form; the copy appends " OÜ"
  | 'registryCode'
  | 'seat' // registered seat address
  | 'vatNumber'
  | 'dateInForce' // date the Organizer terms version in ORGANIZER_TERMS_VERSION takes effect
  | 'complaintReplyDays' // working days to answer a complaint
  | 'mediator1'
  | 'mediator2'
  | 'court' // competent Estonian court
  | 'liabilityCounsel'; // set to '' once the Operator's counsel has confirmed the liability clause

export const OPERATOR_IDENTITY: Readonly<Record<OperatorField, string | null>> = {
  name: null,
  registryCode: null,
  seat: null,
  vatNumber: null,
  dateInForce: null,
  complaintReplyDays: null,
  mediator1: null,
  mediator2: null,
  court: null,
  liabilityCounsel: null,
};

// Placeholder wording per locale: shown as "⟨label⟩" while the field is null.
export const OPERATOR_FIELD_LABELS: Readonly<Record<OperatorField, Readonly<Record<string, string>>>> = {
  name: { en: 'Operator name', et: 'Operaatori nimi', ru: 'название Оператора' },
  registryCode: { en: 'registry code', et: 'registrikood', ru: 'регистрационный код' },
  seat: { en: 'seat address', et: 'asukoha aadress', ru: 'адрес местонахождения' },
  vatNumber: { en: 'VAT number', et: 'KMKR number', ru: 'номер плательщика НДС' },
  dateInForce: { en: 'date in force', et: 'jõustumise kuupäev', ru: 'дата вступления в силу' },
  complaintReplyDays: { en: 'number', et: 'arv', ru: 'число' },
  mediator1: { en: 'mediator 1', et: 'vahendaja 1', ru: 'посредник 1' },
  mediator2: { en: 'mediator 2', et: 'vahendaja 2', ru: 'посредник 2' },
  court: { en: 'competent Estonian court', et: 'pädev Eesti kohus', ru: 'компетентный эстонский суд' },
  liabilityCounsel: {
    en: "Operator's legal counsel to confirm this clause",
    et: 'operaatori juriidiline nõustaja kinnitab selle punkti',
    ru: 'юрист Оператора подтверждает этот пункт',
  },
};

// The Organizer terms page shows a DRAFT notice until legal review is done.
// Set to false when the Operator publishes the terms.
export const ORGANIZER_TERMS_IS_DRAFT = true;
