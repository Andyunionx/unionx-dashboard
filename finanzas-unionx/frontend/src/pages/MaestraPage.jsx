/**
 * Maestra de Ventas — Pagina principal
 */
import { useEffect, useCallback } from 'react'
import { Space, Row, Col, Alert, message, Tag } from 'antd'
import { useMaestraStore } from '../store/maestraStore'
import { maestraAPI } from '../services/maestraApi'
import { MaestraFiltros } from '../components/MaestraFiltros'
import { MaestraKpis } from '../components/MaestraKpis'
import {
  GraficoTendencia,
  GraficoCanales,
  GraficoCategorias,
  GraficoTipoNegocio,
  GraficoTopSkus,
  GraficoBodegas,
  GraficoTendenciaDiaria,
  ComparativaCard,
} from '../components/MaestraGraficos'
import { MaestraTabla } from '../components/MaestraTabla'

export function MaestraPage() {
  const store = useMaestraStore()

  const getFilterParams = useCallback(() => {
    const f = store.filtros
    const params = {}
    if (f.fecha_desde) params.fecha_desde = f.fecha_desde
    if (f.fecha_hasta) params.fecha_hasta = f.fecha_hasta
    if (f.canal) params.canal = f.canal
    if (f.marca) params.marca = f.marca
    if (f.categoria) params.categoria = f.categoria
    if (f.tipo_negocio) params.tipo_negocio = f.tipo_negocio
    if (f.kam) params.kam = f.kam
    if (f.bodega) params.bodega = f.bodega
    return params
  }, [store.filtros])

  const loadData = useCallback(async () => {
    store.setIsLoading(true)
    store.setError(null)
    try {
      const params = getFilterParams()
      const [dataRes, tendRes, tendDiariaRes, detRes, skusRes, bodRes, matrizRes] = await Promise.all([
        maestraAPI.getData(params),
        maestraAPI.getTendencia(params),
        maestraAPI.getTendenciaDiaria(params),
        maestraAPI.getDetalle({
          ...params,
          page: store.page,
          page_size: store.pageSize,
          sort_by: store.sortBy,
          sort_order: store.sortOrder,
          search: store.search || undefined,
        }),
        maestraAPI.getTopSkus(params),
        maestraAPI.getPorBodega(params),
        maestraAPI.getMatriz(params),
      ])
      store.setKpis(dataRes.data.kpis)
      store.setCanales(dataRes.data.canales)
      store.setCategorias(dataRes.data.categorias)
      store.setTipoNegocio(dataRes.data.tipo_negocio)
      store.setTendencia(tendRes.data)
      store.setTendenciaDiaria(tendDiariaRes.data)
      store.setDetalle(detRes.data)
      store.setTopSkus(skusRes.data)
      store.setBodegas(bodRes.data)
      store.setMatriz(matrizRes.data)
    } catch (e) {
      store.setError(e.response?.data?.error || e.message)
    } finally {
      store.setIsLoading(false)
    }
  }, [getFilterParams, store.page, store.pageSize, store.sortBy, store.sortOrder, store.search])

  const loadFiltros = useCallback(async () => {
    try {
      const res = await maestraAPI.getFiltros()
      store.setFiltrosDisponibles(res.data)
    } catch (e) {
      console.error('Error cargando filtros:', e)
    }
  }, [])

  const loadComparativa = useCallback(async () => {
    try {
      const res = await maestraAPI.getComparativa()
      store.setComparativa(res.data)
    } catch (e) {
      console.error('Error cargando comparativa:', e)
    }
  }, [])

  // Cargar filtros y comparativa al montar
  useEffect(() => {
    loadFiltros()
    loadComparativa()
    loadData()
  }, [])

  // Recargar detalle cuando cambia paginacion/sort/search
  useEffect(() => {
    if (store.kpis) {
      const loadDetalle = async () => {
        try {
          const params = getFilterParams()
          const res = await maestraAPI.getDetalle({
            ...params,
            page: store.page,
            page_size: store.pageSize,
            sort_by: store.sortBy,
            sort_order: store.sortOrder,
            search: store.search || undefined,
          })
          store.setDetalle(res.data)
        } catch (e) {
          console.error('Error cargando detalle:', e)
        }
      }
      loadDetalle()
    }
  }, [store.page, store.sortBy, store.sortOrder, store.search])

  const handleExport = async () => {
    try {
      message.loading({ content: 'Generando Excel...', key: 'export' })
      const params = getFilterParams()
      const res = await maestraAPI.downloadExcel(params)
      const url = window.URL.createObjectURL(new Blob([res.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', 'maestra_ventas.xlsx')
      document.body.appendChild(link)
      link.click()
      link.remove()
      message.success({ content: 'Excel descargado', key: 'export' })
    } catch (e) {
      message.error({ content: 'Error exportando', key: 'export' })
    }
  }

  // Calcular días del período para mostrar/no mostrar tendencia diaria
  const getPeriodoDias = () => {
    const f = store.filtros
    if (!f.fecha_desde || !f.fecha_hasta) return 0
    const desde = new Date(f.fecha_desde)
    const hasta = new Date(f.fecha_hasta)
    const dias = Math.ceil((hasta - desde) / (1000 * 60 * 60 * 24))
    return dias
  }

  const periodo_dias = getPeriodoDias()
  const filtros_disponibles = store.filtrosDisponibles || {}

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="middle">
      {/* Header */}
      <div>
        <h2 style={{ margin: '0 0 8px 0' }}>Maestra de Ventas</h2>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
          {filtros_disponibles.total_registros && (
            <Tag>{filtros_disponibles.total_registros.toLocaleString('es-CL')} registros</Tag>
          )}
          {filtros_disponibles.fecha_min && filtros_disponibles.fecha_max && (
            <Tag color="blue">
              desde {filtros_disponibles.fecha_min} hasta {filtros_disponibles.fecha_max}
            </Tag>
          )}
          {filtros_disponibles.ultima_carga && (
            <span style={{ fontSize: '12px', color: '#8c8c8c' }}>
              Actualizado: {filtros_disponibles.ultima_carga}
            </span>
          )}
        </div>
      </div>

      {store.error && (
        <Alert type="error" message={store.error} closable onClose={() => store.setError(null)} />
      )}

      {/* Filtros */}
      <MaestraFiltros onApply={loadData} />

      {/* KPIs */}
      <MaestraKpis />

      {/* Comparativa */}
      {store.comparativa && <ComparativaCard data={store.comparativa} />}

      {/* Tendencia Diaria (si período <= 90 días) */}
      {periodo_dias <= 90 && <GraficoTendenciaDiaria data={store.tendenciaDiaria} periodo_dias={periodo_dias} />}

      {/* Tendencia Mensual */}
      <GraficoTendencia data={store.tendencia} />

      {/* Row 50/50: Canales | Categorías */}
      <Row gutter={16}>
        <Col xs={24} lg={12}>
          <GraficoCanales data={store.canales} />
        </Col>
        <Col xs={24} lg={12}>
          <GraficoCategorias data={store.categorias} />
        </Col>
      </Row>

      {/* Row 50/50: Tipo Negocio | Bodegas */}
      <Row gutter={16}>
        <Col xs={24} lg={12}>
          <GraficoTipoNegocio data={store.tipoNegocio} />
        </Col>
        <Col xs={24} lg={12}>
          <GraficoBodegas data={store.bodegas} />
        </Col>
      </Row>

      {/* Top 20 SKUs */}
      <GraficoTopSkus data={store.topSkus} />

      {/* Tabla Detalle */}
      <MaestraTabla
        onPageChange={(p) => store.setPage(p)}
        onSearch={(s) => store.setSearch(s)}
        onSort={(field, order) => store.setSort(field, order)}
        onExport={handleExport}
        exportLabel="Descargar RAW (40 cols)"
      />
    </Space>
  )
}
