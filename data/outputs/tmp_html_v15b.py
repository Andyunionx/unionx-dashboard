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
rep('<div class="m"><div class="k good">+$441M</div><div class="l">Con plan de reestructuración</div></div>',
    '<div class="m"><div class="k good">+$430M</div><div class="l">Con plan de reestructuración</div></div>')
# S1 good point 9,0 -> 8,8
rep('<circle cx="410" cy="112" r="5.5" fill="var(--good)" stroke="var(--card)" stroke-width="2"/>',
    '<circle cx="410" cy="114" r="5.5" fill="var(--good)" stroke="var(--card)" stroke-width="2"/>')
rep('<text class="vlbl" x="410" y="102" text-anchor="middle" fill="var(--good)">9,0% c/plan</text>',
    '<text class="vlbl" x="410" y="104" text-anchor="middle" fill="var(--good)">8,8% c/plan</text>')
# S6 title + lead
rep('<h2>Cinco palancas: de +$125M a +$441M</h2>','<h2>Cinco palancas: de +$125M a +$430M</h2>')
rep('suman <b>+$316M</b> de menor gasto y llevan el 2027 a utilidad +$441M, cobertura 4,2× y Deuda/EBITDA 2,8×.',
    'suman <b>+$305M</b> de menor gasto y llevan el 2027 a utilidad +$430M, cobertura 4,2× y Deuda/EBITDA 2,8×.')

# Waterfall EIT +91->+80, total 441->430
rep('''          <rect x="302" y="59" width="56" height="31" rx="3" fill="var(--good)"/>
          <text class="vlbl" x="330" y="53" text-anchor="middle" fill="var(--good)">+91</text>
          <rect x="370" y="50" width="56" height="9" rx="3" fill="var(--good)"/>
          <text class="vlbl" x="398" y="44" text-anchor="middle" fill="var(--good)">+26</text>
          <line x1="370" y1="50" x2="440" y2="50" stroke="var(--navy)" stroke-width="2"/>
          <text class="vlbl" x="415" y="44" text-anchor="middle" fill="var(--ink)">441</text>''',
    '''          <rect x="302" y="63" width="56" height="27" rx="3" fill="var(--good)"/>
          <text class="vlbl" x="330" y="57" text-anchor="middle" fill="var(--good)">+80</text>
          <rect x="370" y="54" width="56" height="9" rx="3" fill="var(--good)"/>
          <text class="vlbl" x="398" y="48" text-anchor="middle" fill="var(--good)">+26</text>
          <line x1="370" y1="54" x2="440" y2="54" stroke="var(--navy)" stroke-width="2"/>
          <text class="vlbl" x="415" y="48" text-anchor="middle" fill="var(--ink)">430</text>''')
rep('aria-label="Waterfall desde base 125 hasta 441 con cinco palancas"','aria-label="Waterfall desde base 125 hasta 430 con cinco palancas"')

# Sumatoria table
rep('<tr><td>+ Tercerizar EIT (tarifas negociadas)</td><td>+415</td><td>4,1×</td><td>2,9×</td><td>1,6×</td></tr>\n            <tr class="tot hl-good"><td>+ Ruteros Trade Mkt</td><td>+441</td><td>4,2×</td><td>2,8×</td><td>1,6×</td></tr>',
    '<tr><td>+ Tercerizar EIT (tarifas negociadas)</td><td>+404</td><td>4,0×</td><td>2,9×</td><td>1,7×</td></tr>\n            <tr class="tot hl-good"><td>+ Ruteros Trade Mkt</td><td>+430</td><td>4,2×</td><td>2,8×</td><td>1,6×</td></tr>')

# Vista por palanca
rep('<tr><td>4 · Tercerización EIT (tarifas negociadas)</td><td>10</td><td>+91</td><td>−31,7</td><td>0</td></tr>',
    '<tr><td>4 · Tercerización EIT (tarifas negociadas)</td><td>10</td><td>+80</td><td>−31,7</td><td>0</td></tr>')
rep('<tr class="tot"><td>Total</td><td>15</td><td>+316</td><td>−86,6</td><td>−10</td></tr>',
    '<tr class="tot"><td>Total</td><td>15</td><td>+305</td><td>−86,6</td><td>−10</td></tr>')
# nota
rep('La tercerización EIT usa <b>tarifas negociadas</b> (ahorro +$91M/2027; escala: básico +$44M → negociado +$91M → recomendado +$117M → óptimo +$142M).',
    'La tercerización EIT usa las <b>tarifas negociadas reales (08-jul)</b>: ahorro +$79,7M/2027 (EIT $337M + residual $120M vs operar $537M), frente a +$43,9M con la tarifa inicial.')

# S7 upside 441->430, 593->582
rep('<tr class="tot"><td>Utilidad</td><td class="pos">+441</td><td class="pos">+593</td></tr>',
    '<tr class="tot"><td>Utilidad</td><td class="pos">+430</td><td class="pos">+582</td></tr>')

# RECO 3
rep('Con tarifas negociadas el ahorro es <b>+$91M/año</b> sobre operar interno ($537M), y sube a +$117M reduciendo también supervisión de bodega.',
    'Con las tarifas negociadas reales (08-jul) el ahorro es <b>+$79,7M/año</b> sobre operar interno ($537M); reducir además la supervisión de bodega suma ahorro adicional.')

# FOOTER
rep('EIT en tarifas negociadas (ahorro +$91M/2027).','EIT en tarifas negociadas reales 08-jul (ahorro +$79,7M/2027).')

io.open(p,'w',encoding='utf-8').write(s)
print('escrito. faltantes:',len(R))
for x in R: print('  FALTA:',x)
