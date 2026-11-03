#!/usr/bin/env python3
"""Render docs/index.html from site.json, data/data.json, and data/slates/*.json.

Project-specific code lives in the section renderers near the bottom
(`sections()`) and in LIVE_JS. Everything above them is shared page furniture:
tokens, theme and time zone controls, tables, twisties, footer.

The page embeds the default night's slate and fetches other nights from
docs/slates/. LIVE_JS reads each game's live stats feed in the browser at a
pace set by the game's interest score (see PLAN.md and README.md).
"""
import html
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent
SITE = json.loads((BASE / "site.json").read_text())
DATA = json.loads((BASE / "data" / "data.json").read_text())
SLATES = BASE / "data" / "slates"
OUT = BASE / SITE.get("output", "docs/index.html")
HOME_TZ = ZoneInfo(SITE["timezones"][0]["id"])
NOW = datetime.now(timezone.utc)


def esc(value):
    return html.escape("" if value is None else str(value), quote=True)


def stamp(iso, fmt="%Y-%m-%d %-I:%M %p"):
    """Format an ISO timestamp in the home time zone for footer text."""
    return datetime.fromisoformat(iso).astimezone(HOME_TZ).strftime(fmt)


def time_tag(iso, fmt="full"):
    """A <time> the page re-renders in the viewer's chosen time zone."""
    return f'<time datetime="{esc(iso)}" data-fmt="{fmt}">{esc(stamp(iso))}</time>'


def link(href, text, cls=""):
    """External links open in a new tab. Same-page anchors do not."""
    if href.startswith("#"):
        return f'<a href="{esc(href)}"{f" class={chr(34)}{cls}{chr(34)}" if cls else ""}>{esc(text)}</a>'
    return f'<a href="{esc(href)}" target="_blank" rel="noopener"{f" class={chr(34)}{cls}{chr(34)}" if cls else ""}>{esc(text)}</a>'


def table(headers, rows, lead_cols=1, caption=None, sortable=True):
    """A table whose first `lead_cols` columns are left-aligned and whose data
    columns are centered, header cells included. Headers sort on click unless
    `sortable=False`. Pass cells as HTML strings; put a `data-sort` attribute
    on a cell when its visible text is not what should sort (a date, a rank)."""
    th = "".join(f'<th{" class=lead" if i < lead_cols else ""}{" role=button tabindex=0 aria-sort=none" if sortable else ""}>{h}</th>' for i, h in enumerate(headers))
    body = []
    for row in rows:
        td = "".join(f'<td{" class=lead" if i < lead_cols else ""}>{c}</td>' for i, c in enumerate(row))
        body.append(f"<tr>{td}</tr>")
    cap = f"<caption>{esc(caption)}</caption>" if caption else ""
    return f'<div class="tablewrap"><table{" class=sortable" if sortable else ""}>{cap}<thead><tr>{th}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def twisty(title, inner, count=None, open_=True, id_=None, hidden=False):
    """A section the reader can collapse. All twisties reopen on refresh."""
    badge = f' <span class="count">{esc(count)}</span>' if count is not None else ""
    attrs = (f' id="{esc(id_)}"' if id_ else "") + (" open" if open_ else "") + (" hidden" if hidden else "")
    return f'<details class="group"{attrs}><summary><h2>{esc(title)}{badge}</h2></summary>{inner}</details>'


def opinion_box(title, note, paragraphs):
    """A clearly labeled opinion, set apart from the sourced content."""
    body = "".join(f"<p>{esc(p)}</p>" for p in paragraphs)
    return f'<section class="opinion"><h2>{esc(title)}</h2><p class="note">{esc(note)}</p><blockquote>{body}</blockquote></section>'


