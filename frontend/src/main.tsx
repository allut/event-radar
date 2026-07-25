import React from 'react';
import ReactDOM from 'react-dom/client';
// Self-hosted fonts (bundled into the Vite build, served same-origin) — replaces the
// external Google Fonts <link> so the CSP can drop third-party font/style hosts and
// no font request leaks to a third party. Weights/styles mirror the former Google
// request exactly (DM Sans 300/400/500/600; Cormorant Garamond 400/400-italic/500/600).
// DM Sans ships latin + latin-ext only (no Cyrillic, same as Google) — Russian body
// text falls back to system-ui via the CSS stack, unchanged from before.
import '@fontsource/dm-sans/300.css';
import '@fontsource/dm-sans/400.css';
import '@fontsource/dm-sans/500.css';
import '@fontsource/dm-sans/600.css';
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
