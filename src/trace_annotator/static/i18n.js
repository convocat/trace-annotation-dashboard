// i18n — English (en) and Dutch (nl).
//
// Translations keyed by a stable `data-i18n` attribute used in the template.
// User-facing strings generated from JS (toasts, placeholders) go through t().
//
// Language resolution:
//   1. localStorage.trace_dashboard_lang
//   2. <html lang="..."> on initial load
//   3. 'en' default

const DICT = {
  en: {
    'subtitle': 'Trace annotation · PII-safe',
    'filters.heading': 'Filters',
    'filters.allSources': 'All sources',
    'filters.allTraces': 'All traces',
    'filters.status.todo': 'To do',
    'filters.status.done': 'Annotated',
    'filters.status.pass': 'Pass',
    'filters.status.fail': 'Fail',
    'filters.search.placeholder': 'Search in question...',
    'progress.heading': 'Progress',
    'progress.labelSuffix': 'annotated',
    'categories.heading': 'Categories (axial)',
    'categories.empty': 'No categories yet',
    'nav.prev': '← Prev',
    'nav.next': 'Next →',
    'nav.titlePrev': 'K or arrow left',
    'nav.titleNext': 'J or arrow right',
    'position.tracePrefix': 'Trace',
    'position.noMatch': 'No traces match the filter',
    'context.heading': 'Prior review / context',
    'context.response.label': 'Your response to this prior review',
    'context.response.hint': '— visible to whoever did the original review',
    'context.response.placeholder':
      "e.g. 'Agreed — prompt updated in v3', 'Not adopted; bot now refuses correctly', 'Picked up in sprint X'",
    'sources.heading': 'Sources',
    'form.passFail.label': 'Pass / Fail (binary, Hamel-style)',
    'form.pass': '✓ Pass',
    'form.fail': '✗ Fail',
    'form.note.label': 'Open coding note (first error / observation)',
    'form.note.placeholder':
      "What stands out? Write in your own words — this is the open coding step.",
    'form.category.label': 'Category (axial coding — type new or pick existing)',
    'form.category.placeholder': "e.g. 'incorrect URL', 'hallucination', 'too long'",
    'form.action.label': 'Action',
    'form.action.placeholder': "e.g. 'update prompt', 'add source', 'RAG fix'",
    'form.save.andNext': 'Save & next',
    'form.save.only': 'Save only',
    'footer.hotkeys': 'Hotkeys:',
    'footer.hotkey.next': 'next',
    'footer.hotkey.prev': 'prev',
    'footer.hotkey.pass': 'pass',
    'footer.hotkey.fail': 'fail',
    'footer.hotkey.saveAndNext': 'save & next',
    'toast.saved': 'Saved ✓',
    'toast.nothing': 'Nothing to save',
    'trace.cannotLoad': 'Could not load this trace. Langfuse might be unreachable.',
    'trace.noMessages': '(no messages available for this trace)',
    'trace.openInLangfuse': '↗ Open in Langfuse',
    'bubble.user': 'User',
    'bubble.assistant': 'Assistant',
    'bubble.system': 'System',
    'bubble.tool': 'Tool',
    'lang.toggle.en': 'EN',
    'lang.toggle.nl': 'NL',
  },

  nl: {
    'subtitle': 'Trace-annotatie · PII-veilig',
    'filters.heading': 'Filters',
    'filters.allSources': 'Alle bronnen',
    'filters.allTraces': 'Alle traces',
    'filters.status.todo': 'Nog te doen',
    'filters.status.done': 'Geannoteerd',
    'filters.status.pass': 'Pass',
    'filters.status.fail': 'Fail',
    'filters.search.placeholder': 'Zoek in vraag...',
    'progress.heading': 'Voortgang',
    'progress.labelSuffix': 'geannoteerd',
    'categories.heading': 'Categorieën (axial)',
    'categories.empty': 'Nog geen categorieën',
    'nav.prev': '← Vorige',
    'nav.next': 'Volgende →',
    'nav.titlePrev': 'K of pijl links',
    'nav.titleNext': 'J of pijl rechts',
    'position.tracePrefix': 'Trace',
    'position.noMatch': 'Geen traces in filter',
    'context.heading': 'Eerdere beoordeling / context',
    'context.response.label': 'Jouw reactie op deze beoordeling',
    'context.response.hint': '— zichtbaar voor degene die oorspronkelijk beoordeelde',
    'context.response.placeholder':
      "Bijv. 'Eens — prompt al aangepast in v3', 'Niet overgenomen want bot weigert nu correct', 'Opgepakt in sprint X'",
    'sources.heading': 'Bronnen',
    'form.passFail.label': 'Pass / Fail (binair, Hamel-stijl)',
    'form.pass': '✓ Pass',
    'form.fail': '✗ Fail',
    'form.note.label': 'Open coding-notitie (eerste fout / observatie)',
    'form.note.placeholder':
      "Wat valt je op? Schrijf in eigen woorden — dit is de open coding-stap.",
    'form.category.label': 'Categorie (axial coding — typ nieuw of kies bestaand)',
    'form.category.placeholder': "Bijv. 'onjuiste URL', 'hallucinatie', 'te lang'",
    'form.action.label': 'Actie',
    'form.action.placeholder': "Bijv. 'prompt aanpassen', 'bron toevoegen', 'RAG-fix'",
    'form.save.andNext': 'Opslaan & volgende',
    'form.save.only': 'Alleen opslaan',
    'footer.hotkeys': 'Hotkeys:',
    'footer.hotkey.next': 'volgende',
    'footer.hotkey.prev': 'vorige',
    'footer.hotkey.pass': 'pass',
    'footer.hotkey.fail': 'fail',
    'footer.hotkey.saveAndNext': 'opslaan & door',
    'toast.saved': 'Opgeslagen ✓',
    'toast.nothing': 'Niets om op te slaan',
    'trace.cannotLoad': 'Kon deze trace niet laden. Langfuse is mogelijk onbereikbaar.',
    'trace.noMessages': '(geen berichten beschikbaar voor deze trace)',
    'trace.openInLangfuse': '↗ Open in Langfuse',
    'bubble.user': 'Vraag',
    'bubble.assistant': 'Bot-antwoord',
    'bubble.system': 'Systeem',
    'bubble.tool': 'Tool',
    'lang.toggle.en': 'EN',
    'lang.toggle.nl': 'NL',
  },
};

