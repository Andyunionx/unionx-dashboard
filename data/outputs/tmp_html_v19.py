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
rep('<div class="m"><div class="k good">+$365M</div><div class="l">Con plan de reestructuración</div></div>',
    '<div class="m"><div class="k good">+$349M</div><div class="l">Con plan de reestructuración</div></div>')

# S1 good point 7,9 -> 7,6
rep('<circle cx="410" cy="122" r="5.5" fill="var(--good)" stroke="var(--card)" stroke-width="2"/>',
    '<circle cx="410" cy="125" r="5.5" fill="var(--good)" stroke="var(--card)" stroke-width="2"/>')
rep('<text class="vlbl" x="410" y="112" text-anchor="middle" fill="var(--good)">7,9% c/plan</text>',
    '<text class="vlbl" x="410" y="115" text-anchor="middle" fill="var(--good)">7,6% c/plan</text>')

# Indicadores 2027e Palancas
rep('<tr><td>EBIT</td><td>572</td><td>208</td><td>216</td><td>294</td><td class="pos">534</td></tr>',
    '<tr><td>EBIT</td><td>572</td><td>208</td><td>216</td><td>294</td><td class="pos">518</td></tr>')
rep('<tr><td>Utilidad</td><td>487</td><td>124</td><td>19</td><td class="pos">+125</td><td class="pos">+365</td></tr>',
    '<tr><td>Utilidad</td><td>487</td><td>124</td><td>19</td><td class="pos">+125</td><td class="pos">+349</td></tr>')
rep('<tr><td>Cobertura int.</td><td>5,0×</td><td>1,2×</td><td>1,4×</td><td>2,0×</td><td class="pos">3,7×</td></tr>',
    '<tr><td>Cobertura int.</td><td>5,0×</td><td>1,2×</td><td>1,4×</td><td>2,0×</td><td class="pos">3,6×</td></tr>')
rep('<tr class="tot"><td>Deuda / EBITDA</td><td>2,1×</td><td>8,7×</td><td>8,1×</td><td>5,5×</td><td class="pos">3,1×</td></tr>',
    '<tr class="tot"><td>Deuda / EBITDA</td><td>2,1×</td><td>8,7×</td><td>8,1×</td><td>5,5×</td><td class="pos">3,2×</td></tr>')

# S6 title + lead
rep('<h2>Cinco palancas: de +$125M a +$365M</h2>','<h2>Cinco palancas: de +$125M a +$349M</h2>')
rep('Cinco medidas suman <b>+$240M</b> de menor gasto y llevan el 2027 a utilidad +$365M, cobertura 3,7× y Deuda/EBITDA 3,1×.',
    'Cinco medidas suman <b>+$224M</b> de menor gasto y llevan el 2027 a utilidad +$349M, cobertura 3,6× y Deuda/EBITDA 3,2×.')

# Waterfall EIT +80->+64, total 365->349
rep('''          <rect x="98" y="126" width="56" height="23" rx="3" fill="var(--good)"/>
          <text class="vlbl" x="126" y="120" text-anchor="middle" fill="var(--good)">+55</text>
          <rect x="166" y="107" width="56" height="19" rx="3" fill="var(--good)"/>
          <text class="vlbl" x="194" y="101" text-anchor="middle" fill="var(--good)">+46</text>
          <rect x="234" y="94" width="56" height="13" rx="3" fill="var(--good)"/>
          <text class="vlbl" x="262" y="88" text-anchor="middle" fill="var(--good)">+33</text>
          <rect x="302" y="61" width="56" height="33" rx="3" fill="var(--good)"/>
          <text class="vlbl" x="330" y="55" text-anchor="middle" fill="var(--good)">+80</text>
          <rect x="370" y="50" width="56" height="11" rx="3" fill="var(--good)"/>
          <text class="vlbl" x="398" y="44" text-anchor="middle" fill="var(--good)">+26</text>
          <line x1="370" y1="50" x2="440" y2="50" stroke="var(--navy)" stroke-width="2"/>
          <text class="vlbl" x="415" y="44" text-anchor="middle" fill="var(--ink)">365</text>''',
    '''          <rect x="98" y="123" width="56" height="23" rx="3" fill="var(--good)"/>
          <text class="vlbl" x="126" y="117" text-anchor="middle" fill="var(--good)">+55</text>
          <rect x="166" y="103" width="56" height="20" rx="3" fill="var(--good)"/>
          <text class="vlbl" x="194" y="97" text-anchor="middle" fill="var(--good)">+46</text>
          <rect x="234" y="89" width="56" height="14" rx="3" fill="var(--good)"/>
          <text class="vlbl" x="262" y="83" text-anchor="middle" fill="var(--good)">+33</text>
          <rect x="302" y="61" width="56" height="28" rx="3" fill="var(--good)"/>
          <text class="vlbl" x="330" y="55" text-anchor="middle" fill="var(--good)">+64</text>
          <rect x="370" y="50" width="56" height="11" rx="3" fill="var(--good)"/>
          <text class="vlbl" x="398" y="44" text-anchor="middle" fill="var(--good)">+26</text>
          <line x1="370" y1="50" x2="440" y2="50" stroke="var(--navy)" stroke-width="2"/>
          <text class="vlbl" x="415" y="44" text-anchor="middle" fill="var(--ink)">349</text>''')
