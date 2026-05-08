/**
 * Layout principal con sidebar para navegación
 */
import { Layout, Menu, Button } from 'antd'
import { ShoppingCartOutlined, DatabaseOutlined, BarChartOutlined, GlobalOutlined, BellOutlined, TableOutlined, DashboardOutlined } from '@ant-design/icons'
import { useNavigate, useLocation } from 'react-router-dom'

const { Sider, Content, Header } = Layout

const DASHBOARDS = [
  { key: 'dashboard', label: 'Dashboard YoY', icon: <DashboardOutlined /> },
  { key: 'ventas', label: 'Ventas', icon: <ShoppingCartOutlined /> },
  { key: 'maestra', label: 'Maestra', icon: <TableOutlined /> },
  { key: 'stock', label: 'Stock', icon: <DatabaseOutlined /> },
  { key: 'eerr', label: 'EE.RR.', icon: <BarChartOutlined />, disabled: true },
  { key: 'comex', label: 'COMEX', icon: <GlobalOutlined />, disabled: true },
  { key: 'alertas', label: 'Alertas', icon: <BellOutlined />, disabled: true },
]

export function AppLayout({ children }) {
  const navigate = useNavigate()
  const location = useLocation()

  const currentKey = location.pathname.slice(1) || 'dashboard'

  const handleMenuClick = (e) => {
    if (!DASHBOARDS.find(d => d.key === e.key)?.disabled) {
      navigate(`/${e.key}`)
    }
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{ backgroundColor: '#001529', color: 'white', padding: '0 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ fontSize: 20, fontWeight: 'bold' }}>
          📊 UnionX Finanzas
        </div>
        <div style={{ color: '#999', fontSize: 12 }}>
          Dashboard de Ventas & Operaciones
        </div>
      </Header>

      <Layout>
        <Sider width={250} theme="dark" collapsible collapsedWidth={80}>
          <Menu
            theme="dark"
            selectedKeys={[currentKey]}
            onClick={handleMenuClick}
            items={DASHBOARDS.map(d => ({
              key: d.key,
              icon: d.icon,
              label: d.label,
              disabled: d.disabled,
              title: d.disabled ? 'Próximamente' : d.label,
            }))}
          />
        </Sider>

        <Layout style={{ padding: '24px' }}>
          <Content>
            {children}
          </Content>
        </Layout>
      </Layout>
    </Layout>
  )
}
