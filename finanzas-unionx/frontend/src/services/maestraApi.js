/**
 * API client para Maestra de Ventas
 */
import API from './api'

export const maestraAPI = {
  getData: (params = {}) =>
    API.get('/maestra/data', { params }),

  getFiltros: () =>
    API.get('/maestra/filtros'),

  getTendencia: (params = {}) =>
    API.get('/maestra/tendencia', { params }),

  getDetalle: (params = {}) =>
    API.get('/maestra/detalle', { params }),

  downloadExcel: (params = {}) =>
    API.get('/maestra/export-excel', {
      params,
      responseType: 'blob'
    }),

  getTopSkus: (params = {}) =>
    API.get('/maestra/top-skus', { params }),

  getPorBodega: (params = {}) =>
    API.get('/maestra/por-bodega', { params }),

  getTendenciaDiaria: (params = {}) =>
    API.get('/maestra/tendencia-diaria', { params }),

  getComparativa: () =>
    API.get('/maestra/comparativa'),

  getMatriz: (params = {}) =>
    API.get('/maestra/matriz', { params }),

  // YoY
  getKpisYoY: (params = {}) =>
    API.get('/maestra/yoy/kpis', { params }),

  getTendenciaMensualYoY: () =>
    API.get('/maestra/yoy/tendencia-mensual'),

  getTendenciaDiariaYoY: (params = {}) =>
    API.get('/maestra/yoy/tendencia-diaria', { params }),

  getPorCanalYoY: (params = {}) =>
    API.get('/maestra/yoy/por-canal', { params }),

  getTopSkusYoY: (params = {}) =>
    API.get('/maestra/yoy/top-skus', { params }),

  // Health & Download
  getHealth: () =>
    API.get('/maestra/health'),

  downloadRaw: (desde, hasta) =>
    API.get('/maestra/download/raw', {
      params: { desde, hasta },
      responseType: 'blob'
    }),
}
