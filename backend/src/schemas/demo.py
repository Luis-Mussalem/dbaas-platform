from datetime import datetime

from pydantic import BaseModel


class SimulationEvent(BaseModel):
    """Uma linha do log do roteiro, exibida na página da demonstração."""

    at: datetime
    phase: str
    message: str


class SimulationStatus(BaseModel):
    """
    Estado da simulação de uso, consumido pelo banner e pela página /demo.

    `has_simulated_data` é independente de `running`: quando a simulação para,
    os dados que ela semeou continuam no banco — e o aviso de "uso simulado"
    continua na tela até o usuário limpar.
    """

    enabled: bool
    running: bool
    phase: str
    phase_index: int
    phase_count: int
    phase_progress: float
    # Progresso do roteiro inteiro (0-1). É o que a barra do banner mostra:
    # o da fase zera a cada etapa e parecia andar para trás.
    progress: float = 0.0
    has_simulated_data: bool
    speed_factor: float
    started_at: datetime | None = None
    events: list[SimulationEvent] = []
