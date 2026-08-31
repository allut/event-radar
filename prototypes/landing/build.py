#!/usr/bin/env python3
"""Assemble the ten Landing artboards into one comparison sheet (wayfinder #184).

Throwaway prototype tooling. Reads artboards/*.html, inlines each full document
into a <script type="text/plain"> template block, and emits artboards.html —
the exact file published as the Artifact. Run: python3 prototypes/landing/build.py
"""
from __future__ import annotations

import json
import pathlib

HERE = pathlib.Path(__file__).parent
BOARDS = HERE / "artboards"
OUT = HERE / "artboards.html"

SHEET = [
    {
        "id": "a1", "code": "A1", "name": "dark-editorial", "dir": "A", "dirname": "Editorial supplement",
        "brand": "on-brand", "display": "Cormorant Garamond", "locale": "EN", "mode": "dark",
        "sig": "Dateline masthead, drop cap and a boxed classified ad — density comes from type, not boxes.",
    },
    {
        "id": "a2", "code": "A2", "name": "light-paper", "dir": "A", "dirname": "Editorial supplement",
        "brand": "push · two-colour press", "display": "PT Serif", "locale": "ET", "mode": "light",
        "sig": "Newsprint grey + one spot red, no gold at all. Email capture is a dashed subscription coupon.",
    },
    {
        "id": "a3", "code": "A3", "name": "dense-index", "dir": "A", "dirname": "Editorial supplement",
        "brand": "on-brand", "display": "Cormorant Garamond", "locale": "EN", "mode": "dark",
        "sig": "The page is the listings. Fourteen category letter-codes with a legend; sticky capture rule.",
    },
    {
        "id": "b1", "code": "B1", "name": "full-instrument", "dir": "B", "dirname": "Instrument console",
        "brand": "on-brand", "display": "Cormorant + JetBrains Mono", "locale": "EN", "mode": "dark",
        "sig": "A real sweep with labelled returns, a monospaced signal ledger and CSS-only counting gauges.",
    },
    {
        "id": "b2", "code": "B2", "name": "restrained-instrument", "dir": "B", "dirname": "Instrument console",
        "brand": "on-brand", "display": "Cormorant + JetBrains Mono", "locale": "RU", "mode": "dark",
        "sig": "One instrument only: the eight-week volume histogram. Margin ticks, hairlines, nothing spins.",
    },
    {
        "id": "b3", "code": "B3", "name": "instrument-with-imagery", "dir": "B", "dirname": "Instrument console",
        "brand": "push · red-lit panel", "display": "Cormorant + JetBrains Mono", "locale": "EN", "mode": "dark",
        "sig": "Night-cockpit red instead of gold; photography arrives as duotone channel feeds with readouts.",
    },
    {
        "id": "c1", "code": "C1", "name": "cinematic-on-brand", "dir": "C", "dirname": "Poster-led cinematic",
        "brand": "on-brand", "display": "Cormorant Garamond", "locale": "ET", "mode": "dark",
        "sig": "Stacked full-bleed posters under scrims; a gold hairline cuts through each frame. Flat proof section below.",
    },
    {
        "id": "c2", "code": "C2", "name": "cinematic-new-type", "dir": "C", "dirname": "Poster-led cinematic",
        "brand": "push · oxblood + silver", "display": "Playfair Display (variable)", "locale": "EN", "mode": "dark",
        "sig": "A sticky filmstrip rail of tonight's times down the left margin; Playfair set very large and very tight.",
    },
    {
        "id": "d1", "code": "D1", "name": "dark-board", "dir": "D", "dirname": "Departure board",
        "brand": "on-brand", "display": "Cormorant + Manrope 800 tabular", "locale": "EN", "mode": "dark",
        "sig": "Split-flap reveal on the destination and every row; the email capture is itself a board row at 06:00.",
    },
    {
        "id": "d2", "code": "D2", "name": "warm-light-board", "dir": "D", "dirname": "Departure board",
        "brand": "push · warm light + signal blue", "display": "Oswald (variable)", "locale": "RU", "mode": "light",
        "sig": "Condensed Cyrillic at 100px on a warm board, black rules, one signal blue. The Oswald specimen test.",
    },
]

