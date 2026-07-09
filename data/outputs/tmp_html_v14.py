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

# ===== HERO =====
rep('UnionX cierra 2026 apenas en equilibrio (+$19M) y con un balance sobre-apalancado. El problema no es la venta: es la estructura de costo y el nivel de deuda. El 2027 se planifica sobre la base digital ($6.500M, sin B2B) — y en esa base, el plan de reestructuración es la diferencia entre pérdida y utilidad.',
    'UnionX cierra 2026 apenas en equilibrio (+$19M) y con un balance sobre-apalancado. El problema no es la venta: es la estructura de costo y el nivel de deuda. El 2027 se planifica sobre una base realista —digital $6.500M + B2B $300M— que ya es viable; el plan de reestructuración la lleva a un resultado sólido.')
rep('<div class="m"><div class="k bad">−$83M</div><div class="l">2027 base digital (sin B2B)</div></div>',
    '<div class="m"><div class="k good">+$125M</div><div class="l">2027 base (digital + B2B $300M)</div></div>')
rep('<div class="m"><div class="k good">+$153M</div><div class="l">Con plan de reestructuración</div></div>',
    '<div class="m"><div class="k good">+$394M</div><div class="l">Con plan de reestructuración</div></div>')

# ===== S1 chart =====
rep('<circle cx="410" cy="184" r="5" fill="var(--bad)" stroke="var(--card)" stroke-width="2"/>\n          <circle cx="410" cy="141" r="5.5" fill="var(--good)" stroke="var(--card)" stroke-width="2"/>',
    '<circle cx="410" cy="169" r="5" fill="var(--blue)" stroke="var(--card)" stroke-width="2"/>\n          <circle cx="410" cy="118" r="5.5" fill="var(--good)" stroke="var(--card)" stroke-width="2"/>')
rep('points="80,88 162,144 245,164 327,166 410,184"','points="80,88 162,144 245,164 327,166 410,169"')
rep('<text class="vlbl" x="410" y="200" text-anchor="middle" fill="var(--bad)">1,3% base</text>\n          <text class="vlbl" x="410" y="129" text-anchor="middle" fill="var(--good)">5,0% c/plan</text>',
    '<text class="vlbl" x="410" y="185" text-anchor="middle" fill="var(--blue)">4,3% base</text>\n          <text class="vlbl" x="410" y="108" text-anchor="middle" fill="var(--good)">8,3% c/plan</text>')

# ===== S1 tabla =====
rep('<tr><td>Venta</td><td>4.939</td><td>5.978</td><td>6.164</td><td>6.667</td><td>6.500</td></tr>',
    '<tr><td>Venta</td><td>4.939</td><td>5.978</td><td>6.164</td><td>6.667</td><td>6.800</td></tr>')
rep('<tr><td>EBIT</td><td>572</td><td>336</td><td>208</td><td>216</td><td>86</td></tr>',
    '<tr><td>EBIT</td><td>572</td><td>336</td><td>208</td><td>216</td><td>294</td></tr>')
rep('<tr><td>Utilidad</td><td>487</td><td>19</td><td>124</td><td>19</td><td class="neg">−83</td></tr>',
    '<tr><td>Utilidad</td><td>487</td><td>19</td><td>124</td><td>19</td><td class="pos">+125</td></tr>')
rep('<tr><td>Cobertura int.</td><td>5,0×</td><td>2,2×</td><td>1,2×</td><td>1,4×</td><td>0,6×</td></tr>',
    '<tr><td>Cobertura int.</td><td>5,0×</td><td>2,2×</td><td>1,2×</td><td>1,4×</td><td>2,0×</td></tr>')
rep('<tr><td>Deuda / Patrimonio</td><td>—</td><td>—</td><td>3,0×</td><td>3,0×</td><td>3,1×</td></tr>',
    '<tr><td>Deuda / Patrimonio</td><td>—</td><td>—</td><td>3,0×</td><td>3,0×</td><td>2,3×</td></tr>')
rep('<tr class="tot"><td>Deuda / EBITDA</td><td>2,1×</td><td>5,8×</td><td>8,7×</td><td>8,1×</td><td>16,6×</td></tr>',
    '<tr class="tot"><td>Deuda / EBITDA</td><td>2,1×</td><td>5,8×</td><td>8,7×</td><td>8,1×</td><td>5,5×</td></tr>')

# ===== V/H =====
rep('<tr><td>Margen contribución</td><td>30,4%</td><td>28,8%</td><td>27,1%</td><td>26,1%</td></tr>',
    '<tr><td>Margen contribución</td><td>30,4%</td><td>28,8%</td><td>27,1%</td><td>28,0%</td></tr>')
rep('<tr><td>GAV</td><td>18,8%</td><td>25,4%</td><td>23,9%</td><td>24,7%</td></tr>',
    '<tr><td>GAV</td><td>18,8%</td><td>25,4%</td><td>23,9%</td><td>23,6%</td></tr>')
rep('<tr><td>EBIT</td><td>11,6%</td><td>3,4%</td><td>3,2%</td><td>1,3%</td></tr>',
    '<tr><td>EBIT</td><td>11,6%</td><td>3,4%</td><td>3,2%</td><td>4,3%</td></tr>')
rep('<tr class="tot"><td>Utilidad</td><td>9,9%</td><td>2,0%</td><td>0,3%</td><td class="neg">−1,3%</td></tr>',
    '<tr class="tot"><td>Utilidad</td><td>9,9%</td><td>2,0%</td><td>0,3%</td><td class="pos">+1,8%</td></tr>')
