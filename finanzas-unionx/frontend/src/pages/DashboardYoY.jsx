/**
 * Dashboard principal YoY: KPIs Top + tendencia mensual + diaria + canales + top SKUs.
 * Permite descargar el RAW en formato 40 columnas.
 */
import { useEffect, useState } from 'react'
import { Row, Col, Card, Statistic, Table, DatePicker, Button, Tag, Space, message, Spin, Typography } from 'antd'
import { ArrowUpOutlined, ArrowDownOutlined, DownloadOutlined, ReloadOutlined } from '@ant-design/icons'
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  AreaChart, Area, BarChart, Bar
} from 'recharts'
import dayjs from 'dayjs'
import { maestraAPI } from '../services/maestraApi'

const { RangePicker } = DatePicker
const { Title, Text } = Typography

const fmtMoney = (v) => v == null ? '-' : `$${Math.round(v).toLocaleString('es-CL')}`
const fmtInt = (v) => v == null ? '-' : Math.round(v).toLocaleString('es-CL')
const fmtPct = (v) => v == null ? '-' : `${v.toFixed(1)}%`

function VarTag({ value, isPct = false }) {
  if (value == null) return <Tag>—</Tag>
  const positive = value >= 0
  const color = positive ? 'green' : 'red'
  const icon = positive ? <ArrowUpOutlined /> : <ArrowDownOutlined />
  return (
    <Tag color={color} icon={icon} style={{ fontSize: 13 }}>
      {Math.abs(value).toFixed(1)}{isPct ? ' pts' : '%'}
    </Tag>
  )
}

function KpiCardYoY({ titulo, ty, ly, varPct, formatter, isPct = false }) {
  return (
    <Card>
      <Text type="secondary">{titulo}</Text>
      <div style={{ marginTop: 8, marginBottom: 8 }}>
        <Title level={2} style={{ margin: 0, color: '#1f1f1f' }}>{formatter(ty)}</Title>
      </div>
      <Space>
        <Text type="secondary" style={{ fontSize: 12 }}>LY: {formatter(ly)}</Text>
        <VarTag value={varPct} isPct={isPct} />
      </Space>
    </Card>
  )
}

