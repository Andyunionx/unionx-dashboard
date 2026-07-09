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
rep('<div class="m"><div class="k good">+$125M</div><div class="l">2027 base (digital + B2B $300M)</div></div>',
    '<div class="m"><div class="k good">+$42M</div><div class="l">2027 base (venta $6.500M incl. B2B)</div></div>')
rep('<div class="m"><div class="k good">+$349M</div><div class="l">Con plan de reestructuración</div></div>',
    '<div class="m"><div class="k good">+$266M</div><div class="l">Con plan de reestructuración</div></div>')

# INDICADORES
rep('''            <tr><td>Venta</td><td>4.939</td><td>6.164</td><td>6.667</td><td>6.800</td><td>6.800</td></tr>
            <tr><td>EBIT</td><td>572</td><td>208</td><td>216</td><td>294</td><td class="pos">518</td></tr>
            <tr><td>Utilidad</td><td>487</td><td>124</td><td>19</td><td class="pos">+125</td><td class="pos">+349</td></tr>
            <tr><td>Cobertura int.</td><td>5,0×</td><td>1,2×</td><td>1,4×</td><td>2,0×</td><td class="pos">3,6×</td></tr>
            <tr><td>Deuda / Patrimonio</td><td>—</td><td>3,0×</td><td>3,0×</td><td>2,3×</td><td class="pos">1,8×</td></tr>
            <tr class="tot"><td>Deuda / EBITDA</td><td>2,1×</td><td>8,7×</td><td>8,1×</td><td>5,5×</td><td class="pos">3,2×</td></tr>''',
    '''            <tr><td>Venta</td><td>4.939</td><td>6.164</td><td>6.667</td><td>6.500</td><td>6.500</td></tr>
            <tr><td>EBIT</td><td>572</td><td>208</td><td>216</td><td>211</td><td class="pos">435</td></tr>
            <tr><td>Utilidad</td><td>487</td><td>124</td><td>19</td><td class="pos">+42</td><td class="pos">+266</td></tr>
            <tr><td>Cobertura int.</td><td>5,0×</td><td>1,2×</td><td>1,4×</td><td>1,5×</td><td class="pos">3,0×</td></tr>
            <tr><td>Deuda / Patrimonio</td><td>—</td><td>3,0×</td><td>3,0×</td><td>2,6×</td><td class="pos">2,0×</td></tr>
            <tr class="tot"><td>Deuda / EBITDA</td><td>2,1×</td><td>8,7×</td><td>8,1×</td><td>7,5×</td><td class="pos">3,8×</td></tr>''')

# S1 CHART: base 4,3->3,2 (y156->166), plan 7,6->6,7 (y125->134)
rep('points="80,88 162,144 245,164 327,166 410,156"','points="80,88 162,144 245,164 327,166 410,166"')
rep('<circle cx="410" cy="156" r="5" fill="var(--blue)" stroke="var(--card)" stroke-width="2"/>',
    '<circle cx="410" cy="166" r="5" fill="var(--blue)" stroke="var(--card)" stroke-width="2"/>')
rep('<circle cx="410" cy="125" r="5.5" fill="var(--good)" stroke="var(--card)" stroke-width="2"/>',
    '<circle cx="410" cy="134" r="5.5" fill="var(--good)" stroke="var(--card)" stroke-width="2"/>')
rep('<text class="vlbl" x="410" y="172" text-anchor="middle" fill="var(--blue)">4,3% base</text>',
    '<text class="vlbl" x="410" y="182" text-anchor="middle" fill="var(--blue)">3,2% base</text>')
rep('<text class="vlbl" x="410" y="115" text-anchor="middle" fill="var(--good)">7,6% c/plan</text>',
    '<text class="vlbl" x="410" y="124" text-anchor="middle" fill="var(--good)">6,7% c/plan</text>')

# SECCIONES 5-6
NEW = open(r"g:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA\data\outputs\tmp_html_sec56_v20.html", encoding='utf-8').read()
s2,n = re.subn(r'<!-- 5\. 2027 -->.*?<!-- 7\. ESCENARIOS -->', NEW + '<!-- 7. ESCENARIOS -->', s, flags=re.S)
if n==1: s=s2
else: R.append('SEC5-6 no reemplazada n=%d'%n)

# S7 SENSIBILIDAD + UPSIDE
rep('<div class="tile"><div class="l">Breakeven con el plan</div><div class="v good">−17%</div><div class="d">La venta puede caer 17% y el resultado sigue en azul</div></div>',
    '<div class="tile"><div class="l">Breakeven con el plan</div><div class="v good">−15%</div><div class="d">La venta puede caer 15% y el resultado sigue en azul</div></div>')
rep('<div class="tile"><div class="l">Línea crítica</div><div class="v">Marketplace</div><div class="d">80,7% del mix — cada −5% resta ~$71M de MC</div></div>',
    '<div class="tile"><div class="l">Línea crítica</div><div class="v">Marketplace</div><div class="d">77% del mix — cada −5% resta ~$68M de MC</div></div>')
rep('Sin palancas, la base (digital + B2B) aguanta una caída de venta de ~4% antes de volver a pérdida. Con las palancas ejecutadas el colchón sube a −17%.',
    'Sin palancas, la base aguanta una caída de venta de ~2% antes de volver a pérdida. Con las palancas ejecutadas el colchón sube a −15%.')
rep('''            <tr><td>Venta</td><td>6.800</td><td>7.200</td></tr>
            <tr><td>Margen contribución</td><td>1.902</td><td>2.054</td></tr>
            <tr class="tot"><td>Utilidad</td><td class="pos">+349</td><td class="pos">+501</td></tr>''',
    '''            <tr><td>Venta</td><td>6.500</td><td>6.900</td></tr>
            <tr><td>Margen contribución</td><td>1.819</td><td>1.971</td></tr>
            <tr class="tot"><td>Utilidad</td><td class="pos">+266</td><td class="pos">+418</td></tr>''')

# FOOTER
rep('sobre base digital $6.500M neto (Marketplace + Páginas Web + Fidelización, share real 2026 y márgenes de contribución confirmados) + B2B UnionX $300M.',
    'sobre venta $6.500M (incluye B2B UnionX $300M; digital $6.200M), share real 2026 y márgenes de contribución confirmados.')

io.open(p,'w',encoding='utf-8').write(s)
print('escrito. faltantes:',len(R))
for x in R: print('  FALTA:',x)
