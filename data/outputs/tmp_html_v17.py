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

# ---- Indicadores: D/Pat 2027e base 2,3->2,4 ; palancas 1,7->1,8 ----
rep('<tr><td>Deuda / Patrimonio</td><td>—</td><td>3,0×</td><td>3,0×</td><td>2,3×</td><td class="pos">1,7×</td></tr>',
    '<tr><td>Deuda / Patrimonio</td><td>—</td><td>3,0×</td><td>3,0×</td><td>2,4×</td><td class="pos">1,8×</td></tr>')

# ---- Sumatoria: recomputar columna D/Pat ----
old_sum='''            <tr><td>Base digital $6.500M</td><td>—</td><td class="pos">+20</td><td>1,3×</td><td>8,4×</td><td>2,7×</td></tr>
            <tr><td>+ B2B UnionX $300M</td><td>+105</td><td>+125</td><td>2,0×</td><td>5,5×</td><td>2,3×</td></tr>
            <tr><td>+ Gerencial · solo Nicole</td><td>+55</td><td>+180</td><td>2,4×</td><td>4,7×</td><td>2,1×</td></tr>
            <tr><td>+ Marketing · Michela</td><td>+46</td><td>+226</td><td>2,7×</td><td>4,2×</td><td>2,0×</td></tr>
            <tr><td>+ Ecommerce · Ignacia</td><td>+33</td><td>+259</td><td>3,0×</td><td>3,9×</td><td>2,0×</td></tr>
            <tr><td>+ Tercerizar EIT (negociado)</td><td>+80</td><td>+339</td><td>3,5×</td><td>3,3×</td><td>1,8×</td></tr>
            <tr class="tot hl-good"><td>+ Ruteros Trade Mkt</td><td>+26</td><td>+365</td><td>3,7×</td><td>3,1×</td><td>1,7×</td></tr>'''
new_sum='''            <tr><td>Base digital $6.500M</td><td>—</td><td class="pos">+20</td><td>1,3×</td><td>8,4×</td><td>2,8×</td></tr>
            <tr><td>+ B2B UnionX $300M</td><td>+105</td><td>+125</td><td>2,0×</td><td>5,5×</td><td>2,4×</td></tr>
            <tr><td>+ Gerencial · solo Nicole</td><td>+55</td><td>+180</td><td>2,4×</td><td>4,7×</td><td>2,2×</td></tr>
            <tr><td>+ Marketing · Michela</td><td>+46</td><td>+226</td><td>2,7×</td><td>4,2×</td><td>2,1×</td></tr>
            <tr><td>+ Ecommerce · Ignacia</td><td>+33</td><td>+259</td><td>3,0×</td><td>3,9×</td><td>2,0×</td></tr>
            <tr><td>+ Tercerizar EIT (negociado)</td><td>+80</td><td>+339</td><td>3,5×</td><td>3,3×</td><td>1,9×</td></tr>
            <tr class="tot hl-good"><td>+ Ruteros Trade Mkt</td><td>+26</td><td>+365</td><td>3,7×</td><td>3,1×</td><td>1,8×</td></tr>'''
rep(old_sum,new_sum)

# ---- Vista por palanca: EIT efecto 2026 + total ----
rep('<tr><td>4 · Tercerización EIT (tarifas negociadas)</td><td>10</td><td>+80</td><td>−31,7</td><td>0</td></tr>',
    '<tr><td>4 · Tercerización EIT · <b>cambio de bodega</b></td><td>10</td><td>+80</td><td>−31,7</td><td class="neg">−32</td></tr>')
rep('<tr class="tot"><td>Total</td><td>15</td><td>+240</td><td>−86,6</td><td>−10</td></tr>',
    '<tr class="tot"><td>Total</td><td>15</td><td>+240</td><td>−86,6</td><td class="neg">−44</td></tr>')

