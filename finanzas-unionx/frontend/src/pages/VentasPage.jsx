/**
 * Dashboard de Ventas - Página principal
 */
import { useEffect } from 'react'
import { Space } from 'antd'
import { useVentasStore } from '../store/ventasStore'
import { useVentasData } from '../hooks/useVentasData'
import { StatusBadge } from '../components/StatusBadge'
import { FiltrosPanel } from '../components/FiltrosPanel'
import { KpiStrip } from '../components/KpiStrip'
import { GraficoCanal, GraficoLineaNegocio, GraficoCategoria, GraficoBodega } from '../components/Graficos'
import { TablaResumen } from '../components/TablaResumen'

export function VentasPage() {
  const store = useVentasStore()
  const { triggerRefresh } = useVentasData()

  // Al montar, cargar datos del período actual
  useEffect(() => {
    if (!store.data && !store.isLoading) {
      triggerRefresh(store.periodo_inicio, store.periodo_fin)
    }
  }, [])

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <StatusBadge />
      <FiltrosPanel />
      <KpiStrip />

      {store.resumenes && (
        <>
          <GraficoCanal data={store.resumenes.canal} />
          <GraficoLineaNegocio data={store.resumenes.linea} />
          <GraficoCategoria data={store.resumenes.categoria} />
          <GraficoBodega data={store.resumenes.bodega} />
        </>
      )}

      <TablaResumen />
    </Space>
  )
}
