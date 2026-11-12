#!/usr/bin/env python3
"""Render docs/index.html from site.json, data/data.json, and data/slates/*.json.

Project-specific code lives in the section renderers near the bottom
(`sections()`) and in LIVE_JS. Everything above them is shared page furniture:
tokens, theme and time zone controls, tables, twisties, footer.

The page embeds the default night's slate and fetches other nights from
docs/slates/. LIVE_JS reads each game's live stats feed in the browser at a
pace set by the game's interest score (see PLAN.md and README.md).
"""
import csv
import html
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from player_names import match_player, name_line

BASE = Path(__file__).resolve().parent
SITE = json.loads((BASE / "site.json").read_text())
DATA = json.loads((BASE / "data" / "data.json").read_text())
SLATES = BASE / "data" / "slates"
OUT = BASE / SITE.get("output", "docs/index.html")
HOME_TZ = ZoneInfo(SITE["timezones"][0]["id"])


def esc(value):
    return html.escape("" if value is None else str(value), quote=True)


def stamp(iso, fmt="%B %-d, %Y, %-I:%M %p"):
    """Format an ISO timestamp in the home time zone for footer text: November 12, 2026, 7:14 AM (TERMINOLOGY.md formats)."""
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
/* Brand layer: IBM Plex type, type scale, control size.
   Source: ~/.claude/skills/design/assets/brand.css (version 2026-11-08). Rules: references/brand.md. */
