import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Float, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class SimulationPhase(str, enum.Enum):
    """
    Fases do roteiro de demonstração, na ordem em que o diretor as executa.

    IDLE é o estado de repouso — nenhuma simulação rodando. STEADY é o fim do
    roteiro: o tráfego continua indefinidamente até o usuário parar.
    """

    IDLE = "idle"
    BACKFILL = "backfill"
    WARMUP = "warmup"
    ALERT = "alert"
    BACKUP = "backup"
    MAINTENANCE = "maintenance"
    RECOVER = "recover"
    STEADY = "steady"


class DemoSimulation(Base):
    """
    Estado (singleton) da simulação de uso da frota demo.

    Por que no banco e não em memória do processo?
    - sobrevive a restart do backend (o roteiro continua de onde parou);
    - é a mesma verdade para todas as abas e usuários que estiverem olhando;
    - `restore_points` é justamente o que o reset precisa para desfazer o que a
      simulação alterou nos registros reais (o backdate de created_at).

    Uma única linha existe; `get_state()` no serviço a cria na primeira leitura.
    """

    __tablename__ = "demo_simulation"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    phase: Mapped[SimulationPhase] = mapped_column(
        SAEnum(SimulationPhase, name="simulationphase"),
        nullable=False,
        default=SimulationPhase.IDLE,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    phase_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    stopped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Governa o banner de "uso simulado" e o botão de limpeza: continua True
    # depois que a simulação para, porque os dados semeados seguem no banco.
    has_simulated_data: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    speed_factor: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    # {instance_id: created_at ISO} — estado real anterior ao backfill.
    restore_points: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    # Log curto do roteiro: [{at, phase, message}] — exibido na página da demo.
    events: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