const LANG_KEY = 'trace_dashboard_lang';

let LANG = (() => {
  try {
    const stored = localStorage.getItem(LANG_KEY);
    if (stored && DICT[stored]) return stored;
  } catch { /* ignore */ }
  const htmlLang = document.documentElement.lang;
  if (htmlLang && DICT[htmlLang]) return htmlLang;
  return 'en';
})();

function t(key, fallback) {
  return DICT[LANG]?.[key] ?? DICT.en[key] ?? fallback ?? key;
}

function setLang(code) {
  if (!DICT[code]) return;
  LANG = code;
  try { localStorage.setItem(LANG_KEY, code); } catch { /* ignore */ }
  document.documentElement.lang = code;
  applyTranslations();
  // Let the rest of the app refresh dynamic strings (toast, placeholders)
  document.dispatchEvent(new CustomEvent('langchanged', { detail: { lang: code } }));
}

function applyTranslations() {
  // Static text nodes
  for (const el of document.querySelectorAll('[data-i18n]')) {
    const key = el.getAttribute('data-i18n');
    el.textContent = t(key);
  }
  // Placeholders
  for (const el of document.querySelectorAll('[data-i18n-placeholder]')) {
    const key = el.getAttribute('data-i18n-placeholder');
    el.placeholder = t(key);
  }
  // Title attributes (hover tooltips)
  for (const el of document.querySelectorAll('[data-i18n-title]')) {
    const key = el.getAttribute('data-i18n-title');
    el.title = t(key);
  }
  // Mark active lang button
  for (const btn of document.querySelectorAll('[data-lang]')) {
    btn.classList.toggle('active', btn.getAttribute('data-lang') === LANG);
  }
}

// Expose
window.i18n = { t, setLang, applyTranslations, currentLang: () => LANG };

// Apply as soon as DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', applyTranslations);
} else {
  applyTranslations();
}