:root{color-scheme:light;--bg:#f4f3ef;--surface:#ffffff;--surface2:#ecebe5;--line:#d8d5cb;--ink:#1e2229;--muted:#616873;--faint:#616873;--ctl-line:#80868f;--link:#1f4e79;--pos:#2e8b57;--neg:#c0504d;--live:#d6323c;--warn:#9a5b00;--accent:ACCENT_LIGHT;--on-accent:#fff;--chip:#e9e7df;--gray:#ebeae5;--logo-edge:drop-shadow(0 0 .5px rgba(0,0,0,.5));--lift:0 1px 2px rgba(30,34,41,.1),0 3px 8px rgba(30,34,41,.08);
--s1:4px;--s2:8px;--s3:12px;--s4:16px;--s5:24px;--s6:40px;--pill:36px;--fs-sm:.875rem;--fs-md:1rem;--fs-base:1rem;
--font-sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;--font-mono:"IBM Plex Mono",ui-monospace,"SF Mono",Menlo,Consolas,monospace;
--fs-caption:.75rem;--fs-small:.875rem;--fs-body:1rem;--fs-h3:1.25rem;--fs-h2:1.5rem;--fs-h1:2rem;--control-h:36px;--control-gap:8px}
:root[data-theme="dark"]{color-scheme:dark;--bg:#15181d;--surface:#1d2128;--surface2:#252a32;--line:#363c46;--ink:#e7e9ec;--muted:#a7adb7;--faint:#969da8;--ctl-line:#6f7682;--link:#8ab8e6;--pos:#5fc08a;--neg:#e2807c;--live:#ff6b6b;--warn:#e8b04b;--accent:ACCENT_DARK;--on-accent:#15181d;--chip:#2e343d;--gray:#252a32;--logo-edge:drop-shadow(0 0 .6px rgba(255,255,255,.85)) drop-shadow(0 0 .6px rgba(255,255,255,.55));--lift:0 1px 2px rgba(0,0,0,.45),0 4px 10px rgba(0,0,0,.35)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#15181d;--surface:#1d2128;--surface2:#252a32;--line:#363c46;--ink:#e7e9ec;--muted:#a7adb7;--faint:#969da8;--ctl-line:#6f7682;--link:#8ab8e6;--pos:#5fc08a;--neg:#e2807c;--live:#ff6b6b;--warn:#e8b04b;--accent:ACCENT_DARK;--on-accent:#15181d;--chip:#2e343d;--gray:#252a32;--logo-edge:drop-shadow(0 0 .6px rgba(255,255,255,.85)) drop-shadow(0 0 .6px rgba(255,255,255,.55));--lift:0 1px 2px rgba(0,0,0,.45),0 4px 10px rgba(0,0,0,.35)}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:400 16px/1.5 var(--font-sans)}
code,kbd,samp,pre{font-family:var(--font-mono);font-weight:400}:not(pre)>code{font-size:.875em}
h1,h2,h3,h4,strong,b,th{font-weight:600}h1,h2{letter-spacing:-.01em}
a{color:var(--link)}img{max-width:100%}button{font:inherit;cursor:pointer}
main{max-width:2200px;margin:0 auto;padding:var(--s3) var(--s4) 64px}
h1{font-size:var(--fs-h2);line-height:1.2;margin:0}
h2{font-size:var(--fs-h3);font-weight:600;margin:var(--s4) 0 var(--s2)}
h3{font-size:var(--fs-h3);margin:var(--s5) 0 var(--s2)}
p{margin:0 0 var(--s3)}.sub{color:var(--muted);max-width:760px}.small{font-size:var(--fs-sm);color:var(--muted)}
.muted{color:var(--muted)}.pos{color:var(--pos)}.neg{color:var(--neg)}
.top{display:flex;align-items:center;gap:var(--s3);flex-wrap:wrap}.top .how{margin-left:auto;font-size:var(--fs-sm)}
.settings summary{list-style:none;cursor:pointer;display:inline-flex;align-items:center;height:var(--control-h);border:1px solid var(--ctl-line);background:var(--surface);color:var(--ink);border-radius:999px;padding:0 var(--s3);font-size:var(--fs-md)}.settings summary::-webkit-details-marker{display:none}.settings[open] summary{background:var(--accent);border-color:var(--accent);color:var(--on-accent);font-weight:600}
.settings-panel{flex-basis:100%;order:3}.top:has(.settings[open]) .settings-panel{display:block}.settings-panel{display:none;padding:var(--s2) 0}
.controls{display:flex;gap:var(--s4);align-items:flex-start;flex-wrap:wrap}.ctl{display:flex;flex-direction:column;gap:var(--s1)}
.seglabel{font-size:var(--fs-caption);font-weight:500;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);padding-left:2px}
.seg{display:inline-flex;align-items:stretch;border:1px solid var(--ctl-line);border-radius:999px;overflow:hidden;background:var(--surface)}
.seg button{border:0;background:transparent;color:var(--muted);height:calc(var(--control-h) - 2px);padding:0 var(--s3);font-size:var(--fs-md);min-width:44px}.seg button+button{border-left:1px solid var(--line)}
.seg button.active{background:var(--accent);color:#fff;font-weight:600}.seg button.active::before{content:"\2713\00a0"}
:root[data-theme="dark"] .seg button.active{color:#15181d}@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .seg button.active{color:#15181d}}
.toggles{display:flex;gap:var(--s2)}.toggles button{height:var(--pill);border:1px solid var(--ctl-line);background:var(--surface);color:var(--ink);border-radius:999px;padding:0 var(--s4);font-size:var(--fs-md)}
.group summary{list-style:none;cursor:pointer;width:fit-content}.group summary::-webkit-details-marker{display:none}.group summary h2{display:inline-block}
.group summary h2::before{content:"\25BE";display:inline-block;width:1.1em;color:var(--muted)}.group:not([open]) summary h2::before{content:"\25B8"}
.count{font-weight:600;color:var(--muted);margin-left:var(--s1)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:var(--s4)}
.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:var(--s4)}
.card h3{margin:0 0 var(--s2)}.card .big{font-size:var(--fs-h2);font-weight:600;line-height:1.1}
.chips{display:flex;flex-wrap:wrap;gap:var(--s1) var(--s2)}.chip{display:inline-block;background:var(--chip);border-radius:999px;padding:1px 9px;font-size:var(--fs-sm);color:var(--ink)}
.tablewrap{overflow-x:auto;background:var(--surface);border:1px solid var(--line);border-radius:14px}
table{border-collapse:collapse;width:100%;font-size:var(--fs-md)}caption{text-align:left;padding:var(--s3) var(--s4) 0;font-weight:600}
th,td{padding:var(--s2) var(--s3);border-top:1px solid var(--line);text-align:center;white-space:nowrap}
thead th{border-top:0;background:var(--surface2);font-weight:600;color:var(--muted)}
th.lead,td.lead{text-align:left}td.lead{font-weight:600}
.sortable th{cursor:pointer;user-select:none}.sortable th::after{content:"";display:inline-block;width:.9em;color:var(--faint)}.sortable th[aria-sort="ascending"]::after{content:"\25B4"}.sortable th[aria-sort="descending"]::after{content:"\25BE"}
.opinion{margin-top:var(--s6);padding:var(--s4) var(--s5);border-radius:12px;background:var(--gray)}
.opinion h2{margin:0 0 var(--s2);border:0;padding:0;font-size:var(--fs-h3)}.opinion .note{margin:0 0 var(--s3);font-size:var(--fs-sm);font-weight:600;color:var(--muted)}
.opinion blockquote{margin:0;padding:0;font-style:italic}.opinion blockquote p::before{content:"\201C"}.opinion blockquote p::after{content:"\201D"}
footer{margin-top:var(--s6);padding-top:var(--s4);border-top:1px solid var(--line);font-size:var(--fs-sm);color:var(--muted)}
.toolbar{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:var(--s2);margin:var(--s2) 0 var(--s3);padding:var(--s2) 0;background:var(--bg);box-shadow:0 1px 0 var(--line)}
.toolbar button{height:var(--pill);border:1px solid var(--ctl-line);background:var(--surface);color:var(--ink);border-radius:999px;padding:0 var(--s3);font-size:var(--fs-md);white-space:nowrap}
.toolbar button:disabled{color:var(--faint);cursor:default}.toolbar .step{padding:0;width:var(--pill)}.toolbar .label{font-weight:600;white-space:nowrap;text-align:center;min-width:5.6em}
.toolbar input{flex:0 1 220px;min-width:0;width:100%;height:var(--pill);border:1px solid var(--ctl-line);background:var(--surface);color:var(--ink);border-radius:999px;padding:0 var(--s3);font:inherit}.toolbar input::placeholder{color:var(--muted)}
.toolbar .mine{margin-left:auto}.toolbar .mine[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:var(--on-accent);font-weight:600}
.sortbar{margin:var(--s3) 0;align-items:flex-start}.sortbar .caption{width:100%}.sortbar .caption{display:flex;justify-content:space-between;gap:var(--s3)}.sortbar .checked{font-size:var(--fs-caption);color:var(--muted)}
.board{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,320px),1fr));grid-auto-rows:1fr;gap:var(--s3);padding-bottom:var(--s1)}
.gc{display:grid;grid-template-columns:36px minmax(0,1fr) 32px;grid-template-rows:auto auto 1fr;grid-template-areas:"ix teams teams" ". side star" ". meta meta";gap:0 var(--s1);align-items:start;padding:var(--s2) var(--s2) var(--s1) var(--s2);background:var(--surface);border:1px solid var(--line);border-radius:12px;box-shadow:var(--lift);font-size:var(--fs-small);line-height:1.25}
.ix{grid-area:ix;padding-top:2px}.int{display:block;font-variant-numeric:tabular-nums;font-weight:600;font-size:var(--fs-h3);line-height:1.2}.bar{display:block;height:4px;border-radius:2px;background:var(--surface2);margin-top:3px}.bar i{display:block;height:4px;border-radius:2px;background:var(--accent)}
.teams{grid-area:teams;display:flex;flex-direction:column;gap:2px;color:inherit;text-decoration:none}a.teams:hover .team{text-decoration:underline}
.ln{display:flex;align-items:center;gap:var(--s1);min-height:22px}.at{flex:0 0 16px;color:var(--muted);font-size:var(--fs-caption)}
.lg{flex:0 0 20px;width:20px;height:20px;object-fit:contain;filter:var(--logo-edge)}.lg.none{display:flex;align-items:center;justify-content:center;background:var(--chip);border-radius:5px;color:var(--muted);font-size:var(--fs-caption);font-weight:600;filter:none}
.team{font-weight:600;min-width:0;overflow-wrap:anywhere}.rk{flex:none;color:var(--muted);font-size:var(--fs-caption)}.rk.top{background:var(--accent);color:var(--on-accent);border-radius:4px;padding:0 4px;font-weight:600}
.dv{flex:none;border:1px solid var(--line);border-radius:4px;padding:0 4px;font-size:var(--fs-caption);font-weight:600;color:var(--muted);line-height:1.35}
.pts{margin-left:auto;padding-left:var(--s2);font-variant-numeric:tabular-nums;font-weight:600;font-size:var(--fs-h2);line-height:1}
.gc.final .team{font-weight:400;color:var(--muted)}.gc.final .pts{font-weight:400;color:var(--muted)}.gc.final .team.win{font-weight:600;color:var(--ink)}.gc.final .pts.win{font-weight:600;color:var(--pos)}
.side{grid-area:side;display:flex;flex-wrap:wrap;align-items:center;gap:0 var(--s2);min-width:0;min-height:24px;font-size:var(--fs-caption);color:var(--muted)}.side>span{white-space:nowrap}.side .wc{display:flex;gap:.3em}.state{font-size:var(--fs-small);font-weight:600;color:var(--ink)}.gc.live .state{color:var(--live);font-weight:600}.gc.final .state{color:var(--muted)}
.star{grid-area:star;align-self:start;margin:-4px -4px -4px 0;border:0;background:transparent;color:var(--muted);width:32px;height:32px;padding:0;font-size:var(--fs-body);line-height:1}.star[aria-pressed="true"]{color:var(--warn)}
.meta{grid-area:meta;display:flex;flex-wrap:wrap;gap:0 var(--s3);font-size:var(--fs-caption);color:var(--muted);padding-bottom:var(--s1)}.meta:empty{display:none}
.tag{white-space:nowrap}.tag.upset{color:var(--warn);font-weight:600}.tag.close{color:var(--ink)}.tag.quiet{color:var(--faint)}.watch{color:var(--link);font-weight:600;text-decoration:none}.watch:hover{text-decoration:underline}
#how{scroll-margin-top:64px}dl.terms{max-width:900px}
.nc td.lead{font-weight:400}.nc td:last-child{white-space:normal;min-width:150px}.nc td.lead:first-child{font-weight:600}.nc td.lead .reason{display:block;font-size:var(--fs-caption);color:var(--muted);font-weight:400}
.nc td.m{display:none}.nc .cls{display:none}
@media (max-width:640px){.nc thead{display:none}.nc,.nc tbody{display:block}
.nc tr{display:grid;grid-template-columns:minmax(0,1fr) auto;grid-template-areas:"p g" "t g" "m m" "gm gm";column-gap:var(--s3);row-gap:2px;padding:var(--s2) var(--s3);border-top:1px solid var(--line)}
.nc tr:first-child{border-top:0}.nc td,.nc td.gm{padding:0;border:0;white-space:normal;min-width:0;text-align:left}
.nc .cls{display:inline}.nc td.n{display:none}.nc td.p{grid-area:p}.nc td.t{grid-area:t;color:var(--muted);font-size:var(--fs-sm)}
.nc td.m{display:block;grid-area:m;font-variant-numeric:tabular-nums;padding-top:2px}
.nc td.gs{grid-area:g;align-self:center;text-align:right;font-size:var(--fs-h2);font-weight:600;font-variant-numeric:tabular-nums}
.nc td.gs::after{content:"adjusted game score";display:block;font-size:var(--fs-caption);font-weight:400;color:var(--muted);letter-spacing:.02em}
.nc td.gm{grid-area:gm;font-size:var(--fs-caption);color:var(--muted)}.nc td.lead.gm .reason{display:inline}.nc td.gm .reason::before{content:" · "}}
.empty{color:var(--muted);padding:var(--s3) var(--s4);margin:0}
dl.terms{display:grid;grid-template-columns:minmax(120px,180px) 1fr;gap:var(--s2) var(--s4);margin:0}dl.terms dt{font-weight:600}dl.terms dd{margin:0;color:var(--muted)}dl.terms dd p{margin:0 0 var(--s2)}dl.terms ul{margin:0 0 var(--s2);padding-left:1.2em}dl.terms li{margin:0 0 var(--s1)}dl.terms dd>:last-child{margin-bottom:0}dl.terms b{font-weight:600;color:var(--ink)}dl.terms .sym{display:inline-block;width:1.7em}dl.terms ul.legend{list-style:none;padding-left:0}
@media (max-width:640px){.board{grid-auto-rows:auto;gap:var(--s2)}main{padding:var(--s2) var(--s4) 48px}h1{font-size:var(--fs-h3)}.controls{width:100%}th,td{padding:var(--s2)}.toolbar .mine span{display:none}.toolbar input{flex:1 1 56px;padding:0 var(--s2)}.toolbar .label{min-width:0}.toolbar button{padding:0 var(--s2)}.toolbar .step{padding:0}.toolbar .mine{margin-left:0;flex:none;width:var(--pill);padding:0}.toolbar button,.toolbar input,.settings summary{font-size:var(--fs-sm)}dl.terms{grid-template-columns:1fr}dl.terms dd{margin-bottom:var(--s2)}}
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
function bindSort(t){
  if(t.dataset.sortBound)return;t.dataset.sortBound='1';
  const ths=[...t.querySelectorAll('thead th')],body=t.tBodies[0];if(!body)return;
  ths.forEach((th,i)=>{const go=()=>{const dir=th.getAttribute('aria-sort')==='ascending'?'descending':'ascending';ths.forEach(h=>h.setAttribute('aria-sort','none'));th.setAttribute('aria-sort',dir);
    const rows=[...body.rows];rows.sort((a,b)=>{const x=cellKey(a.cells[i]),y=cellKey(b.cells[i]);const r=typeof x==='number'&&typeof y==='number'?x-y:typeof x==='number'?-1:typeof y==='number'?1:String(x).localeCompare(String(y));return dir==='ascending'?r:-r;});
    rows.forEach(r=>body.appendChild(r));};
    th.addEventListener('click',go);th.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();go();}});});
}
window.bindSort=bindSort;document.querySelectorAll('table.sortable').forEach(bindSort);
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
    icon = (f'<link rel="icon" type="image/svg+xml" href="{esc(SITE["favicon"])}">\n'
            '<link rel="apple-touch-icon" href="apple-touch-icon.png">\n') if SITE.get("favicon") else ""
    css = CSS.replace("ACCENT_LIGHT", SITE.get("accent", {}).get("light", "#1f5fbf")).replace("ACCENT_DARK", SITE.get("accent", {}).get("dark", "#7fb0ff"))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="darkreader-lock">