HEAD = """<title>Radar Landing Artboards</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#0c0d10;--panel:#141519;--panel-2:#1b1d22;--line:#26282f;--line-2:#1c1e23;
  --fg:#e7e5e0;--fg-2:#a7a9b0;--fg-3:#6e727c;--acc:#c8922a;--push:#7fa6d8;
  --mono:'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
  --sans:'IBM Plex Sans',system-ui,-apple-system,'Segoe UI',sans-serif;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font-family:var(--sans);font-size:14px;line-height:1.55}
a{color:inherit}
.lab{font-family:var(--mono);font-size:10px;letter-spacing:.12em;text-transform:uppercase}

/* ---- masthead ---- */
.head{border-bottom:1px solid var(--line);padding:26px 22px 0}
.head h1{margin:0;font-size:clamp(22px,3.4vw,34px);font-weight:600;letter-spacing:-.022em;text-wrap:balance}
.head p{margin:8px 0 0;color:var(--fg-2);max-width:78ch;font-size:14px}
.head p b{color:var(--fg)}
.meta{display:flex;flex-wrap:wrap;gap:0;margin-top:16px}
.meta span{font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--fg-3);
  padding:0 13px;border-left:1px solid var(--line)}
.meta span:first-child{padding-left:0;border-left:0}
.meta b{color:var(--acc)}

/* ---- controls ---- */
.bar{position:sticky;top:0;z-index:20;background:rgba(12,13,16,.94);backdrop-filter:blur(8px);
  border-bottom:1px solid var(--line);padding:9px 22px;display:flex;gap:10px 22px;align-items:center;flex-wrap:wrap}
.grp{display:flex;align-items:center;gap:8px}
.grp>.lab{color:var(--fg-3)}
.seg{display:flex;border:1px solid var(--line);border-radius:2px;overflow:hidden}
.seg button{background:transparent;border:0;color:var(--fg-2);font-family:var(--mono);font-size:10.5px;
  letter-spacing:.09em;text-transform:uppercase;padding:6px 11px;cursor:pointer}
.seg button+button{border-left:1px solid var(--line)}
.seg button[aria-pressed=true]{background:var(--acc);color:#14151a;font-weight:700}
.tog{display:inline-flex;align-items:center;gap:7px;font-family:var(--mono);font-size:10.5px;letter-spacing:.09em;
  text-transform:uppercase;color:var(--fg-2);cursor:pointer;border:1px solid var(--line);padding:6px 11px;border-radius:2px}
.tog input{accent-color:var(--acc);margin:0}
.tog:has(input:checked){border-color:var(--acc);color:var(--fg)}
.jump{margin-left:auto;display:flex;flex-wrap:wrap;gap:0}
.jump a{font-family:var(--mono);font-size:10.5px;letter-spacing:.08em;color:var(--fg-3);text-decoration:none;
  padding:5px 8px;border:1px solid transparent}
.jump a:hover{color:var(--acc);border-color:var(--line)}

/* ---- boards ---- */
.sheet{padding:0 22px 90px}
.dirhead{padding:38px 0 12px;border-bottom:1px solid var(--line);display:flex;align-items:baseline;gap:14px;
  flex-wrap:wrap}
.dirhead h2{margin:0;font-size:19px;font-weight:650;letter-spacing:-.012em}
.dirhead h2 em{font-style:normal;color:var(--acc);font-family:var(--mono);margin-right:8px}
.dirhead p{margin:0;color:var(--fg-3);font-size:12.5px;flex:1;min-width:220px}

.card{margin-top:24px;border:1px solid var(--line);background:var(--panel)}
.card>header{display:flex;gap:12px 18px;align-items:baseline;flex-wrap:wrap;padding:12px 14px;
  border-bottom:1px solid var(--line);background:var(--panel-2)}
.card h3{margin:0;font-size:15px;font-weight:650;letter-spacing:-.01em}
.card h3 em{font-style:normal;font-family:var(--mono);color:var(--acc);margin-right:9px;font-size:13px}
.chips{display:flex;gap:6px;flex-wrap:wrap}
.chip{font-family:var(--mono);font-size:9.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--fg-2);
  border:1px solid var(--line);padding:3px 8px;border-radius:2px;white-space:nowrap}
.chip.brand{color:var(--acc);border-color:rgba(200,146,42,.4)}
.chip.push{color:var(--push);border-color:rgba(127,166,216,.4)}
.chip.loc{color:var(--fg)}
.card .sig{margin:0;padding:11px 14px;border-bottom:1px solid var(--line);color:var(--fg-2);font-size:13px}
.stage{background:#000;position:relative;overflow:hidden}
.stage.pending{min-height:280px}
.stage.pending:after{content:"loading…";position:absolute;inset:0;display:flex;align-items:center;
  justify-content:center;font-family:var(--mono);font-size:11px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--fg-3)}
.stage iframe{border:0;display:block;transform-origin:0 0;background:#000}
.scalenote{padding:8px 14px;font-family:var(--mono);font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--fg-3);border-top:1px solid var(--line);display:flex;justify-content:space-between;gap:12px;
  flex-wrap:wrap}

footer.end{padding:34px 22px 70px;border-top:1px solid var(--line);color:var(--fg-3);font-size:13px}
footer.end p{max-width:80ch;margin:0 0 10px}
footer.end b{color:var(--fg-2)}
@media(max-width:700px){
  .head,.bar,.sheet{padding-left:14px;padding-right:14px}
  .jump{display:none}
}
:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
</style>"""