CSS = r"""
:root{color-scheme:light;--bg:#f4f3ef;--surface:#ffffff;--surface2:#ecebe5;--line:#d8d5cb;--ink:#1e2229;--muted:#616873;--faint:#8c939d;--link:#1f4e79;--pos:#2e8b57;--neg:#c0504d;--live:#d6323c;--warn:#9a5b00;--accent:ACCENT_LIGHT;--on-accent:#fff;--chip:#e9e7df;--gray:#ebeae5;--logo-edge:drop-shadow(0 0 .5px rgba(0,0,0,.5));--lift:0 1px 2px rgba(30,34,41,.1),0 3px 8px rgba(30,34,41,.08);
--s1:4px;--s2:8px;--s3:12px;--s4:16px;--s5:24px;--s6:40px;--pill:36px;--fs-sm:.85rem;--fs-md:.95rem;--fs-base:1rem}
:root[data-theme="dark"]{color-scheme:dark;--bg:#15181d;--surface:#1d2128;--surface2:#252a32;--line:#363c46;--ink:#e7e9ec;--muted:#a7adb7;--faint:#7d848f;--link:#8ab8e6;--pos:#5fc08a;--neg:#e2807c;--live:#ff6b6b;--warn:#e8b04b;--accent:ACCENT_DARK;--on-accent:#15181d;--chip:#2e343d;--gray:#252a32;--logo-edge:drop-shadow(0 0 .6px rgba(255,255,255,.85)) drop-shadow(0 0 .6px rgba(255,255,255,.55));--lift:0 1px 2px rgba(0,0,0,.45),0 4px 10px rgba(0,0,0,.35)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#15181d;--surface:#1d2128;--surface2:#252a32;--line:#363c46;--ink:#e7e9ec;--muted:#a7adb7;--faint:#7d848f;--link:#8ab8e6;--pos:#5fc08a;--neg:#e2807c;--live:#ff6b6b;--warn:#e8b04b;--accent:ACCENT_DARK;--on-accent:#15181d;--chip:#2e343d;--gray:#252a32;--logo-edge:drop-shadow(0 0 .6px rgba(255,255,255,.85)) drop-shadow(0 0 .6px rgba(255,255,255,.55));--lift:0 1px 2px rgba(0,0,0,.45),0 4px 10px rgba(0,0,0,.35)}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
a{color:var(--link)}img{max-width:100%}button{font:inherit;cursor:pointer}
main{max-width:2200px;margin:0 auto;padding:var(--s3) var(--s4) 64px}
h1{font-size:1.35rem;line-height:1.2;margin:0}
h2{font-size:1.1rem;font-weight:700;margin:var(--s4) 0 var(--s2)}
h3{font-size:1.2rem;margin:var(--s5) 0 var(--s2)}
p{margin:0 0 var(--s3)}.sub{color:var(--muted);max-width:760px}.small{font-size:var(--fs-sm);color:var(--muted)}
.muted{color:var(--muted)}.pos{color:var(--pos)}.neg{color:var(--neg)}
.top{display:flex;align-items:center;gap:var(--s3);flex-wrap:wrap}.top .how{margin-left:auto;font-size:var(--fs-sm)}
.settings summary{list-style:none;cursor:pointer;display:inline-flex;align-items:center;height:32px;border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:999px;padding:0 var(--s3);font-size:var(--fs-sm)}.settings summary::-webkit-details-marker{display:none}.settings[open] summary{background:var(--accent);border-color:var(--accent);color:var(--on-accent);font-weight:700}
.settings-panel{flex-basis:100%;order:3}.top:has(.settings[open]) .settings-panel{display:block}.settings-panel{display:none;padding:var(--s2) 0}
.controls{display:flex;gap:var(--s4);align-items:flex-start;flex-wrap:wrap}.ctl{display:flex;flex-direction:column;gap:var(--s1)}
.seglabel{font-size:.72rem;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);padding-left:2px}
.seg{display:inline-flex;align-items:stretch;border:1px solid var(--line);border-radius:999px;overflow:hidden;background:var(--surface)}
.seg button{border:0;background:transparent;color:var(--muted);padding:9px 14px;font-size:var(--fs-md);min-width:44px}.seg button+button{border-left:1px solid var(--line)}
.seg button.active{background:var(--accent);color:#fff;font-weight:700}.seg button.active::before{content:"\2713\00a0"}
:root[data-theme="dark"] .seg button.active{color:#15181d}@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .seg button.active{color:#15181d}}
.toggles{display:flex;gap:var(--s2)}.toggles button{height:var(--pill);border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:999px;padding:0 var(--s4);font-size:var(--fs-md)}
.group summary{list-style:none;cursor:pointer}.group summary::-webkit-details-marker{display:none}.group summary h2{display:inline-block;width:100%}
.group summary h2::before{content:"\25BE";display:inline-block;width:1.1em;color:var(--muted)}.group:not([open]) summary h2::before{content:"\25B8"}
.count{font-weight:600;color:var(--faint);margin-left:var(--s1)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:var(--s4)}
.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:var(--s4)}
.card h3{margin:0 0 var(--s2)}.card .big{font-size:1.8rem;font-weight:700;line-height:1.1}
.chips{display:flex;flex-wrap:wrap;gap:var(--s1) var(--s2)}.chip{display:inline-block;background:var(--chip);border-radius:999px;padding:1px 9px;font-size:var(--fs-sm);color:var(--ink)}
.tablewrap{overflow-x:auto;background:var(--surface);border:1px solid var(--line);border-radius:14px}
table{border-collapse:collapse;width:100%;font-size:var(--fs-md)}caption{text-align:left;padding:var(--s3) var(--s4) 0;font-weight:600}
th,td{padding:var(--s2) var(--s3);border-top:1px solid var(--line);text-align:center;white-space:nowrap}
thead th{border-top:0;background:var(--surface2);font-weight:600;color:var(--muted)}
th.lead,td.lead{text-align:left}td.lead{font-weight:600}
.sortable th{cursor:pointer;user-select:none}.sortable th::after{content:"";display:inline-block;width:.9em;color:var(--faint)}.sortable th[aria-sort="ascending"]::after{content:"\25B4"}.sortable th[aria-sort="descending"]::after{content:"\25BE"}
.opinion{margin-top:var(--s6);padding:var(--s4) var(--s5);border-radius:12px;background:var(--gray)}
.opinion h2{margin:0 0 var(--s2);border:0;padding:0;font-size:1.15rem}.opinion .note{margin:0 0 var(--s3);font-size:var(--fs-sm);font-weight:600;color:var(--muted)}
.opinion blockquote{margin:0;padding:0;font-style:italic}.opinion blockquote p::before{content:"\201C"}.opinion blockquote p::after{content:"\201D"}
footer{margin-top:var(--s6);padding-top:var(--s4);border-top:1px solid var(--line);font-size:var(--fs-sm);color:var(--muted)}
.toolbar{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:var(--s2);margin:var(--s2) 0 0;padding:var(--s2) 0;background:var(--bg);border-bottom:1px solid var(--line)}
.toolbar button{height:var(--pill);border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:999px;padding:0 var(--s3);font-size:var(--fs-sm);white-space:nowrap}
.toolbar button:disabled{color:var(--faint);cursor:default}.toolbar .step{padding:0;width:var(--pill)}.toolbar .label{font-weight:700;white-space:nowrap;text-align:center;min-width:5.6em}
.toolbar input{flex:0 1 220px;min-width:0;width:100%;height:var(--pill);border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:999px;padding:0 var(--s3);font:inherit}.toolbar input::placeholder{color:var(--muted)}
.toolbar .mine{margin-left:auto}.toolbar .mine[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:var(--on-accent);font-weight:700}
.sortbar{margin:var(--s3) 0 0;align-items:flex-start}.sortbar .caption{width:100%}.sortbar .caption{display:flex;justify-content:space-between;gap:var(--s3)}.sortbar .checked{font-size:.75rem;color:var(--muted)}
.sortbar .seg button{padding:5px 11px;font-size:var(--fs-sm)}
.board{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,320px),1fr));grid-auto-rows:1fr;gap:var(--s3);padding-bottom:var(--s1)}
.gc{display:grid;grid-template-columns:30px minmax(0,1fr);grid-template-rows:auto auto 1fr;grid-template-areas:"ix teams" ". side" ". meta";gap:0 var(--s1);align-items:start;padding:var(--s2) var(--s2) var(--s1) var(--s2);background:var(--surface);border:1px solid var(--line);border-radius:12px;box-shadow:var(--lift);font-size:.875rem;line-height:1.25}
.ix{grid-area:ix;padding-top:2px}.int{display:block;font-variant-numeric:tabular-nums;font-weight:700;font-size:1.05rem;line-height:1.2}.bar{display:block;height:4px;border-radius:2px;background:var(--surface2);margin-top:3px}.bar i{display:block;height:4px;border-radius:2px;background:var(--accent)}
.teams{grid-area:teams;display:flex;flex-direction:column;gap:2px;color:inherit;text-decoration:none}a.teams:hover .team{text-decoration:underline}
.ln{display:flex;align-items:center;gap:var(--s1);min-height:22px}.at{flex:0 0 16px;color:var(--muted);font-size:.72rem}
.lg{flex:0 0 20px;width:20px;height:20px;object-fit:contain;filter:var(--logo-edge)}.lg.none{display:flex;align-items:center;justify-content:center;background:var(--chip);border-radius:5px;color:var(--muted);font-size:.72rem;font-weight:700;filter:none}
.team{font-weight:600;min-width:0;overflow-wrap:anywhere}.rk{flex:none;color:var(--muted);font-size:.72rem}.rk.top{background:var(--accent);color:var(--on-accent);border-radius:4px;padding:0 4px;font-weight:700}
.dv{flex:none;border:1px solid var(--line);border-radius:4px;padding:0 4px;font-size:.68rem;font-weight:700;color:var(--muted);line-height:1.35}
.pts{margin-left:auto;padding-left:var(--s2);font-variant-numeric:tabular-nums;font-weight:700;font-size:1.1rem}
.gc.final .team{font-weight:400;color:var(--muted)}.gc.final .pts{font-weight:400;color:var(--muted)}.gc.final .team.win{font-weight:700;color:var(--ink)}.gc.final .pts.win{font-weight:700;color:var(--pos)}
.side{grid-area:side;display:flex;align-items:center;gap:var(--s2);min-width:0;min-height:24px;font-size:.75rem;color:var(--muted)}.side>span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.side .state,.side .lv{flex:none}.side .wc{display:flex;gap:.3em;min-width:0}.wc .who{min-width:0;overflow:hidden;text-overflow:ellipsis}.wc .pct{flex:none}.state{font-size:.8rem;font-weight:600;color:var(--ink)}.gc.live .state{color:var(--live);font-weight:700}.gc.final .state{color:var(--muted)}
.star{flex:none;margin-left:auto;border:0;background:transparent;color:var(--muted);width:26px;height:24px;padding:0;font-size:1.05rem;line-height:1}.star[aria-pressed="true"]{color:var(--warn)}
.meta{grid-area:meta;display:flex;flex-wrap:wrap;gap:0 var(--s3);font-size:.75rem;color:var(--muted);padding-bottom:var(--s1)}.meta:empty{display:none}
.tag{white-space:nowrap}.tag.upset{color:var(--warn);font-weight:700}.tag.close{color:var(--ink)}.tag.quiet{color:var(--faint)}.watch{color:var(--link);font-weight:600;text-decoration:none}.watch:hover{text-decoration:underline}
#how{scroll-margin-top:64px}dl.terms{max-width:900px}
.nc td.lead{font-weight:400}.nc td:last-child{white-space:normal;min-width:150px}.nc td.lead:first-child{font-weight:600}.nc td.lead .reason{display:block;font-size:.78rem;color:var(--muted);font-weight:400}
.empty{color:var(--muted);padding:var(--s3) var(--s4);margin:0}
dl.terms{display:grid;grid-template-columns:minmax(120px,180px) 1fr;gap:var(--s2) var(--s4);margin:0}dl.terms dt{font-weight:600}dl.terms dd{margin:0;color:var(--muted)}dl.terms ul{margin:var(--s1) 0;padding-left:1.2em}
@media (max-width:640px){.board{grid-auto-rows:auto;gap:var(--s2)}main{padding:var(--s2) var(--s4) 48px}h1{font-size:1.15rem}.controls{width:100%}th,td{padding:var(--s2)}.toolbar{gap:var(--s1)}.toolbar .mine span{display:none}.toolbar input{flex:1 1 56px;padding:0 var(--s2)}.toolbar .step{width:30px}.toolbar .label{min-width:0}.toolbar button{padding:0 var(--s2)}.toolbar .step{padding:0}.toolbar .mine{margin-left:0;flex:none;width:34px;padding:0}dl.terms{grid-template-columns:1fr}dl.terms dd{margin-bottom:var(--s2)}}
"""