<meta name="ste-allow" content="leverage,NPI,WBB,D1,D2,D3,OT,NAIA,NCAA,II,III,PTS,REB,AST,STL,BLK,FG,FGM,FGA,FTM,FTA,OREB,DREB,PF,TO">
<meta name="theme-color" content="#f4f3ef" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#15181d" media="(prefers-color-scheme: dark)">
<title>{esc(SITE["title"])}</title>
<meta name="description" content="{esc(SITE["description"])}">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:ital,wght@0,400;1,400&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400&display=swap">
{icon}{tag}<style>{css}</style></head><body><main>
<div class="top"><h1>{esc(SITE["title"])}</h1>{link("#how", "How it works", "how")}<details class="settings"><summary>Settings</summary></details><div class="settings-panel">{controls()}</div></div>
"""


def footer():
    # The update line follows the approved format "Updated November 12, 2026, 7:14 AM ET". It reports when the
    # data was fetched, because that is the age of what the reader sees; the build time adds nothing for a reader.
    # HOME_TZ is America/New_York (site.json), so the zone is written as ET.
    fetched = stamp(DATA["fetched_at"])
    credit = SITE.get("footer_credit", "")
    return (f'<footer>Updated {esc(fetched)} ET. '
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
    return fill_classes(json.loads(path.read_text()), roster_classes()) if path.exists() else None


SEASON_N = 10
NC_HEADERS = ["Player", "Team", "Class", "Points", "Rebounds", "Assists", "Steals plus blocks", "Field goals", "Game score", "Adjusted game score", "Game"]


def roster_classes(rows=None):
    """{team: [{'name', 'class'}]} from data/rosters.csv: the canonical names and class years."""
    if rows is None:
        path, rows = BASE / "data" / "rosters.csv", []
        if path.exists():
            with open(path, newline="", encoding="utf-8") as f:
                rows = [(r["team"], r["player"], r.get("class") or "") for r in csv.DictReader(f)]
    out = {}
    for team, name, cls in rows:
        out.setdefault(team, []).append({"name": name, "class": cls})
    return out


def roster_player(team, name, rosters):
    """(name, class) for a stored line: the roster player's when one fits (the roster name is canonical), else the
    stored spelling with no class."""
    who = match_player(name_line(name), rosters.get(team, []))
    return (who["name"], who.get("class") or "") if who else (name, "")


def fill_classes(slate, rosters):
    """Give every stored line in a slate its roster name and class year, and every game its rosters with classes,
    when the fetcher stored them without (slates built before 2026-11-11). The page reads both from the line."""
    for g in slate.get("games", []):
        for key in ("home", "away"):
            if not g.get(f"{key}_classes"):
                g[f"{key}_classes"] = rosters.get(g[key], [])
        for lines in (g.get("top_lines") or [], g.get("newcomer_games") or []):
            for x in lines:
                if not x.get("class"):
                    x["name"], x["class"] = roster_player(x["team"], x["name"], rosters)
    return slate


def season_lines():
    """The SEASON_N best stored box lines of the season by adjusted game score, three ways: every player ("top"),
    newcomers ("nc"), and freshmen ("fr"). Reads only the lines each slate already stores (at most 15 per team per
    game) and keeps a running cut at the tenth score, so a line below it costs one comparison."""
    lists = {"top": [], "nc": [], "fr": []}

    def offer(key, x):
        lst = lists[key]
        if len(lst) >= SEASON_N and x["adj"] <= lst[-1]["adj"]:
            return
        lst.append(x)
        lst.sort(key=lambda y: (-y["adj"], -y["gmsc"]))
        del lst[SEASON_N:]

    for path in sorted(SLATES.glob("*.json")):
        slate = json.loads(path.read_text())
        for g in slate.get("games", []):
            for key, lines in (("top", g.get("top_lines") or []), ("nc", g.get("newcomer_games") or [])):
                for x in lines:
                    # The opponent's defense factor, as the page applies it: a home player's line meets the away defense.
                    factor = (g.get("away_def") if x["team"] == g["home"] else g.get("home_def")) or 1
                    item = dict(x, adj=round(x["gmsc"] * factor, 1), date=slate["date"], game=g)
                    offer(key, item)
                    if key == "nc" and x.get("reason") in ("Freshman", "First-year"):
                        offer("fr", item)
    rosters = roster_classes()
    for lst in lists.values():
        for x in lst:
            if not x.get("class"):
                x["name"], x["class"] = roster_player(x["team"], x["name"], rosters)
    return lists


def reason_text(reason):
    """The newcomer reason as a reader sees it. The newcomer source says "Freshman"; prose uses "First-year"
    (TERMINOLOGY.md formats). LIVE_JS has the same mapping in reasonText()."""
    return "First-year" if reason == "Freshman" else reason


def line_row(x):
    """One row of a season list, in the shape LIVE_JS draws for the nightly lists (td.m is the phone layout's one-line stats)."""
    l, g, cls = x["line"], x["game"], x.get("class") or ""
    when = datetime.fromisoformat(x["date"]).strftime("%b %-d")
    reason = f'<span class="reason">{esc(reason_text(x["reason"]))}</span>' if x.get("reason") else ""
    stats = f'{l["pts"]} PTS · {l["reb"]} REB · {l["ast"]} AST · {l["stl"] + l["blk"]} STL+BLK · {l["fgm"]}-{l["fga"]} FG · {x["gmsc"]:.1f} game score'
    return (f'<tr><td class="lead p">{esc(x["name"])}{reason}</td><td class="lead t">{esc(x["team"])}{f"<span class={chr(34)}cls{chr(34)}> · {esc(cls)}</span>" if cls else ""}</td>'
            f'<td class="n">{esc(cls)}</td><td class="n">{l["pts"]}</td><td class="n">{l["reb"]}</td><td class="n">{l["ast"]}</td><td class="n">{l["stl"] + l["blk"]}</td>'
            f'<td class="n">{l["fgm"]}-{l["fga"]}</td><td class="m">{stats}</td><td class="n">{x["gmsc"]:.1f}</td><td class="gs">{x["adj"]:.1f}</td>'
            f'<td class="lead gm">{esc(g["away"])} at {esc(g["home"])}<span class="reason">{esc(when)}</span></td></tr>')


def nc_table(rows, empty):
    if not rows:
        return f'<p class="empty">{esc(empty)}</p>'
    th = "".join(f'<th{" class=lead" if i in (0, 1, len(NC_HEADERS) - 1) else ""} role=button tabindex=0 aria-sort=none>{h}</th>' for i, h in enumerate(NC_HEADERS))
    return f'<div class="tablewrap"><table class="nc sortable"><thead><tr>{th}</tr></thead><tbody>{"".join(line_row(x) for x in rows)}</tbody></table></div>'


def season_sections():
    season = season_lines()
    tail = ' Ranked by adjusted game score. The list updates at each rebuild, so a game still going joins after its final is recorded.</p>'
    return "\n".join((
        twisty("Top 10 game scores this season", '<p class="small">The 10 best adjusted game scores since opening night by any player, from every recorded box score.' + tail
               + nc_table(season["top"], "No box score has been recorded yet."), count=len(season["top"]), open_=False, id_="s-top"),
        twisty("Top 10 newcomer game scores this season", '<p class="small">The 10 best adjusted game scores since opening night by first-years, transfers, and players with no 2025-26 minutes or under 30 minutes.' + tail
               + nc_table(season["nc"], "No newcomer line has been recorded yet."), count=len(season["nc"]), open_=False, id_="s-nc"),
        twisty("Top 10 first-year game scores this season", '<p class="small">The 10 best adjusted game scores since opening night by first-years.' + tail
               + nc_table(season["fr"], "No first-year line has been recorded yet."), count=len(season["fr"]), open_=False, id_="s-fr")))


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
               '<button type="button" class="mine" id="mine" aria-pressed="false" aria-label="Show only My Watchlist">\u2605<span> My Watchlist</span></button></div>')
    def rank_bar(list_id):
        # Both lists share one rank cut; the two button rows stay in step.
        buttons = "".join(f'<button type="button" class="cut" data-cut="{n}">{label}</button>'
                          for n, label in ((0, "All teams"), (200, "Top 200"), (100, "Top 100")))
        return (f'<div class="sortbar ctl"><span class="seglabel caption" id="lbl-cut-{list_id}">Teams</span>'
                f'<div class="seg" role="group" aria-labelledby="lbl-cut-{list_id}">{buttons}</div></div>')
    newcomers = twisty("Top 15 newcomer games", '<p class="small">The 15 best adjusted game scores on this night by first-years, transfers, and players with no 2025-26 minutes or under 30 minutes. '
                       'Game score adds points, rebounds, assists, steals, and blocks, and takes away missed shots, turnovers, and fouls. '
                       'Lines arrive when a game ends, or during play when its feed includes box lines (Presto feeds do, Sidearm feeds do not).</p>' + rank_bar("nc") + '<div id="newcomers"></div>', count="", open_=False, id_="nc")
    topgames = twisty("Top 15 game scores", '<p class="small">The 15 best adjusted game scores on this night by any player, in every game with a live stats feed. '
                      'Lines arrive when a game ends, or during play when its feed includes box lines (Presto feeds do, Sidearm feeds do not).</p>' + rank_bar("top") + '<div id="topgames"></div>', count="", open_=False, id_="top")
    sort = ('<div class="sortbar ctl"><span class="seglabel caption"><span id="lbl-sort">Sort</span><span class="checked" id="checked"></span></span>'
            '<div class="seg" role="group" aria-labelledby="lbl-sort">'
            '<button type="button" class="sorter" data-sort="interest">Interest</button><button type="button" class="sorter" data-sort="tipoff">Tipoff</button>'
            '<button type="button" class="sorter" data-sort="closest">Closest</button><button type="button" class="sorter" data-sort="leverage">Leverage</button></div></div>')
    groups = "".join(twisty(title, '<div class="board"></div>', count="", id_=f"g-{key}", hidden=True)
                     for key, title in (("mine", "My Watchlist"), ("live", "Live"), ("pre", "Not started"), ("final", "Final")))
    board = f'{sort}<p class="empty" id="boardmsg" hidden></p>{groups}'
    how = twisty("How it works", HOW, open_=False, id_="how")
    data = json.dumps(boot, separators=(",", ":")).replace("</", "<\\/")
    return f'{toolbar}\n{newcomers}\n{topgames}\n{board}\n{season_sections()}\n{how}\n<script id="boot" type="application/json">{data}</script><script>{LIVE_JS}</script>'


