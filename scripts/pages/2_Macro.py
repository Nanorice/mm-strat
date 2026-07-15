"""Macro — Market Regime & Macro. Section 2 (sector/subsector heatmap) is live;
Sections 1 (regime headline) and 3 (indicator board) are ingestion-gated and land
later (see docs/session_logs/sprint_14/plans/dashboard_uplift/macro_page.md).

S2 renders the `sector_breadth` nightly snapshot (sector_breadth_engine): per
sector, today's return distribution (KDE from stored quantiles) + up/down breadth
+ trend/breakout participation + names added today/5d. Click a sector to expand
its subsectors. Native Yahoo/FMP taxonomy; ETF:* excluded; subsectors below the
min-name threshold collapse into an 'Other' card (a KDE over <5 names is a dot).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dashboard_utils import load_sector_breadth
from src.sector_breadth_engine import HIST_LO, HIST_HI, HIST_BINS

MIN_NAMES = 5  # below this a KDE is a dot → collapse into "Other" (plan §S2 constraint 1)


def _sector_payload(df) -> tuple[list[dict], str]:
    """Shape the flat sector_breadth frame into the nested JSON the S2 renderer wants."""
    sec = df[df.grain == "sector"].sort_values("n_names", ascending=False)
    subs = df[df.grain == "subsector"]
    as_of = str(df["as_of_date"].iloc[0])[:10] if len(df) else "—"

    payload = []
    for _, r in sec.iterrows():
        kids = subs[subs.sector == r["name"]].sort_values("n_names", ascending=False)
        payload.append({
            "name": r["name"], "cos": int(r["n_names"]),
            "ret": float(r["ret_median_pct"]),
            "hist": json.loads(r["ret_hist"]),
            "up": int(r["n_up"]), "down": int(r["n_down"]),
            "trend": int(r["n_trend_ok"]), "brk": int(r["n_breakout_ok"]),
            "add1": int(r["trend_added_today"]), "add5": int(r["trend_added_5d"]),
            "subs": [{
                "name": s["name"], "cos": int(s["n_names"]),
                "ret": float(s["ret_median_pct"]),
                "hist": json.loads(s["ret_hist"]),
                "up": int(s["n_up"]), "down": int(s["n_down"]),
                "trend": int(s["n_trend_ok"]), "brk": int(s["n_breakout_ok"]),
            } for _, s in kids.iterrows()],
        })
    return payload, as_of


def _render(df) -> None:
    payload, as_of = _sector_payload(df)
    data_js = json.dumps(payload)
    # CSS + JS lifted from the design mock; SECTORS is injected from the DB and the
    # KDE is drawn from real quantiles (mock faked a bell). f-string: literal braces
    # are doubled; {data_js}/{as_of}/{MIN_NAMES} are the only interpolations.
    html = f"""