JS = r"""
(function(){
const root=document.documentElement,KEY='SITE_KEY';
// Theme: the viewer's choice wins; otherwise follow the device. Dark Reader is locked out in <head>.
const savedTheme=(()=>{try{return localStorage.getItem(KEY+'-theme')}catch(e){return null}})();
if(savedTheme==='dark'||savedTheme==='light')root.setAttribute('data-theme',savedTheme);
function isDark(){const t=root.getAttribute('data-theme');return t==='dark'||(!t&&matchMedia('(prefers-color-scheme:dark)').matches)}
function paintTheme(){const dark=isDark();document.querySelectorAll('.th').forEach(b=>b.classList.toggle('active',(b.dataset.theme==='dark')===dark));document.querySelectorAll('meta[name=theme-color]').forEach(m=>{m.removeAttribute('media');m.content=dark?'#15181d':'#f4f3ef'});}
document.querySelectorAll('.th').forEach(b=>b.addEventListener('click',()=>{root.setAttribute('data-theme',b.dataset.theme);try{localStorage.setItem(KEY+'-theme',b.dataset.theme)}catch(e){}paintTheme();}));
matchMedia('(prefers-color-scheme:dark)').addEventListener('change',paintTheme);
paintTheme();
// Times: every <time datetime> renders in the chosen zone. 'local' means the device's zone.
const deviceTz=Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC';
let tzChoice=(()=>{try{return localStorage.getItem(KEY+'-tz')}catch(e){return null}})()||'local';
function zone(){return tzChoice==='local'?deviceTz:tzChoice}
function renderTimes(){
  const z=zone();
  document.querySelectorAll('time[datetime]').forEach(t=>{
    const d=new Date(t.getAttribute('datetime'));if(isNaN(d))return;
    const opts=t.dataset.fmt==='full'?{weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short',timeZone:z}:{hour:'numeric',minute:'2-digit',timeZoneName:'short',timeZone:z};
    t.textContent=new Intl.DateTimeFormat('en-US',opts).format(d);
  });
  document.querySelectorAll('.tz').forEach(b=>b.classList.toggle('active',b.dataset.tz===tzChoice));
}
document.querySelectorAll('.tz').forEach(b=>b.addEventListener('click',()=>{tzChoice=b.dataset.tz;try{localStorage.setItem(KEY+'-tz',tzChoice)}catch(e){}renderTimes();document.dispatchEvent(new Event('tzchange'));}));
window.currentZone=zone;
window.renderTimes=renderTimes;
renderTimes();
// Countdowns: any element with data-until.
function tick(){const now=Date.now();document.querySelectorAll('[data-until]').forEach(el=>{const ms=new Date(el.dataset.until)-now;if(ms<=0){el.textContent='';return}const m=Math.floor(ms/60000),d=Math.floor(m/1440),h=Math.floor((m%1440)/60),mm=m%60;el.textContent='in '+(d?d+'d ':'')+(d||h?h+'h ':'')+(d?'':mm+'m');});}
tick();setInterval(tick,60000);
// Sortable tables: click a header to sort by that column; click again to reverse.
function cellKey(td){const raw=td.dataset.sort!==undefined?td.dataset.sort:td.textContent.trim();const n=parseFloat(raw.replace(/[,%#$]/g,''));return isNaN(n)||!/^[-+#$]?[\d.,]+%?$/.test(raw.replace(/\s/g,''))?raw.toLowerCase():n;}
document.querySelectorAll('table.sortable').forEach(t=>{
  const ths=[...t.querySelectorAll('thead th')],body=t.tBodies[0];if(!body)return;
  ths.forEach((th,i)=>{const go=()=>{const dir=th.getAttribute('aria-sort')==='ascending'?'descending':'ascending';ths.forEach(h=>h.setAttribute('aria-sort','none'));th.setAttribute('aria-sort',dir);
    const rows=[...body.rows];rows.sort((a,b)=>{const x=cellKey(a.cells[i]),y=cellKey(b.cells[i]);const r=typeof x==='number'&&typeof y==='number'?x-y:typeof x==='number'?-1:typeof y==='number'?1:String(x).localeCompare(String(y));return dir==='ascending'?r:-r;});
    rows.forEach(r=>body.appendChild(r));};
    th.addEventListener('click',go);th.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();go();}});});
});
// Expand all / collapse all for the twisties.
window.setAll=function(open){document.querySelectorAll('details.group').forEach(d=>{d.open=open});};
})();
"""


def controls():
    zones = "".join(f'<button type="button" class="tz" data-tz="{esc(z["id"])}">{esc(z["label"])}</button>' for z in SITE["timezones"])
    zones += '<button type="button" class="tz" data-tz="local">Device</button>'
    return (f'<div class="controls"><div class="ctl"><span class="seglabel" id="lbl-times">Times</span>'
            f'<div class="seg" role="group" aria-labelledby="lbl-times">{zones}</div></div>'
            f'<div class="ctl"><span class="seglabel" id="lbl-theme">Theme</span>'
            f'<div class="seg" role="group" aria-labelledby="lbl-theme"><button type="button" class="th" data-theme="light">Light</button>'
            f'<button type="button" class="th" data-theme="dark">Dark</button></div></div>'
            f'<div class="ctl"><span class="seglabel">Sections</span><div class="toggles"><button type="button" onclick="setAll(true)">Expand all</button>'
            f'<button type="button" onclick="setAll(false)">Collapse all</button></div></div></div>')


def head():
    gc = SITE.get("goatcounter")
    tag = f'<script data-goatcounter="https://{esc(gc)}.goatcounter.com/count" async src="//gc.zgo.at/count.js"></script>\n' if gc else ""
    icon = f'<link rel="icon" href="{esc(SITE["favicon"])}">\n' if SITE.get("favicon") else ""
    css = CSS.replace("ACCENT_LIGHT", SITE.get("accent", {}).get("light", "#1f5fbf")).replace("ACCENT_DARK", SITE.get("accent", {}).get("dark", "#7fb0ff"))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="darkreader-lock">