export function DashboardYoY() {
  const [loading, setLoading] = useState(true)
  const [periodo, setPeriodo] = useState([dayjs().startOf('month'), dayjs()])
  const [kpis, setKpis] = useState(null)
  const [mensual, setMensual] = useState([])
  const [diaria, setDiaria] = useState([])
  const [canales, setCanales] = useState([])
  const [topSkus, setTopSkus] = useState([])
  const [health, setHealth] = useState(null)
  const [downloading, setDownloading] = useState(false)

  const cargar = async () => {
    setLoading(true)
    const params = {
      fecha_desde: periodo[0].format('YYYY-MM-DD'),
      fecha_hasta: periodo[1].format('YYYY-MM-DD'),
    }
    try {
      const [r1, r2, r3, r4, r5, r6] = await Promise.all([
        maestraAPI.getKpisYoY(params),
        maestraAPI.getTendenciaMensualYoY(),
        maestraAPI.getTendenciaDiariaYoY({ anio: periodo[1].year(), mes: periodo[1].month() + 1 }),
        maestraAPI.getPorCanalYoY(params),
        maestraAPI.getTopSkusYoY({ ...params, limit: 20 }),
        maestraAPI.getHealth(),
      ])
      setKpis(r1.data)
      setMensual(r2.data)
      setDiaria(r3.data)
      setCanales(r4.data)
      setTopSkus(r5.data)
      setHealth(r6.data)
    } catch (e) {
      message.error('Error cargando dashboard: ' + (e.message || ''))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { cargar() }, [])

  const descargarRaw = async () => {
    setDownloading(true)
    try {
      const desde = periodo[0].format('YYYY-MM-DD')
      const hasta = periodo[1].format('YYYY-MM-DD')
      const r = await maestraAPI.downloadRaw(desde, hasta)
      const blob = new Blob([r.data], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `Raw_ventas_Y_${desde}_${hasta}.xlsx`
      a.click()
      URL.revokeObjectURL(url)
      message.success('RAW descargado')
    } catch (e) {
      message.error('Error descargando: ' + (e.message || ''))
    } finally {
      setDownloading(false)
    }
  }

  const healthColor = {
    ok: 'green', atrasado: 'orange', falla: 'red', desconocido: 'default'
  }[health?.estado || 'desconocido']

  if (loading && !kpis) return <Spin size="large" style={{ display: 'block', margin: '120px auto' }} />

  return (
    <div style={{ padding: 16 }}>
      {/* Header */}
      <Row justify="space-between" align="middle" gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col>
          <Title level={3} style={{ margin: 0 }}>Dashboard Ventas (YoY)</Title>
          <Space>
            <Text type="secondary">Período TY: {kpis?.periodo_ty?.desde} → {kpis?.periodo_ty?.hasta}</Text>
            <Text type="secondary">|  Comparado vs LY: {kpis?.periodo_ly?.desde} → {kpis?.periodo_ly?.hasta}</Text>
          </Space>
        </Col>
        <Col>
          <Space>
            <Tag color={healthColor}>
              {health?.estado === 'ok' ? '🟢' : health?.estado === 'atrasado' ? '🟡' : '🔴'} {health?.estado}
              {health?.atraso_horas != null && ` (${health.atraso_horas}h)`}
            </Tag>
            <RangePicker
              value={periodo}
              onChange={(v) => v && setPeriodo(v)}
              format="YYYY-MM-DD"
            />
            <Button icon={<ReloadOutlined />} onClick={cargar}>Refrescar</Button>
            <Button type="primary" icon={<DownloadOutlined />} loading={downloading} onClick={descargarRaw}>
              Descargar RAW
            </Button>
          </Space>
        </Col>
      </Row>

      {/* KPIs YoY */}
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} md={6}>
          <KpiCardYoY titulo="Venta Neta" ty={kpis?.ty?.venta} ly={kpis?.ly?.venta}
                      varPct={kpis?.var_pct?.venta} formatter={fmtMoney} />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <KpiCardYoY titulo="Margen Final" ty={kpis?.ty?.margen} ly={kpis?.ly?.margen}
                      varPct={kpis?.var_pct?.margen} formatter={fmtMoney} />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <KpiCardYoY titulo="% Margen" ty={kpis?.ty?.pct_margen} ly={kpis?.ly?.pct_margen}
                      varPct={kpis?.var_pct?.pct_margen} formatter={(v) => v == null ? '-' : `${v.toFixed(1)}%`} isPct={true} />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <KpiCardYoY titulo="Unidades" ty={kpis?.ty?.unidades} ly={kpis?.ly?.unidades}
                      varPct={kpis?.var_pct?.unidades} formatter={fmtInt} />
        </Col>
      </Row>

      {/* Tendencia mensual */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24}>
          <Card title="Evolución mensual: TY vs LY">
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={mensual}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="mes_nombre" />
                <YAxis tickFormatter={(v) => `${(v/1e6).toFixed(0)}M`} />
                <Tooltip formatter={(v) => fmtMoney(v)} />
                <Legend />
                <Area type="monotone" dataKey="venta_ly" name="LY" fill="#bfbfbf" stroke="#8c8c8c" />
                <Area type="monotone" dataKey="venta_ty" name="TY" fill="#1890ff66" stroke="#1890ff" />
              </AreaChart>
            </ResponsiveContainer>
          </Card>
        </Col>
      </Row>

      {/* Tendencia diaria mes actual */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24}>
          <Card title={`Tendencia diaria — ${periodo[1].format('MMMM YYYY')} vs mismo mes LY`}>
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={diaria}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="dia" />
                <YAxis tickFormatter={(v) => `${(v/1e6).toFixed(0)}M`} />
                <Tooltip formatter={(v) => fmtMoney(v)} />
                <Legend />
                <Line type="monotone" dataKey="venta_ly" name="LY" stroke="#8c8c8c" dot={false} />
                <Line type="monotone" dataKey="venta_ty" name="TY" stroke="#1890ff" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </Card>
        </Col>
      </Row>

      {/* Por Canal y Top SKUs */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={12}>
          <Card title="Por Canal (TY vs LY)">
            <Table
              size="small"
              dataSource={canales}
              rowKey="canal"
              pagination={false}
              scroll={{ y: 360 }}
              columns={[
                { title: 'Canal', dataIndex: 'canal', width: 140 },
                { title: 'V. TY', dataIndex: 'venta_ty', align: 'right', render: fmtMoney },
                { title: 'V. LY', dataIndex: 'venta_ly', align: 'right', render: fmtMoney },
                { title: 'Var %', dataIndex: 'var_venta_pct', align: 'right',
                  render: (v) => v == null ? '-' : <VarTag value={v} /> },
                { title: '% Mg', dataIndex: 'pct_margen', align: 'right',
                  render: (v) => v == null ? '-' : `${v}%` },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="Top 20 SKUs (con var YoY)">
            <Table
              size="small"
              dataSource={topSkus}
              rowKey="sku"
              pagination={false}
              scroll={{ y: 360 }}
              columns={[
                { title: 'SKU', dataIndex: 'sku', width: 100 },
                { title: 'Producto', dataIndex: 'producto', ellipsis: true },
                { title: 'Venta TY', dataIndex: 'venta', align: 'right', render: fmtMoney },
                { title: 'Var %', dataIndex: 'var_venta_pct', align: 'right',
                  render: (v) => v == null ? '-' : <VarTag value={v} /> },
              ]}
            />
          </Card>
        </Col>
      </Row>

      <div style={{ marginTop: 24, textAlign: 'center', color: '#8c8c8c', fontSize: 12 }}>
        DB: {health?.filas_total?.toLocaleString('es-CL')} filas | Rango: {health?.fecha_min} → {health?.fecha_max} | Última carga: {health?.ultima_carga ? new Date(health.ultima_carga).toLocaleString('es-CL') : '—'}
      </div>
    </div>
  )
}
