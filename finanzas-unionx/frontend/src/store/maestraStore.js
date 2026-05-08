/**
 * Store Zustand para Maestra de Ventas
 */
import { create } from 'zustand'

export const useMaestraStore = create((set) => ({
  // Data
  kpis: null,
  canales: null,
  categorias: null,
  tipoNegocio: null,
  tendencia: null,
  tendenciaDiaria: null,
  detalle: null,
  filtrosDisponibles: null,
  topSkus: null,
  bodegas: null,
  comparativa: null,
  matriz: null,

  // UI state
  isLoading: false,
  error: null,

  // Filtros activos
  filtros: {
    fecha_desde: null,
    fecha_hasta: null,
    canal: null,
    marca: null,
    categoria: null,
    tipo_negocio: null,
    kam: null,
    bodega: null,
  },

  // Tabla
  page: 1,
  pageSize: 50,
  sortBy: 'venta_bruta',
  sortOrder: 'desc',
  search: '',

  // Actions
  setKpis: (kpis) => set({ kpis }),
  setCanales: (canales) => set({ canales }),
  setCategorias: (categorias) => set({ categorias }),
  setTipoNegocio: (tipoNegocio) => set({ tipoNegocio }),
  setTendencia: (tendencia) => set({ tendencia }),
  setTendenciaDiaria: (tendenciaDiaria) => set({ tendenciaDiaria }),
  setDetalle: (detalle) => set({ detalle }),
  setFiltrosDisponibles: (f) => set({ filtrosDisponibles: f }),
  setTopSkus: (topSkus) => set({ topSkus }),
  setBodegas: (bodegas) => set({ bodegas }),
  setComparativa: (comparativa) => set({ comparativa }),
  setMatriz: (matriz) => set({ matriz }),
  setIsLoading: (v) => set({ isLoading: v }),
  setError: (e) => set({ error: e }),
  setPage: (p) => set({ page: p }),
  setSearch: (s) => set({ search: s, page: 1 }),
  setSort: (sortBy, sortOrder) => set({ sortBy, sortOrder, page: 1 }),

  setFiltro: (key, value) => set((state) => ({
    filtros: { ...state.filtros, [key]: value || null },
    page: 1,
  })),

  resetFiltros: () => set({
    filtros: {
      fecha_desde: null, fecha_hasta: null, canal: null, marca: null,
      categoria: null, tipo_negocio: null, kam: null, bodega: null,
    },
    page: 1,
    search: '',
  }),
}))
