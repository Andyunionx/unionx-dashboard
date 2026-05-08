/**
 * Graficos para Maestra de Ventas
 */
import {
  BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer
} from 'recharts'
import { Card, Row, Col } from 'antd'

const COLORS = ['#1890ff', '#52c41a', '#faad14', '#ff4d4f', '#722ed1', '#13c2c2', '#eb2f96', '#fa8c16']

const fmtM = (v) => `$${(v / 1000000).toFixed(1)}M`
const fmtTooltip = (value) => `$${Number(value).toLocaleString('es-CL')}`

export function GraficoTendencia({ data }) {
  if (!data || data.length === 0) return null

  const chartData = data.map(d => ({
    periodo: d.periodo,
    'Venta Bruta': Math.round(d.venta_bruta / 1000000),
    'Margen Final': Math.round(d.margen_final / 1000000),
  }))

  return (
    <Card title="Tendencia Mensual" size="small" style={{ marginBottom: 16 }}>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="periodo" />
          <YAxis />
          <Tooltip formatter={(v) => `$${v}M`} />
          <Legend />
          <Line type="monotone" dataKey="Venta Bruta" stroke="#1890ff" strokeWidth={2} dot={{ r: 4 }} />
          <Line type="monotone" dataKey="Margen Final" stroke="#52c41a" strokeWidth={2} dot={{ r: 4 }} />
        </LineChart>
      </ResponsiveContainer>
    </Card>
  )
}

export function GraficoCanales({ data }) {
  if (!data || data.length === 0) return null

  const chartData = data.slice(0, 10).map(d => ({
    name: d.canal || 'Sin canal',
    'Venta': Math.round(d.venta_bruta / 1000000),
    'Margen': Math.round(d.margen_final / 1000000),
  }))

  return (
    <Card title="Top 10 Canales" size="small">
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={chartData} layout="vertical">
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis type="number" />
          <YAxis dataKey="name" type="category" width={140} tick={{ fontSize: 11 }} />
          <Tooltip formatter={(v) => `$${v}M`} />
          <Legend />
          <Bar dataKey="Venta" fill="#1890ff" />
          <Bar dataKey="Margen" fill="#52c41a" />
        </BarChart>
      </ResponsiveContainer>
    </Card>
  )
}

export function GraficoCategorias({ data }) {
  if (!data || data.length === 0) return null

  const chartData = data.slice(0, 8).map(d => ({
    name: d.categoria || 'Sin categoria',
    'Venta': Math.round(d.venta_bruta / 1000000),
  }))

  return (
    <Card title="Top Categorias" size="small">
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="name" angle={-30} textAnchor="end" height={70} tick={{ fontSize: 11 }} />
          <YAxis />
          <Tooltip formatter={(v) => `$${v}M`} />
          <Bar dataKey="Venta" fill="#1890ff" />
        </BarChart>
      </ResponsiveContainer>
    </Card>
  )
}

