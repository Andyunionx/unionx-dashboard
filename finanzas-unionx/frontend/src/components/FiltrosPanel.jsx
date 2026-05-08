/**
 * Panel de filtros
 * Período, Canal, Categoría, Bodega
 */
import { Card, Row, Col, Button, Select, DatePicker, Space } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { useVentasStore } from '../store/ventasStore'
import { useVentasData } from '../hooks/useVentasData'

export function FiltrosPanel() {
  const store = useVentasStore()
  const { triggerRefresh, applyFilters } = useVentasData()

  const handleRefresh = async () => {
    await triggerRefresh(store.periodo_inicio, store.periodo_fin)
  }

  const handleFilterChange = async (field, value) => {
    const newFilters = {
      canal: field === 'canal' ? value : store.canal,
      categoria: field === 'categoria' ? value : store.categoria,
      bodega: field === 'bodega' ? value : store.bodega,
    }
    await applyFilters(newFilters.canal, newFilters.categoria, newFilters.bodega)
  }

  const handlePeriodoChange = (dates) => {
    if (dates && dates.length === 2) {
      const inicio = dates[0].format('YYYY-MM-01')
      const fin = dates[1].format('YYYY-MM-DD')
      store.setPeriodo(inicio, fin)
    }
  }

  const opciones = store.filtrosDisponibles || {}

  return (
    <Card style={{ marginBottom: 20 }}>
      <Space direction="vertical" style={{ width: '100%' }} size="large">
        <Row gutter={16}>
          <Col span={6}>
            <label style={{ display: 'block', marginBottom: 8, fontSize: 12, fontWeight: 'bold' }}>
              Período
            </label>
            <Button
              block
              onClick={handleRefresh}
              type="primary"
              icon={<ReloadOutlined />}
            >
              Actualizar Datos ({store.periodo_inicio})
            </Button>
          </Col>

          <Col span={6}>
            <label style={{ display: 'block', marginBottom: 8, fontSize: 12, fontWeight: 'bold' }}>
              Canal
            </label>
            <Select
              allowClear
              placeholder="Todos los canales"
              value={store.canal}
              onChange={(val) => handleFilterChange('canal', val)}
              options={opciones.canales?.map(c => ({ label: c, value: c })) || []}
              disabled={!opciones.canales}
            />
          </Col>

          <Col span={6}>
            <label style={{ display: 'block', marginBottom: 8, fontSize: 12, fontWeight: 'bold' }}>
              Categoría
            </label>
            <Select
              allowClear
              placeholder="Todas las categorías"
              value={store.categoria}
              onChange={(val) => handleFilterChange('categoria', val)}
              options={opciones.categorias?.map(c => ({ label: c, value: c })) || []}
              disabled={!opciones.categorias}
            />
          </Col>

          <Col span={6}>
            <label style={{ display: 'block', marginBottom: 8, fontSize: 12, fontWeight: 'bold' }}>
              Bodega
            </label>
            <Select
              allowClear
              placeholder="Todas las bodegas"
              value={store.bodega}
              onChange={(val) => handleFilterChange('bodega', val)}
              options={opciones.bodegas?.map(b => ({ label: b, value: b })) || []}
              disabled={!opciones.bodegas}
            />
          </Col>
        </Row>
      </Space>
    </Card>
  )
}
