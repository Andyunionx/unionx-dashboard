/**
 * KPIs para Maestra de Ventas
 */
import { Row, Col, Card, Statistic, Spin } from 'antd'
import { useMaestraStore } from '../store/maestraStore'

const fmtCurrency = (v) => {
  if (v >= 1000000000) return `$${(v / 1000000000).toFixed(1)}B`
  if (v >= 1000000) return `$${(v / 1000000).toFixed(1)}M`
  if (v >= 1000) return `$${(v / 1000).toFixed(0)}K`
  return `$${Math.round(v)}`
}

const fmtNumber = (v) => Number(v).toLocaleString('es-CL')

export function MaestraKpis() {
  const { kpis, isLoading } = useMaestraStore()

  if (!kpis) return null

  const margenColor = kpis.pct_margen > 25 ? '#52c41a' : kpis.pct_margen > 15 ? '#faad14' : '#ff4d4f'

  const items = [
    { title: 'Venta Bruta', value: fmtCurrency(kpis.venta_bruta), color: '#1890ff' },
    { title: 'Margen Final', value: fmtCurrency(kpis.margen_final), color: '#52c41a' },
    { title: '% Margen', value: `${kpis.pct_margen}%`, color: margenColor },
    { title: 'Unidades', value: fmtNumber(kpis.unidades), color: '#faad14' },
    { title: 'Ordenes', value: fmtNumber(kpis.ordenes), color: '#722ed1' },
    { title: 'Ticket Promedio', value: fmtCurrency(kpis.ticket_promedio), color: '#13c2c2' },
  ]

  return (
    <Spin spinning={isLoading}>
      <Row gutter={[12, 12]}>
        {items.map((item, i) => (
          <Col xs={12} sm={8} md={4} key={i}>
            <Card size="small" style={{ boxShadow: '0 2px 8px rgba(0,0,0,0.06)' }}>
              <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>{item.title}</div>
              <div style={{ fontSize: 20, fontWeight: 600, color: item.color }}>{item.value}</div>
            </Card>
          </Col>
        ))}
      </Row>
    </Spin>
  )
}