def build() -> str:
    parts: list[str] = [HEAD]
    parts.append("""
<div class="head">
  <h1>Landing artboards — ten prototypes, four directions</h1>
  <p>Throwaway single-file HTML artboards for the Landing redesign (<b>#184</b>, under <b>#181</b>). Every number,
  event title, venue and price below is real, taken from the published catalogue on 31 Aug 2026. Six artboards keep the
  current brand (<b>#13161e / #c8922a /</b> Cormorant Garamond); four push palette, type or mode. Body type is
  <b>Manrope</b> on all ten — settled by #190 and not a lever any direction may pull.</p>
  <div class="meta">
    <span>10 artboards</span><span>4 directions</span><span><b>6</b> on-brand · <b>4</b> pushing</span>
    <span>2× ET · 2× RU · 6× EN</span><span>CSS-only motion</span><span>Images are CSS stand-ins</span>
  </div>
</div>

<div class="bar">
  <div class="grp"><span class="lab">Width</span>
    <div class="seg" id="w">
      <button data-w="1280" aria-pressed="true">1280</button>
      <button data-w="900" aria-pressed="false">900</button>
      <button data-w="390" aria-pressed="false">390</button>
    </div>
  </div>
  <label class="tog"><input type="checkbox" id="noimg"> Strip imagery</label>
  <label class="tog"><input type="checkbox" id="rm"> Reduced motion</label>
  <nav class="jump" id="jump"></nav>
</div>

<div class="sheet" id="sheet"></div>

<footer class="end">
  <p><b>Reading the toggles.</b> <em>Strip imagery</em> removes every photographic plate, so you can check the ticket's
  rule that imagery amplifies but is never load-bearing. <em>Reduced motion</em> applies the same collapse that
  <code>prefers-reduced-motion: reduce</code> does inside each artboard.</p>
  <p><b>What is faked.</b> Photography — the artboard sandbox cannot load external images, so every "photo" is a layered
  CSS gradient with film grain. Judge composition and scrim behaviour, not the picture. Everything else — counts, event
  titles, venues, times, prices, source names, schedule times — is real.</p>
</footer>
""")

    for b in SHEET:
        html = (BOARDS / f"{b['id']}.html").read_text(encoding="utf-8")
        assert "</script" not in html.lower(), f"{b['id']}: template contains a script close tag"
        parts.append(f'<script type="text/plain" data-board="{b["id"]}">\n{html}\n</script>')

    meta_js = json.dumps(SHEET, ensure_ascii=False, indent=1)
    parts.append("<script>\nconst BOARDS = " + meta_js + ";\n" + RUNTIME + "\n</script>")
    return "\n".join(parts)


