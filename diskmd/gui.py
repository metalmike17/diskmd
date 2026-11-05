"""Local web GUI: a tiny stdlib HTTP server on 127.0.0.1, protected by a random token.

The server runs as you. Each scan runs `diskmd --json` through pkexec (graphical password
prompt) so the GUI itself never has root.
"""
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import bench as bench_mod, cli, history, probe, window

PAGE = r"""<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>diskmd</title><style>
:root{--ink:#0D0F14;--panel:#12151C;--cyan:#00C8D6;--mag:#FF2BD6;--ok:#2BFFB0;--watch:#FFC145;--warn:#FF2BD6;--fail:#FF4D6D;
--fg:#E6EBF2;--dim:#A9B4C2;--mono:"JetBrains Mono","Fira Code","DejaVu Sans Mono",ui-monospace,monospace}
*{box-sizing:border-box}html{background:var(--ink)}
body{margin:0;min-height:100vh;color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;background-attachment:fixed;
background:radial-gradient(900px 520px at 6% -8%,rgba(0,200,214,.22),transparent 62%),radial-gradient(820px 540px at 102% 2%,rgba(255,43,214,.16),transparent 62%),
radial-gradient(760px 520px at 50% 118%,rgba(43,255,176,.11),transparent 62%),var(--ink);background-attachment:fixed}
body:before{content:"";position:fixed;inset:0;pointer-events:none;z-index:9;background:repeating-linear-gradient(0deg,rgba(255,255,255,.022) 0 1px,transparent 1px 3px)}
header{position:sticky;top:0;z-index:5;display:flex;flex-wrap:wrap;align-items:center;gap:10px 18px;padding:16px 28px;background:rgba(13,15,20,.5);
-webkit-backdrop-filter:blur(26px) saturate(170%);backdrop-filter:blur(26px) saturate(170%);border-bottom:1px solid rgba(0,200,214,.38);box-shadow:inset 0 1px 0 rgba(255,255,255,.06)}
h1{margin:0;font:800 20px var(--mono);letter-spacing:.45em;color:#F2F4F8;text-shadow:0 0 10px rgba(0,200,214,.95),0 0 30px rgba(0,200,214,.45)}
.sub{color:var(--cyan);font:12px var(--mono);letter-spacing:.16em;text-transform:uppercase}
#sum{margin-left:auto;white-space:nowrap;color:var(--dim);font:13px var(--mono)}
button{color:var(--cyan);font:600 13px var(--mono);letter-spacing:.06em;padding:9px 18px;border-radius:999px;cursor:pointer;border:1px solid rgba(0,200,214,.7);
background:linear-gradient(180deg,rgba(0,200,214,.26),rgba(0,200,214,.08));box-shadow:inset 0 1px 0 rgba(255,255,255,.25),0 0 18px rgba(0,200,214,.22);
transition:transform .25s cubic-bezier(.2,.9,.3,1.4),box-shadow .25s,background .25s}
button:hover{transform:scale(1.05);box-shadow:inset 0 1px 0 rgba(255,255,255,.35),0 0 26px rgba(0,200,214,.5)}
button:active{transform:scale(.97)}button:disabled{opacity:.45;cursor:wait;transform:none}#rep{margin-left:-6px}
main{display:grid;grid-template-columns:repeat(auto-fill,minmax(390px,1fr));gap:22px;padding:28px}
.card{position:relative;overflow:hidden;padding:20px 22px;border-radius:22px;border:1px solid rgba(255,255,255,.09);border-top-color:rgba(255,255,255,.22);
background:linear-gradient(155deg,rgba(255,255,255,.085),rgba(255,255,255,.025) 38%,rgba(18,21,28,.6));
-webkit-backdrop-filter:blur(24px) saturate(180%);backdrop-filter:blur(24px) saturate(180%);
box-shadow:0 14px 44px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,255,255,.14),0 0 0 1px color-mix(in srgb,var(--c) 16%,transparent),0 0 34px color-mix(in srgb,var(--c) 13%,transparent);
transition:transform .4s cubic-bezier(.2,.9,.3,1.35),box-shadow .4s;animation:rise .7s cubic-bezier(.2,.9,.3,1) both}
.card:nth-child(2){animation-delay:.06s}.card:nth-child(3){animation-delay:.12s}.card:nth-child(4){animation-delay:.18s}.card:nth-child(n+5){animation-delay:.24s}
.card:before{content:"";position:absolute;top:0;left:14%;right:14%;height:2px;background:linear-gradient(90deg,transparent,var(--c),transparent);box-shadow:0 0 16px var(--c)}
.card:hover{transform:translateY(-5px) scale(1.012);box-shadow:0 22px 60px rgba(0,0,0,.55),inset 0 1px 0 rgba(255,255,255,.2),0 0 0 1px color-mix(in srgb,var(--c) 40%,transparent),0 0 48px color-mix(in srgb,var(--c) 28%,transparent)}
@keyframes rise{from{opacity:0;transform:translateY(18px) scale(.97)}}
.top{display:flex;justify-content:space-between;align-items:center;gap:10px}.name{font:700 17px var(--mono);letter-spacing:.04em}
.badge{font:700 11px var(--mono);letter-spacing:.14em;color:var(--c);padding:3px 11px;border-radius:999px;border:1px solid color-mix(in srgb,var(--c) 65%,transparent);
background:color-mix(in srgb,var(--c) 13%,transparent);text-shadow:0 0 10px var(--c);box-shadow:0 0 14px color-mix(in srgb,var(--c) 25%,transparent)}
.model{color:var(--dim);font-size:13px;margin:3px 0 14px}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:12px}
.stat b{display:block;font:600 17px var(--mono);color:#fff}.stat small{color:var(--cyan);font:11px var(--mono);letter-spacing:.1em;text-transform:uppercase;opacity:.85}
.bar{height:7px;background:rgba(255,255,255,.07);border-radius:4px;overflow:hidden;margin:4px 0 14px;box-shadow:inset 0 1px 2px rgba(0,0,0,.5)}
.bar i{display:block;height:100%;border-radius:4px;background:linear-gradient(90deg,var(--cyan),var(--c));box-shadow:0 0 12px var(--c)}
ul{margin:8px 0 0;padding-left:18px}li{margin:3px 0}.issue{color:var(--c2);text-shadow:0 0 12px color-mix(in srgb,var(--c2) 35%,transparent)}.note{color:var(--dim);font-size:13px}
.chg{color:var(--watch);font:12px var(--mono);margin-top:10px}.same{color:var(--dim);font:12px var(--mono);margin-top:10px;opacity:.8}
.spark{display:flex;align-items:center;gap:10px;color:var(--dim);font:11px var(--mono);margin-top:10px}.spark svg{flex:none;filter:drop-shadow(0 0 4px rgba(0,200,214,.7))}
.trend{color:var(--ok);font:12px var(--mono);margin-top:8px}
#toast{position:fixed;left:50%;bottom:26px;transform:translate(-50%,30px);opacity:0;z-index:20;padding:12px 22px;border-radius:999px;
font:13px var(--mono);color:#fff;background:rgba(13,15,20,.8);border:1px solid var(--cyan);box-shadow:0 0 28px rgba(0,200,214,.4);
-webkit-backdrop-filter:blur(20px);backdrop-filter:blur(20px);transition:all .4s cubic-bezier(.2,.9,.3,1.3);pointer-events:none}
#toast.on{opacity:1;transform:translate(-50%,0)}
.st{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-top:12px;padding-top:12px;border-top:1px solid rgba(255,255,255,.08);color:var(--dim);font:12px var(--mono)}
.st .bad{color:var(--fail)}.btns{display:flex;gap:6px}.mini{padding:4px 11px;font-size:11px}
.card{cursor:pointer}main.detail{display:block;max-width:1180px;margin:0 auto}
.panel{margin:0 0 20px;padding:20px 24px;border-radius:22px;border:1px solid rgba(255,255,255,.09);border-top-color:rgba(255,255,255,.22);
background:linear-gradient(155deg,rgba(255,255,255,.075),rgba(255,255,255,.02) 40%,rgba(18,21,28,.6));-webkit-backdrop-filter:blur(24px) saturate(180%);backdrop-filter:blur(24px) saturate(180%);
box-shadow:0 14px 44px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,255,255,.12);animation:rise .6s cubic-bezier(.2,.9,.3,1) both}
.panel h2{margin:0 0 14px;font:700 12px var(--mono);letter-spacing:.22em;text-transform:uppercase;color:var(--cyan)}
.dhead{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:20px}.dhead .name{font-size:24px}.dhead .model{margin:0;flex:1}
.facts{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:14px 22px}
.fact small{display:block;color:var(--cyan);font:11px var(--mono);letter-spacing:.1em;text-transform:uppercase;opacity:.85}.fact b{font:600 15px var(--mono);word-break:break-all}
.charts{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:18px}
.chart{padding:12px 14px;border-radius:14px;background:rgba(0,0,0,.25);border:1px solid rgba(255,255,255,.06)}
.ch{display:flex;justify-content:space-between;font:11px var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--dim);margin-bottom:6px}.ch span{color:#fff}
.chart svg{width:100%;height:90px;display:block;filter:drop-shadow(0 0 5px rgba(0,200,214,.5))}.cx{display:flex;justify-content:space-between;font:10px var(--mono);color:var(--dim);margin-top:4px}
.tbl{width:100%;border-collapse:collapse;font-size:13px}.tbl th{text-align:left;color:var(--cyan);font:11px var(--mono);letter-spacing:.1em;text-transform:uppercase;padding:6px 10px;border-bottom:1px solid rgba(255,255,255,.1)}
.tbl td{padding:8px 10px;border-bottom:1px solid rgba(255,255,255,.05);vertical-align:top;font-family:var(--mono)}.tbl tr.bad td{color:var(--fail)}
.hp{font:12px system-ui,sans-serif;color:var(--dim);margin-top:2px;max-width:640px}.tbl tr.bad .hp{color:var(--fail)}
.prow{padding:10px 0;border-bottom:1px solid rgba(255,255,255,.06)}.prow:last-child{border:0}.prow .pt{display:flex;justify-content:space-between;gap:10px;font:13px var(--mono);margin-bottom:6px}
.pbar{height:6px;border-radius:3px;background:rgba(255,255,255,.07);overflow:hidden}.pbar i{display:block;height:100%;background:linear-gradient(90deg,var(--cyan),var(--ok));box-shadow:0 0 10px var(--cyan)}
.brun{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:12px 0}select{background:#12151C;color:var(--fg);border:1px solid rgba(0,200,214,.5);border-radius:999px;padding:8px 14px;font:13px var(--mono)}
.warnbox{font-size:13px;color:var(--watch);margin:6px 0 4px}.code{font:13px var(--mono);background:rgba(0,0,0,.35);padding:2px 8px;border-radius:6px;color:var(--ok)}
.prog{height:8px;border-radius:4px;background:rgba(255,255,255,.07);overflow:hidden;margin:12px 0 6px}.prog i{display:block;height:100%;background:linear-gradient(90deg,var(--cyan),var(--mag));box-shadow:0 0 14px var(--cyan);transition:width .5s}
.big{font:700 20px var(--mono);color:#fff}.link{color:var(--cyan);cursor:pointer}
#msg{padding:48px 28px;color:var(--cyan);font:13px var(--mono);letter-spacing:.14em;text-transform:uppercase;white-space:pre-wrap;animation:pulse 1.4s ease-in-out infinite}
@keyframes pulse{50%{opacity:.4}}
::-webkit-scrollbar{width:10px}::-webkit-scrollbar-thumb{background:rgba(0,200,214,.45);border-radius:5px}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style><header><h1>DISKMD</h1><span class=sub>// drive health, in plain English</span><div id=sum></div><button id=go>Rescan</button><button id=rep>Copy report</button></header>
<svg width=0 height=0 style=position:absolute><defs><linearGradient id=cg x1=0 y1=0 x2=0 y2=1><stop offset=0 stop-color="#00C8D6" stop-opacity=.35 /><stop offset=1 stop-color="#00C8D6" stop-opacity=0 /></linearGradient></defs></svg><div id=toast></div><div id=msg>// scanning drives... enter your password in the dialog (check behind this window)</div><main id=out></main><script>
const T=new URLSearchParams(location.search).get('t'),C={0:'--ok',1:'--watch',2:'--warn',3:'--fail'},$=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const size=n=>n>=1e12?(n/1e12).toFixed(1)+' TB':(n/1e9).toFixed(0)+' GB';
const life=y=>y==null?'-':y>=10?'10+ yrs':y>=2?'~'+Math.round(y)+' yrs':'~'+Math.round(y*12)+' mo';
function spark(pts,label,fmt){const v=pts.filter(x=>x!=null);if(v.length<3)return'';
 const lo=Math.min(...v),hi=Math.max(...v),r=hi-lo||1,w=120,h=26,xy=v.map((y,i)=>[i*w/(v.length-1),h-2-(y-lo)/r*(h-4)]);
 return `<div class=spark><svg width=${w} height=${h}><polyline fill=none stroke="#00C8D6" stroke-width=1.6 points="${xy.map(p=>p.join(',')).join(' ')}"/>
 <circle cx=${xy.at(-1)[0]} cy=${xy.at(-1)[1]} r=2.5 fill="#fff"/></svg>${label}: ${fmt(lo)}–${fmt(hi)} over ${v.length} checks</div>`}
const ago=h=>h==null?'':h<48?h+' h ago':Math.round(h/24)+' days ago';
function stest(d){const s=d.selftest;if(!s)return'';const m=s.minutes||{},l=s.last;
 const txt=s.running!=null?`Self-test running (${s.running}% left) - rescan to update`:l?`Last self-test: ${l.type}, ${l.result}${l.hours_ago!=null?' · '+ago(l.hours_ago):''}`:'No self-test run yet';
 const b=(t,label,min)=>`<button class=mini data-dev="${esc(d.name)}" data-t=${t}>${label}${min?' · ~'+min+' min':''}</button>`;
 return `<div class=st><span class="${l&&l.passed===false?'bad':''}">${esc(txt)}</span><span class=btns>${b('short','Short test',m.short)}${b('long','Extended',m.long)}</span></div>`}
function card(d){const c=`var(${C[d.level]})`,kind={nvme:'NVMe',ssd:'SSD',hdd:'HDD'}[d.kind]+(d.usb?' · USB':'');
 const top=d.wear_pct==null&&d.written_tb==null?[['Bad sectors',d.reallocated],['Pending',d.pending],['CRC errors',d.crc_errors]]
  :[['Wear',d.wear_pct==null?'-':d.wear_pct+'%'],['Written',d.written_tb==null?'-':d.written_tb.toFixed(1)+' TB'],['Est. life left',life(d.years_left)]];
 const st=[...top,
  ['Temp',d.temp_c==null?'-':d.temp_c+'°C'],['Power-on',d.hours==null?'-':d.hours.toLocaleString()+' h'],['Capacity',size(d.size_bytes)]];
 const iss=d.issues.map(([l,t])=>`<li class=issue style="--c2:var(${C[l]})">${esc(t)}</li>`).join('')+d.notes.map(t=>`<li class=note>${esc(t)}</li>`).join('');
 const when=d.days_since==null?'':d.days_since<1?'today':Math.round(d.days_since)+' days ago';
 const chg=d.days_since==null?'':d.changes.length?`<div class=chg>Since last check (${when}): ${esc(d.changes.join(', '))}</div>`:`<div class=same>No changes since last check (${when})</div>`;
 return `<div class=card data-name="${esc(d.name)}" style="--c:${c}"><div class=top><span class=name>${esc(d.name)}</span><span class=badge>${esc(d.verdict)}</span></div>
 <div class=model>${esc(d.model)} · ${kind}${d.link?' · '+esc(d.link.summary):''}</div>${d.wear_pct==null?'':`<div class=bar><i style="width:${Math.min(d.wear_pct,100)}%"></i></div>`}
 <div class=stats>${st.map(([k,v])=>`<div class=stat><b>${v}</b><small>${k}</small></div>`).join('')}</div>${iss?`<ul>${iss}</ul>`:''}${spark(d.series.map(p=>p[1]),'Temp',x=>x+'°C')}${trend(d)}${chg}${stest(d)}</div>`}
function trend(d){if(d.trend_years_left==null)return'';const y=d.trend_years_left;
 return `<div class=trend>At your recent write rate: ${y>=10?'10+ years':y>=2?'~'+Math.round(y)+' years':'~'+Math.round(y*12)+' months'} left</div>`}
let DATA=[];
const api=async p=>(await fetch(p+(p.includes('?')?'&':'?')+'t='+T)).json();
const post=async(p,b)=>(await fetch(p+'?t='+T,{method:'POST',body:JSON.stringify(b||{})})).json();
const fmtDate=ts=>new Date(ts*1000).toLocaleDateString(undefined,{month:'short',day:'numeric'});
function chart(pts,i,label,fmt){const p=pts.filter(x=>x[i]!=null);if(p.length<2)return'';
 const W=420,H=110,P=6,xs=p.map(x=>x[0]),ys=p.map(x=>x[i]),x0=Math.min(...xs),x1=Math.max(...xs),y0=Math.min(...ys),y1=Math.max(...ys),yr=(y1-y0)||1,xr=(x1-x0)||1;
 const xy=p.map(x=>[P+(x[0]-x0)/xr*(W-2*P),y1===y0?H/2:H-P-(x[i]-y0)/yr*(H-2*P)]),line=xy.map(a=>a.map(n=>n.toFixed(1)).join(',')).join(' ');
 return `<div class=chart><div class=ch>${label}<span>${fmt(y0)===fmt(y1)?fmt(y0):fmt(y0)+' – '+fmt(y1)}</span></div><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio=none><polygon points="${P},${H-P} ${line} ${W-P},${H-P}" fill="url(#cg)"/><polyline points="${line}" fill=none stroke="#00C8D6" stroke-width=2 vector-effect=non-scaling-stroke /></svg><div class=cx><span>${fmtDate(x0)}</span><span>${fmtDate(x1)}</span></div></div>`}
const fact=(k,v)=>`<div class=fact><small>${k}</small><b>${v}</b></div>`;
function smartTable(d){if(!d.smart_table.length)return'<p class=note>This drive reported no SMART attributes.</p>';const ata=d.smart_table[0].id!=null;
 const hp=r=>r.help?`<div class=hp>${esc(r.help)}</div>`:'';
 return '<table class=tbl>'+(ata?'<tr><th>ID<th>Attribute<th>Value<th>Worst<th>Thresh<th>Raw':'<tr><th>Item<th>Value')+d.smart_table.map(r=>ata
  ?`<tr class="${r.failing?'bad':''}"><td>${r.id}<td>${esc(r.name)}${hp(r)}<td>${r.value??''}<td>${r.worst??''}<td>${r.thresh??''}<td>${esc(r.raw)}`
  :`<tr><td>${esc(r.name)}${hp(r)}<td>${esc(r.raw)}`).join('')+'</table>'}
function partsHtml(d){if(!d.partitions.length)return'<p class=note>No partitions found.</p>';
 return d.partitions.map(p=>{const tot=p.used!=null?p.used+p.free:0,pc=tot?Math.round(p.used/tot*100):null;
  return `<div class=prow><div class=pt><span>${esc(p.name)} · ${esc(p.fstype||'no filesystem')}${p.label?' · '+esc(p.label):''}</span><span>${size(p.size)}${pc!=null?` · ${pc}% used`:''}</span></div>${pc!=null?`<div class=pbar><i style="width:${pc}%"></i></div>`:''}<div class=hp>${p.mounts.length?'Mounted at '+p.mounts.map(esc).join(', '):'Not mounted'}</div></div>`}).join('')}
function detail(d){const c=`var(${C[d.level]})`,kind={nvme:'NVMe SSD',ssd:'SATA SSD',hdd:'Hard drive'}[d.kind]+(d.usb?' (USB)':'');
 const iss=d.issues.map(([l,t])=>`<li class=issue style="--c2:var(${C[l]})">${esc(t)}</li>`).join('')+d.notes.map(t=>`<li class=note>${esc(t)}</li>`).join('');
 const ev=(d.io_errors||d.link_resets)?`<p>${d.io_errors} kernel I/O errors and ${d.link_resets} link resets in the last 7 days.</p>${d.kernel_samples.map(x=>`<div class=hp><span class=code>${esc(x)}</span></div>`).join('')}`:'<p class=note>No kernel I/O errors or link resets in the last 7 days.</p>';
 const sr=d.series;
 const charts=chart(sr,1,'Temperature',x=>x+'°C')+chart(sr,2,'Wear',x=>x+'%')+chart(sr,3,'Written',x=>x.toFixed(2)+' TB');
 return `<div class=dhead style="--c:${c}"><button data-act=back>← All drives</button><span class=name>${esc(d.name)}</span><span class=badge style="--c:${c}">${esc(d.verdict)}</span><span class=model>${esc(d.model)}</span></div>
 <section class=panel><h2>Overview</h2><div class=facts>${fact('Model',esc(d.model))}${fact('Type',kind)}${fact('Capacity',size(d.size_bytes))}${fact('Firmware',esc(d.firmware||'-'))}
  ${fact('Connection',esc(d.link?d.link.summary:d.usb?'USB':'-'))}${fact('Temperature',d.temp_c==null?'-':d.temp_c+'°C')}${fact('Power-on',d.hours==null?'-':d.hours.toLocaleString()+' h')}
  ${fact('Power cycles',d.power_cycles==null?'-':d.power_cycles.toLocaleString())}${fact('Wear',d.wear_pct==null?'n/a':d.wear_pct+'%')}${fact('Written',d.written_tb==null?'n/a':d.written_tb.toFixed(1)+' TB')}
  ${fact('Est. life left',life(d.years_left))}${fact('Serial',`<span id=serial data-s="${esc(d.serial||'')}">••••••••</span> <button class=mini data-act=reveal>Reveal</button>`)}</div></section>
 <section class=panel><h2>What diskmd found</h2>${iss?`<ul>${iss}</ul>`:'<p class=note>Nothing to report: all counters look normal.</p>'}${stest(d)}</section>
 <section class=panel><h2>History</h2>${charts?`<div class=charts>${charts}</div>`:'<p class=note>Charts appear after a few scans. Install the daily timer (diskmd --install-timer) to build history automatically.</p>'}</section>
 <section class=panel><h2>Partitions and space</h2>${partsHtml(d)}</section>
 <section class=panel><h2>Kernel events</h2>${ev}</section>
 <section class=panel><h2>Speed test</h2><div id=bench data-dev="${esc(d.name)}"><p class=note>Loading...</p></div></section>
 <section class=panel><h2>SMART data</h2>${smartTable(d)}</section>`}
function benchTable(res){const labels=[...new Set(res.map(r=>r.label))];
 const cell=x=>x?`<b>${x.mbps.toLocaleString()} MB/s</b><div class=hp>${x.iops.toLocaleString()} IOPS · ${x.lat_us} µs</div>`:'<span class=note>…</span>';
 return '<table class=tbl><tr><th>Test<th>Read<th>Write'+labels.map(l=>`<tr><td>${l}<td>${cell(res.find(x=>x.label===l&&x.rw==='read'))}<td>${cell(res.find(x=>x.label===l&&x.rw==='write'))}`).join('')+'</table>'}
async function benchUI(dev){const el=$('bench');if(!el||el.dataset.dev!==dev)return;
 const [s,h]=await Promise.all([api('/api/bench/status'),api('/api/bench/history?dev='+dev)]);const el2=$('bench');if(!el2||el2.dataset.dev!==dev)return;
 const mine=s.dev===dev,run=s.running&&mine;let html='';
 if(!s.fio)html+=`<p class=warnbox>The speed test uses <b>fio</b>, which isn't installed. Install it with <span class=code>${esc(s.hint)}</span> then reopen this page.</p>`;
 else if(s.running&&!mine)html+=`<p class=note>A speed test is running on ${esc(s.dev)}.</p>`;
 else html+=`<div class=brun>${run?`<button data-act=bench-cancel>Cancel</button>`:`<select id=bsize><option value=256>256 MB</option><option value=512>512 MB</option><option value=1024 selected>1 GiB</option><option value=4096>4 GiB</option></select><button data-act=bench-run>Run speed test</button>`}${s.kdiskmark?'<button data-act=bench-kdm>Open KDiskMark</button>':''}</div>
 <p class=warnbox>Writes one temporary file on this drive's filesystem, then deletes it. It never touches the raw device. On SSDs it adds a little wear (a few GB).</p>`;
 if(mine&&s.error)html+=`<p class=issue style="--c2:var(--fail)">${esc(s.error)}</p>`;
 if(run)html+=`<div class=prog><i style="width:${Math.round(s.step/s.total*100)}%"></i></div><div class=note>Running ${esc(s.label)} (${s.step+1}/${s.total})...</div>`;
 if(mine&&s.results.length)html+=benchTable(s.results)+(s.note?`<p class=note>${esc(s.note)}</p>`:'');
 const hist=(mine&&s.results.length&&!run)?h.slice(0,-1):h;
 if(hist.length&&!run){const best=r=>{const f=(l,w)=>r.results.find(x=>x.label===l&&x.rw===w);return[f('SEQ1M Q8T1','read'),f('SEQ1M Q8T1','write'),f('RND4K Q1T1','read')].map(x=>x?x.mbps.toLocaleString():'-')};
  html+='<h2 style="margin-top:18px">Previous tests</h2><table class=tbl><tr><th>Date<th>Size<th>Seq read<th>Seq write<th>4K Q1 read'+hist.slice().reverse().map(r=>`<tr><td>${fmtDate(r.ts)}<td>${r.size_mb} MB${best(r).map(v=>`<td>${v} MB/s`).join('')}`).join('')+'</table>'}
 el2.innerHTML=html;if(run)setTimeout(()=>{if(location.hash==='#/drive/'+dev)benchUI(dev)},1000)}
function route(){const m=location.hash.match(/^#\/drive\/(.+)$/),main=$('out');
 if(m&&DATA.length){const d=DATA.find(x=>x.name===decodeURIComponent(m[1]));if(d){main.className='detail';main.innerHTML=detail(d);window.scrollTo(0,0);benchUI(d.name);return}}
 main.className='';main.innerHTML=DATA.map(card).join('')}
window.onhashchange=route;
async function act(a){const k=a.dataset.act,dev=($('bench')||{dataset:{}}).dataset.dev;
 if(k==='back')location.hash='';
 else if(k==='reveal'){const e=$('serial');e.textContent=e.textContent.includes('•')?(e.dataset.s||'unknown'):'••••••••';a.textContent=e.textContent.includes('•')?'Reveal':'Hide'}
 else if(k==='bench-run'){const j=await post('/api/bench/start',{dev,size_mb:+$('bsize').value});if(!j.ok)toast(j.message);benchUI(dev)}
 else if(k==='bench-cancel'){await post('/api/bench/cancel');toast('Cancelling...');benchUI(dev)}
 else if(k==='bench-kdm'){const j=await post('/api/bench/kdiskmark');toast(j.message)}}
let REPORT='';async function scan(){$('go').disabled=true;$('msg').textContent='// scanning drives... enter your password in the dialog (check behind this window)';$('msg').hidden=false;
 try{const r=await fetch('/api/scan?t='+T),j=await r.json();if(j.error)throw new Error(j.error);
  REPORT=j.report;DATA=j.drives;route();$('msg').hidden=true;const w=Math.max(0,...j.drives.map(d=>d.level));
  $('sum').textContent=j.drives.length+' drives'+(w?'':' · all healthy')+(j.skipped?` · ${j.skipped} without SMART data`:'');}
 catch(e){$('out').innerHTML='';$('msg').textContent='Scan failed: '+e.message}$('go').disabled=false}
$('rep').onclick=async()=>{try{await navigator.clipboard.writeText(REPORT);$('rep').textContent='Copied!'}catch(e){prompt('Copy your report:',REPORT)}setTimeout(()=>$('rep').textContent='Copy report',1500)};
const toast=t=>{const e=$('toast');e.textContent=t;e.classList.add('on');setTimeout(()=>e.classList.remove('on'),5200)};
$('out').onclick=async e=>{const a=e.target.closest('[data-act]');if(a)return act(a);const b=e.target.closest('button.mini[data-t]');
 if(!b){const c=e.target.closest('.card[data-name]');if(c)location.hash='#/drive/'+encodeURIComponent(c.dataset.name);return}const dev=b.dataset.dev,type=b.dataset.t;
 if(!confirm(`Start a ${type==='short'?'short':'extended'} SMART self-test on ${dev}?\nIt is read-only and the drive stays usable (extended tests can be slower).`))return;
 b.disabled=true;try{const r=await fetch('/api/selftest?t='+T,{method:'POST',body:JSON.stringify({dev,type})}),j=await r.json();
  toast(j.ok?`${j.message}${j.minutes?' - about '+j.minutes+' min. Press Rescan afterwards.':''}`:'Could not start test: '+j.message)}
 catch(err){toast('Could not start test: '+err.message)}b.disabled=false};
$('go').onclick=scan;scan();
</script></html>"""