rep('<rect x="30" y="149" width="56" height="51" rx="3" fill="var(--blue)"/>\n          <text class="vlbl" x="58" y="143" text-anchor="middle" fill="var(--blue)">125</text>',
    '<rect x="30" y="146" width="56" height="54" rx="3" fill="var(--blue)"/>\n          <text class="vlbl" x="58" y="140" text-anchor="middle" fill="var(--blue)">125</text>')
rep('aria-label="Waterfall desde base 125 hasta 365 con cinco palancas"','aria-label="Waterfall desde base 125 hasta 349 con cinco palancas"')

# Sumatoria EIT + Ruteros rows
rep('<tr><td>+ Tercerizar EIT (negociado)</td><td>+80</td><td>+339</td><td>3,5×</td><td>3,3×</td><td>1,9×</td></tr>\n            <tr class="tot hl-good"><td>+ Ruteros Trade Mkt</td><td>+26</td><td>+365</td><td>3,7×</td><td>3,1×</td><td>1,8×</td></tr>',
    '<tr><td>+ Tercerizar EIT (negociado)</td><td>+64</td><td>+323</td><td>3,4×</td><td>3,4×</td><td>1,9×</td></tr>\n            <tr class="tot hl-good"><td>+ Ruteros Trade Mkt</td><td>+26</td><td>+349</td><td>3,6×</td><td>3,2×</td><td>1,8×</td></tr>')

# Vista EIT aporte + total
rep('<tr><td>4 · Tercerización EIT · <b>cambio de bodega</b> (01/01/2027)</td><td>10</td><td>+80</td><td>−31,7</td><td>0</td></tr>',
    '<tr><td>4 · Tercerización EIT · <b>cambio de bodega</b> (01/01/2027)</td><td>10</td><td>+64</td><td>−31,7</td><td>0</td></tr>')
rep('<tr class="tot"><td>Total</td><td>15</td><td>+240</td><td>−86,6</td><td>−10</td></tr>',
    '<tr class="tot"><td>Total</td><td>15</td><td>+224</td><td>−86,6</td><td>−10</td></tr>')

# Bridge der: util 349, patrimonio 942
rep('<tr><td>(+) Utilidad 2027 normalizada (full-stack)</td><td class="pos">+365</td></tr>\n            <tr><td>(−) One-time cambio de bodega (2027)</td><td class="neg">−32</td></tr>\n            <tr><td><b>Patrimonio 2027-cierre</b></td><td><b>958</b></td></tr>',
    '<tr><td>(+) Utilidad 2027 normalizada (full-stack)</td><td class="pos">+349</td></tr>\n            <tr><td>(−) One-time cambio de bodega (2027)</td><td class="neg">−32</td></tr>\n            <tr><td><b>Patrimonio 2027-cierre</b></td><td><b>942</b></td></tr>')

# RECO 3 y footer: ahorro 79,7 -> 64,2
rep('Con las tarifas negociadas reales (08-jul) el ahorro es <b>+$79,7M/año</b> sobre operar interno ($537M); reducir además la supervisión de bodega suma ahorro adicional.',
    'Con las tarifas negociadas reales (08-jul) el ahorro es <b>+$64,2M/año</b> sobre operar interno ($537M) — ya incluye etiquetado 100% B2B y extras (rotulación, arriendo pallet, insumos).')
rep('EIT en tarifas negociadas reales 08-jul (+$79,7M/2027). Gerencial = solo Nicole (Erich no sale).',
    'EIT en tarifas negociadas reales 08-jul (+$64,2M/2027, etiquetado 100% B2B + extras). Gerencial = solo Nicole (Erich no sale).')

io.open(p,'w',encoding='utf-8').write(s)
print('escrito. faltantes:',len(R))
for x in R: print('  FALTA:',x)
