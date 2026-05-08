/**
 * Componentes de gráficos usando Recharts
 */
import { BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import { Card, Row, Col } from 'antd'

const COLORS = ['#1890ff', '#52c41a', '#faad14', '#ff4d4f', '#722ed1', '#13c2c2']

export function GraficoCanal({ data }) {
  if (!data || data.length === 0) return null

  const chartData = data.slice(0, 10).map(item => ({
    name: item.Canal || 'Sin canal',
    'Venta': Math.round(item['Venta Neta'] / 1000000),
    'Margen Final': Math.round(item['Margen Final'] / 1000000),
  }))

  return (
    <Card title="Venta por Canal (Top 10)" style={{ marginBottom: 20 }}>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={chartData} layout="vertical">
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis type="number" />
          <YAxis dataKey="name" type="category" width={150} />
          <Tooltip formatter={(value) => `$${value}M`} />
          <Legend />
          <Bar dataKey="Venta" fill="#1890ff" />
          <Bar dataKey="Margen Final" fill="#52c41a" />
        </BarChart>
      </ResponsiveContainer>
    </Card>
  )
}

export function GraficoLineaNegocio({ data }) {
  if (!data || data.length === 0) return null

  const chartData = data.map(item => ({
    name: item['Línea de Negocio'] || 'Sin clasificar',
    value: Math.round(item['Venta Neta'] / 1000000),
    margen: item['% Margen Final'],
  }))

  return (
    <Card title="Venta por Línea de Negocio" style={{ marginBottom: 20 }}>
      <ResponsiveContainer width="100%" height={300}>
        <PieChart>
          <Pie
            data={chartData}
            cx="50%"
            cy="50%"
            labelLine={true}
            label={({ name, value }) => `${name}: $${value}M`}
            outerRadius={100}
            fill="#8884d8"
            dataKey="value"
          >
            {chartData.map((entry, index) => (
              <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip formatter={(value) => `$${value}M`} />
        </PieChart>
      </ResponsiveContainer>
    </Card>
  )
}

export function GraficoCategoria({ data }) {
  if (!data || data.length === 0) return null

  const chartData = data.slice(0, 8).map(item => ({
    name: item.Categoría || 'Sin categoría',
    'Venta': Math.round(item['Venta Neta'] / 1000000),
  }))

  return (
    <Card title="Venta por Categoría (Top 8)" style={{ marginBottom: 20 }}>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="name" angle={-45} textAnchor="end" height={80} />
          <YAxis />
          <Tooltip formatter={(value) => `$${value}M`} />
          <Bar dataKey="Venta" fill="#1890ff" />
        </BarChart>
      </ResponsiveContainer>
    </Card>
  )
}

export function GraficoBodega({ data }) {
  if (!data || data.length === 0) return null

  const chartData = data.map(item => ({
    name: item.Bodega || 'Sin bodega',
    value: Math.round(item['Venta Neta'] / 1000000),
    margen: item['% Margen Final'],
  }))

  return (
    <Card title="Distribución por Bodega" style={{ marginBottom: 20 }}>
      <ResponsiveContainer width="100%" height={300}>
        <PieChart>
          <Pie
            data={chartData}
            cx="50%"
            cy="50%"
            label={({ name, value }) => `${name}: $${value}M`}
            outerRadius={100}
            fill="#8884d8"
            dataKey="value"
          >
            {chartData.map((entry, index) => (
              <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip formatter={(value) => `$${value}M`} />
        </PieChart>
      </ResponsiveContainer>
    </Card>
  )
}
