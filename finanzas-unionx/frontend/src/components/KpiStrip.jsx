/**
 * Strip de KPIs principales
 */
import { Row, Col, Card, Statistic, Spin } from 'antd'
import { ArrowUpOutlined } from '@ant-design/icons'
import { useVentasStore } from '../store/ventasStore'

export function KpiStrip() {
  const { kpis, isLoading } = useVentasStore()

  if (!kpis) return null

  const formatCurrency = (value) => {
    if (value >= 1000000) return (value / 1000000).toFixed(1) + 'M'
    if (value >= 1000) return (value / 1000).toFixed(0) + 'K'
    return Math.round(value)
  }

  const getMargenColor = (pct) => {
    if (pct > 25) return '#52c41a' // Verde
    if (pct > 15) return '#faad14' // Amarillo
    return '#ff4d4f' // Rojo
  }

  return (
    <Spin spinning={isLoading}>
      <Row gutter={16} style={{ marginBottom: 20 }}>
        <Col xs={24} sm={12} md={4.8}>
          <Card style={{ boxShadow: '0 2px 8px rgba(0,0,0,0.08)' }}>
            <Statistic
              title="Venta Neta"
              value={kpis.venta_neta}
              prefix="$"
              formatter={(value) => formatCurrency(value)}
              valueStyle={{ color: '#1890ff', fontSize: 20 }}
            />
          </Card>
        </Col>

        <Col xs={24} sm={12} md={4.8}>
          <Card style={{ boxShadow: '0 2px 8px rgba(0,0,0,0.08)' }}>
            <Statistic
              title="Margen Final"
              value={kpis.margen_final}
              prefix="$"
              formatter={(value) => formatCurrency(value)}
              valueStyle={{ color: '#52c41a', fontSize: 20 }}
            />
          </Card>
        </Col>

        <Col xs={24} sm={12} md={4.8}>
          <Card style={{ boxShadow: '0 2px 8px rgba(0,0,0,0.08)' }}>
            <Statistic
              title="% Margen"
              value={kpis.pct_margen_final}
              suffix="%"
              valueStyle={{ color: getMargenColor(kpis.pct_margen_final), fontSize: 20, fontWeight: 'bold' }}
              precision={1}
            />
          </Card>
        </Col>

        <Col xs={24} sm={12} md={4.8}>
          <Card style={{ boxShadow: '0 2px 8px rgba(0,0,0,0.08)' }}>
            <Statistic
              title="Órdenes"
              value={kpis.total_ordenes}
              valueStyle={{ color: '#faad14', fontSize: 20 }}
            />
          </Card>
        </Col>

        <Col xs={24} sm={12} md={4.8}>
          <Card style={{ boxShadow: '0 2px 8px rgba(0,0,0,0.08)' }}>
            <Statistic
              title="Líneas"
              value={kpis.total_lineas}
              valueStyle={{ color: '#722ed1', fontSize: 20 }}
            />
          </Card>
        </Col>
      </Row>
    </Spin>
  )
}
