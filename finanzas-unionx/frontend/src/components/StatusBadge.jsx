/**
 * Componente para mostrar estado del job con barra de progreso
 */
import { Progress, Card, Spin, Alert } from 'antd'
import { useVentasStore } from '../store/ventasStore'

export function StatusBadge() {
  const { jobStatus, jobProgress, jobLabel, error, isLoading } = useVentasStore()

  if (!isLoading && !jobStatus) return null

  if (error) {
    return (
      <Card style={{ marginBottom: 20 }}>
        <Alert
          message="Error"
          description={error}
          type="error"
          showIcon
          closable
        />
      </Card>
    )
  }

  if (!isLoading) return null

  return (
    <Card style={{ marginBottom: 20, backgroundColor: '#fafafa' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
        <Spin size="large" />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 'bold', marginBottom: 8 }}>
            {jobLabel}
          </div>
          <Progress
            percent={jobProgress}
            status={jobStatus === 'ERROR' ? 'exception' : 'active'}
            strokeColor={jobStatus === 'DONE' ? '#52c41a' : '#1890ff'}
          />
          <div style={{ fontSize: 12, color: '#999', marginTop: 8 }}>
            {jobProgress}% completo
          </div>
        </div>
      </div>
    </Card>
  )
}
