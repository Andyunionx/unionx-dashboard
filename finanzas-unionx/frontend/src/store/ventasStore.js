/**
 * Store de Zustand para estado global de ventas
 */
import { create } from 'zustand'

export const useVentasStore = create((set) => ({
  // Estado de datos
  data: null,
  kpis: null,
  resumenes: null,
  filtrosDisponibles: null,

  // Estado de jobs
  jobId: null,
  jobStatus: null,
  jobProgress: 0,
  jobLabel: '',
  isLoading: false,
  error: null,

  // Estado de filtros
  periodo_inicio: '2026-04-01',
  periodo_fin: '2026-04-30',
  canal: null,
  categoria: null,
  bodega: null,

  // Actions
  setData: (data) => set({ data }),
  setKpis: (kpis) => set({ kpis }),
  setResumenes: (resumenes) => set({ resumenes }),
  setFiltrosDisponibles: (filtros) => set({ filtrosDisponibles: filtros }),

  setJobId: (jobId) => set({ jobId }),
  setJobStatus: (jobStatus) => set({ jobStatus }),
  setJobProgress: (progress) => set({ jobProgress: progress }),
  setJobLabel: (label) => set({ jobLabel: label }),
  setIsLoading: (isLoading) => set({ isLoading }),
  setError: (error) => set({ error }),

  setPeriodo: (inicio, fin) => set({ periodo_inicio: inicio, periodo_fin: fin }),
  setFiltros: (canal, categoria, bodega) => set({ canal, categoria, bodega }),

  // Reset
  reset: () => set({
    data: null,
    kpis: null,
    resumenes: null,
    jobId: null,
    jobStatus: null,
    jobProgress: 0,
    jobLabel: '',
    isLoading: false,
    error: null,
  }),
}))
