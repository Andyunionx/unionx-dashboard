/**
 * Tabla paginada de detalle para Maestra de Ventas
 */
import { Table, Card, Input, Button, Space, Tag } from 'antd'
import { DownloadOutlined, SearchOutlined } from '@ant-design/icons'
import { useMaestraStore } from '../store/maestraStore'

const fmtCLP = (v) => v != null ? `$${Number(v).toLocaleString('es-CL')}` : '-'

export function MaestraTabla({ onPageChange, onSearch, onSort, onExport, exportLabel = 'Excel' }) {
  const { detalle, page, pageSize, search, isLoading } = useMaestraStore()

  const columns = [
    { title: 'Fecha', dataIndex: 'fecha_venta', key: 'fecha_venta', width: 100, sorter: true },
    { title: 'SKU', dataIndex: 'sku', key: 'sku', width: 130, ellipsis: true },
    { title: 'Producto', dataIndex: 'producto', key: 'producto', width: 220, ellipsis: true },
    { title: 'Canal', dataIndex: 'canal', key: 'canal', width: 130, ellipsis: true },
    { title: 'Marca', dataIndex: 'marca', key: 'marca', width: 110, ellipsis: true },
    { title: 'Categoria', dataIndex: 'categoria_macro', key: 'categoria_macro', width: 110, ellipsis: true },
    { title: 'Cant', dataIndex: 'cantidad', key: 'cantidad', width: 60, align: 'right', sorter: true },
    {
      title: 'Venta Bruta', dataIndex: 'venta_bruta', key: 'venta_bruta', width: 120,
      align: 'right', sorter: true, render: fmtCLP,
    },
    {
      title: 'Costo', dataIndex: 'costo_total', key: 'costo_total', width: 100,
      align: 'right', render: fmtCLP,
    },
    {
      title: 'Margen Final', dataIndex: 'margen_final', key: 'margen_final', width: 120,
      align: 'right', sorter: true, render: (v) => {
        const color = v > 0 ? '#52c41a' : v < 0 ? '#ff4d4f' : '#999'
        return <span style={{ color, fontWeight: 500 }}>{fmtCLP(v)}</span>
      },
    },
  ]

  const handleTableChange = (pagination, _, sorter) => {
    if (pagination.current !== page) {
      onPageChange(pagination.current)
    }
    if (sorter.field && sorter.order) {
      onSort(sorter.field, sorter.order === 'ascend' ? 'asc' : 'desc')
    }
  }

  return (
    <Card
      title="Detalle de Transacciones"
      size="small"
      extra={
        <Space>
          <Input.Search
            placeholder="Buscar SKU o producto..."
            size="small"
            style={{ width: 250 }}
            allowClear
            defaultValue={search}
            onSearch={onSearch}
            enterButton={<SearchOutlined />}
          />
          <Button size="small" icon={<DownloadOutlined />} onClick={onExport}>
            {exportLabel}
          </Button>
        </Space>
      }
    >
      <Table
        columns={columns}
        dataSource={detalle?.data || []}
        rowKey={(r) => `${r.fecha_venta}-${r.sku}-${r.canal}-${r.venta_bruta}`}
        loading={isLoading}
        size="small"
        scroll={{ x: 1200 }}
        onChange={handleTableChange}
        pagination={{
          current: detalle?.page || 1,
          pageSize: detalle?.page_size || 50,
          total: detalle?.total || 0,
          showTotal: (total) => `${total.toLocaleString('es-CL')} registros`,
          showSizeChanger: false,
        }}
      />
    </Card>
  )
}
