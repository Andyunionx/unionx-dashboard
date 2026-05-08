/**
 * Componente de tarjeta KPI
 * Muestra un valor principal con subtítulo y color según umbral
 */
import { Card, Statistic, Row, Col } from 'antd'
import { ArrowUpOutlined, ArrowDownOutlined } from '@ant-design/icons'

export function KpiCard({ title, value, prefix = '$', suffix = '', color = 'blue', delta = null }) {
  // Formatear valor
  const formattedValue = typeof value === 'number'
    ? prefix + (value > 999999 ? (value / 1000000).toFixed(1) + 'M' : (value / 1000).toFixed(0) + 'K')
    : value

  // Color según umbral (para % margen)
  let valueColor = color
  if (suffix === '%') {
    if (value > 25) valueColor = '#52c41a' // verde
    else if (value > 15) valueColor = '#faad14' // amarillo
    else valueColor = '#ff4d4f' // rojo
  }

  return (
    <Card bordered={false} style={{ borderRadius: 8, boxShadow: '0 2px 8px rgba(0,0,0,0.08)' }}>
      <Row gutter={16}>
        <Col>
          <div style={{ fontSize: 12, color: '#999', marginBottom: 8 }}>{title}</div>
          <div style={{ fontSize: 24, fontWeight: 'bold', color: valueColor }}>
            {formattedValue}{suffix}
          </div>
          {delta && (
            <div style={{ fontSize: 12, marginTop: 8, color: delta > 0 ? '#52c41a' : '#ff4d4f' }}>
              {delta > 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />} {Math.abs(delta).toFixed(1)}%
            </div>
          )}
        </Col>
      </Row>
    </Card>
  )
}
