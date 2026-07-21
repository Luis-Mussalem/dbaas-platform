from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.models.user import User
from src.schemas.demo import SimulationStatus
from src.services import demo_simulation

router = APIRouter(prefix="/demo", tags=["Demo"])


def _require_demo_mode() -> None:
    """
    Fora do modo demo estes endpoints não existem — 404, não 403: numa
    instalação real não faz sentido anunciar que há um gerador de dados falsos.
    """
    if not settings.DEMO_MODE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.get(
    "/simulation",
    response_model=SimulationStatus,
    summary="Get the current state of the usage simulation",
)
def get_simulation(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> SimulationStatus:
    """
    Estado do roteiro: fase atual, progresso, log de eventos e se a frota
    contém dados semeados pela simulação.

    Continua respondendo com DEMO_MODE desligado (com `enabled: false`), para o
    frontend simplesmente esconder o controle em vez de tratar erro.
    """
    return SimulationStatus.model_validate(demo_simulation.status(db))


@router.post(
    "/simulation/start",
    response_model=SimulationStatus,
    summary="Start the scripted usage simulation on the demo fleet",
)
def start_simulation(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> SimulationStatus:
    """
    Inicia o roteiro (backfill → tráfego → alerta → backup → manutenção →
    recuperação → regime). Idempotente: chamar com a simulação já rodando
    devolve o estado atual sem reiniciar nada.
    """
    _require_demo_mode()
    demo_simulation.start(db)
    return SimulationStatus.model_validate(demo_simulation.status(db))


@router.post(
    "/simulation/stop",
    response_model=SimulationStatus,
    summary="Stop the simulation, keeping the data it produced",
)
def stop_simulation(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> SimulationStatus:
    """Para o tráfego e o roteiro. Os dados gerados continuam navegáveis."""
    _require_demo_mode()
    demo_simulation.stop(db)
    return SimulationStatus.model_validate(demo_simulation.status(db))


@router.post(
    "/simulation/reset",
    response_model=SimulationStatus,
    summary="Erase everything the simulation produced and restore the real fleet",
)
def reset_simulation(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> SimulationStatus:
    """
    Apaga métricas, alertas, backups (registros e arquivos), manutenção,
    histórico de status e audit das empresas demo, restaurando o `created_at`
    original das instâncias. Containers e dataset permanecem — são reais.
    """
    _require_demo_mode()
    demo_simulation.reset(db)
    return SimulationStatus.model_validate(demo_simulation.status(db))