RUNTIME = r"""
const sheet = document.getElementById('sheet');
const jump = document.getElementById('jump');
const NOMINAL_VH = 900;   // the window height every artboard's vh units are measured against
const state = { w: 1280, noimg: false, rm: false };
const frames = [];

let lastDir = null;
for (const b of BOARDS) {
  if (b.dir !== lastDir) {
    lastDir = b.dir;
    const dh = document.createElement('div');
    dh.className = 'dirhead';
    dh.innerHTML = '<h2><em>' + b.dir + '</em>' + b.dirname + '</h2>';
    sheet.appendChild(dh);
  }
  const card = document.createElement('section');
  card.className = 'card';
  card.id = b.id;
  const pushed = b.brand.indexOf('push') === 0;
  card.innerHTML =
    '<header><h3><em>' + b.code + '</em>' + b.name + '</h3><div class="chips">' +
      '<span class="chip ' + (pushed ? 'push' : 'brand') + '">' + b.brand + '</span>' +
      '<span class="chip">' + b.display + '</span>' +
      '<span class="chip">Manrope body</span>' +
      '<span class="chip loc">' + b.locale + '</span>' +
      '<span class="chip">' + b.mode + '</span>' +
    '</div></header>' +
    '<p class="sig">' + b.sig + '</p>' +
    '<div class="stage pending"></div>' +
    '<div class="scalenote"><span data-note>—</span><span>' + b.code + ' · ' + b.dirname + '</span></div>';
  sheet.appendChild(card);

  const a = document.createElement('a');
  a.href = '#' + b.id;
  a.textContent = b.code;
  jump.appendChild(a);

  frames.push({ meta: b, stage: card.querySelector('.stage'), note: card.querySelector('[data-note]'), iframe: null });
}

function source(id) {
  const tpl = document.querySelector('script[data-board="' + id + '"]');
  let cls = 'ab';
  if (state.noimg) cls += ' noimg';
  if (state.rm) cls += ' rm';
  return tpl.textContent.replace('class="ab"', 'class="' + cls + '"');
}

function fit(f) {
  if (!f.iframe) return;
  const cw = f.stage.clientWidth;
  const scale = Math.min(1, cw / state.w);
  // Width first: the artboard has to reflow at the new viewport before its
  // height means anything. Measuring first reports the previous width's height.
  f.iframe.style.width = state.w + 'px';
  f.iframe.style.height = NOMINAL_VH + 'px';   // resolve vh units against a real window height
  let h = NOMINAL_VH;
  try {
    const d = f.iframe.contentDocument;
    if (d) h = Math.max(d.documentElement.scrollHeight, d.body ? d.body.scrollHeight : 0);
  } catch (e) { /* cross-origin fallback */ }
  f.iframe.style.height = h + 'px';
  f.iframe.style.transform = 'scale(' + scale + ')';
  f.iframe.style.marginLeft = Math.max(0, (cw - state.w * scale) / 2) + 'px';
  f.stage.style.height = Math.round(h * scale) + 'px';
  f.note.textContent = state.w + ' px viewport · ' + Math.round(h) + ' px tall · shown at ' +
    Math.round(scale * 100) + '%';
}

function mount(f) {
  if (f.iframe) return;
  const el = document.createElement('iframe');
  el.setAttribute('title', f.meta.code + ' — ' + f.meta.name);
  el.setAttribute('scrolling', 'no');
  el.addEventListener('load', () => {
    f.stage.classList.remove('pending');
    fit(f);
    setTimeout(() => fit(f), 700);   // settle after webfonts land
    setTimeout(() => fit(f), 2200);
  });
  f.iframe = el;
  f.stage.appendChild(el);
  el.srcdoc = source(f.meta.id);
}

function remount() {
  for (const f of frames) {
    if (!f.iframe) continue;
    f.stage.classList.add('pending');
    f.iframe.srcdoc = source(f.meta.id);
  }
}

const io = new IntersectionObserver((entries) => {
  for (const e of entries) {
    if (!e.isIntersecting) continue;
    const f = frames.find((x) => x.stage === e.target);
    if (f) { mount(f); io.unobserve(e.target); }
  }
}, { rootMargin: '600px 0px' });
frames.forEach((f) => io.observe(f.stage));

document.getElementById('w').addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-w]');
  if (!btn) return;
  state.w = parseInt(btn.dataset.w, 10);
  for (const b of document.querySelectorAll('#w button')) {
    b.setAttribute('aria-pressed', String(b === btn));
  }
  frames.forEach(fit);
});
document.getElementById('noimg').addEventListener('change', (e) => {
  state.noimg = e.target.checked; remount();
});
document.getElementById('rm').addEventListener('change', (e) => {
  state.rm = e.target.checked; remount();
});

let t;
addEventListener('resize', () => { clearTimeout(t); t = setTimeout(() => frames.forEach(fit), 160); });
"""


if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.1f} KB)")