HOW = f"""<dl class="terms">
<dt>This page</dt><dd><p>{esc(SITE["intro"])}</p></dd>
<dt>Reading a card</dt><dd>
<p>The left column shows the interest score and its bar.</p>
<p>A number before a team is its season efficiency rank among Division III teams. A filled badge marks the top 25. The rating starts at the preseason projection and moves in equal steps to the team's box-score rating over its first eight games.</p>
<p>The line under the teams shows the status, the favorite's win probability, and the leverage (Lev).</p>
<ul>
<li><b>Before tipoff</b>, the win probability comes from the efficiency margin line.</li>
<li><b>During the game</b>, the line counts as one game of evidence and the score so far as the part of a game played. A heavy favorite that leads by one after a quarter sits near 97% rather than the 99% the line alone gives.</li>
</ul>
<p><span class="sym" aria-hidden="true">★</span>Click the star to add a game to My Watchlist at the top of the page. The game also stays in its usual group, starred in both places. This browser remembers your stars.</p>
</dd>
<dt>Order</dt><dd>
<p>Games group as live, not started, and final. A game whose score the page read from a box score during play counts as live for two hours after that read.</p>
<p>The Sort buttons set the order inside each group:</p>
<ul>
<li><b>Interest</b> puts the highest score first.</li>
<li><b>Tipoff</b> puts the earliest game first.</li>
<li><b>Closest</b> puts the smallest gap in win probability first.</li>
<li><b>Leverage</b> puts the most at stake first.</li>
</ul>
</dd>
<dt>Which games</dt><dd>
<p>Every game between two teams that count for the NCAA Power Index. A game appears only when a schedule page lists it.</p>
<p>These games do not appear:</p>
<ul>
<li>Exhibitions.</li>
<li>Games against Division I, II, NAIA, and two-year opponents.</li>
<li>Games against second-year provisional members or earlier.</li>
</ul>
<p>Sometimes the schedule pages list a game before the NPI data does, such as a tournament's second-day game. That game shows an even win probability and no leverage until the next NPI update.</p>
</dd>
<dt>Interest</dt><dd>
<p>A score from 0 to 100, from four parts:</p>
<ul>
<li><b>Team quality.</b> The season efficiency ranks of both teams. The better team counts more, and a rank near the top counts far more than one in the middle. The gap between 13th and 39th counts about four times the gap between 213th and 239th.</li>
<li><b>Leverage.</b> The leverage of the game.</li>
<li><b>Closeness.</b> How close the game is. Late in the game, this counts more. It is weighted by the quality of the two teams, so a close game between two teams ranked near 300 adds little.</li>
<li><b>Upset.</b> How far an underdog is past its pregame chance, weighted by the quality of the team being upset. An upset of the 20th team is news. An upset of the 254th is not.</li>
</ul>
<p>The page then multiplies the score by the better of the two teams' tournament chances. A game between two teams with almost no chance scores near 0.</p>
<p>A finished game gets its own score from four parts:</p>
<ul>
<li><b>Team quality (30%).</b> The season efficiency ranks of both teams.</li>
<li><b>Upset (30%).</b> How far the underdog beat the pregame spread. A win counts in full. A closer loss than expected counts 60%.</li>
<li><b>Closeness (25%).</b> How close the final score is. Overtime counts as the closest finish.</li>
<li><b>Leverage (15%).</b> The leverage of the game.</li>
</ul>
<p>The upset and closeness parts count in full between top teams. Between teams ranked near 400, they count about a third as much. A one-point upset in the middle of the table therefore sits below a six-point game between two top-50 teams.</p>
<p>Tournament chances lower a finished game's score by at most half.</p>
</dd>
<dt>Win probability</dt><dd>
<ul>
<li><b>Before tipoff:</b> the season efficiency margins plus 3 points for the home team.</li>
<li><b>During the game:</b> the current lead plus the expected margin for the time left, against a spread that shrinks as the clock runs down.</li>
</ul>
</dd>
<dt>Leverage</dt><dd><p>From the season simulations: how many percentage points each team's tournament chance moves between a win and a loss, added for both teams.</p></dd>
<dt>How often a game is checked</dt><dd>
<p>The page reads each game's live stats feed itself. Hover over a card to see its last and next check.</p>
<p>The wait between checks:</p>
<ul>
<li><b>Interest</b> sets the base wait: 1 minute at interest 100, 60 minutes at interest 0.</li>
<li><b>Margin</b> stretches it. The wait grows with the leader's margin. A tie keeps the wait as it is.</li>
<li><b>Decided</b> games stretch it past the end of the game, so the next check reads the final score. A game is decided when the model's win probability, from the pregame line and the score, passes 98%. The score and clock alone must also put the comeback chance under 20%. A 30-point lead at the half does it.</li>
<li><b>No tournament chance</b> for either team: about two checks for the whole game.</li>
</ul>
<p>Finding the feed:</p>
<ul>
<li>A tournament host runs one Sidearm feed per court. If a feed shows another game after tipoff, the page also tries the host's other feeds and every other feed the schedule pages gave.</li>
<li>A feed that does not show its game yet gets a look every 5 minutes for 45 minutes after tipoff, whatever the game's interest. If it still does not show the game, the page stops checking and the game shows "no live stats".</li>
<li>A game whose stats link goes to StatBroadcast, which the page cannot read, shows "stats on StatBroadcast" from the start. The team names link to that page.</li>
</ul>
</dd>
<dt>Colors</dt><dd>
<ul>
<li><b>Red:</b> a game in progress. The dot and the clock are red. Nothing else on the page is red.</li>
<li><b>Green:</b> the winner of a finished game.</li>
<li><b>Amber:</b> an upset. The team won after the model gave it 35% or less before tipoff. During play, its win probability is more than 20 points above its pregame chance. A game the model has no line for (one the schedule pages added) gets no upset tag.</li>
<li><b>Gray:</b> a game with nothing left to decide.</li>
</ul>
</dd>
<dt>Symbols</dt><dd>
<ul class="legend">
<li><span class="sym" aria-hidden="true">\U0001F534</span>A game in progress.</li>
<li><span class="sym" aria-hidden="true">\U0001F525</span>Close: a live game where the trailing team still has better than a 30% chance.</li>
<li><span class="sym" aria-hidden="true">\U0001F6A8</span>Upset, or an upset alert during play.</li>
<li><span class="sym" aria-hidden="true">\U0001F512</span>Decided: the trailing team has under a 2% chance.</li>
<li><span class="sym" aria-hidden="true">\U0001F4A4</span>Neither team has a tournament chance.</li>
<li><span class="sym" aria-hidden="true">⚡</span>Leverage of 15 or more.</li>
<li><span class="sym" aria-hidden="true">\U0001F4FA</span>Watch: opens the video stream when the schedule page lists one.</li>
<li><span class="sym" aria-hidden="true">★</span>On My Watchlist.</li>
</ul>
</dd>
<dt>Status words</dt><dd>
<ul>
<li><b>Postponed</b> or <b>Canceled</b> replaces the tipoff time when a schedule page says so.</li>
<li><b>Final pending</b> marks a game whose host's feed moved on to its next game before the host posted a box score. The last score the page read stays on the card. The score follows once a schedule page links the box score.</li>
</ul>
<p>The page remembers the last live score it read for each game, so a reload keeps it.</p>
</dd>
<dt>Top 15 lists</dt><dd>
<p>Each score check reads the game's full box score, so the lists move with the games.</p>
<p><b>Top 200</b> and <b>Top 100</b> show only players whose team has that season efficiency rank or better. The choice applies to both lists. This browser remembers it.</p>
<p><b>Class</b> is the player's class year on this season's roster.</p>
</dd>
<dt>Game score</dt><dd>
<p>Game score adds PTS, 0.4 FGM, 0.7 OREB, 0.3 DREB, STL, 0.7 AST, and 0.7 BLK. It subtracts 0.7 FGA, 0.4 missed free throws (FTA minus FTM), 0.4 PF, and TO.</p>
<p>The lists rank players by <b>adjusted game score</b>: game score times the Division III average adjusted defense divided by the opponent's. A line against a team that allows 10% more points than average counts about 9% less. An opponent outside Division III counts as average.</p>
</dd>
<dt>Season top 10 lists</dt><dd>
<p>Three lists under the games hold the best adjusted game scores since opening night: by any player, by newcomers, and by first-years. They come from every recorded box score.</p>
<p>They update at each rebuild. Rebuilds run a few times a day, plus every 20 minutes on game nights. A game still going joins after its final is recorded.</p>
</dd>
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
let night=BOOT.night,games=[],timer=null,sortKey='interest',onlyMine=false,findText='';
// The team rank cut for both top 15 lists: 0 shows every team. This browser remembers it.
let rankCut=(()=>{try{const v=+localStorage.getItem(KEY+'-cut');return [0,100,200].includes(v)?v:0}catch(e){return 0}})();
const LOGOS=new Set(BOOT.logos||[]);
const stars=new Set((()=>{try{return JSON.parse(localStorage.getItem(KEY+'-stars'))||[]}catch(e){return []}})());
const tokens=[];                   // timestamps of recent feed reads, for the budget

// ---------- model
function phi(z){const t=1/(1+0.2316419*Math.abs(z)),d=0.3989423*Math.exp(-z*z/2);const p=d*t*(0.3193815+t*(-0.3565638+t*(1.781478+t*(-1.821256+t*1.330274))));return z>0?1-p:p;}
// Home team's chance to win. lead is home minus away; progress is the share of regulation played.
// The chance the leader holds on from the score and clock alone, with no pregame line. "Decided" needs both the
// model (line and score) under 2% and this under SCORE_DECIDED: Haverford trailed #2 NYU by one after a quarter
// (2026-11-08) and the line alone said 99%.
const SCORE_DECIDED=0.2;
function scoreWp(lead,progress){
  const left=Math.max(0,1-progress);
  if(left<=0)return lead>0?1:lead<0?0:0.5;
  return phi(lead/(SD*Math.sqrt(left)));
}
// Live win probability. The pregame line is a prior on the true margin worth one game of evidence (LINE_SD), and the
// score so far is `progress` of a game of evidence, so a quarter played at even terms pulls a 35-point line toward
// the scoreboard (#2 NYU led Haverford by one after a quarter, 2026-11-08: 99.8% as a certain line, 97% here).
const LINE_SD=SD;
function winProb(g,lead,progress){
  const left=Math.max(0,1-progress);
  if(left<=0)return lead>0?1:lead<0?0:0.5;
  const precision=1/(LINE_SD*LINE_SD)+progress/(SD*SD);
  const margin=(g.pregame_margin/(LINE_SD*LINE_SD)+lead/(SD*SD))/precision;
  return phi((lead+margin*left)/Math.sqrt(SD*SD*left+left*left/precision));
}
// Team quality: a team outside Division III has no season rank; it counts as an average team. The better team counts
// more. The curve is cubic, so a rank near the top counts far more than one in the middle: 13th against 39th is a
// gap of 0.17, 213th against 239th a gap of 0.04. On a linear scale Concordia (MN) at Wartburg (22 at 13, leverage
// 23) ranked below RIT at Rochester (39 at 54) on 2026-11-07 because the second game was a little closer.
function teamQuality(r){return r?Math.pow(1-(r-1)/409,3):0.125;}
function quality(g){const q1=teamQuality(g.home_rank),q2=teamQuality(g.away_rank);return 0.6*Math.max(q1,q2)+0.4*Math.min(q1,q2);}
function stakes(g){return 1-Math.exp(-(Math.abs(g.home_lev)+Math.abs(g.away_lev))/12);}
// How far the underdog beat the pregame spread, 0 to 1. A win counts in full and a closer-than-expected loss counts 60%.
function dogSurprise(g,score){
  if(g.division||!g.pregame_margin)return 0;
  const homeDog=g.pregame_margin<0,dogMargin=homeDog?score[0]-score[1]:score[1]-score[0];
  const z=Math.max(0,(dogMargin+Math.abs(g.pregame_margin))/SD);
  return (1-Math.exp(-z))*(dogMargin>0?1:0.6);
}
// A finished game: team quality, the upset or near upset, how close it ended, and leverage. Tournament chances
// scale it down only halfway, so a good game between two long shots still ranks above a blowout. The upset and
// closeness terms scale with team quality: a one-point upset of #86 by #208 (Albright over Rutgers-Camden,
// 2026-11-07) scored 53, level with a top-ten game, and now scores 38.
const QUALITY_GATE=0.35;
function finalInterest(g,st){
  const T=Math.max(g.home_tourn,g.away_tourn),S=T/(T+0.01),Q=quality(g);
  const ot=/OT/.test(st.status||''),C=ot?1:Math.exp(-Math.abs(st.score[0]-st.score[1])/7);
  const gate=QUALITY_GATE+(1-QUALITY_GATE)*Q;
  return Math.min(100,100*(0.5+0.5*S)*(0.30*Q+(0.30*dogSurprise(g,st.score)+0.25*C)*gate+0.15*stakes(g)));
}
function interest(g,st){
  if(g.off)return 0;
  if(st.final&&st.score)return finalInterest(g,st);
  const Q=quality(g),L=stakes(g);
  const T=Math.max(g.home_tourn,g.away_tourn),S=T/(T+0.01);
  const P=st.progress||0,wp=st.wp;
  const C=1-Math.abs(2*wp-1);
  const homeDog=g.pregame_wp<0.5;
  // A game against a Division I or II team has no pregame model, so it has no upset term.
  const U=g.division||g.modeled===false?0:Math.max(0,homeDog?wp-g.pregame_wp:(1-wp)-(1-g.pregame_wp));
  // Rank and leverage fade as the result becomes certain: at the final whistle of a blowout they count for little.
  const settled=1-P*(1-Math.sqrt(C));
  // A close game counts by the quality of the two teams, and an upset by the quality of the team being upset:
  // #327 Curry leading #254 Elmira by 14 in the third quarter scored 9, above every decided game between ranked
  // teams (2026-11-08), because the upset term alone carried it.
  const favorite=teamQuality(homeDog?g.away_rank:g.home_rank);
  return Math.min(100,100*S*((0.30*Q+0.25*L)*settled+(0.20+0.15*P)*C*Q+0.25*U*favorite));
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
const GIVE_UP_MS=45*60000,RETRY_MS=10*60000,EARLY_RETRY_MS=5*60000,LAST_LOOK_MS=4*3600000,FINAL_EARLIEST_MS=45*60000;
const SIBLING_FEEDS=2;
// A win by a team given more than this before tipoff is no upset: William Peace (41%) won at Roanoke, 2026-11-07.
const UPSET_MAX_DOG=0.35;
// A game with a pregame line: the Stat Lab's games. One the schedule pages added sits at 50% with no line.
function modeled(g){return !g.division&&g.modeled!==false;}
function dogChance(g){return Math.min(g.pregame_wp,1-g.pregame_wp);}
// A tournament host runs its own game on wbball and the other game on wbball2 (Hope, 2026-11-07), and the schools'
// pages can link either folder until the crews settle which game is on which. When a Sidearm feed shows another
// game after tipoff, the host's other feeds get a look.
function siblingFeeds(f){
  const m=f&&f.type==='sidearm'?/^(https:\/\/sidearmstats\.com\/[^/]+\/)([a-z]+?)(\d*)\/game\.json$/.exec(f.url):null;
  if(!m)return [];
  const folders=[m[2]];for(let n=2;n<=SIBLING_FEEDS+1;n++)folders.push(m[2]+n);
  return folders.filter(x=>x!==m[2]+m[3]).map(x=>({type:'sidearm',url:m[1]+x+'/game.json'}));
}
// Feeds to try when the main feed has not shown the game after tipoff: the host's other courts, then the other
// feeds the schedule pages gave (a school's own idle feed sat first for Christopher Newport at Susquehanna, 2026-11-07).
function probeFeeds(g){
  const out=siblingFeeds(g.feed).map(f=>({feed:f,link:siblingLink(g.link,f)}));
  (g.alt_feeds||[]).forEach(a=>{if(a.feed&&a.feed.url!==(g.feed||{}).url&&!out.some(o=>o.feed.url===a.feed.url))out.push({feed:a.feed,link:a.link||g.link});});
  return out;
}
function siblingLink(link,f){const m=/\/([a-z]+?\d*)\/game\.json$/.exec(f.url);return link&&m?link.replace(/\/sidearmstats\/[a-z]+?\d*\//,'/sidearmstats/'+m[1]+'/'):link;}
// No game ends within 45 minutes of tipoff, so a final before that (in the slate, in this browser's memory, or on a
// feed showing the host's earlier game) is not this game's.
function canBeFinal(g){const t=tipMs(g);return t?Date.now()>=t+FINAL_EARLIEST_MS:g.date<=todayET();}
// A StatBroadcast page cannot be read (Cloudflare blocks scripted requests, the data calls need per-session tokens),
// so a game whose stats link goes there says so from the start instead of waiting 45 minutes to say "no live stats"
// (McMurry at Trinity (TX), 2026-11-08). The team names link to the page.
function statsLabel(g,st){
  if(st.seen||st.final||st.ended||st.snap||g.off)return null;
  if(/statbroadcast\.com/i.test(g.link||''))return 'stats on StatBroadcast';
  return !g.feed||st.noStats?'no live stats':null;
}
function nextCheck(g,st,now){
  if(st.final||st.ended||!g.feed||g.off)return null;
  // A feed that has not shown this game by GIVE_UP_MS gets a look every RETRY_MS until LAST_LOOK_MS: a tournament
  // host's feed shows the earlier game first, and some crews start late.
  if(st.noStats){const tip=tipMs(g);return tip&&now<tip+LAST_LOOK_MS?now+RETRY_MS:null;}
  const tip=tipMs(g);
  if(tip&&now<tip+5*60000&&!st.live)return tip+5*60000;
  const end=(tip||now)+GAME_MS;
  if(now>=end)return now+15*60000;                 // past the expected end: look for the final every 15 minutes
  // A feed that has not shown the game yet: every EARLY_RETRY_MS until GIVE_UP_MS, whatever the interest. Crews
  // start the feed late (La Verne, UMass Dartmouth, Hollins, Smith: nothing 9 minutes after tipoff, 2026-11-08).
  if(tip&&!st.seen&&now<tip+GIVE_UP_MS)return Math.min(now+EARLY_RETRY_MS,tip+GIVE_UP_MS);
  return Math.min(now+waitMs(g,st),end);
}

// ---------- feeds
function teamTokens(n){return new Set(String(n||'').toLowerCase().match(/[a-z]+/g)||[]);}
function overlap(a,b){const B=teamTokens(b);let n=0;teamTokens(a).forEach(t=>{if(B.has(t)&&!['college','university','of','the','state'].includes(t))n++;});return n;}
// Orienting a feed to the schedule. Crews sometimes type the team names on the wrong sides (Medgar Evers vs
// St. Joseph's Long Island, 2026-11-06: the side coded MEDGAR, carrying Medgar Evers' players and score, was named
// St. Joseph's Long Island). So the box score's players count most, then the team code, then the typed name.
function initials(n){return (String(n||'').replace(/['\u2019]/g,'').match(/[A-Za-z]+/g)||[]).map(w=>w[0]).join('').toLowerCase();}
function codeHit(code,team){
  const c=String(code||'').toLowerCase().replace(/[^a-z]/g,''),t=String(team||'').toLowerCase().replace(/[^a-z]/g,'');
  return c.length>=2&&(teamTokens(team).has(c)||initials(team)===c||(c.length>=4&&t.startsWith(c)))?1:0;
}
const GENERIC_WORDS=new Set(['university','college','of','the','at','vs','state','st','saint','s','institute','inst']),MIN_ROSTER=5;
// Distinctive words of a team name: "St. Joseph's (LI)" -> josephs, li.
function nameWords(n){return new Set((String(n||'').toLowerCase().replace(/['\u2019]/g,'').match(/[a-z]+/g)||[]).filter(w=>!GENERIC_WORDS.has(w)));}
function lineLast(l){const a=String(l.abbr||'').trim();return String(String(l.last||'').trim()||(a.includes(',')?a.split(',')[0]:a.split(/\s+/).pop())).toLowerCase().replace(/[^a-z]/g,'');}
function rosterOf(g,t){const r=g[t+'_roster']||[];return r.length>=MIN_ROSTER?r:null;}
function rosterHits(lines,roster){const last=new Set((roster||[]).map(n=>String(n).trim().split(/\s+/).pop().toLowerCase().replace(/[^a-z]/g,'')));return (lines||[]).filter(l=>last.has(lineLast(l))).length;}
function namesTeam(side,g,t){
  const w=nameWords(side.name);
  return (g[t+'_names']||[g[t]]).some(n=>{const v=nameWords(n);return codeHit(side.id,n)||(w.size&&v.size&&([...w].every(x=>v.has(x))||[...v].every(x=>w.has(x))));});
}
// A host's crew can run one feed for every game of its tournament (St. Joseph's Brooklyn, 2026-11-06), so a feed
// counts only when it shows this game: two of our teams' players in the box score make it ours, none make it
// another game's; without players, one feed side has to match one of our teams by name or code.
function feedIsGame(g,s){
  const L=s.lines||{},S=s.sides||{},known=['home','away'].filter(t=>rosterOf(g,t));
  if(known.length&&(L.H||[]).length+(L.V||[]).length>=MIN_ROSTER){
    const hits=known.map(t=>['H','V'].reduce((n,k)=>n+rosterHits(L[k],rosterOf(g,t)),0)),total=hits.reduce((a,b)=>a+b,0);
    if(total===0)return false;
    // Both rosters known and both sides listed: a team with no player in the box score is not playing (Principia's
    // tournament feed showed Aurora vs Westminster; Aurora's players alone must not make it Aurora at Principia).
    if(known.length===2&&(L.H||[]).length&&(L.V||[]).length&&Math.min(...hits)===0)return false;
    if(total>=2)return true;
  }
  if(!Object.values(S).some(x=>x&&(x.name||x.id)))return true;
  return ['H','V'].some(k=>S[k]&&['home','away'].some(t=>namesTeam(S[k],g,t)));
}
function sideFit(side,g,t,lines){
  const roster=rosterOf(g,t),names=g[t+'_names']||[g[t]];
  const players=roster?rosterHits(lines,roster):(lines||[]).filter(l=>matchNewcomer(l,g['newcomers_'+t]||[])).length;
  return 4*players+2*(names.some(n=>codeHit(side.id,n))?1:0)+(names.some(n=>overlap(side.name,n)>0)?1:0);
}
function orientFit(g,s,swap){
  const L=s.lines||{},S=s.sides||{},h=swap?'away':'home',a=swap?'home':'away';
  return sideFit(S.H||{},g,h,L.H)+sideFit(S.V||{},g,a,L.V);
}
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
  const tm=h=>({name:(side(h).team||{}).location,id:(side(h).team||{}).abbreviation});
  return {home:num(side('home').score),away:num(side('away').score),sides:{H:tm('home'),V:tm('away')},complete,period,regulation,
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
    if(!G)return null;
    // Stat crews sometimes leave the feed's date unset or stale (1/1/0001). Then the feed counts when one of its teams
    // is one of ours and the game is not over, or when this page already read it live.
    const ours=overlap(G.HomeTeam.Name,g.home)+overlap(G.HomeTeam.Name,g.away)+overlap(G.VisitingTeam.Name,g.home)+overlap(G.VisitingTeam.Name,g.away)>0;
    // A host's feed set up for its next game today (Susquehanna's doubleheader, 2026-11-07) says ours is over.
    if(G.Date===mdy(g.date)&&!ours)g.st.other=true;
    if(!G.HasStarted)return null;
    if(G.Date!==mdy(g.date)&&!(ours&&(!G.IsComplete||g.st.live)))return null;
    const regulation=num((G.Rules||{}).PeriodMinutes)>=20?2:4,period=num(G.Period),clock=num(G.ClockSeconds);
    // Some crews never set IsComplete (Butler, 2026-10-28). The clock at 0:00 in the last period with no tie is a final.
    const complete=!!G.IsComplete||(period>=regulation&&G.ClockSeconds===0&&num(G.HomeTeam.Score)!==num(G.VisitingTeam.Score));
    s={home:num(G.HomeTeam.Score),away:num(G.VisitingTeam.Score),sides:{H:{name:G.HomeTeam.Name,id:G.HomeTeam.Id},V:{name:G.VisitingTeam.Name,id:G.VisitingTeam.Id}},complete,period,regulation,
       progress:complete?1:progressOf(period,clock,regulation),status:statusText(period,clock,regulation),lines:full?sidearmLines(j):null};
  }else{
    const x=new DOMParser().parseFromString(await r.text(),'application/xml');
    const venue=x.querySelector('venue'),st=x.querySelector('status'),rules=x.querySelector('rules');
    if(!venue||!st||venue.getAttribute('date')!==mdy(g.date)||!x.querySelector('play'))return null;
    const regulation=+(rules&&rules.getAttribute('prds'))||4,period=num(st.getAttribute('period')),clock=clockToSec(st.getAttribute('clock'));
    const sc={},sides={H:{name:venue.getAttribute('homename')},V:{name:venue.getAttribute('visname')}};
    x.querySelectorAll('team').forEach(t=>{const ls=t.querySelector('linescore'),vh=t.getAttribute('vh');sc[vh]=num(ls&&ls.getAttribute('score'));
      if(sides[vh])sides[vh]={name:t.getAttribute('name')||sides[vh].name,id:t.getAttribute('id')};});
    const complete=st.getAttribute('complete')==='Y';
    s={home:sc.H||0,away:sc.V||0,sides,complete,period,regulation,
       progress:complete?1:progressOf(period,clock,regulation),status:statusText(period,clock,regulation),lines:prestoLines(x)};
  }
  if(f.type!=='espn'&&!feedIsGame(g,s)){g.st.other=true;return null;}
  // The stat crew's home side can differ from the schedule's, and so can its labels; flip when the evidence says so.
  if(orientFit(g,s,true)>orientFit(g,s,false)){[s.home,s.away]=[s.away,s.home];if(s.lines)s.lines={H:s.lines.V||[],V:s.lines.H||[]};}
  return s;
}

// ---------- newcomers
function gameScore(l){return l.pts+0.4*l.fgm-0.7*l.fga-0.4*(l.fta-l.ftm)+0.7*l.oreb+0.3*l.dreb+l.stl+0.7*l.ast+0.7*l.blk-0.4*l.pf-l.to;}
// A newcomer who saw the floor; some crews leave minutes blank, so any counting stat also counts.
function played(l){return (+l.min||0)>0||['pts','reb','ast','stl','blk','fga','fta','to','pf'].some(k=>(+l[k]||0)>0);}
const TOP_N=15;
const boxLine=l=>({min:l.min,pts:l.pts,reb:l.reb,ast:l.ast,stl:l.stl,blk:l.blk,fgm:l.fgm,fga:l.fga});
// Feeds name players "First Last", "LAST,FIRST", or "Last, First". Show "First Last" and soften all-caps words.
function lineName(l){
  const n=l.first&&l.last?l.first+' '+l.last:String(l.abbr||'').replace(/^\s*(.+?),\s*(.+)$/,'$2 $1');
  return n.trim().split(/\s+/).map(w=>w.length>1&&w===w.toUpperCase()?w.charAt(0)+w.slice(1).toLowerCase():w).join(' ');
}
// The best TOP_N lines of each team in one game. The rank filter can hide one team, so each team keeps its own.
function topLines(g,s,when){
  const out=[];
  [['H',g.home,g.home_classes],['V',g.away,g.away_classes]].forEach(([side,team,classes])=>{
    const mine=((s.lines||{})[side]||[]).filter(played).map(l=>{const who=matchNewcomer(l,classes||[]);
      return {team,name:who?who.name:lineName(l),reason:'',gmsc:Math.round(gameScore(l)*10)/10,when,line:boxLine(l),class:(who&&who.class)||''};});
    out.push(...mine.sort((a,b)=>b.gmsc-a.gmsc).slice(0,TOP_N));
  });
  return out.sort((a,b)=>b.gmsc-a.gmsc);
}
// A line's team rank, for the rank filter. A team with no rank (Division I or II) is outside every cut.
function lineRank(x){return (x.team===x.game.home?x.game.home_rank:x.team===x.game.away?x.game.away_rank:null)||Infinity;}
const norm=n=>String(n||'').toLowerCase().replace(/[^a-z]/g,'');
const words=n=>String(n||'').split(/\s+/).map(norm).filter(Boolean);
// A box line's name words when the feed gives a first name; [] for an initial ("F. Last"), which goes by initial and last name.
function lineWords(l){
  if(l.first&&l.last)return words(l.first+' '+l.last);
  const a=String(l.abbr||'');
  if(a.includes(',')){const i=a.indexOf(','),found=words(a.slice(i+1)).concat(words(a.slice(0,i)));return found.length&&found[0].length>1?found:[];}
  const found=words(a);return found.length&&found[0].length>1?found:[];
}
// The roster player a box line belongs to (player_names.py has the same steps): the roster name is canonical.
function matchNewcomer(l,roster){
  const w=lineWords(l);
  if(w.length){
    const full=w.join('');let hit=roster.find(p=>norm(p.name)===full);if(hit)return hit;
    const key=w.slice().sort().join(' ');let hits=roster.filter(p=>words(p.name).sort().join(' ')===key);if(hits.length===1)return hits[0];
    if(w.length>=2){const mine=new Set(w);hits=roster.filter(p=>{const t=words(p.name);return t.length>=2&&(t.every(x=>mine.has(x))||w.every(x=>t.includes(x)));});if(hits.length===1)return hits[0];}
  }
  let m=/^\s*([A-Za-z])[a-z]*\.?\s+(.+)$/.exec(l.abbr),initial,last;
  if(l.abbr.includes(',')){const k=/^\s*(.+?),\s*([A-Za-z])/.exec(l.abbr);if(!k)return null;last=k[1];initial=k[2];}
  else if(m){initial=m[1];last=m[2];}else return null;
  const hits=roster.filter(p=>norm(p.name.split(' ').slice(-1)[0])===norm(last)&&norm(p.name)[0]===initial.toLowerCase());
  return hits.length===1?hits[0]:null;
}
// The class year of the roster player a box line belongs to, or '' when no one fits.
function classOf(l,roster){const who=matchNewcomer(l,roster||[]);return (who&&who.class)||'';}
function newcomerLines(g,s,when){
  const out=[];
  [['H',g.home,g.newcomers_home,g.home_classes],['V',g.away,g.newcomers_away,g.away_classes]].forEach(([side,team,roster,classes])=>{
    ((s.lines||{})[side]||[]).forEach(l=>{const who=matchNewcomer(l,roster||[]);if(who&&played(l))out.push({team,name:who.name,reason:who.reason,gmsc:Math.round(gameScore(l)*10)/10,when,
      line:boxLine(l),class:who.class||classOf(l,classes)});});
  });
  return out;
}

// ---------- state
function initState(g){
  const st={wp:g.pregame_wp,progress:0,live:false,final:false,score:null,status:null,finalRead:!!g.box_read,nc:(g.newcomer_games||[]).map(x=>Object.assign({when:'final'},x)),
    top:(g.top_lines||[]).map(x=>Object.assign({when:'final'},x))};
  // A final this browser read from the feed counts until the slate has one: the feed moves on to the host's next game,
  // and a reload must not put a finished game back under Not started.
  const possible=canBeFinal(g),slateFinal=possible?g.final:null,seenFinal=slateFinal||!possible?null:remembered()[g.id];
  if(seenFinal)st.status=seenFinal.status;
  const fin=slateFinal||(seenFinal&&seenFinal.score);
  if(fin){st.final=true;st.score=fin;const lead=fin[0]-fin[1];st.wp=lead>0?1:lead<0?0:0.5;st.progress=1;}
  // A score the fetcher read from a box score page during the game, or the last score this browser read from the feed
  // before a reload, whichever is newer. Without it a reload forgot a game the page had seen live, and when the host's
  // crew reset the feed for its next game the card said "no live stats" (Hardin-Simmons vs CMS at UCSC, 2026-11-08).
  else{const snap=newerSnap(g.snapshot,possible?liveSeen()[g.id]:null);if(snap)snapState(g,st,snap);}
  st.interest=interest(g,st);
  return st;
}
function newerSnap(a,b){if(!a||!b)return a||b||null;return Date.parse(b.at)>Date.parse(a.at)?b:a;}
// The last live score this browser read from a feed, by game id, kept the same way as finals.
function liveSeen(){try{return JSON.parse(localStorage.getItem(KEY+'-live'))||{}}catch(e){return {}}}
function rememberLive(id,snap){
  try{
    const cut=new Date(Date.now()-4*86400000).toISOString().slice(0,10),all=liveSeen(),keep={};
    Object.keys(all).forEach(k=>{if(k.slice(0,10)>=cut)keep[k]=all[k];});
    keep[id]=snap;localStorage.setItem(KEY+'-live',JSON.stringify(keep));
  }catch(e){}
}
// Finals this browser read from feeds, by game id. Ids start with the date, so entries older than 4 days drop out.
function remembered(){try{return JSON.parse(localStorage.getItem(KEY+'-finals'))||{}}catch(e){return {}}}
function remember(id,score,status){
  try{
    const cut=new Date(Date.now()-4*86400000).toISOString().slice(0,10),all=remembered(),keep={};
    Object.keys(all).forEach(k=>{if(k.slice(0,10)>=cut)keep[k]=all[k];});
    keep[id]={score,status};localStorage.setItem(KEY+'-finals',JSON.stringify(keep));
  }catch(e){}
}
// Every box read feeds both top 15 lists.
function readBox(g,s,when){addNewcomers(g,newcomerLines(g,s,when));g.st.top=topLines(g,s,when);}
// The host's feed has moved on to another game today: ours is over when this page saw it live (before or since a
// reload), or once its expected end has passed. The box score follows through the slate.
function feedMovedOn(g,st,now){const tip=tipMs(g);return !!st.other&&((st.seen&&st.live)||snapLive(st,now)||(!!tip&&now>=tip+GAME_MS));}
async function check(g){
  const st=g.st;let s=null;st.other=false;
  // Every check of an unfinished game reads the full box, so both top 15 lists move with the score.
  try{s=await readFeed(g,!st.final);}catch(e){s=null;}
  const other=st.other;
  // A feed that has never shown this game, after tipoff: the host's other courts, once every RETRY_MS.
  if(!s&&!st.seen&&tipMs(g)&&Date.now()>=tipMs(g)&&!(st.probed&&Date.now()-st.probed<RETRY_MS)){
    st.probed=Date.now();
    for(const p of probeFeeds(g)){
      let t=null;try{t=await readFeed(Object.assign({},g,{feed:p.feed}),!st.final);}catch(e){}
      if(t){g.link=p.link;g.feed=p.feed;s=t;break;}
    }
    st.other=other;
  }
  if(s&&s.complete&&!canBeFinal(g))s=null;
  const now=Date.now();
  if(!s&&feedMovedOn(g,st,now)){st.ended=true;st.live=false;st.noStats=false;st.status='Final pending';}
  if(!s&&!st.seen&&!st.ended&&tipMs(g)&&now>=tipMs(g)+GIVE_UP_MS){st.noStats=true;st.nextAt=null;}
  if(s){
    st.noStats=false;st.snap=null;st.ended=false;
    st.seen=true;st.live=!s.complete;st.score=[s.home,s.away];st.progress=s.progress;
    if(!s.complete)rememberLive(g.id,{home:s.home,away:s.away,status:s.status,at:new Date().toISOString()});
    const lead=s.home-s.away;
    st.wp=s.complete?(lead>0?1:lead<0?0:0.5):winProb(g,lead,s.progress);
    st.status=s.complete?'Final'+(s.period>s.regulation?' (OT)':''):s.status;
    if(s.lines&&!s.complete)readBox(g,s,'live');
    if(s.complete){
      st.final=true;st.live=false;remember(g.id,st.score,st.status);
      if(!st.finalRead){
        let full=s;if(g.feed.type!=='presto'&&!s.lines){try{full=await readFeed(g,true)||s;}catch(e){}}
        st.finalRead=true;readBox(g,full,'final');
      }
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
// The fetcher reads box score pages every 20 minutes on game nights, so an open page rereads its slate for finals,
// box score lines, and scores it cannot read itself.
const SLATE_MS=10*60000;let slateAt=Date.now();
async function refreshSlate(){
  slateAt=Date.now();
  let fresh;try{const r=await fetch('slates/'+night+'.json',{cache:'no-store'});if(!r.ok)return;fresh=await r.json();}catch(e){return;}
  if(fresh.date!==night)return;
  const byId=new Map(fresh.games.map(x=>[x.id,x]));
  games.forEach(g=>{
    const x=byId.get(g.id);if(!x||g.st.final)return;
    // A feed this page has seen the game on stays, even when the slate still names the host's other court.
    ['feed','link','alt_feeds'].forEach(k=>{if(x[k]&&!g.st.seen)g[k]=x[k];});
    ['boxscore','snapshot'].forEach(k=>{if(x[k])g[k]=x[k];});
    if(x.off&&!g.off){g.off=x.off;g.st=initState(g);g.st.nextAt=null;}
    if(x.final){
      Object.assign(g,{final:x.final,box_read:x.box_read,top_lines:x.top_lines||[],newcomer_games:x.newcomer_games||[]});
      const st=initState(g);st.nextAt=null;g.st=st;
    }else if(x.snapshot&&!g.st.live){snapState(g,g.st,x.snapshot);g.st.interest=interest(g,g.st);}
    if(x.feed&&!g.st.nextAt&&!g.st.final&&!g.off)g.st.nextAt=Date.now();
  });
  renderNewcomers();render();
}
async function tick(){
  if(document.hidden||!isToday())return;
  const now=Date.now();
  if(now-slateAt>=SLATE_MS)refreshSlate();
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
// A Division I or II opponent gets its division badge where a D3 team shows its season rank.
function sideTag(g,side){return g.division&&g[side]!==g.d3?'<span class="dv">D'+g.division+'</span>':rank(g[side+'_rank']);}
// tools/make_logos.py writes the files, and its slug() must match this.
function logoSlug(n){return String(n||'').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');}
function logo(n){const f=logoSlug(n);return LOGOS.has(f)?'<img class="lg" src="logos/'+f+'.webp" alt="" width="20" height="20" loading="lazy" decoding="async">':'<span class="lg none" aria-hidden="true">'+esc(String(n||'?')[0])+'</span>';}
function fmtTime(iso){return '<time datetime="'+esc(iso)+'" data-fmt="short"></time>';}
// The newcomer source says "Freshman"; prose uses "First-year". reason_text() in build_site.py matches.
function reasonText(r){return r==='Freshman'?'First-year':r;}
function ago(ms){const m=Math.max(0,Math.round((Date.now()-ms)/60000));return m<1?'just now':m<60?m+'m ago':Math.floor(m/60)+'h '+(m%60)+'m ago';}
function inMin(ms){const m=Math.max(0,Math.round((ms-Date.now())/60000));return m<1?'now':m<60?'in '+m+'m':'in '+Math.floor(m/60)+'h '+(m%60)+'m';}
function winCell(g,st){
  if(st.final||g.division)return '-';
  const home=st.wp>=0.5,p=home?st.wp:1-st.wp,team=home?g.home:g.away;
  // p is at least 0.5 here. A chance that rounds to 100 shows as >99% because the game is not over.
  return esc(team)+' '+(p>=0.995?'>99':Math.round(p*100))+'%';
}
function tags(g,st){
  // Each tag: [class, symbol, words]. Red marks a live game, green a winner, amber an upset, gray a game with nothing left to decide.
  const out=g.label?[['quiet','',g.label.toLowerCase()]]:[];
  const dogWp=g.pregame_wp<0.5?st.wp-g.pregame_wp:(1-st.wp)-(1-g.pregame_wp);
  if(modeled(g)&&dogChance(g)<=UPSET_MAX_DOG&&(st.live||st.final)&&dogWp>0.2)out.push(['upset','\u{1F6A8}',st.final?'upset':'upset alert']);
  if(st.live&&Math.min(st.wp,1-st.wp)>0.3)out.push(['close','\u{1F525}','close']);
  const sw=st.live&&st.score?scoreWp(st.score[0]-st.score[1],st.progress||0):0.5;
  if(st.live&&Math.min(st.wp,1-st.wp)<0.02&&Math.min(sw,1-sw)<SCORE_DECIDED)out.push(['quiet','\u{1F512}','decided']);
  if(!g.division&&Math.max(g.home_tourn,g.away_tourn)<0.005)out.push(['quiet','\u{1F4A4}','no tournament stakes']);
  return out.map(t=>'<span class="tag '+t[0]+'">'+(t[1]?t[1]+'\u00a0':'')+esc(t[2])+'</span>').join('');
}
// A score the fetcher read from a Presto box score page counts as live while it is fresh (SNAP_LIVE_MS): those
// games sat under Not started with a score on the card (Bryn Mawr at SUNY Delhi, 2026-11-08).
const SNAP_LIVE_MS=2*3600000;
function snapLive(st,now){return !!st.snap&&!st.final&&!st.ended&&(now||Date.now())-Date.parse(st.snap.at)<SNAP_LIVE_MS;}
// Take a snapshot into the state: the score, and the win probability from the clock when the status reads like "04:55 Q4".
function snapState(g,st,snap){
  st.snap=snap;st.score=[snap.home,snap.away];
  const m=/^(\d+:\d+)\s+(?:Q(\d+)|OT(\d*))$/.exec(snap.status||'');
  if(m){st.progress=progressOf(m[2]?+m[2]:4+(+m[3]||1),clockToSec(m[1]),4);if(modeled(g))st.wp=winProb(g,snap.home-snap.away,st.progress);}
}
function groupOf(st){return st.live||snapLive(st)?0:(st.final||st.ended)?2:1;}
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
  if(g.off)state=esc(g.off);
  else if(st.final)state=esc(st.status||'Final');
  else if(st.ended)state='Final pending';
  else if(st.live)state='\u{1F534} '+esc(st.status);
  else if(st.snap)state=(snapLive(st)?'\u{1F534} ':'')+esc(st.snap.status)+' \u00b7 '+ago(Date.parse(st.snap.at));
  else state=g.tip?fmtTime(g.tip):'Time TBA';
  const teams=line(g,'away',1)+line(g,'home',0);
  const wc=winCell(g,st),lev=leverage(g),side=['<span class="state">'+state+'</span>'],meta=[];
  if(wc!=='-'){const m=/^(.*) (\S+%)$/.exec(wc);side.push('<span class="wc" title="'+wc+'"><span class="who">'+m[1]+'</span><span class="pct">'+m[2]+'</span></span>');};
  if(!g.division&&lev>0)side.push('<span class="lv" title="Leverage">'+(lev>=15?'⚡ ':'')+'Lev '+lev.toFixed(1)+'</span>');
  const w=tags(g,st);if(w)meta.push(w);
  const label=statsLabel(g,st);if(label)meta.push('<span class="tag quiet">'+esc(label)+'</span>');
  if(g.video&&!st.final)meta.push('<a class="watch" href="'+esc(g.video)+'" target="_blank" rel="noopener">\u{1F4FA} Watch</a>');
  return '<article class="gc '+(st.live||snapLive(st)?'live':st.final?'final':'pre')+'" data-id="'+esc(g.id)+'">'+
    '<div class="ix" title="Interest score" aria-label="Interest score '+I+'"><span class="int">'+I+'</span><span class="bar"><i style="width:'+I+'%"></i></span></div>'+
    (g.link?'<a class="teams" href="'+esc(g.link)+'" target="_blank" rel="noopener">'+teams+'</a>':'<div class="teams">'+teams+'</div>')+
    '<div class="side">'+side.join('')+'</div><button type="button" class="star" aria-pressed="'+starred+'" aria-label="'+(starred?'Remove this game from My Watchlist':'Add this game to My Watchlist')+'" title="'+(starred?'Remove from My Watchlist':'Add to My Watchlist')+'">'+(starred?'\u2605':'\u2606')+'</button>'+
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
  // A starred game appears in My Watchlist and stays in its status group. The My Watchlist button shows the watchlist alone.
  GROUPS.forEach(name=>{
    const d=$('#g-'+name),part=name==='mine'?list.filter(g=>stars.has(g.id)):onlyMine?[]:list.filter(g=>groupOf(g.st)===STATES.indexOf(name));
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
// The opponent's defense factor (D3 average adjusted defense / the opponent's). An opponent outside Division III counts as average.
function defFactor(x){const g=x.game,f=x.team===g.home?g.away_def:x.team===g.away?g.home_def:null;return f||1;}
// The same columns as the season lists build_site.py renders (NC_HEADERS); a test keeps the two in step.
const NC_HEAD='<thead><tr>'+['Player','Team','Class','Points','Rebounds','Assists','Steals plus blocks','Field goals','Game score','Adjusted game score','Game'].map((h,i)=>'<th'+(i<2||i===10?' class="lead"':'')+' role="button" tabindex="0" aria-sort="none">'+h+'</th>').join('')+'</tr></thead>';
function renderLines(id,box,list,empty){
  if(rankCut){list=list.filter(x=>lineRank(x)<=rankCut);if(list.length===0)empty='No player from a top '+rankCut+' team has a line on this night yet.';}
  list.forEach(x=>{x.adj=Math.round(x.gmsc*defFactor(x)*10)/10;});
  list.sort((a,b)=>b.adj-a.adj||b.gmsc-a.gmsc);list.splice(TOP_N);
  const sec=$('#'+id);sec.querySelector('.count').textContent=list.length;
  if(!list.length){$(box).innerHTML='<p class="empty">'+empty+'</p>';return;}
  const rows=list.map(x=>{const l=x.line,g=x.game;
    // td.m repeats the five stat cells as one line; the phone layout shows it in their place.
    return '<tr><td class="lead p">'+esc(x.name)+(x.reason?'<span class="reason">'+esc(reasonText(x.reason))+'</span>':'')+'</td><td class="lead t">'+esc(x.team)+(x.class?'<span class="cls"> · '+esc(x.class)+'</span>':'')+'</td><td class="n">'+esc(x.class||'')+'</td>'+
      '<td class="n">'+l.pts+'</td><td class="n">'+l.reb+'</td><td class="n">'+l.ast+'</td><td class="n">'+(l.stl+l.blk)+'</td><td class="n">'+l.fgm+'-'+l.fga+'</td>'+
      `<td class="m">${l.pts} PTS · ${l.reb} REB · ${l.ast} AST · ${l.stl+l.blk} STL+BLK · ${l.fgm}-${l.fga} FG · ${x.gmsc.toFixed(1)} game score</td>`+
      '<td class="n">'+x.gmsc.toFixed(1)+'</td><td class="gs">'+x.adj.toFixed(1)+'</td><td class="lead gm">'+esc(g.away)+' at '+esc(g.home)+'<span class="reason">'+(x.when==='live'?'Live, '+esc(g.st.status||''):'Final')+'</span></td></tr>';}).join('');
  $(box).innerHTML='<div class="tablewrap"><table class="nc sortable">'+NC_HEAD+'<tbody>'+rows+'</tbody></table></div>';
  if(window.bindSort)$(box).querySelectorAll('table.sortable').forEach(window.bindSort);
}
function renderNewcomers(){
  document.querySelectorAll('.cut').forEach(b=>b.classList.toggle('active',+b.dataset.cut===rankCut));
  const nc=[],top=[];
  games.forEach(g=>{g.st.nc.forEach(x=>nc.push(Object.assign({game:g},x)));g.st.top.forEach(x=>top.push(Object.assign({game:g},x)));});
  renderLines('nc','#newcomers',nc,'No newcomer line has been read on this night yet.');
  renderLines('top','#topgames',top,'No box score has been read on this night yet.');
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
  render();
}
function firstCheck(g,now){
  if(g.st.final||!g.feed||g.off)return null;
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
document.querySelectorAll('.cut').forEach(b=>b.addEventListener('click',()=>{rankCut=+b.dataset.cut;try{localStorage.setItem(KEY+'-cut',rankCut)}catch(err){}renderNewcomers();}));
$('#mine').addEventListener('click',()=>{onlyMine=!onlyMine;$('#mine').setAttribute('aria-pressed',onlyMine);render();});
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
    """Publish each slate with every line's class year filled in (fill_classes)."""
    dest, rosters = OUT.parent / "slates", roster_classes()
    dest.mkdir(parents=True, exist_ok=True)
    for path in SLATES.glob("*.json"):
        slate = fill_classes(json.loads(path.read_text()), rosters)
        (dest / path.name).write_text(json.dumps(slate, separators=(",", ":")) + "\n")


def main():
    copy_slates()
    page = head() + sections() + footer()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page)
    print(f"wrote {OUT} ({len(page)} bytes)")


if __name__ == "__main__":
    main()