export function GraficoTipoNegocio({ data }) {
  if (!data || data.length === 0) return null

  const chartData = data.map(d => ({
    name: d.tipo_negocio || 'Sin tipo',
    value: Math.round(d.venta_bruta / 1000000),
  }))

  return (
    <Card title="Mix Tipo de Negocio" size="small">
      <ResponsiveContainer width="100%" height={280}>
        <PieChart>
          <Pie
            data={chartData}
            cx="50%"
            cy="50%"
            labelLine={true}
            label={({ name, value }) => `${name}: $${value}M`}
            outerRadius={90}
            dataKey="value"
          >
            {chartData.map((_, i) => (
              <Cell key={i} fill={COLORS[i % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip formatter={(v) => `$${v}M`} />
        </PieChart>
      </ResponsiveContainer>
    </Card>
  )
}

export function GraficoTopSkus({ data }) {
  if (!data || data.length === 0) return null

  const chartData = data.map(d => ({
    name: `${d.sku} | ${(d.producto || '').substring(0, 30)}`,
    'Venta': Math.round(d.venta_bruta / 1000000),
    'Margen': Math.round(d.margen_final / 1000000),
  }))

  return (
    <Card title="Top 20 SKUs" size="small">
      <ResponsiveContainer width="100%" height={420}>
        <BarChart data={chartData} layout="vertical">
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis type="number" />
          <YAxis dataKey="name" type="category" width={200} tick={{ fontSize: 10 }} />
          <Tooltip
            formatter={(v) => `$${v}M`}
            contentStyle={{ backgroundColor: '#f5f5f5', border: '1px solid #d9d9d9' }}
          />
          <Legend />
          <Bar dataKey="Venta" fill="#1890ff" />
          <Bar dataKey="Margen" fill="#52c41a" />
        </BarChart>
      </ResponsiveContainer>
    </Card>
  )
}

export function GraficoBodegas({ data }) {
  if (!data || data.length === 0) return null

  const chartData = data.map(d => ({
    name: d.bodega || 'Sin bodega',
    'Venta': Math.round(d.venta_bruta / 1000000),
    'Margen': Math.round(d.margen_final / 1000000),
  }))

  return (
    <Card title="Resumen por Bodega" size="small">
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={chartData} layout="vertical">
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis type="number" />
          <YAxis dataKey="name" type="category" width={140} tick={{ fontSize: 11 }} />
          <Tooltip formatter={(v) => `$${v}M`} />
          <Legend />
          <Bar dataKey="Venta" fill="#1890ff" />
          <Bar dataKey="Margen" fill="#52c41a" />
        </BarChart>
      </ResponsiveContainer>
    </Card>
  )
}

export function GraficoTendenciaDiaria({ data, periodo_dias = 0 }) {
  // Solo mostrar si período <= 90 días
  if (!data || data.length === 0 || periodo_dias > 90) return null

  const chartData = data.map(d => ({
    fecha: d.fecha_venta,
    'Venta Bruta': Math.round(d.venta_bruta / 1000000),
    'Margen Final': Math.round(d.margen_final / 1000000),
  }))

  return (
    <Card title="Tendencia Diaria" size="small" style={{ marginBottom: 16 }}>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="fecha" />
          <YAxis />
          <Tooltip formatter={(v) => `$${v}M`} />
          <Legend />
          <Line type="monotone" dataKey="Venta Bruta" stroke="#1890ff" strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="Margen Final" stroke="#52c41a" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </Card>
  )
}

export function ComparativaCard({ data }) {
  if (!data) return null

  const {
    actual = {},
    anterior = {},
    variacion_venta_pct = 0,
    variacion_margen_pct = 0
  } = data

  const fmtMoneda = (v) => `$${Number(v).toLocaleString('es-CL', { maximumFractionDigits: 0 })}`
  const fmtPct = (v) => `${v > 0 ? '+' : ''}${v}%`

  const colorVariacion = (v) => v > 0 ? '#52c41a' : v < 0 ? '#ff4d4f' : '#8c8c8c'

  return (
    <Card title="Comparativa: Últimos 7 días vs Semana Anterior" size="small" style={{ marginBottom: 16 }}>
      <Row gutter={16}>
        <Col xs={24} sm={12} lg={6}>
          <div style={{ padding: '12px', border: '1px solid #f0f0f0', borderRadius: '4px' }}>
            <div style={{ fontSize: '12px', color: '#8c8c8c' }}>Venta Bruta (Actual)</div>
            <div style={{ fontSize: '18px', fontWeight: 'bold', color: '#1890ff' }}>
              {fmtMoneda(actual.venta_bruta || 0)}
            </div>
          </div>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <div style={{ padding: '12px', border: '1px solid #f0f0f0', borderRadius: '4px' }}>
            <div style={{ fontSize: '12px', color: '#8c8c8c' }}>Venta Bruta (Anterior)</div>
            <div style={{ fontSize: '18px', fontWeight: 'bold', color: '#bfbfbf' }}>
              {fmtMoneda(anterior.venta_bruta || 0)}
            </div>
          </div>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <div style={{ padding: '12px', border: '1px solid #f0f0f0', borderRadius: '4px' }}>
            <div style={{ fontSize: '12px', color: '#8c8c8c' }}>Variación Venta</div>
            <div style={{ fontSize: '18px', fontWeight: 'bold', color: colorVariacion(variacion_venta_pct) }}>
              {fmtPct(variacion_venta_pct)}
            </div>
          </div>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <div style={{ padding: '12px', border: '1px solid #f0f0f0', borderRadius: '4px' }}>
            <div style={{ fontSize: '12px', color: '#8c8c8c' }}>Variación Margen</div>
            <div style={{ fontSize: '18px', fontWeight: 'bold', color: colorVariacion(variacion_margen_pct) }}>
              {fmtPct(variacion_margen_pct)}
            </div>
          </div>
        </Col>
      </Row>
    </Card>
  )
}
