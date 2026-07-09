# -*- coding: utf-8 -*-
import io, sys
sys.stdout.reconfigure(encoding='utf-8')
p = r"C:\Users\andre\AppData\Local\Temp\claude\g--Mi-unidad-TRABAJO-RESPALDO-OPERACIONES-UNION-X---IA\582f00fe-315c-4ab8-9730-8c40eafa42c9\scratchpad\directorio_cfo.html"
s = io.open(p, encoding='utf-8').read()
R=[]
def rep(a,b):
    global s
    if a in s: s=s.replace(a,b); return
    R.append(a[:70])

# HERO
rep('<div class="m"><div class="k good">+$394M</div><div class="l">Con plan de reestructuración</div></div>',
    '<div class="m"><div class="k good">+$441M</div><div class="l">Con plan de reestructuración</div></div>')
# S1 chart good point 8,3% -> 9,0%
rep('<circle cx="410" cy="118" r="5.5" fill="var(--good)" stroke="var(--card)" stroke-width="2"/>',
    '<circle cx="410" cy="112" r="5.5" fill="var(--good)" stroke="var(--card)" stroke-width="2"/>')
rep('<text class="vlbl" x="410" y="108" text-anchor="middle" fill="var(--good)">8,3% c/plan</text>',
    '<text class="vlbl" x="410" y="102" text-anchor="middle" fill="var(--good)">9,0% c/plan</text>')

# S6 title + lead
rep('<h2>Cinco palancas: de +$125M a +$394M</h2>','<h2>Cinco palancas: de +$125M a +$441M</h2>')
rep('suman <b>+$269M</b> de menor gasto y llevan el 2027 a utilidad +$394M, cobertura 3,9× y Deuda/EBITDA 3,0×.',
    'suman <b>+$316M</b> de menor gasto y llevan el 2027 a utilidad +$441M, cobertura 4,2× y Deuda/EBITDA 2,8×.')

# S6 waterfall (EIT +44 -> +91)
old_wf='''<svg class="chart" viewBox="0 0 460 250" role="img" aria-label="Waterfall desde base 125 hasta 394 con cinco palancas">
          <line class="gl" x1="20" y1="200" x2="452" y2="200"/>
          <rect x="30" y="152" width="56" height="48" rx="3" fill="var(--blue)"/>
          <text class="vlbl" x="58" y="146" text-anchor="middle" fill="var(--blue)">125</text>
          <text class="axl" x="58" y="145" text-anchor="middle" opacity="0"></text>
          <rect x="98" y="107" width="56" height="45" rx="3" fill="var(--good)"/>
          <text class="vlbl" x="126" y="101" text-anchor="middle" fill="var(--good)">+120</text>
          <rect x="166" y="89" width="56" height="18" rx="3" fill="var(--good)"/>
          <text class="vlbl" x="194" y="83" text-anchor="middle" fill="var(--good)">+46</text>
          <rect x="234" y="76" width="56" height="13" rx="3" fill="var(--good)"/>
          <text class="vlbl" x="262" y="70" text-anchor="middle" fill="var(--good)">+33</text>
          <rect x="302" y="59" width="56" height="17" rx="3" fill="var(--good)"/>
          <text class="vlbl" x="330" y="53" text-anchor="middle" fill="var(--good)">+44</text>
          <rect x="370" y="49" width="56" height="10" rx="3" fill="var(--good)"/>
          <text class="vlbl" x="398" y="43" text-anchor="middle" fill="var(--good)">+26</text>
          <line x1="370" y1="49" x2="440" y2="49" stroke="var(--navy)" stroke-width="2"/>
          <text class="vlbl" x="415" y="43" text-anchor="middle" fill="var(--ink)">394</text>
          <g class="axl" text-anchor="middle">
            <text x="58" y="216">Base+B2B</text><text x="126" y="216">Gerencia</text><text x="194" y="216">Michela</text>
            <text x="262" y="216">Ignacia</text><text x="330" y="216">EIT</text><text x="398" y="216">Ruteros</text>
          </g>
        </svg>'''
