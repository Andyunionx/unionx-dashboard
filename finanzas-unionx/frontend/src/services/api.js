/**
 * Cliente Axios para todas las llamadas a la API del backend
 */
import axios from 'axios'

const API = axios.create({
  baseURL: 'http://localhost:5001/api',
  timeout: 120000,
  withCredentials: false,
})

// Interceptor para errores
API.interceptors.response.use(
  response => response,
  error => {
    console.error('API Error:', error.response?.data || error.message)
    return Promise.reject(error)
  }
)

export const ventasAPI = {
  // Lanza un job de extracción
  refresh: (periodo_inicio, periodo_fin) =>
    API.post('/ventas/refresh', { periodo_inicio, periodo_fin }),

  // Obtiene estado del job
  getJobStatus: (jobId) =>
    API.get(`/jobs/${jobId}`),

  // Obtiene datos filtrados (KPIs + resúmenes)
  getData: (params = {}) =>
    API.get('/ventas/data', { params }),

  // Descarga Excel
  downloadExcel: (params = {}) =>
    API.get('/ventas/export-excel', {
      params,
      responseType: 'blob'
    }),

  // Obtiene opciones de filtro
  getFiltros: () =>
    API.get('/ventas/filtros'),
}

export default API
