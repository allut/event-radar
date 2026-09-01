import React from 'react';
import ReactDOM from 'react-dom/client';
// Self-hosted fonts (bundled into the Vite build, served same-origin) — replaces the
// external Google Fonts <link> so the CSP can drop third-party font/style hosts and
// no font request leaks to a third party.
// Manrope Variable (wayfinder #190) replaces DM Sans SPA-wide: DM Sans had no
// Cyrillic cut (ru fell back to system-ui), Manrope's variable-axis build covers
// latin+latin-ext+cyrillic in one file, at less payload than DM Sans's four
// static weights, and its 200-800 axis fixes --fw-bold:700 call sites that
// previously had no 700 weight file in the build.
import '@fontsource-variable/manrope';
import '@fontsource/cormorant-garamond/300.css';
import '@fontsource/cormorant-garamond/300-italic.css';
import '@fontsource/cormorant-garamond/400.css';
import '@fontsource/cormorant-garamond/400-italic.css';
import '@fontsource/cormorant-garamond/500.css';
import '@fontsource/cormorant-garamond/600.css';
import App from './App';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