new_wf='''<svg class="chart" viewBox="0 0 460 250" role="img" aria-label="Waterfall desde base 125 hasta 441 con cinco palancas">
          <line class="gl" x1="20" y1="200" x2="452" y2="200"/>
          <rect x="30" y="157" width="56" height="43" rx="3" fill="var(--blue)"/>
          <text class="vlbl" x="58" y="151" text-anchor="middle" fill="var(--blue)">125</text>
          <rect x="98" y="117" width="56" height="40" rx="3" fill="var(--good)"/>
          <text class="vlbl" x="126" y="111" text-anchor="middle" fill="var(--good)">+120</text>
          <rect x="166" y="101" width="56" height="16" rx="3" fill="var(--good)"/>
          <text class="vlbl" x="194" y="95" text-anchor="middle" fill="var(--good)">+46</text>
          <rect x="234" y="90" width="56" height="11" rx="3" fill="var(--good)"/>
          <text class="vlbl" x="262" y="84" text-anchor="middle" fill="var(--good)">+33</text>
          <rect x="302" y="59" width="56" height="31" rx="3" fill="var(--good)"/>
          <text class="vlbl" x="330" y="53" text-anchor="middle" fill="var(--good)">+91</text>
          <rect x="370" y="50" width="56" height="9" rx="3" fill="var(--good)"/>
          <text class="vlbl" x="398" y="44" text-anchor="middle" fill="var(--good)">+26</text>
          <line x1="370" y1="50" x2="440" y2="50" stroke="var(--navy)" stroke-width="2"/>
          <text class="vlbl" x="415" y="44" text-anchor="middle" fill="var(--ink)">441</text>
          <g class="axl" text-anchor="middle">
            <text x="58" y="216">Base+B2B</text><text x="126" y="216">Gerencia</text><text x="194" y="216">Michela</text>
            <text x="262" y="216">Ignacia</text><text x="330" y="216">EIT</text><text x="398" y="216">Ruteros</text>
          </g>
        </svg>'''
rep(old_wf,new_wf)

# S6 sumatoria table (EIT + total)
rep('<tr><td>+ Ecommerce · Ignacia</td><td>+324</td><td>3,4×</td><td>3,4×</td><td>1,8×</td></tr>\n            <tr class="tot hl-good"><td>+ EIT + Ruteros Trade Mkt</td><td>+394</td><td>3,9×</td><td>3,0×</td><td>1,7×</td></tr>',
    '<tr><td>+ Ecommerce · Ignacia</td><td>+324</td><td>3,4×</td><td>3,4×</td><td>1,8×</td></tr>\n            <tr><td>+ Tercerizar EIT (tarifas negociadas)</td><td>+415</td><td>4,1×</td><td>2,9×</td><td>1,6×</td></tr>\n            <tr class="tot hl-good"><td>+ Ruteros Trade Mkt</td><td>+441</td><td>4,2×</td><td>2,8×</td><td>1,6×</td></tr>')

# S6 vista por palanca
rep('<tr><td>4 · Tercerización EIT (básico)</td><td>10</td><td>+44</td><td>−31,7</td><td>0</td></tr>',
    '<tr><td>4 · Tercerización EIT (tarifas negociadas)</td><td>10</td><td>+91</td><td>−31,7</td><td>0</td></tr>')
rep('<tr class="tot"><td>Total</td><td>15</td><td>+269</td><td>−86,6</td><td>−10</td></tr>',
    '<tr class="tot"><td>Total</td><td>15</td><td>+316</td><td>−86,6</td><td>−10</td></tr>')
# nota S6
rep('Indemnizaciones 2026: $54,9M (EIT $31,7M en 2027). Con todo, la utilidad 2026 pasa de +$19M a <b>~+$9M</b> — se paga una vez y el 2027 queda limpio.',
    'La tercerización EIT usa <b>tarifas negociadas</b> (ahorro +$91M/2027; escala: básico +$44M → negociado +$91M → recomendado +$117M → óptimo +$142M). Indemnizaciones 2026: $54,9M (EIT $31,7M en 2027). Con todo, la utilidad 2026 pasa de +$19M a <b>~+$9M</b> — se paga una vez y el 2027 queda limpio.')

# S7 upside table (base+palancas 394 -> 441 ; +B2B full 546 -> 593)
rep('<tr class="tot"><td>Utilidad</td><td class="pos">+394</td><td class="pos">+546</td></tr>',
    '<tr class="tot"><td>Utilidad</td><td class="pos">+441</td><td class="pos">+593</td></tr>')

# RECO 3 EIT
rep('<div class="reco"><div class="n">3</div><div><h3>Avanzar con la tercerización logística (EIT)</h3><p>Ahorro de al menos $44M/año en el escenario conservador, condicionado a negociar tarifas y blindar el contrato (SLA con penalidad, renegociación anual por volumen).</p></div></div>',
    '<div class="reco hi"><div class="n">3</div><div><h3>Avanzar con la tercerización logística (EIT)</h3><p>Con tarifas negociadas el ahorro es <b>+$91M/año</b> sobre operar interno ($537M), y sube a +$117M reduciendo también supervisión de bodega. Blindar el contrato (SLA con penalidad, renegociación anual por volumen).</p></div></div>')

# FOOTER
rep('EIT en escenario básico.','EIT en tarifas negociadas (ahorro +$91M/2027).')

io.open(p,'w',encoding='utf-8').write(s)
print('escrito. faltantes:',len(R))
for x in R: print('  FALTA:',x)