# ---- Panel izq: indemnizaciones 2026 (agregar cambio de bodega) ----
rep('''            <tr><td>Ruteros Trade Mkt (dic-26)</td><td class="neg">−5,8</td></tr>
            <tr><td><b>Total indemnizaciones 2026</b></td><td class="neg"><b>−54,9</b></td></tr>
            <tr><td>(+) Ahorro de sueldo en 2026 (año parcial)</td><td class="pos">+43,0</td></tr>
            <tr class="tot"><td>Efecto neto en el resultado 2026</td><td class="neg">−11,9</td></tr>''',
    '''            <tr><td>Ruteros Trade Mkt (dic-26)</td><td class="neg">−5,8</td></tr>
            <tr><td><b>Cambio de bodega</b> (tercerización EIT)</td><td class="neg">−31,7</td></tr>
            <tr><td><b>Total indemnizaciones 2026</b></td><td class="neg"><b>−86,6</b></td></tr>
            <tr><td>(+) Ahorro de sueldo en 2026 (año parcial)</td><td class="pos">+43,0</td></tr>
            <tr class="tot"><td>Efecto neto en el resultado 2026</td><td class="neg">−43,6</td></tr>''')
rep('<p class="note">El ahorro de sueldo del propio 2026 compensa casi toda la indemnización: la utilidad 2026 pasa de +$19M a <b>~+$7M</b>. EIT ($31,7M) se paga en 2027.</p>',
    '<p class="note">El 2026 absorbe TODA la indemnización (personas + cambio de bodega = $86,6M). El ahorro de sueldo compensa parte, pero la utilidad 2026 pasa de +$19M a <b>~−$25M</b>. Es un golpe one-time; el 2027 queda limpio.</p>')

# ---- Panel der: puente patrimonio ----
rep('''            <tr><td>(−) Efecto neto exits en 2026</td><td class="neg">−12</td></tr>
            <tr><td>Patrimonio 2026-cierre ajustado</td><td>625</td></tr>
            <tr><td>(+) Utilidad 2027 (full-stack)</td><td class="pos">+365</td></tr>
            <tr><td><b>Patrimonio 2027-cierre</b></td><td><b>990</b></td></tr>
            <tr><td>Deuda financiera 2027 (amortiza $210M)</td><td>1.729</td></tr>
            <tr class="tot hl-good"><td>Deuda / Patrimonio 2027</td><td>1,7×</td></tr>''',
    '''            <tr><td>(−) Efecto neto exits en 2026 (incl. bodega)</td><td class="neg">−44</td></tr>
            <tr><td>Patrimonio 2026-cierre ajustado</td><td>593</td></tr>
            <tr><td>(+) Utilidad 2027 (full-stack)</td><td class="pos">+365</td></tr>
            <tr><td><b>Patrimonio 2027-cierre</b></td><td><b>958</b></td></tr>
            <tr><td>Deuda financiera 2027 (amortiza $210M)</td><td>1.729</td></tr>
            <tr class="tot hl-good"><td>Deuda / Patrimonio 2027</td><td>1,8×</td></tr>''')
rep('<p class="note">La D/Pat cae de 3,0× (2026) a 2,3× en la base y 1,7× con palancas por dos efectos reales: la deuda amortiza $210M y el patrimonio crece con el resultado. Las indemnizaciones netean solo −$12M, por eso no golpean el patrimonio.</p>',
    '<p class="note">La D/Pat cae de 3,0× (2026) a 2,4× en la base y 1,8× con palancas: la deuda amortiza $210M y el patrimonio crece con el resultado. Las indemnizaciones ($86,6M, incl. cambio de bodega) llevan el 2026 a −$25M one-time, pero el patrimonio se recupera con el resultado 2027.</p>')

# ---- nota vista principal ----
rep('Indemnizaciones 2026: $54,9M (EIT $31,7M en 2027).',
    'Indemnizaciones 2026: $86,6M (personas $54,9M + cambio de bodega $31,7M).')

io.open(p,'w',encoding='utf-8').write(s)
print('escrito. faltantes:',len(R))
for x in R: print('  FALTA:',x)
