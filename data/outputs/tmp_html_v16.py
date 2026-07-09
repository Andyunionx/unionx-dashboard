# -*- coding: utf-8 -*-
import io, re, sys
sys.stdout.reconfigure(encoding='utf-8')
p = r"C:\Users\andre\AppData\Local\Temp\claude\g--Mi-unidad-TRABAJO-RESPALDO-OPERACIONES-UNION-X---IA\582f00fe-315c-4ab8-9730-8c40eafa42c9\scratchpad\directorio_cfo.html"
s = io.open(p, encoding='utf-8').read()
R=[]
def rep(a,b):
    global s
    if a in s: s=s.replace(a,b); return
    R.append(a[:70])

# HERO
rep('<div class="m"><div class="k good">+$430M</div><div class="l">Con plan de reestructuración</div></div>',
    '<div class="m"><div class="k good">+$365M</div><div class="l">Con plan de reestructuración</div></div>')

# S1 good point 8,8 -> 7,9
rep('<circle cx="410" cy="114" r="5.5" fill="var(--good)" stroke="var(--card)" stroke-width="2"/>',
    '<circle cx="410" cy="122" r="5.5" fill="var(--good)" stroke="var(--card)" stroke-width="2"/>')
rep('<text class="vlbl" x="410" y="104" text-anchor="middle" fill="var(--good)">8,8% c/plan</text>',
    '<text class="vlbl" x="410" y="112" text-anchor="middle" fill="var(--good)">7,9% c/plan</text>')

# INDICADORES TABLE -> agregar columna 2027e Palancas
rep('<thead><tr><th>Indicador</th><th>2023</th><th>2024</th><th>2025</th><th>2026</th><th>2027e base</th></tr></thead>\n          <tbody>\n            <tr><td>Venta</td><td>4.939</td><td>5.978</td><td>6.164</td><td>6.667</td><td>6.800</td></tr>\n            <tr><td>EBIT</td><td>572</td><td>336</td><td>208</td><td>216</td><td>294</td></tr>\n            <tr><td>Utilidad</td><td>487</td><td>19</td><td>124</td><td>19</td><td class="pos">+125</td></tr>\n            <tr><td>Cobertura int.</td><td>5,0×</td><td>2,2×</td><td>1,2×</td><td>1,4×</td><td>2,0×</td></tr>\n            <tr><td>Deuda / Patrimonio</td><td>—</td><td>—</td><td>3,0×</td><td>3,0×</td><td>2,3×</td></tr>\n            <tr class="tot"><td>Deuda / EBITDA</td><td>2,1×</td><td>5,8×</td><td>8,7×</td><td>8,1×</td><td>5,5×</td></tr>\n          </tbody>',
    '<thead><tr><th>Indicador</th><th>2023</th><th>2025</th><th>2026</th><th>2027e base</th><th>2027e Palancas</th></tr></thead>\n          <tbody>\n            <tr><td>Venta</td><td>4.939</td><td>6.164</td><td>6.667</td><td>6.800</td><td>6.800</td></tr>\n            <tr><td>EBIT</td><td>572</td><td>208</td><td>216</td><td>294</td><td class="pos">534</td></tr>\n            <tr><td>Utilidad</td><td>487</td><td>124</td><td>19</td><td class="pos">+125</td><td class="pos">+365</td></tr>\n            <tr><td>Cobertura int.</td><td>5,0×</td><td>1,2×</td><td>1,4×</td><td>2,0×</td><td class="pos">3,7×</td></tr>\n            <tr><td>Deuda / Patrimonio</td><td>—</td><td>3,0×</td><td>3,0×</td><td>2,3×</td><td class="pos">1,7×</td></tr>\n            <tr class="tot"><td>Deuda / EBITDA</td><td>2,1×</td><td>8,7×</td><td>8,1×</td><td>5,5×</td><td class="pos">3,1×</td></tr>\n          </tbody>')

# SECCION 6 completa
NEW = open(r"g:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA\data\outputs\tmp_html_sec6_v16.html", encoding='utf-8').read()
s2,n = re.subn(r'  <div class="wrap">\s*<span class="eyebrow">06 · El plan de reestructuración</span>.*?</section>\s*\n\s*<!-- 7\.', NEW + '\n<!-- 7.', s, flags=re.S)
if n==1: s=s2
else: R.append('SEC6 no reemplazada n=%d'%n)

# S7 upside 430->365, 582->517 (365+152)
rep('<tr class="tot"><td>Utilidad</td><td class="pos">+430</td><td class="pos">+582</td></tr>',
    '<tr class="tot"><td>Utilidad</td><td class="pos">+365</td><td class="pos">+517</td></tr>')
rep('<th>Base + palancas</th><th>+ B2B a $700M</th>','<th>Base + palancas</th><th>+ B2B a $700M</th>')

# RECO 2 (gerencial solo Nicole, Erich no sale)
rep('<h3>Reducir el rango gerencial en 2027 (~$120M)</h3><p>Meta de reducción de estructura gerencial de ~$120M/año. Hoy solo está confirmada la salida de Nicole (Subgerencia Comercial, nov-26); <b>el saldo queda pendiente de decisión</b>. Se suman ruteros de Trade Marketing (+$26M). Marketing (Michela) y Ecommerce (Ignacia) ya se ejecutaron en julio (+$79M run-rate 2027).</p>',
    '<h3>Liberar la Subgerencia Comercial (Nicole)</h3><p>Erich se mantiene; la única liberación gerencial es Nicole (Subgerencia Comercial, nov-26): ~$55M/año, indemnización $21,3M. Se suman ruteros de Trade Marketing (+$26M). Marketing (Michela) y Ecommerce (Ignacia) ya se ejecutaron en julio (+$79M run-rate 2027).</p>')

# FOOTER
rep('B2B UnionX $300M. Deuda real. EIT en tarifas negociadas reales 08-jul (ahorro +$79,7M/2027).',
    'B2B UnionX $300M. Deuda real (D/Pat 2027 con palancas 1,7×). EIT en tarifas negociadas reales 08-jul (+$79,7M/2027). Gerencial = solo Nicole (Erich no sale).')

io.open(p,'w',encoding='utf-8').write(s)
print('escrito. faltantes:',len(R))
for x in R: print('  FALTA:',x)
