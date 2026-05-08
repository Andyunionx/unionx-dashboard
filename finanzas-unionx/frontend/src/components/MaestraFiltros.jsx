/**
 * Panel de filtros para Maestra de Ventas
 */
import { Card, Row, Col, Select, DatePicker, Button, Space } from 'antd'
import { FilterOutlined, ClearOutlined } from '@ant-design/icons'
import { useMaestraStore } from '../store/maestraStore'
import dayjs from 'dayjs'

const { RangePicker } = DatePicker

export function MaestraFiltros({ onApply }) {
  const { filtros, filtrosDisponibles, setFiltro, resetFiltros } = useMaestraStore()

  if (!filtrosDisponibles) return null

  const handleDateChange = (dates) => {
    if (dates) {
      setFiltro('fecha_desde', dates[0].format('YYYY-MM-DD'))
      setFiltro('fecha_hasta', dates[1].format('YYYY-MM-DD'))
    } else {
      setFiltro('fecha_desde', null)
      setFiltro('fecha_hasta', null)
    }
  }

  const handleReset = () => {
    resetFiltros()
    onApply()
  }

  const selectProps = {
    allowClear: true,
    showSearch: true,
    style: { width: '100%' },
    optionFilterProp: 'label',
  }

  return (
    <Card
      title={<><FilterOutlined /> Filtros</>}
      size="small"
      extra={
        <Space>
          <Button size="small" icon={<ClearOutlined />} onClick={handleReset}>Limpiar</Button>
          <Button size="small" type="primary" onClick={onApply}>Aplicar</Button>
        </Space>
      }
    >
      <Row gutter={[12, 12]}>
        <Col xs={24} sm={12} md={6}>
          <label style={{ fontSize: 12, color: '#999' }}>Periodo</label>
          <RangePicker
            style={{ width: '100%' }}
            size="small"
            value={filtros.fecha_desde ? [dayjs(filtros.fecha_desde), dayjs(filtros.fecha_hasta)] : null}
            onChange={handleDateChange}
          />
        </Col>
        <Col xs={24} sm={12} md={4}>
          <label style={{ fontSize: 12, color: '#999' }}>Canal</label>
          <Select
            {...selectProps}
            size="small"
            placeholder="Todos"
            value={filtros.canal}
            onChange={(v) => setFiltro('canal', v)}
            options={filtrosDisponibles.canales?.map(c => ({ label: c, value: c }))}
          />
        </Col>
        <Col xs={24} sm={12} md={3}>
          <label style={{ fontSize: 12, color: '#999' }}>Marca</label>
          <Select
            {...selectProps}
            size="small"
            placeholder="Todas"
            value={filtros.marca}
            onChange={(v) => setFiltro('marca', v)}
            options={filtrosDisponibles.marcas?.map(c => ({ label: c, value: c }))}
          />
        </Col>
        <Col xs={24} sm={12} md={3}>
          <label style={{ fontSize: 12, color: '#999' }}>Categoria</label>
          <Select
            {...selectProps}
            size="small"
            placeholder="Todas"
            value={filtros.categoria}
            onChange={(v) => setFiltro('categoria', v)}
            options={filtrosDisponibles.categorias?.map(c => ({ label: c, value: c }))}
          />
        </Col>
        <Col xs={24} sm={12} md={3}>
          <label style={{ fontSize: 12, color: '#999' }}>Tipo Negocio</label>
          <Select
            {...selectProps}
            size="small"
            placeholder="Todos"
            value={filtros.tipo_negocio}
            onChange={(v) => setFiltro('tipo_negocio', v)}
            options={filtrosDisponibles.tipos_negocio?.map(c => ({ label: c, value: c }))}
          />
        </Col>
        <Col xs={24} sm={12} md={3}>
          <label style={{ fontSize: 12, color: '#999' }}>KAM</label>
          <Select
            {...selectProps}
            size="small"
            placeholder="Todos"
            value={filtros.kam}
            onChange={(v) => setFiltro('kam', v)}
            options={filtrosDisponibles.kams?.map(c => ({ label: c, value: c }))}
          />
        </Col>
        <Col xs={24} sm={12} md={2}>
          <label style={{ fontSize: 12, color: '#999' }}>Bodega</label>
          <Select
            {...selectProps}
            size="small"
            placeholder="Todas"
            value={filtros.bodega}
            onChange={(v) => setFiltro('bodega', v)}
            options={filtrosDisponibles.bodegas?.map(c => ({ label: c, value: c }))}
          />
        </Col>
      </Row>
    </Card>
  )
}
