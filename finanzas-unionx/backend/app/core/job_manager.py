"""
Gestor de jobs de extracción Odoo.
Mantiene el estado de los jobs en memoria (simple dict).
"""
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, Optional
import threading


@dataclass
class JobState:
    """Estado de un job de extracción"""
    job_id: str
    status: str  # PENDING | RUNNING | DONE | ERROR
    progress: int  # 0-100
    progress_label: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    error: Optional[str] = None

    def to_dict(self):
        """Convierte a dict serializable (datetime → ISO string)"""
        data = asdict(self)
        data['started_at'] = self.started_at.isoformat()
        data['finished_at'] = self.finished_at.isoformat() if self.finished_at else None
        return data


class JobManager:
    """
    Gestor de jobs en memoria.
    Un job es un proceso de extracción Odoo que corre en background (Thread).
    """

    def __init__(self):
        self._jobs: Dict[str, JobState] = {}
        self._lock = threading.Lock()

    def create_job(self, job_id: str) -> JobState:
        """Crea un nuevo job en estado PENDING"""
        with self._lock:
            if job_id in self._jobs:
                raise ValueError(f"Job {job_id} ya existe")

            job = JobState(
                job_id=job_id,
                status='PENDING',
                progress=0,
                progress_label='Inicializando...',
                started_at=datetime.now()
            )
            self._jobs[job_id] = job
            return job

    def start_job(self, job_id: str):
        """Marca el job como RUNNING"""
        with self._lock:
            if job_id not in self._jobs:
                raise ValueError(f"Job {job_id} no existe")
            self._jobs[job_id].status = 'RUNNING'
            self._jobs[job_id].progress = 0

    def update_progress(self, job_id: str, progress: int, label: str):
        """Actualiza el progreso de un job"""
        with self._lock:
            if job_id not in self._jobs:
                raise ValueError(f"Job {job_id} no existe")

            job = self._jobs[job_id]
            job.progress = min(100, max(0, progress))  # 0-100
            job.progress_label = label
            job.status = 'RUNNING'

    def mark_done(self, job_id: str):
        """Marca el job como DONE"""
        with self._lock:
            if job_id not in self._jobs:
                raise ValueError(f"Job {job_id} no existe")
            job = self._jobs[job_id]
            job.status = 'DONE'
            job.progress = 100
            job.progress_label = 'Completado'
            job.finished_at = datetime.now()

    def mark_error(self, job_id: str, error: str):
        """Marca el job como ERROR"""
        with self._lock:
            if job_id not in self._jobs:
                raise ValueError(f"Job {job_id} no existe")
            job = self._jobs[job_id]
            job.status = 'ERROR'
            job.error = error
            job.finished_at = datetime.now()

    def get_status(self, job_id: str) -> Optional[Dict]:
        """Obtiene el estado actual de un job (dict serializable)"""
        with self._lock:
            if job_id not in self._jobs:
                return None
            return self._jobs[job_id].to_dict()

    def get_all_jobs(self) -> Dict[str, Dict]:
        """Obtiene todos los jobs (para debugging)"""
        with self._lock:
            return {job_id: job.to_dict() for job_id, job in self._jobs.items()}


# Instancia global del job manager
job_manager = JobManager()