<meta name="ste-allow" content="NPI,WBB,D1,D2,D3,OT,NAIA,NCAA,II,III">
<meta name="theme-color" content="#f4f3ef" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#15181d" media="(prefers-color-scheme: dark)">
<title>{esc(SITE["title"])}</title>
<meta name="description" content="{esc(SITE["description"])}">
{icon}{tag}<style>{css}</style></head><body><main>
<div class="top"><h1>{esc(SITE["title"])}</h1>{link("#how", "How it works", "how")}<details class="settings"><summary>Settings</summary></details><div class="settings-panel">{controls()}</div></div>
"""


def footer():
    built = stamp(NOW.isoformat())
    fetched = stamp(DATA["fetched_at"])
    zone_name = SITE["timezones"][0]["label"]
    credit = SITE.get("footer_credit", "")
    return (f'<footer>Built {esc(built)} {esc(zone_name)}. Data fetched {esc(fetched)} {esc(zone_name)}. '
            f'{esc(credit)}</footer></main><script>{JS.replace("SITE_KEY", SITE["slug"])}</script></body></html>')


# ---------------------------------------------------------------------------
# Section renderers. The rows are drawn by LIVE_JS from the embedded slate, so
# the same code renders the first paint, other nights, and every live update.
# ---------------------------------------------------------------------------

def default_night(dates):
    """Tonight in Eastern time when it has games; otherwise the next night with games, else the last one.

    This only picks which slate the page embeds. The browser makes the same choice from the device clock on
    every load, so a page built yesterday still opens on tonight.
    """
    today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    ahead = sorted(d for d in dates if d >= today)
    return ahead[0] if ahead else (max(dates) if dates else today)


def load_slate(day):
    path = SLATES / f"{day}.json"
    return json.loads(path.read_text()) if path.exists() else None


def sections():
    dates = sorted(DATA.get("dates", {}))
    night = default_night(dates)
    slate = load_slate(night)
    boot = {"dates": dates, "counts": DATA.get("dates", {}), "night": night, "slate": slate,
            "slates": sorted(p.stem for p in SLATES.glob("*.json")),
            "logos": sorted(p.stem for p in (OUT.parent / "logos").glob("*.webp"))}
    toolbar = ('<div class="toolbar" role="group" aria-label="Night and filters">'
               '<button type="button" class="step" id="prev" aria-label="Previous night">&#8249;</button>'
               '<span class="label" id="nightlabel"></span>'
               '<button type="button" class="step" id="next" aria-label="Next night">&#8250;</button>'
               '<button type="button" id="tonight">Tonight</button>'
               '<input type="search" id="find" placeholder="Team" aria-label="Find a team" autocomplete="off">'
               '<button type="button" class="mine" id="mine" aria-pressed="false" aria-label="Show only my starred games">\u2605<span> My games</span></button></div>')
    newcomers = twisty("Newcomers with big games", '<p class="small">Freshmen, transfers, and players with no 2025-26 minutes or under 30 minutes. '
                       'A big game is a game score of 11 or more, 20 points, 12 rebounds, 8 assists, or 5 blocks or steals. '
                       'Live lines are read at halftime and at the final.</p><div id="newcomers"></div>', count="", open_=False, id_="nc")
    sort = ('<div class="sortbar ctl"><span class="seglabel caption"><span id="lbl-sort">Sort</span><span class="checked" id="checked"></span></span>'
            '<div class="seg" role="group" aria-labelledby="lbl-sort">'
            '<button type="button" class="sorter" data-sort="interest">Interest</button><button type="button" class="sorter" data-sort="tipoff">Tipoff</button>'
            '<button type="button" class="sorter" data-sort="closest">Closest</button><button type="button" class="sorter" data-sort="leverage">Leverage</button></div></div>')
    groups = "".join(twisty(title, '<div class="board"></div>', count="", id_=f"g-{key}", hidden=True)
                     for key, title in (("mine", "My games"), ("live", "Live"), ("pre", "Not started"), ("final", "Final")))
    board = f'{sort}<p class="empty" id="boardmsg" hidden></p>{groups}'
    how = twisty("How it works", HOW, open_=False, id_="how")
    data = json.dumps(boot, separators=(",", ":")).replace("</", "<\\/")
    return f'{toolbar}\n{newcomers}\n{board}\n{how}\n<script id="boot" type="application/json">{data}</script><script>{LIVE_JS}</script>'


HOW = f"""<dl class="terms">
<dt>This page</dt><dd>{esc(SITE["intro"])}</dd>
<dt>Reading a card</dt><dd>The left column shows the interest score and its bar. A number before a team is its preseason efficiency rank among Division III teams, and a filled badge marks the top 25. The line under the teams shows the status, the favorite's win chance, and the leverage (Lev). Click a star to move a game into My games at the top of the page. This browser remembers your stars.</dd>
<dt>Order</dt><dd>Games group as live, not started, and final. The Sort buttons set the order inside each group. Interest puts the highest score first, Tipoff the earliest game, Closest the smallest gap in win chance, and Leverage the most at stake.</dd>
<dt>Which games</dt><dd>Every game between two teams that count for the NCAA Power Index. Games between one of those teams and a Division I or II team appear too, exhibitions included. A D1 or D2 badge takes the place of the opponent's rank. They do not count for the NPI, so they have no win chance or leverage. Exhibitions against Division III teams, games against NAIA and two-year opponents, and games against second-year provisional members or earlier do not appear. A game appears only when a schedule page lists it.</dd>
<dt>Interest</dt><dd>A score from 0 to 100. Four things raise it:<ul><li>The preseason efficiency ranks of both teams. The better team counts more.</li><li>The leverage of the game.</li><li>How close the game is. Late in the game, this counts more.</li><li>How far an underdog is past its pregame chance.</li></ul>The page then multiplies the score by the better of the two teams' tournament chances. A game between two teams with almost no chance scores near 0.</dd>
<dt>Win chance</dt><dd>Before tipoff: the preseason efficiency margins plus 3 points for the home team. During the game: the current lead plus the expected margin for the time left, against a spread that shrinks as the clock runs down.</dd>
<dt>Leverage</dt><dd>From the season simulations: how many percentage points each team's tournament chance moves between a win and a loss, added for both teams.</dd>
<dt>How often a game is checked</dt><dd>The page reads each game's live stats feed itself. The wait between checks runs from 1 minute at interest 100 to 60 minutes at interest 0. The wait then grows with the leader's margin. A tie keeps the wait as it is. A 30-point lead at the half stretches it past the end of the game, so the next check reads the final score. A game between two teams with no tournament chance gets about two checks. Hover over a card to see its last and next check. If a game's feed still does not show it 45 minutes after tipoff, the page stops checking and the game shows "no live stats".</dd>
<dt>Colors and symbols</dt><dd>Red means live: a red dot and a red clock mark a game in progress, and nothing else on the page is red. Green marks the winner of a finished game. Amber marks an upset: an underdog that won, or whose win chance is now more than 20 points above its pregame chance. Gray marks a game with nothing left to decide. A lock icon means the trailing team has under a 2% chance. A sleep icon means neither team has a tournament chance. A fire icon marks a live game where the trailing team still has better than a 30% chance. A lightning bolt marks leverage of 15 or more. A Watch link opens the video stream when the schedule page lists one.</dd>
<dt>Newcomers</dt><dd>The full box score is read twice a game, at halftime and at the final, and only when a team has newcomers on its roster.</dd>
</dl>"""

LIVE_JS = r"""
(function(){
const BOOT=JSON.parse(document.getElementById('boot').textContent);
const KEY='SITE_KEY';
const BUDGET_PER_MIN=40;           // feed reads per minute for the whole page
const GAME_MS=2*3600000;           // tipoff to expected final
const SD=11;                       // points, full-game spread of the final margin
const $=s=>document.querySelector(s);
const esc=t=>String(t==null?'':t).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let night=BOOT.night,games=[],timer=null,sortKey='interest',onlyMine=false,findText='',ncUser=false,ncLast=0;
const LOGOS=new Set(BOOT.logos||[]);
const stars=new Set((()=>{try{return JSON.parse(localStorage.getItem(KEY+'-stars'))||[]}catch(e){return []}})());
const tokens=[];                   // timestamps of recent feed reads, for the budget

// ---------- model
function phi(z){const t=1/(1+0.2316419*Math.abs(z)),d=0.3989423*Math.exp(-z*z/2);const p=d*t*(0.3193815+t*(-0.3565638+t*(1.781478+t*(-1.821256+t*1.330274))));return z>0?1-p:p;}
// Home team's chance to win. lead is home minus away; progress is the share of regulation played.
function winProb(g,lead,progress){
  const left=Math.max(0,1-progress);
  if(left<=0)return lead>0?1:lead<0?0:0.5;
  return phi((lead+g.pregame_margin*left)/(SD*Math.sqrt(left)));
}
function interest(g,st){
  // A team outside Division III has no preseason rank; it counts as an average team.
  const q=r=>r?1-(r-1)/409:0.5,q1=q(g.home_rank),q2=q(g.away_rank);
  const Q=0.6*Math.max(q1,q2)+0.4*Math.min(q1,q2);
  const L=1-Math.exp(-(Math.abs(g.home_lev)+Math.abs(g.away_lev))/12);
  const T=Math.max(g.home_tourn,g.away_tourn),S=T/(T+0.01);
  const P=st.progress||0,wp=st.wp;
  const C=1-Math.abs(2*wp-1);
  const homeDog=g.pregame_wp<0.5;
  // A game against a Division I or II team has no pregame model, so it has no upset term.
  const U=g.division?0:Math.max(0,homeDog?wp-g.pregame_wp:(1-wp)-(1-g.pregame_wp));
  // Rank and leverage fade as the result becomes certain: at the final whistle of a blowout they count for little.
  const settled=1-P*(1-Math.sqrt(C));
  return Math.min(100,100*S*((0.30*Q+0.25*L)*settled+(0.20+0.15*P)*C+0.25*U));
}
// Minutes to wait before the next check: 60^((1 - I/100)^WAIT_CURVE), so 1 at interest 100 and 60 at interest 0,
// stretched by the leader's margin, (0.5/p)^MARGIN_STRETCH with p the trailing team's chance.
const WAIT_CURVE=2,MARGIN_STRETCH=0.35;
function waitMs(g,st){
  const base=Math.pow(60,Math.pow(1-st.interest/100,WAIT_CURVE));
  const p=Math.max(1e-9,Math.min(st.wp,1-st.wp));
  return base*Math.pow(0.5/p,MARGIN_STRETCH)*60000;
}
function tipMs(g){return g.tip?new Date(g.tip).getTime():null;}
// A feed that has not shown tonight's game this long after tipoff is not covering it: the crew posts elsewhere
// or not at all. Checks stop there.
const GIVE_UP_MS=45*60000;
function nextCheck(g,st,now){
  if(st.final||st.noStats||!g.feed)return null;
  const tip=tipMs(g);
  if(tip&&now<tip+5*60000&&!st.live)return tip+5*60000;
  const end=(tip||now)+GAME_MS;
  if(now>=end)return now+15*60000;                 // past the expected end: look for the final every 15 minutes
  const next=Math.min(now+waitMs(g,st),end);
  return tip&&!st.seen&&now<tip+GIVE_UP_MS?Math.min(next,tip+GIVE_UP_MS):next;
}

// ---------- feeds
function teamTokens(n){return new Set(String(n||'').toLowerCase().match(/[a-z]+/g)||[]);}
function overlap(a,b){const B=teamTokens(b);let n=0;teamTokens(a).forEach(t=>{if(B.has(t)&&!['college','university','of','the','state'].includes(t))n++;});return n;}
function mdy(day){const [y,m,d]=day.split('-').map(Number);return m+'/'+d+'/'+y;}
function progressOf(period,clockSec,regulation){
  const len=regulation===2?1200:600,total=regulation*len;
  if(period<=regulation)return((period-1)*len+(len-clockSec))/total;
  return 1;                                        // overtime: the regulation clock has run out
}
function clockToSec(t){const m=/^(\d+):(\d+)/.exec(t||'');return m?(+m[1])*60+(+m[2]):0;}
function periodName(period,regulation){
  if(period>regulation)return 'OT'+(period-regulation>1?period-regulation:'');
  return regulation===2?['','1st half','2nd half'][period]:'Q'+period;
}
function statusText(period,clockSec,regulation){
  if(clockSec===0&&period===regulation/2)return 'Halftime';
  if(clockSec===0&&period<regulation)return 'End '+periodName(period,regulation);
  return Math.floor(clockSec/60)+':'+String(clockSec%60).padStart(2,'0')+' '+periodName(period,regulation);
}
function num(v){const n=parseFloat(v);return isNaN(n)?0:n;}
function ma(v){const m=/(\d+)\s*-\s*(\d+)/.exec(v||'');return m?[+m[1],+m[2]]:[0,0];}
function sidearmLines(full){
  const out={};
  [['H','HomeTeam'],['V','VisitingTeam']].forEach(([side,key])=>{
    const t=(full.Stats||{})[key]||{},people={};(t.Players||[]).forEach(p=>{people[p.PersonId||('#'+p.UniformNumber)]=p;});
    out[side]=(((t.PlayerGroups||{}).Players||{}).Values||[]).map(v=>{const p=people[v.PersonId]||people['#'+v.Uni]||{};const fg=ma(v.Fgam),ft=ma(v.Ftma);
      return {first:p.FirstName||'',last:p.LastName||'',abbr:v.Name||'',min:num(v.Minutes),pts:num(v.Points),fgm:fg[0],fga:fg[1],ftm:ft[0],fta:ft[1],
        oreb:num(v.OffensiveRebounds),dreb:num(v.DefensiveRebounds),reb:num(v.TotalRebounds),ast:num(v.Assists),to:num(v.Turnovers),stl:num(v.Steals),blk:num(v.Blocks),pf:num(v.PersonalFouls)};});
  });
  return out;
}
function prestoLines(x){
  const out={};
  x.querySelectorAll('team').forEach(t=>{out[t.getAttribute('vh')]=[...t.querySelectorAll('player')].filter(p=>p.getAttribute('code')!=='TM'&&p.querySelector('stats')).map(p=>{
    const a=p.querySelector('stats'),g=k=>num(a.getAttribute(k)),name=p.getAttribute('name')||p.getAttribute('checkname')||'';
    const [last,first]=name.includes(',')?name.split(',').map(s=>s.trim()):[name.split(' ').slice(-1)[0],name.split(' ').slice(0,-1).join(' ')];
    return {first,last,abbr:name,min:g('min'),pts:g('tp'),fgm:g('fgm'),fga:g('fga'),ftm:g('ftm'),fta:g('fta'),oreb:g('oreb'),dreb:g('dreb'),reb:g('treb'),ast:g('ast'),to:g('to'),stl:g('stl'),blk:g('blk'),pf:g('pf')};
  });});
  return out;
}
// ESPN's light feed (one scoreboard event) and its summary (header plus player box scores) share these fields.
// The event id names one game, so no date check is needed.
function espnState(j){
  const c=(j.header||j).competitions[0],st=c.status||j.status||{},type=st.type||{};
  if(type.state==='pre'||/POSTPONED|CANCELED/.test(type.name||'')||(type.state==='post'&&!type.completed))return null;
  // The summary carries only displayClock; the light feed carries clock in seconds.
  const side=h=>c.competitors.find(x=>x.homeAway===h)||{},regulation=4,period=num(st.period),
    clock=typeof st.clock==='number'?Math.round(st.clock):clockToSec(st.displayClock||'0:00');
  const complete=!!type.completed;
  return {home:num(side('home').score),away:num(side('away').score),feedHome:(side('home').team||{}).location,complete,period,regulation,
    progress:complete?1:progressOf(period,clock,regulation),status:statusText(period,clock,regulation),lines:j.boxscore?espnLines(j):null};
}
function espnLines(j){
  const side={},out={};
  j.header.competitions[0].competitors.forEach(c=>{side[c.team.id]=c.homeAway==='home'?'H':'V';});
  ((j.boxscore||{}).players||[]).forEach(t=>{
    const b=(t.statistics||[])[0]||{},names=b.names||b.labels||[];
    out[side[t.team.id]||'V']=(b.athletes||[]).filter(a=>(a.stats||[]).length).map(a=>{
      const v={};names.forEach((n,i)=>{v[n]=a.stats[i];});const fg=ma(v.FG),ft=ma(v.FT),full=a.athlete.displayName||'',sp=full.indexOf(' ');
      return {first:sp>0?full.slice(0,sp):full,last:sp>0?full.slice(sp+1):'',abbr:a.athlete.shortName||full,min:num(v.MIN),pts:num(v.PTS),fgm:fg[0],fga:fg[1],ftm:ft[0],fta:ft[1],
        oreb:num(v.OREB),dreb:num(v.DREB),reb:num(v.REB),ast:num(v.AST),to:num(v.TO),stl:num(v.STL),blk:num(v.BLK),pf:num(v.PF)};});
  });
  return out;
}
// One read of a game's feed. Returns null when the feed shows a different game or has not started.
async function readFeed(g,full){
  const f=g.feed;tokens.push(Date.now());
  const url=f.type==='espn'?(full?f.full:f.url):f.type==='sidearm'&&full?f.url+'?detail=full':f.url;
  const r=await fetch(url,{cache:'no-store'});if(!r.ok)return null;
  let s;
  if(f.type==='espn'){
    s=espnState(await r.json());if(!s)return null;
  }else if(f.type==='sidearm'){
    const j=await r.json(),G=j.Game;
    if(!G||!G.HasStarted)return null;
    // Stat crews sometimes leave the feed's date unset or stale (1/1/0001). Then the feed counts when one of its teams
    // is one of ours and the game is not over, or when this page already read it live.
    const ours=overlap(G.HomeTeam.Name,g.home)+overlap(G.HomeTeam.Name,g.away)+overlap(G.VisitingTeam.Name,g.home)+overlap(G.VisitingTeam.Name,g.away)>0;
    if(G.Date!==mdy(g.date)&&!(ours&&(!G.IsComplete||g.st.live)))return null;
    const regulation=num((G.Rules||{}).PeriodMinutes)>=20?2:4,period=num(G.Period),clock=num(G.ClockSeconds);
    // Some crews never set IsComplete (Butler, 2026-10-28). The clock at 0:00 in the last period with no tie is a final.
    const complete=!!G.IsComplete||(period>=regulation&&G.ClockSeconds===0&&num(G.HomeTeam.Score)!==num(G.VisitingTeam.Score));
    s={home:num(G.HomeTeam.Score),away:num(G.VisitingTeam.Score),feedHome:G.HomeTeam.Name,complete,period,regulation,
       progress:complete?1:progressOf(period,clock,regulation),status:statusText(period,clock,regulation),lines:full?sidearmLines(j):null};
  }else{
    const x=new DOMParser().parseFromString(await r.text(),'application/xml');
    const venue=x.querySelector('venue'),st=x.querySelector('status'),rules=x.querySelector('rules');
    if(!venue||!st||venue.getAttribute('date')!==mdy(g.date)||!x.querySelector('play'))return null;
    const regulation=+(rules&&rules.getAttribute('prds'))||4,period=num(st.getAttribute('period')),clock=clockToSec(st.getAttribute('clock'));
    const sc={};x.querySelectorAll('team').forEach(t=>{const ls=t.querySelector('linescore');sc[t.getAttribute('vh')]=num(ls&&ls.getAttribute('score'));});
    const complete=st.getAttribute('complete')==='Y';
    s={home:sc.H||0,away:sc.V||0,feedHome:venue.getAttribute('homename'),complete,period,regulation,
       progress:complete?1:progressOf(period,clock,regulation),status:statusText(period,clock,regulation),lines:prestoLines(x)};
  }
  // The stat crew's home side can differ from the schedule's; flip when the feed's home name matches our away team.
  if(overlap(s.feedHome,g.away)>overlap(s.feedHome,g.home)){[s.home,s.away]=[s.away,s.home];if(s.lines)s.lines={H:s.lines.V||[],V:s.lines.H||[]};}
  return s;
}

// ---------- newcomers
function gameScore(l){return l.pts+0.4*l.fgm-0.7*l.fga-0.4*(l.fta-l.ftm)+0.7*l.oreb+0.3*l.dreb+l.stl+0.7*l.ast+0.7*l.blk-0.4*l.pf-l.to;}
function bigGame(l){return gameScore(l)>=11||l.pts>=20||l.reb>=12||l.ast>=8||l.blk>=5||l.stl>=5;}
const norm=n=>String(n||'').toLowerCase().replace(/[^a-z]/g,'');
function matchNewcomer(l,roster){
  if(l.first&&l.last){const full=norm(l.first+l.last),hit=roster.find(p=>norm(p.name)===full);if(hit)return hit;}
  let m=/^\s*([A-Za-z])[a-z]*\.?\s+(.+)$/.exec(l.abbr),initial,last;
  if(l.abbr.includes(',')){const k=/^\s*(.+?),\s*([A-Za-z])/.exec(l.abbr);if(!k)return null;last=k[1];initial=k[2];}
  else if(m){initial=m[1];last=m[2];}else return null;
  const hits=roster.filter(p=>norm(p.name.split(' ').slice(-1)[0])===norm(last)&&norm(p.name)[0]===initial.toLowerCase());
  return hits.length===1?hits[0]:null;
}
function newcomerLines(g,s,when){
  const out=[];
  [['H',g.home,g.newcomers_home],['V',g.away,g.newcomers_away]].forEach(([side,team,roster])=>{
    ((s.lines||{})[side]||[]).forEach(l=>{const who=matchNewcomer(l,roster||[]);if(who&&bigGame(l))out.push({team,name:who.name,reason:who.reason,gmsc:Math.round(gameScore(l)*10)/10,when,
      line:{min:l.min,pts:l.pts,reb:l.reb,ast:l.ast,stl:l.stl,blk:l.blk,fgm:l.fgm,fga:l.fga}});});
  });
  return out;
}

// ---------- state
function initState(g){
  const st={wp:g.pregame_wp,progress:0,live:false,final:false,score:null,status:null,halfRead:false,finalRead:!!g.newcomers_read,nc:(g.newcomer_games||[]).map(x=>Object.assign({when:'final'},x))};
  if(g.final){st.final=true;st.score=g.final;const lead=g.final[0]-g.final[1];st.wp=lead>0?1:lead<0?0:0.5;st.progress=1;}
  st.interest=interest(g,st);
  return st;
}
function hasNewcomers(g){return (g.newcomers_home||[]).length+(g.newcomers_away||[]).length>0;}
async function check(g){
  const st=g.st;let s=null;
  const wantHalf=hasNewcomers(g)&&!st.halfRead&&st.progress>=0.5&&!st.final;
  try{s=await readFeed(g,wantHalf);}catch(e){s=null;}
  const now=Date.now();
  if(!s&&!st.seen&&tipMs(g)&&now>=tipMs(g)+GIVE_UP_MS){st.noStats=true;st.nextAt=null;}
  if(s){
    st.seen=true;st.live=!s.complete;st.score=[s.home,s.away];st.progress=s.progress;
    const lead=s.home-s.away;
    st.wp=s.complete?(lead>0?1:lead<0?0:0.5):winProb(g,lead,s.progress);
    st.status=s.complete?'Final'+(s.period>s.regulation?' (OT)':''):s.status;
    if(s.lines&&!s.complete&&s.progress>=0.5&&!st.halfRead){st.halfRead=true;addNewcomers(g,newcomerLines(g,s,'half'));}
    if(s.complete){
      st.final=true;st.live=false;
      if(hasNewcomers(g)&&!st.finalRead){
        let full=s;if(g.feed.type!=='presto'&&!s.lines){try{full=await readFeed(g,true)||s;}catch(e){}}
        st.finalRead=true;addNewcomers(g,newcomerLines(g,full,'final'));
      }
    }else if(!s.lines&&hasNewcomers(g)&&!st.halfRead&&s.progress>=0.5){
      // Crossed halftime since the last check: read the full box now.
      st.nextAt=now;
    }
  }
  st.interest=interest(g,st);
  st.checked=now;
  if(!st.nextAt||st.nextAt<=now)st.nextAt=nextCheck(g,st,now);
}
function addNewcomers(g,list){
  const keep=g.st.nc.filter(x=>!list.some(y=>y.name===x.name&&y.team===x.team));
  g.st.nc=keep.concat(list);
}

// ---------- scheduler: the most interesting due games first, within the per-minute budget
function todayET(){return new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York'}).format(new Date());}
function isToday(){const t=todayET();return night===t||night===prevDay(t);}
function prevDay(d){const x=new Date(d+'T12:00:00Z');x.setUTCDate(x.getUTCDate()-1);return x.toISOString().slice(0,10);}
async function tick(){
  if(document.hidden||!isToday())return;
  const now=Date.now();
  while(tokens.length&&tokens[0]<now-60000)tokens.shift();
  const due=games.filter(g=>g.feed&&g.st.nextAt&&g.st.nextAt<=now).sort((a,b)=>b.st.interest-a.st.interest);
  const room=Math.max(0,BUDGET_PER_MIN-tokens.length);
  const batch=due.slice(0,room);
  if(!batch.length){renderNext();return;}
  await Promise.all(batch.map(check));
  render();
}

// ---------- render
function rank(r){return r?'<span class="rk'+(r<=25?' top':'')+'">#'+r+'</span>':'';}
// A Division I or II opponent gets its division badge where a D3 team shows its preseason rank.
function sideTag(g,side){return g.division&&g[side]!==g.d3?'<span class="dv">D'+g.division+'</span>':rank(g[side+'_rank']);}
// tools/make_logos.py writes the files, and its slug() must match this.
function logoSlug(n){return String(n||'').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');}
function logo(n){const f=logoSlug(n);return LOGOS.has(f)?'<img class="lg" src="logos/'+f+'.webp" alt="" width="20" height="20" loading="lazy" decoding="async">':'<span class="lg none" aria-hidden="true">'+esc(String(n||'?')[0])+'</span>';}
function fmtTime(iso){return '<time datetime="'+esc(iso)+'" data-fmt="short"></time>';}
function ago(ms){const m=Math.max(0,Math.round((Date.now()-ms)/60000));return m<1?'just now':m<60?m+'m ago':Math.floor(m/60)+'h '+(m%60)+'m ago';}
function inMin(ms){const m=Math.max(0,Math.round((ms-Date.now())/60000));return m<1?'now':m<60?'in '+m+'m':'in '+Math.floor(m/60)+'h '+(m%60)+'m';}
function winCell(g,st){
  if(st.final||g.division)return '-';
  const home=st.wp>=0.5,p=home?st.wp:1-st.wp,team=home?g.home:g.away;
  return esc(team)+' '+(p>0.995?'>99':Math.round(p*100))+'%';
}
function tags(g,st){
  // Each tag: [class, symbol, words]. Red marks a live game, green a winner, amber an upset, gray a game with nothing left to decide.
  const out=g.label?[['quiet','',g.label.toLowerCase()]]:[];
  const dogWp=g.pregame_wp<0.5?st.wp-g.pregame_wp:(1-st.wp)-(1-g.pregame_wp);
  if(!g.division&&(st.live||st.final)&&dogWp>0.2)out.push(['upset','\u{1F6A8}',st.final?'upset':'upset alert']);
  if(st.live&&Math.min(st.wp,1-st.wp)>0.3)out.push(['close','\u{1F525}','close']);
  if(st.live&&Math.min(st.wp,1-st.wp)<0.02)out.push(['quiet','\u{1F512}','decided']);
  if(!g.division&&Math.max(g.home_tourn,g.away_tourn)<0.005)out.push(['quiet','\u{1F4A4}','no tournament stakes']);
  return out.map(t=>'<span class="tag '+t[0]+'">'+(t[1]?t[1]+'\u00a0':'')+esc(t[2])+'</span>').join('');
}
function groupOf(st){return st.live?0:st.final?2:1;}
function leverage(g){return Math.abs(g.home_lev)+Math.abs(g.away_lev);}
function line(g,side,i){
  const st=g.st,other=st.score?st.score[1-i]:0,mine=st.score?st.score[i]:0,won=st.final&&st.score&&mine>other,ahead=st.score&&mine>other;
  const at=side==='home'?(g.neutral?'vs':'at'):'';
  return '<div class="ln"><span class="at">'+at+'</span>'+logo(g[side])+sideTag(g,side)+'<span class="team'+(won?' win':'')+'">'+esc(g[side])+'</span>'+
    (st.score?'<span class="pts'+(won?' win':ahead?' ahead':'')+'">'+mine+'</span>':'')+'</div>';
}
function card(g){
  const st=g.st,I=Math.round(st.interest),starred=stars.has(g.id);
  let state;
  if(st.final)state=esc(st.status||'Final');
  else if(st.live)state='\u{1F534} '+esc(st.status);
  else state=g.tip?fmtTime(g.tip):'Time TBA';
  const teams=line(g,'away',1)+line(g,'home',0);
  const wc=winCell(g,st),lev=leverage(g),side=['<span class="state">'+state+'</span>'],meta=[];
  if(wc!=='-'){const m=/^(.*) (\S+%)$/.exec(wc);side.push('<span class="wc" title="'+wc+'"><span class="who">'+m[1]+'</span><span class="pct">'+m[2]+'</span></span>');};
  if(!g.division&&lev>0)side.push('<span class="lv" title="Leverage">'+(lev>=15?'⚡ ':'')+'Lev '+lev.toFixed(1)+'</span>');
  const w=tags(g,st);if(w)meta.push(w);
  if((!g.feed||st.noStats)&&!st.final)meta.push('<span class="tag quiet">no live stats</span>');
  if(g.video&&!st.final)meta.push('<a class="watch" href="'+esc(g.video)+'" target="_blank" rel="noopener">\u{1F4FA} Watch</a>');
  return '<article class="gc '+(st.live?'live':st.final?'final':'pre')+'" data-id="'+esc(g.id)+'">'+
    '<div class="ix" title="Interest score" aria-label="Interest score '+I+'"><span class="int">'+I+'</span><span class="bar"><i style="width:'+I+'%"></i></span></div>'+
    (g.link?'<a class="teams" href="'+esc(g.link)+'" target="_blank" rel="noopener">'+teams+'</a>':'<div class="teams">'+teams+'</div>')+
    '<div class="side">'+side.join('')+'<button type="button" class="star" aria-pressed="'+starred+'" aria-label="'+(starred?'Remove this game from My games':'Add this game to My games')+'" title="'+(starred?'Remove from My games':'Add to My games')+'">'+(starred?'\u2605':'\u2606')+'</button></div>'+
    '<div class="meta">'+meta.join('')+'</div></article>';
}
const SORTS={
  interest:(a,b)=>b.st.interest-a.st.interest,
  tipoff:(a,b)=>(tipMs(a)||Infinity)-(tipMs(b)||Infinity),
  closest:(a,b)=>Math.min(b.st.wp,1-b.st.wp)-Math.min(a.st.wp,1-a.st.wp),
  leverage:(a,b)=>(b.division?-1:leverage(b))-(a.division?-1:leverage(a)),
};
const plain=t=>String(t||'').toLowerCase().replace(/[^a-z0-9]/g,'');
function shown(g){
  if(onlyMine&&!stars.has(g.id))return false;
  const q=plain(findText);
  return !q||plain(g.home).includes(q)||plain(g.away).includes(q);
}
// Update one group's cards in place, so logos do not reload and the reader's focus stays put when a score changes.
function paint(grid,list){
  const have=new Map([...grid.children].map(el=>[el.dataset.id,el]));
  list.forEach((g,i)=>{
    const h=card(g);let el=have.get(g.id);
    if(!el||el._h!==h){const t=document.createElement('template');t.innerHTML=h;const fresh=t.content.firstChild;fresh._h=h;if(el)el.replaceWith(fresh);el=fresh;}
    have.delete(g.id);
    if(grid.children[i]!==el)grid.insertBefore(el,grid.children[i]||null);
  });
  have.forEach(el=>el.remove());
}
function message(text){const m=$('#boardmsg');m.textContent=text||'';m.hidden=!text;}
function clearBoard(text){GROUPS.forEach(name=>{const d=$('#g-'+name);d.hidden=true;d.querySelector('.board').replaceChildren();});message(text);}
const GROUPS=['mine','live','pre','final'],STATES=['live','pre','final'];
function render(){
  const list=games.filter(shown).sort((a,b)=>groupOf(a.st)-groupOf(b.st)||SORTS[sortKey](a,b)||b.st.interest-a.st.interest);
  // A starred game moves out of its status group and into My games at the top.
  GROUPS.forEach(name=>{
    const d=$('#g-'+name),part=name==='mine'?list.filter(g=>stars.has(g.id)):list.filter(g=>!stars.has(g.id)&&groupOf(g.st)===STATES.indexOf(name));
    d.hidden=!part.length;d.querySelector('.count').textContent=part.length;
    paint(d.querySelector('.board'),part);
  });
  message(!games.length?'No NPI games on this night.':list.length?'':onlyMine&&!findText?'You have no starred games on this night.':'No game on this night matches.');
  document.querySelectorAll('.sorter').forEach(b=>b.classList.toggle('active',b.dataset.sort===sortKey));
  renderNewcomers();
  renderNext();
  if(window.renderTimes)window.renderTimes();
}
function renderNext(){
  let latest=0;
  document.querySelectorAll('.gc').forEach(el=>{
    const g=games.find(x=>x.id===el.dataset.id);if(!g)return;
    const parts=[];if(g.st.checked)parts.push('Checked '+ago(g.st.checked)+'.');
    if(!g.st.final&&g.feed&&g.st.nextAt&&isToday())parts.push('Next check '+inMin(g.st.nextAt)+'.');
    el.title=parts.join(' ');
  });
  games.forEach(g=>{if(g.st.checked>latest)latest=g.st.checked;});
  $('#checked').textContent=latest?'Latest check '+ago(latest):'';
}
function renderNewcomers(){
  const all=[];games.forEach(g=>g.st.nc.forEach(x=>all.push(Object.assign({game:g},x))));
  all.sort((a,b)=>b.gmsc-a.gmsc);
  const nc=$('#nc');nc.querySelector('.count').textContent=all.length;
  // The section stays one line until a newcomer has a big game, unless the reader has opened or closed it.
  if(!ncUser&&(all.length>0)!==(ncLast>0))nc.open=all.length>0;
  ncLast=all.length;
  if(!all.length){$('#newcomers').innerHTML='<p class="empty">No newcomer has a big game on this night yet.</p>';return;}
  const rows=all.map(x=>{const l=x.line,g=x.game;
    return '<tr><td class="lead">'+esc(x.name)+'<span class="reason">'+esc(x.reason)+'</span></td><td class="lead">'+esc(x.team)+'</td>'+
      '<td>'+l.pts+'</td><td>'+l.reb+'</td><td>'+l.ast+'</td><td>'+(l.stl+l.blk)+'</td><td>'+l.fgm+'-'+l.fga+'</td>'+
      '<td>'+x.gmsc.toFixed(1)+'</td><td class="lead">'+esc(g.away)+' at '+esc(g.home)+'<span class="reason">'+(x.when==='half'?'At halftime':'Final')+'</span></td></tr>';}).join('');
  $('#newcomers').innerHTML='<div class="tablewrap"><table class="nc"><thead><tr><th class="lead">Player</th><th class="lead">Team</th><th>Points</th><th>Rebounds</th><th>Assists</th><th>Steals plus blocks</th><th>Field goals</th><th>Game score</th><th class="lead">Game</th></tr></thead><tbody>'+rows+'</tbody></table></div>';
}

// ---------- nights
const fmtNight=d=>new Intl.DateTimeFormat('en-US',{weekday:'short',month:'short',day:'numeric',timeZone:'UTC'}).format(new Date(d+'T12:00:00Z'));
function showNight(slate){
  night=slate.date;
  games=slate.games.map(g=>Object.assign(g,{st:initState(g)}));
  const now=Date.now();
  games.forEach(g=>{g.st.nextAt=isToday()?firstCheck(g,now):null;});
  $('#nightlabel').textContent=fmtNight(night);
  const i=BOOT.dates.indexOf(night);
  $('#prev').disabled=i<=0;$('#next').disabled=i<0||i>=BOOT.dates.length-1;
  ncUser=false;
  render();
}
function firstCheck(g,now){
  if(g.st.final||!g.feed)return null;
  const tip=tipMs(g);
  if(!tip)return now;                               // time TBA: look now, then by interest
  if(now<tip+5*60000)return tip+5*60000;
  return now;                                       // in progress or past: read it on the first tick
}
async function go(d){
  if(BOOT.slate&&d===BOOT.slate.date){showNight(BOOT.slate);return;}
  if(!BOOT.slates.includes(d)){
    // A future night beyond the slate window has no slate yet: show its game count only.
    night=d;games=[];$('#nightlabel').textContent=fmtNight(d);
    const i=BOOT.dates.indexOf(d);$('#prev').disabled=i<=0;$('#next').disabled=i>=BOOT.dates.length-1;
    clearBoard((BOOT.counts[d]||0)+' NPI games. Tipoff times and live feeds appear the day before.');
    renderNewcomers();return;
  }
  try{const r=await fetch('slates/'+d+'.json',{cache:'no-store'});showNight(await r.json());}
  catch(e){clearBoard('This night did not load. Try again.');}
}
$('#prev').addEventListener('click',()=>{const i=BOOT.dates.indexOf(night);if(i>0)go(BOOT.dates[i-1]);});
$('#next').addEventListener('click',()=>{const i=BOOT.dates.indexOf(night);if(i<BOOT.dates.length-1)go(BOOT.dates[i+1]);});
// The page is built a few times a day, so BOOT.night can be stale by morning: pick tonight from the device clock.
function defaultNight(){const t=todayET(),ahead=BOOT.dates.filter(d=>d>=t);return ahead[0]||(BOOT.dates.length?BOOT.dates[BOOT.dates.length-1]:BOOT.night);}
$('#tonight').addEventListener('click',()=>go(defaultNight()));
document.querySelectorAll('.sorter').forEach(b=>b.addEventListener('click',()=>{sortKey=b.dataset.sort;render();}));
$('#find').addEventListener('input',e=>{findText=e.target.value;render();});
$('#mine').addEventListener('click',()=>{onlyMine=!onlyMine;$('#mine').setAttribute('aria-pressed',onlyMine);render();});
document.querySelector('#nc summary').addEventListener('click',()=>{ncUser=true;});
// One listener for every star, because cards come and go as scores change.
document.querySelector('main').addEventListener('click',e=>{
  const b=e.target.closest('.star');if(!b)return;
  const id=b.closest('.gc').dataset.id;
  if(stars.has(id))stars.delete(id);else stars.add(id);
  try{localStorage.setItem(KEY+'-stars',JSON.stringify([...stars]))}catch(err){}
  render();
});
$('.top a.how').addEventListener('click',()=>{$('#how').open=true;});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)tick();});
document.addEventListener('tzchange',render);
go(defaultNight());
tick();timer=setInterval(tick,5000);
})();
""".replace("SITE_KEY", SITE["slug"])


def copy_slates():
    dest = OUT.parent / "slates"
    dest.mkdir(parents=True, exist_ok=True)
    for path in SLATES.glob("*.json"):
        shutil.copy(path, dest / path.name)


def main():
    copy_slates()
    page = head() + sections() + footer()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page)
    print(f"wrote {OUT} ({len(page)} bytes)")


if __name__ == "__main__":
    main()