<style>
  :root{{--background:#fcfbf8;--foreground:#1c1a17;--muted:#8a8272;--border:#e8e3d6;
    --accent:#6b6a3a;--rust:#a5542f;--positive:#3f7d4e;--negative:#b23b3b;
    --warn:#b9862e;--card:#fffefb;}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--background);color:var(--foreground);
    font-family:"Source Serif 4",Georgia,serif;font-size:15px;line-height:1.5}}
  .mono{{font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-variant-numeric:tabular-nums}}
  .sub{{color:var(--muted);font-size:13px}}
  .pos{{color:var(--positive)}} .neg{{color:var(--negative)}}
  .sectitle{{font-family:"JetBrains Mono",monospace;font-size:11px;letter-spacing:.18em;
    text-transform:uppercase;color:var(--muted);margin:6px 0 14px;
    border-bottom:1px solid var(--border);padding-bottom:8px}}
  .card{{background:var(--card);border:1px solid var(--border);border-radius:6px;padding:14px}}
  .heat{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
  .scard{{cursor:pointer;transition:border-color .12s}}
  .scard:hover{{border-color:var(--accent)}}
  .scard .row1{{display:flex;justify-content:space-between;align-items:baseline}}
  .scard .name{{font-size:15px;font-weight:600}}
  .scard .ret{{font-family:"JetBrains Mono",monospace;font-size:17px;font-weight:600}}
  .kde{{margin:8px 0 6px}}
  .breadth{{display:flex;font-size:11px;justify-content:space-between;color:var(--muted);
    font-family:"JetBrains Mono",monospace}}
  .partbar{{height:6px;border-radius:3px;overflow:hidden;display:flex;margin-top:6px;background:#ece4d4}}
  .partbar i{{display:block;height:100%}}
  .addnote{{font-size:11px;color:var(--muted);margin-top:6px;font-family:"JetBrains Mono",monospace}}
  .subrow{{grid-column:1/-1;background:#f4f1e8;border:1px solid var(--border);
    border-radius:6px;padding:12px;display:none}}
  .subrow.open{{display:block}}
  .subgrid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:8px}}
  .subhdr{{font-family:"JetBrains Mono",monospace;font-size:11px;letter-spacing:.1em;
    color:var(--accent);text-transform:uppercase}}
</style>

<div class="sectitle">2 · Sector / subsector heatmap
  <span class="sub" style="text-transform:none;letter-spacing:0"> — as of {as_of} · click a sector to expand subsectors</span></div>
<div class="heat" id="heat"></div>

<script>
const SECTORS = {data_js};
const MIN_NAMES = {MIN_NAMES};
const H_LO={HIST_LO}, H_HI={HIST_HI}, H_BINS={HIST_BINS};  // fixed return-bin axis (%)

// Density from the real per-name return histogram: one filled area over fixed
// bins (shared x-axis across cards). A light 3-tap smooth softens the staircase.
// today's median = solid marker; 0% = dashed reference.
function kde(hist, med){{
  const w=180,h=42,pad=4, n=hist.length;
  const X=v=>pad+((Math.max(H_LO,Math.min(H_HI,v))-H_LO)/(H_HI-H_LO))*(w-2*pad);
  const sm=hist.map((_,i)=>(hist[Math.max(0,i-1)]+2*hist[i]+hist[Math.min(n-1,i+1)])/4);
  const maxd=Math.max(...sm)||1;
  const bx=i=>pad+(i/(n-1))*(w-2*pad);
  let d=`M ${{pad}} ${{h-pad}}`;
  sm.forEach((v,i)=>{{d+=` L ${{bx(i).toFixed(1)}} ${{(h-pad-(v/maxd)*(h-2*pad)).toFixed(1)}}`;}});
  d+=` L ${{w-pad}} ${{h-pad}} Z`;
  const col=med>=0?"var(--positive)":"var(--negative)";
  const mx=X(med), zx=X(0);
  return `<svg class="kde" width="${{w}}" height="${{h}}" viewBox="0 0 ${{w}} ${{h}}">
    <path d="${{d}}" fill="${{col}}" fill-opacity=".14" stroke="${{col}}" stroke-width="1.3" opacity=".85"/>
    <line x1="${{zx}}" y1="6" x2="${{zx}}" y2="${{h-pad}}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="2 2" opacity=".5"/>
    <line x1="${{mx}}" y1="4" x2="${{mx}}" y2="${{h-pad}}" stroke="${{col}}" stroke-width="2"/>
  </svg>`;
}}
function sclass(r){{return r>=0?"pos":"neg"}}
function sign(r){{return (r>=0?"+":"")+r.toFixed(2)+"%"}}

function scard(s,isSub){{
  const partT=(s.trend/s.cos*100), partB=(s.brk/s.cos*100);
  return `<div class="card scard" ${{isSub?"":`onclick="toggle(this)"`}} data-name="${{s.name}}">
    <div class="row1"><span class="name">${{s.name}}</span><span class="ret ${{sclass(s.ret)}}">${{sign(s.ret)}}</span></div>
    <div class="sub mono">${{s.cos}} names</div>
    ${{kde(s.hist,s.ret)}}
    <div class="breadth"><span class="pos">▲${{s.up}}</span><span class="neg">▼${{s.down}}</span></div>
    <div class="partbar" title="trend_ok / breakout_ok">
      <i style="width:${{partT}}%;background:var(--accent)"></i>
      <i style="width:${{partB}}%;background:var(--rust)"></i></div>
    ${{isSub?"":`<div class="addnote">trend ${{s.trend}} · brk ${{s.brk}} · +${{s.add1}} today · +${{s.add5}} 5d</div>`}}
  </div>`;
}}

function render(){{
  let html='';
  SECTORS.forEach((s,i)=>{{
    html+=scard(s,false);
    const big=s.subs.filter(x=>x.cos>=MIN_NAMES);
    const small=s.subs.filter(x=>x.cos<MIN_NAMES);
    let subs=big.map(x=>scard(x,true)).join('');
    if(small.length){{
      const merged=Array(H_BINS).fill(0);
      small.forEach(x=>x.hist.forEach((c,j)=>merged[j]+=c));
      // representative center = count-weighted mean of bin centers.
      const bw=(H_HI-H_LO)/H_BINS, tot=merged.reduce((a,c)=>a+c,0)||1;
      const ctr=merged.reduce((a,c,j)=>a+c*(H_LO+(j+0.5)*bw),0)/tot;
      const roll=k=>small.reduce((a,x)=>a+x[k],0);
      subs+=scard({{name:`Other (${{small.length}})`,cos:roll('cos'),ret:ctr,hist:merged,
        up:roll('up'),down:roll('down'),trend:roll('trend'),brk:roll('brk')}},true);
    }}
    html+=`<div class="subrow" id="sub-${{i}}">
      <div class="subhdr">${{s.name}} — subsectors</div>
      <div class="subgrid">${{subs||'<span class=sub>no subsectors</span>'}}</div></div>`;
  }});
  document.getElementById('heat').innerHTML=html;
}}
function toggle(el){{
  const cards=[...document.querySelectorAll('#heat > .scard')];
  const i=cards.indexOf(el);
  if(i>=0) document.getElementById('sub-'+i).classList.toggle('open');
}}
render();
</script>
"""
    components.html(html, height=1400, scrolling=True)


st.markdown("### Market Regime & Macro")
st.caption("Where to deploy, and whether to deploy at all. "
           "S1 regime headline & S3 indicator board land after macro ingestion.")

df = load_sector_breadth()
if df is None or df.empty:
    st.info("sector_breadth snapshot not found — run "
            "`python -c \"from src.sector_breadth_engine import SectorBreadthEngine; "
            "SectorBreadthEngine().refresh()\"` (or the nightly pipeline Phase 7.46).")
else:
    _render(df)
