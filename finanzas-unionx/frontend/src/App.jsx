/**
 * Componente App principal
 * Configura React Router y tema global
 */
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import { AppLayout } from './layouts/AppLayout'
import { VentasPage } from './pages/VentasPage'
import { StockPage } from './pages/StockPage'
import { MaestraPage } from './pages/MaestraPage'
import { DashboardYoY } from './pages/DashboardYoY'

const theme = {
  token: {
    colorPrimary: '#1890ff',
    borderRadius: 8,
  },
  components: {
    Card: {
      boxShadowSecondary: '0 2px 8px rgba(0, 0, 0, 0.08)',
    },
  },
}

function App() {
  return (
    <ConfigProvider theme={theme}>
      <BrowserRouter>
        <Routes>
          <Route
            path="/"
            element={
              <AppLayout>
                <DashboardYoY />
              </AppLayout>
            }
          />
          <Route
            path="/dashboard"
            element={
              <AppLayout>
                <DashboardYoY />
              </AppLayout>
            }
          />
          <Route
            path="/ventas"
            element={
              <AppLayout>
                <VentasPage />
              </AppLayout>
            }
          />
          <Route
            path="/stock"
            element={
              <AppLayout>
                <StockPage />
              </AppLayout>
            }
          />
          <Route
            path="/maestra"
            element={
              <AppLayout>
                <MaestraPage />
              </AppLayout>
            }
          />
          <Route path="*" element={<Navigate to="/ventas" replace />} />
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  )
}

export default App
