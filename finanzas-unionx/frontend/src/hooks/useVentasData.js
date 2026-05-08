/**
 * Hook principal para extracción y polling de datos de ventas
 * Máquina de estados: IDLE → REFRESHING → POLLING → READY
 */
import { useEffect, useCallback } from 'react'
import { ventasAPI } from '../services/api'
import { useVentasStore } from '../store/ventasStore'

export function useVentasData() {
  const store = useVentasStore()

  const triggerRefresh = useCallback(async (periodo_inicio, periodo_fin) => {
    store.reset()
    store.setPeriodo(periodo_inicio, periodo_fin)
    store.setIsLoading(true)
    store.setJobLabel('Iniciando extracción...')

    try {
      // Lanzar job
      const response = await ventasAPI.refresh(periodo_inicio, periodo_fin)
      const jobId = response.data.job_id

      store.setJobId(jobId)
      store.setJobStatus('PENDING')
      store.setJobProgress(0)

      // Comenzar polling
      startPolling(jobId)
    } catch (err) {
      store.setError(err.response?.data?.error || err.message)
      store.setIsLoading(false)
    }
  }, [store])

  const startPolling = useCallback(async (jobId) => {
    const pollInterval = setInterval(async () => {
      try {
        const response = await ventasAPI.getJobStatus(jobId)
        const { status, progress, progress_label, error } = response.data

        store.setJobStatus(status)
        store.setJobProgress(progress)
        store.setJobLabel(progress_label)

        if (status === 'DONE') {
          clearInterval(pollInterval)
          // Cargar datos
          await loadData()
          store.setIsLoading(false)
        } else if (status === 'ERROR') {
          clearInterval(pollInterval)
          store.setError(error)
          store.setIsLoading(false)
        }
      } catch (err) {
        clearInterval(pollInterval)
        store.setError(err.message)
        store.setIsLoading(false)
      }
    }, 2000) // Poll cada 2 segundos
  }, [store])

  const loadData = useCallback(async () => {
    try {
      const response = await ventasAPI.getData({
        canal: store.canal,
        categoria: store.categoria,
        bodega: store.bodega,
      })

      const { kpis, resumenes, filtros_disponibles } = response.data

      store.setKpis(kpis)
      store.setResumenes(resumenes)
      store.setFiltrosDisponibles(filtros_disponibles)
    } catch (err) {
      store.setError(err.message)
    }
  }, [store])

  const applyFilters = useCallback(async (canal, categoria, bodega) => {
    store.setFiltros(canal, categoria, bodega)
    store.setIsLoading(true)

    try {
      await loadData()
    } finally {
      store.setIsLoading(false)
    }
  }, [store, loadData])

  const downloadExcel = useCallback(async () => {
    try {
      const response = await ventasAPI.downloadExcel({
        canal: store.canal,
        categoria: store.categoria,
        bodega: store.bodega,
      })

      // Crear descarga
      const blob = new Blob([response.data], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `reporte_ventas_${store.periodo_inicio.split('-').slice(0, 2).join('-')}.xlsx`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      store.setError(err.message)
    }
  }, [store])

  return {
    triggerRefresh,
    applyFilters,
    downloadExcel,
  }
}