def _run_root(args):
    """Run `diskmd <args> --json` as root (graphical prompt) and return its parsed JSON."""
    gui_ok = os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    runner = ["pkexec"] if shutil.which("pkexec") and gui_ok else ["sudo", "-n"]
    r = subprocess.run(runner + cli.reexec_prefix() + args + ["--json"], capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except ValueError:
        if r.returncode in (126, 127):  # pkexec: dialog dismissed / not authorized / timed out
            raise RuntimeError("the password prompt was cancelled or timed out. Press Rescan and enter your "
                               "password when the dialog appears.")
        why = (r.stderr or "").strip().splitlines()[-1:] or ["unknown error"]
        raise RuntimeError(why[0])


def _scan_privileged():
    if os.geteuid() == 0:
        drives, skipped = cli.scan()
        allrec = history.load_all()
        data = cli.payload(drives, skipped, {k: v[-1] for k, v in allrec.items()}, allrec)
        history.save(drives)
        return data
    return _run_root([])


def _selftest_privileged(dev, kind):
    if os.geteuid() == 0:
        return probe.start_selftest(dev, kind)
    return _run_root(["--selftest", kind, dev])


def _demo_selftest(dev, kind):
    return {"ok": True, "message": f"{kind} self-test started on {dev} (demo)", "minutes": 2 if kind == "short" else 90}


def _demo():
    from . import demo
    ds = demo.drives()
    allrec = demo.history_records(ds)
    return cli.payload(ds, 0, {k: v[-1] for k, v in allrec.items()}, allrec)


import re


def run(demo=False, port=0, prefer="auto"):
    token, lock = secrets.token_urlsafe(16), threading.Lock()
    scan = _demo if demo else _scan_privileged
    selftest = _demo_selftest if demo else _selftest_privileged
    bench = bench_mod.Bench(demo=demo)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body, ctype, code=200):
            b = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b)

        def _authorized(self, u):
            host_ok = self.headers.get("Host", "").split(":")[0] in ("127.0.0.1", "localhost")
            return host_ok and parse_qs(u.query).get("t") == [token]

        def do_POST(self):
            u = urlparse(self.path)
            if not self._authorized(u) or u.path not in ("/api/selftest", "/api/bench/start", "/api/bench/cancel",
                                                         "/api/bench/kdiskmark"):
                return self._send("forbidden", "text/plain", 403)
            try:
                n = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(min(n, 1024)) or b"{}")
                dev, kind = str(req.get("dev", "")), str(req.get("type", ""))
                if u.path in ("/api/selftest", "/api/bench/start") and not re.fullmatch(r"[a-z0-9]{1,16}", dev):
                    raise ValueError("bad request")
                if u.path == "/api/selftest" and kind not in probe.SELFTESTS:
                    raise ValueError("bad request")
                size_mb = int(req.get("size_mb", 0))
            except (ValueError, TypeError):
                return self._send(json.dumps({"ok": False, "message": "bad request"}), "application/json", 400)
            if u.path == "/api/bench/start":
                res = bench.start(dev, size_mb)
            elif u.path == "/api/bench/cancel":
                res = bench.cancel()
            elif u.path == "/api/bench/kdiskmark":
                cmd = bench_mod.kdiskmark_command()
                if cmd:
                    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                res = {"ok": bool(cmd), "message": "Opening KDiskMark..." if cmd else "KDiskMark isn't installed"}
            else:
                with lock:
                    try:
                        res = selftest(dev, kind)
                    except Exception as e:
                        res = {"ok": False, "message": str(e)}
            self._send(json.dumps(res), "application/json")

        def do_GET(self):
            u = urlparse(self.path)
            if not self._authorized(u):
                return self._send("forbidden", "text/plain", 403)
            if u.path == "/":
                return self._send(PAGE, "text/html; charset=utf-8")
            if u.path == "/api/bench/status":
                return self._send(json.dumps(bench.status()), "application/json")
            if u.path == "/api/bench/history":
                dev = parse_qs(u.query).get("dev", [""])[0]
                ok = re.fullmatch(r"[a-z0-9]{1,16}", dev) and not demo
                return self._send(json.dumps(bench_mod.past_results(dev) if ok else []), "application/json")
            if u.path == "/api/scan":
                with lock:
                    try:
                        body = json.dumps(scan())
                    except Exception as e:  # shown in the page
                        body = json.dumps({"error": str(e)})
                return self._send(body, "application/json")
            self._send("not found", "text/plain", 404)

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    url = f"http://127.0.0.1:{srv.server_port}/?t={token}"
    print(f"diskmd GUI: {url}", flush=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        if os.environ.get("DISKMD_NO_BROWSER"):
            kind = "none"
        else:
            kind = window.show(url, prefer)
        if kind != "qt":  # the window runs separately: keep serving until Ctrl+C
            print("(Ctrl+C to quit)", flush=True)
            threading.Event().wait()
    except KeyboardInterrupt:
        pass
    srv.shutdown()
    return 0
