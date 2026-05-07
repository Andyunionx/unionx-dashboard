/**
 * Dashboard de Stock - Control de Inventario
 *
 * Vista basica (KPIs + tablas por bodega/categoria) +
 * Vista avanzada (semaforo + ocupacion CA1/Stock + rotacion + SKUs detalle).
 */
import { useEffect, useState } from 'react'
import {
  Space, Row, Col, Card, Button, Table, Tabs, Tag, Progress,
  Select, Statistic, Alert, Spin
} from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import axios from 'axios'
import { StatusBadge } from '../components/StatusBadge'

const SEMAFORO_COLORS = {
  QUIEBRE: '#DC2626',
  CRITICO: '#DC2626',
  BAJO: '#EA580C',
  OPTIMO: '#16A34A',
  SOBRESTOCK: '#1F4E79',
  'SIN VENTA': '#94A3B8',
}

const SEMAFORO_EMOJI = {
  QUIEBRE: '🔴',
  CRITICO: '🔴',
  BAJO: '🟡',
  OPTIMO: '🟢',
  SOBRESTOCK: '🔵',
  'SIN VENTA': '⚪',
}

export function StockPage() {
  // Estado vista basica
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState(null)
  const [jobStatus, setJobStatus] = useState(null)

  // Estado vista avanzada
  const [advLoading, setAdvLoading] = useState(false)
  const [advData, setAdvData] = useState(null)
  const [advJobStatus, setAdvJobStatus] = useState(null)
  const [filtroSemaforo, setFiltroSemaforo] = useState(null)
  const [filtroBodega, setFiltroBodega] = useState(null)

  // Estado para mostrar "ultima actualizacion"
  const [lastUpdate, setLastUpdate] = useState(null)
  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState(true)

  useEffect(() => {
    triggerRefreshBasic()
    loadAdvancedFromCache()  // primera carga: usa cache backend (rapido)

    // Auto-refresh cada 5 minutos: lee del cache backend
    // (el backend tiene un APScheduler que refresca el cache cada 5 min independientemente)
    let interval
    if (autoRefreshEnabled) {
      interval = setInterval(() => {
        loadAdvancedFromCache()
      }, 5 * 60 * 1000)  // 5 min
    }
    return () => interval && clearInterval(interval)
  }, [autoRefreshEnabled])

  // Carga rapida: lee del cache backend sin disparar nuevo job
  const loadAdvancedFromCache = async () => {
    try {
      const params = new URLSearchParams()
      if (filtroSemaforo) params.append('semaforo', filtroSemaforo)
      if (filtroBodega) params.append('bodega', filtroBodega)
      const r = await axios.get(`/api/stock/advanced/data?${params.toString()}`)
      setAdvData(r.data)
      setLastUpdate(new Date())
    } catch (err) {
      // Si el cache esta vacio (primera vez), disparar job manual
      if (err?.response?.status === 400) {
        triggerRefreshAdvanced()
      }
    }
  }

  // ============== VISTA BASICA ==============
  const triggerRefreshBasic = async () => {
    setLoading(true)
    try {
      const res = await axios.post('/api/stock/refresh')
      pollJob(res.data.job_id, '/api/stock/data', setJobStatus, setData, setLoading)
    } catch (err) {
      console.error('Error:', err)
      setLoading(false)
    }
  }

  // ============== VISTA AVANZADA ==============
  const triggerRefreshAdvanced = async () => {
    setAdvLoading(true)
    try {
      const res = await axios.post('/api/stock/advanced/refresh')
      pollJob(res.data.job_id, '/api/stock/advanced/data', setAdvJobStatus, setAdvData, setAdvLoading)
    } catch (err) {
      console.error('Error advanced:', err)
      setAdvLoading(false)
    }
  }

  const pollJob = (id, dataUrl, setJobS, setD, setL) => {
    const interval = setInterval(async () => {
      try {
        const r = await axios.get(`/api/jobs/${id}`)
        setJobS(r.data)
        if (r.data.status === 'DONE') {
          clearInterval(interval)
          const dr = await axios.get(dataUrl)
          setD(dr.data)
          setL(false)
        } else if (r.data.status === 'ERROR') {
          clearInterval(interval)
          setL(false)
        }
      } catch (err) {
        clearInterval(interval)
        setL(false)
      }
    }, 2500)
  }

  const reloadFiltered = async () => {
    if (!advData) return
    const params = new URLSearchParams()
    if (filtroSemaforo) params.append('semaforo', filtroSemaforo)
    if (filtroBodega) params.append('bodega', filtroBodega)
    try {
      const r = await axios.get(`/api/stock/advanced/data?${params.toString()}`)
      setAdvData(r.data)
    } catch (e) {
      console.error(e)
    }
  }

  useEffect(() => {
    if (advData) reloadFiltered()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtroSemaforo, filtroBodega])

  // ============== RENDER ==============
  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <StatusBadge />

      <Card>
        <Space wrap>
          <Button type="primary" icon={<ReloadOutlined />}
                  onClick={triggerRefreshBasic} loading={loading}>
            Actualizar resumen
          </Button>
          <Button icon={<ReloadOutlined />}
                  onClick={triggerRefreshAdvanced} loading={advLoading}>
            Forzar refresh avanzado
          </Button>
          <Tag color={autoRefreshEnabled ? 'green' : 'default'}
               style={{ cursor: 'pointer' }}
               onClick={() => setAutoRefreshEnabled(v => !v)}>
            🔴 LIVE · auto-refresh {autoRefreshEnabled ? 'ON (5 min)' : 'OFF'}
          </Tag>
          {lastUpdate && (
            <span style={{ color: '#94A3B8', fontSize: 13 }}>
              Última actualización: {lastUpdate.toLocaleTimeString('es-CL')}
            </span>
          )}
          {advData?.metadata?.generado_en && (
            <span style={{ color: '#94A3B8', fontSize: 13 }}>
              Datos del backend: {new Date(advData.metadata.generado_en).toLocaleString('es-CL')}
            </span>
          )}
        </Space>
        {(loading || advLoading) && jobStatus && (
          <div style={{ marginTop: 12 }}>
            <Progress percent={jobStatus.progress || 0} size="small" />
            <small style={{ color: '#999' }}>{jobStatus.label || 'Procesando...'}</small>
          </div>
        )}
      </Card>

      <Tabs defaultActiveKey="resumen" items={[
        // ============== TAB 1: Resumen (vista basica existente) ==============
        {
          key: 'resumen',
          label: '📊 Resumen',
          children: data ? (
            <>
              <Row gutter={16}>
                <Col xs={24} sm={12} md={6}><Card>
                  <Statistic title="Stock Total" value={data.kpis.stock_total}
                    valueStyle={{ color: '#1890ff' }} />
                </Card></Col>
                <Col xs={24} sm={12} md={6}><Card>
                  <Statistic title="Valor Total" value={data.kpis.valor_total / 1e6}
                    precision={1} suffix="M" prefix="$"
                    valueStyle={{ color: '#52c41a' }} />
                </Card></Col>
                <Col xs={24} sm={12} md={6}><Card>
                  <Statistic title="Productos Activos" value={data.kpis.productos_activos}
                    valueStyle={{ color: '#faad14' }} />
                </Card></Col>
                <Col xs={24} sm={12} md={6}><Card>
                  <Statistic title="Stock Reservado" value={data.kpis.stock_reservado}
                    valueStyle={{ color: '#722ed1' }} />
                </Card></Col>
              </Row>

              <div style={{ marginTop: 16 }}>
                <Tabs defaultActiveKey="bodega" items={[
                  {
                    key: 'bodega', label: 'Por Bodega',
                    children: (<Table size="small" pagination={{ pageSize: 20 }}
                      dataSource={data.resumenes.bodega} rowKey={(_, i) => i}
                      columns={[
                        { title: 'Bodega', dataIndex: 'Bodega', width: 250 },
                        { title: 'Stock Total', dataIndex: 'Stock Total', render: v => v?.toLocaleString() },
                        { title: 'Reservado', dataIndex: 'Stock Reservado', render: v => v?.toLocaleString() },
                        { title: 'Libre', dataIndex: 'Stock Libre', render: v => v?.toLocaleString() },
                        { title: 'Valor', dataIndex: 'Valor Total', render: v => '$' + (v/1e6).toFixed(1) + 'M' },
                      ]} />),
                  },
                  {
                    key: 'categoria', label: 'Por Categoría',
                    children: (<Table size="small" pagination={{ pageSize: 20 }}
                      dataSource={data.resumenes.categoria} rowKey={(_, i) => i}
                      columns={[
                        { title: 'Categoría', dataIndex: 'Categoría', width: 250 },
                        { title: 'Stock Total', dataIndex: 'Stock Total', render: v => v?.toLocaleString() },
                        { title: 'Valor', dataIndex: 'Valor Total', render: v => '$' + (v/1e6).toFixed(1) + 'M' },
                      ]} />),
                  },
                ]} />
              </div>
            </>
          ) : <Alert message="Cargando datos..." type="info" />,
        },

        // ============== TAB 2: Semaforo & Ocupacion (NUEVO) ==============
        {
          key: 'semaforo',
          label: '🚦 Semáforo & Ocupación',
          children: advData ? (
            <>
              {/* KPIs semaforo */}
              <Row gutter={16}>
                <Col xs={12} md={4}><Card>
                  <Statistic title="Valor Inventario"
                    value={advData.kpis.valor_total / 1e6} precision={1} suffix="M" prefix="$"
                    valueStyle={{ color: '#1F4E79', fontSize: 18 }} />
                  <small style={{ color: '#94A3B8' }}>{advData.kpis.n_skus} SKUs</small>
                </Card></Col>
                <Col xs={12} md={4}><Card>
                  <Statistic title="🔴 Críticos"
                    value={advData.kpis.n_quiebre_critico}
                    valueStyle={{ color: '#DC2626', fontSize: 22 }} />
                  <small style={{ color: '#94A3B8' }}>{'<'} 30 días</small>
                </Card></Col>
                <Col xs={12} md={4}><Card>
                  <Statistic title="🟡 Bajo"
                    value={advData.kpis.n_bajo}
                    valueStyle={{ color: '#EA580C', fontSize: 22 }} />
                  <small style={{ color: '#94A3B8' }}>30-89 días</small>
                </Card></Col>
                <Col xs={12} md={4}><Card>
                  <Statistic title="🟢 Óptimo"
                    value={advData.kpis.n_optimo}
                    valueStyle={{ color: '#16A34A', fontSize: 22 }} />
                  <small style={{ color: '#94A3B8' }}>90-180 días</small>
                </Card></Col>
                <Col xs={12} md={4}><Card>
                  <Statistic title="🔵 Sobrestock"
                    value={advData.kpis.n_sobrestock}
                    valueStyle={{ color: '#1F4E79', fontSize: 22 }} />
                  <small style={{ color: '#94A3B8' }}>{'>'} 180 días</small>
                </Card></Col>
                <Col xs={12} md={4}><Card>
                  <Statistic title="⚪ Sin venta"
                    value={advData.kpis.n_sin_venta}
                    valueStyle={{ color: '#94A3B8', fontSize: 22 }} />
                  <small style={{ color: '#94A3B8' }}>30d sin movimiento</small>
                </Card></Col>
              </Row>

              {/* Ocupacion CA1/Stock */}
              <Row gutter={16} style={{ marginTop: 16 }}>
                <Col xs={24} md={12}>
                  <Card title="🏭 Ocupación CA1/Stock">
                    {advData.ocupacion ? (
                      <>
                        <Progress
                          percent={advData.ocupacion.pct}
                          status={advData.ocupacion.pct > 85 ? 'exception' : 'active'}
                          format={p => `${p}%`}
                        />
                        <Row gutter={8} style={{ marginTop: 12 }}>
                          <Col span={8}>
                            <Statistic title="Total" value={advData.ocupacion.total}
                              valueStyle={{ fontSize: 18 }} />
                          </Col>
                          <Col span={8}>
                            <Statistic title="Ocupadas" value={advData.ocupacion.occupied}
                              valueStyle={{ fontSize: 18, color: '#16A34A' }} />
                          </Col>
                          <Col span={8}>
                            <Statistic title="Vacías" value={advData.ocupacion.empty}
                              valueStyle={{ fontSize: 18, color: '#94A3B8' }} />
                          </Col>
                        </Row>
                      </>
                    ) : <Alert message="Sin datos de ocupación" type="warning" />}
                  </Card>
                </Col>

                <Col xs={24} md={12}>
                  <Card title="🚦 Distribución de Semáforo">
                    <Table size="small" pagination={false}
                      dataSource={advData.semaforo || []} rowKey="Categoria"
                      columns={[
                        {
                          title: 'Categoría', dataIndex: 'Categoria',
                          render: c => (
                            <Tag color={SEMAFORO_COLORS[c] || '#94A3B8'}>
                              {SEMAFORO_EMOJI[c] || '⚪'} {c}
                            </Tag>
                          ),
                        },
                        { title: 'SKUs', dataIndex: 'SKUs',
                          render: v => v?.toLocaleString() },
                        {
                          title: '%', dataIndex: 'SKUs',
                          render: v => `${((v / advData.kpis.n_skus) * 100).toFixed(1)}%`,
                        },
                      ]} />
                  </Card>
                </Col>
              </Row>

              {/* Valor por Bodega */}
              <Row gutter={16} style={{ marginTop: 16 }}>
                <Col xs={24}>
                  <Card title="💰 Valor por Bodega">
                    <Table size="small" pagination={{ pageSize: 10 }}
                      dataSource={advData.valor_bodega || []} rowKey="Bodega"
                      columns={[
                        { title: 'Bodega', dataIndex: 'Bodega', width: 200 },
                        { title: 'Valor', dataIndex: 'Valor',
                          render: v => '$' + (v/1e6).toFixed(1) + 'M',
                          sorter: (a, b) => a.Valor - b.Valor,
                          defaultSortOrder: 'descend' },
                        { title: 'SKUs', dataIndex: 'SKUs',
                          render: v => v?.toLocaleString() },
                        { title: 'Unidades', dataIndex: 'Unidades',
                          render: v => v?.toLocaleString() },
                      ]} />
                  </Card>
                </Col>
              </Row>
            </>
          ) : <Alert message="Cargando análisis avanzado... (puede tardar 30-60s la primera vez)" type="info" />,
        },

        // ============== TAB 3: SKUs detalle ==============
        {
          key: 'skus',
          label: '🔍 SKUs detalle',
          children: advData ? (
            <>
              <Card style={{ marginBottom: 16 }}>
                <Space>
                  <Select placeholder="Filtrar Semáforo" allowClear style={{ width: 200 }}
                    value={filtroSemaforo} onChange={setFiltroSemaforo}
                    options={(advData.filtros_disponibles?.semaforos || []).map(s => ({
                      label: `${SEMAFORO_EMOJI[s] || ''} ${s}`, value: s,
                    }))} />
                  <Select placeholder="Filtrar Bodega" allowClear style={{ width: 250 }}
                    value={filtroBodega} onChange={setFiltroBodega}
                    options={(advData.filtros_disponibles?.bodegas || []).map(b => ({
                      label: b, value: b,
                    }))} />
                  <span style={{ color: '#94A3B8' }}>
                    Mostrando {advData.skus?.length || 0} de {advData.skus_total_count || 0}
                  </span>
                </Space>
              </Card>

              <Table size="small" pagination={{ pageSize: 50, showSizeChanger: true }}
                dataSource={advData.skus || []} rowKey="product_id"
                columns={[
                  { title: 'SKU', dataIndex: 'SKU', width: 100, fixed: 'left' },
                  { title: 'Producto', dataIndex: 'Producto', ellipsis: true, width: 250 },
                  { title: 'Categoría', dataIndex: 'Categoria', width: 150 },
                  { title: 'Bodega', dataIndex: 'Bodega', ellipsis: true, width: 150 },
                  { title: 'Qty', dataIndex: 'Qty',
                    render: v => Math.round(v).toLocaleString(),
                    sorter: (a, b) => a.Qty - b.Qty },
                  { title: 'Valor', dataIndex: 'Valor',
                    render: v => '$' + Math.round(v/1e3).toLocaleString() + 'K',
                    sorter: (a, b) => a.Valor - b.Valor },
                  { title: 'Vta 30d', dataIndex: 'Vta 30d Qty',
                    render: v => Math.round(v).toLocaleString(),
                    sorter: (a, b) => a['Vta 30d Qty'] - b['Vta 30d Qty'] },
                  { title: 'Días Stock', dataIndex: 'Dias Stock',
                    render: v => v >= 999 ? '∞' : v,
                    sorter: (a, b) => a['Dias Stock'] - b['Dias Stock'] },
                  { title: 'Rot 30d', dataIndex: 'Rot 30d Uds', render: v => `${v}x` },
                  { title: 'Rot 90d', dataIndex: 'Rot 90d Uds', render: v => `${v}x` },
                  { title: 'Semáforo', dataIndex: 'Semaforo',
                    render: s => (
                      <Tag color={SEMAFORO_COLORS[s] || '#94A3B8'}>
                        {SEMAFORO_EMOJI[s] || '⚪'} {s}
                      </Tag>
                    ),
                    filters: (advData.filtros_disponibles?.semaforos || []).map(s => ({
                      text: s, value: s,
                    })),
                    onFilter: (v, r) => r.Semaforo === v },
                ]}
                scroll={{ x: 1500 }} />
            </>
          ) : <Alert message="Cargando datos avanzados..." type="info" />,
        },
      ]} />
    </Space>
  )
}
