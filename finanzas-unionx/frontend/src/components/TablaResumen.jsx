/**
 * Tabla de resumen con tabs para diferentes dimensiones
 */
import { Card, Table, Tabs, Button, Space, Spin } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import { useVentasStore } from '../store/ventasStore'
import { useVentasData } from '../hooks/useVentasData'

const formatMoney = (value) => {
  if (!value) return '$0'
  return '$' + (value > 1000000 ? (value / 1000000).toFixed(1) + 'M' : (value / 1000).toFixed(0) + 'K')
}

const columns = {
  linea: [
    { title: 'Línea de Negocio', dataIndex: 'Línea de Negocio', width: 250, sorter: (a, b) => (a['Línea de Negocio'] || '').localeCompare(b['Línea de Negocio'] || '') },
    { title: 'Venta Neta', dataIndex: 'Venta Neta', render: formatMoney, width: 120, sorter: (a, b) => a['Venta Neta'] - b['Venta Neta'] },
    { title: 'Costo', dataIndex: 'Costo', render: formatMoney, width: 120 },
    { title: 'Margen Directo', dataIndex: 'Margen Directo', render: formatMoney, width: 140 },
    { title: 'Comisión', dataIndex: 'Comisión', render: formatMoney, width: 120 },
    { title: 'Logística', dataIndex: 'Logística', render: formatMoney, width: 120 },
    { title: 'Margen Final', dataIndex: 'Margen Final', render: formatMoney, width: 120 },
    {
      title: '% Margen',
      dataIndex: '% Margen Final',
      render: (val) => {
        const color = val > 25 ? '#52c41a' : val > 15 ? '#faad14' : '#ff4d4f'
        return <span style={{ color, fontWeight: 'bold' }}>{val?.toFixed(1)}%</span>
      },
      width: 100,
    },
  ],
  canal: [
    { title: 'Canal', dataIndex: 'Canal', width: 200, sorter: (a, b) => (a.Canal || '').localeCompare(b.Canal || '') },
    { title: 'Venta Neta', dataIndex: 'Venta Neta', render: formatMoney, width: 120, sorter: (a, b) => a['Venta Neta'] - b['Venta Neta'] },
    { title: 'Margen Final', dataIndex: 'Margen Final', render: formatMoney, width: 120 },
    { title: '% Margen', dataIndex: '% Margen Final', render: (val) => <span style={{ color: val > 25 ? '#52c41a' : val > 15 ? '#faad14' : '#ff4d4f', fontWeight: 'bold' }}>{val?.toFixed(1)}%</span>, width: 100 },
  ],
  categoria: [
    { title: 'Categoría', dataIndex: 'Categoría', width: 200, sorter: (a, b) => (a.Categoría || '').localeCompare(b.Categoría || '') },
    { title: 'Venta Neta', dataIndex: 'Venta Neta', render: formatMoney, width: 120, sorter: (a, b) => a['Venta Neta'] - b['Venta Neta'] },
    { title: 'Margen Final', dataIndex: 'Margen Final', render: formatMoney, width: 120 },
    { title: '% Margen', dataIndex: '% Margen Final', render: (val) => <span style={{ color: val > 25 ? '#52c41a' : val > 15 ? '#faad14' : '#ff4d4f', fontWeight: 'bold' }}>{val?.toFixed(1)}%</span>, width: 100 },
  ],
  bodega: [
    { title: 'Bodega', dataIndex: 'Bodega', width: 200, sorter: (a, b) => (a.Bodega || '').localeCompare(b.Bodega || '') },
    { title: 'Venta Neta', dataIndex: 'Venta Neta', render: formatMoney, width: 120, sorter: (a, b) => a['Venta Neta'] - b['Venta Neta'] },
    { title: 'Margen Final', dataIndex: 'Margen Final', render: formatMoney, width: 120 },
    { title: '% Margen', dataIndex: '% Margen Final', render: (val) => <span style={{ color: val > 25 ? '#52c41a' : val > 15 ? '#faad14' : '#ff4d4f', fontWeight: 'bold' }}>{val?.toFixed(1)}%</span>, width: 100 },
  ],
}

export function TablaResumen() {
  const { resumenes, isLoading } = useVentasStore()
  const { downloadExcel } = useVentasData()

  if (!resumenes) return null

  const tabs = [
    { label: 'Por Línea de Negocio', key: 'linea', data: resumenes.linea },
    { label: 'Por Canal', key: 'canal', data: resumenes.canal },
    { label: 'Por Categoría', key: 'categoria', data: resumenes.categoria },
    { label: 'Por Bodega', key: 'bodega', data: resumenes.bodega },
  ]

  return (
    <Card style={{ marginBottom: 20 }}>
      <Spin spinning={isLoading}>
        <Space direction="vertical" style={{ width: '100%' }} size="large">
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            onClick={downloadExcel}
            loading={isLoading}
          >
            Descargar Excel Completo
          </Button>

          <Tabs
            defaultActiveKey="linea"
            items={tabs.map(tab => ({
              label: tab.label,
              key: tab.key,
              children: (
                <Table
                  columns={columns[tab.key]}
                  dataSource={tab.data || []}
                  pagination={{ pageSize: 20 }}
                  scroll={{ x: 'max-content' }}
                  rowKey={(_, index) => index}
                  size="small"
                />
              ),
            }))}
          />
        </Space>
      </Spin>
    </Card>
  )
}