rep('<tr><td>Venta</td><td>+21%</td><td>+3%</td><td>+8%</td><td class="neg">−3%</td></tr>',
    '<tr><td>Venta</td><td>+21%</td><td>+3%</td><td>+8%</td><td>+2%</td></tr>')
rep('<tr><td>Margen contribución</td><td>+13%</td><td>+5%</td><td>+2%</td><td>−6%</td></tr>',
    '<tr><td>Margen contribución</td><td>+13%</td><td>+5%</td><td>+2%</td><td>+5%</td></tr>')
rep('<tr class="tot"><td>EBIT</td><td class="neg">−41%</td><td class="neg">−38%</td><td>+4%</td><td class="neg">−60%</td></tr>',
    '<tr class="tot"><td>EBIT</td><td class="neg">−41%</td><td class="neg">−38%</td><td>+4%</td><td class="pos">+36%</td></tr>')

# ===== S4 bars margen por linea (margenes confirmados) =====
rep('''          <div class="bar-row"><span>Corporativo</span><span class="bar-track"><span class="bar-fill hi" style="width:100%"></span></span><span class="bar-val">41%</span></div>
          <div class="bar-row"><span>Fidelización</span><span class="bar-track"><span class="bar-fill hi" style="width:87%"></span></span><span class="bar-val">36%</span></div>
          <div class="bar-row"><span>Distribución</span><span class="bar-track"><span class="bar-fill hi" style="width:83%"></span></span><span class="bar-val">34%</span></div>
          <div class="bar-row"><span>Marketplace</span><span class="bar-track"><span class="bar-fill" style="width:61%;background:var(--warn)"></span></span><span class="bar-val">25%</span></div>
          <div class="bar-row"><span>Páginas Web</span><span class="bar-track"><span class="bar-fill" style="width:60%;background:var(--warn)"></span></span><span class="bar-val">25%</span></div>''',
    '''          <div class="bar-row"><span>B2B UnionX</span><span class="bar-track"><span class="bar-fill hi" style="width:100%"></span></span><span class="bar-val">35%</span></div>
          <div class="bar-row"><span>Fidelización</span><span class="bar-track"><span class="bar-fill hi" style="width:94%"></span></span><span class="bar-val">33%</span></div>
          <div class="bar-row"><span>Páginas Web</span><span class="bar-track"><span class="bar-fill" style="width:79%;background:var(--warn)"></span></span><span class="bar-val">27,5%</span></div>
          <div class="bar-row"><span>Marketplace</span><span class="bar-track"><span class="bar-fill" style="width:77%;background:var(--warn)"></span></span><span class="bar-val">27%</span></div>''')
rep('<p class="cap">% sobre venta · las líneas premium rinden hasta 1,6× más que Marketplace</p>',
    '<p class="cap">% de contribución sobre venta · confirmado (Análisis de Contribución)</p>')
rep('<p class="note">Marketplace (naranjo) mueve el volumen; las líneas premium (azul) dejan el margen. Cuando las premium caen, el golpe a la contribución es desproporcionado.</p>',
    '<p class="note">Marketplace (naranjo) mueve el volumen a 27%; Fidelización (33%) y el B2B (35%) dejan más margen porque cargan menos comisión de marketplace.</p>')

# ===== reemplazo bloques 5-6-7 =====
NEW = open(r"g:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA\data\outputs\tmp_html_567_v14.html", encoding='utf-8').read()
s2,n = re.subn(r'<!-- 5\. 2027 -->.*?<!-- 8\. RECOMENDACIONES -->', NEW + '<!-- 8. RECOMENDACIONES -->', s, flags=re.S)
if n==1: s=s2
else: R.append('BLOQUE 5-7 no reemplazado n=%d'%n)

# ===== RECOs =====
rep('<div class="reco hi"><div class="n">2</div><div><h3>Rediseñar la estructura gerencial para 2027</h3><p>Recorte gerencial de ~$120M/año (Co-Founder Erich + Subgerencia Comercial Nicole) más ruteros de Trade Marketing (+$26M). Indemnizaciones una vez: ~$66M.</p></div></div>',
    '<div class="reco hi"><div class="n">2</div><div><h3>Reducir el rango gerencial en 2027 (~$120M)</h3><p>Reducción de estructura gerencial por ~$120M/año; la salida de Nicole (Subgerencia Comercial, nov-26) es el primer paso confirmado. Se suman ruteros de Trade Marketing (+$26M). Marketing (Michela) y Ecommerce (Ignacia) ya se ejecutaron en julio (+$79M run-rate 2027).</p></div></div>')

# ===== FOOTER =====
rep('Proyección 2027 sobre BASE DIGITAL $6.500M (Marketplace + Páginas Web + Fidelización, mix FCST 2026); B2B solo como upside. Deuda real. EIT en escenario básico.',
    'Proyección 2027 sobre base digital $6.500M neto (Marketplace + Páginas Web + Fidelización, share real 2026 y márgenes de contribución confirmados) + B2B UnionX $300M. Deuda real. EIT en escenario básico. Michela e Ignacia con finiquitos reales (Buk).')

io.open(p,'w',encoding='utf-8').write(s)
print('escrito. faltantes:',len(R))
for x in R: print('  FALTA:',x)
