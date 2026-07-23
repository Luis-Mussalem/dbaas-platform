"""
Gerador de carga sintética para a frota de demonstração.

Um clone limpo sobe containers PostgreSQL reais, mas ninguém os usa: o poller
mede 1 conexão, 0 transação/s e o pg_stat_statements fica vazio. O produto
funciona, só que parece desligado — sparklines planos, KPIs zerados, nenhuma
query lenta para investigar.

Este loop de background dá "vida" a essas instâncias: mantém um pool de
conexões abertas cujo tamanho segue uma curva diária (pico à tarde, vale de
madrugada, fim de semana mais fraco) e dispara um mix de queries por ciclo.
Tudo o que o resto da plataforma mede passa a ter sinal real — conexões,
transações/s, cache hit, p95 de latência, queries lentas, crescimento de disco.

Em modo demo ele roda o tempo todo numa **carga-base** leve
(`BASELINE_INTENSITY`), para a frota nunca parecer morta desde o primeiro login.
Fora do modo demo os loops nem sobem (main.py), então instâncias criadas pelo
usuário jamais recebem carga.

Escopo e segurança:
- Só toca instâncias da frota demo (`notes == DEMO_MARKER`), RUNNING e com
  connection_uri. Instâncias criadas pelo usuário nunca recebem carga.
- Só roda com `DEMO_MODE=true` e simulação ativa; o teto de conexões por
  instância é configurável (`DEMO_WORKLOAD_MAX_CONNECTIONS`).
- As conexões usam application_name='dbaas-demo-workload', então aparecem
  identificadas na tela de conexões ativas — nada disso se disfarça de
  tráfego de usuário.
- Escritas ficam confinadas à tabela `workload_events`, criada por este módulo.
  O dataset semeado (transactions/products/inventory) é só lido.

A MESMA curva (`target_connections`) alimenta o backfill histórico do seed,
para o gráfico de 24h emendar sem degrau no ponto em que o histórico sintético
termina e a carga ao vivo começa.
"""
import asyncio
import logging
import random
import uuid
from datetime import datetime, timezone
from math import cos, pi

import psycopg
from psycopg import sql as psql

from src.core.config import settings
from src.core.database import SessionLocal
from src.core.encryption import decrypt_value
from src.models.database_instance import DatabaseInstance, Environment, InstanceStatus

logger = logging.getLogger(__name__)

# Nome com que as conexões do simulador se identificam no pg_stat_activity.
APPLICATION_NAME = "dbaas-demo-workload"

# Tabela de escrita do simulador (criada na primeira passagem por instância).
WORKLOAD_TABLE = "workload_events"

# Tabela de lastro de armazenamento, gravada pelo seed (ver seed/demo.py).
# A constante vive aqui, e não no seed, porque quem a consulta a cada ciclo é
# este módulo — importá-la do seed no caminho quente exigiria import tardio.
BALLAST_TABLE = "storage_ballast"

# Linhas mantidas na tabela de escrita: o insert contínuo faria o banco crescer
# sem limite, e o gráfico de tamanho viraria uma rampa infinita.
_WORKLOAD_TABLE_MAX_ROWS = 2_000

# Hora (UTC) do pico de tráfego. A frota é global (us/eu/sa), então uma curva
# única com defasagem por instância é mais honesta que fingir fuso por região.
_PEAK_HOUR_UTC = 15.0

# Piso da curva: mesmo de madrugada um app real mantém conexões ociosas.
_TROUGH_FACTOR = 0.18

# Fim de semana movimenta menos.
_WEEKEND_FACTOR = 0.55

# Passo máximo de variação do pool por ciclo — rampa suave em vez de degrau.
# Com o ciclo acelerado (5s) da simulação, 4 conexões por passo levam o pool ao
# alvo dentro dos 18s da fase WARMUP sem virar um salto instantâneo.
_MAX_POOL_STEP = 4

# Linhas varridas pela query pesada do mix. ~20k × 640 B = ~13 MB hasheados,
# medidos em ~170 ms contra ~2 ms de uma leitura pontual: cauda suficiente para
# aparecer no p95 e no pg_stat_statements, e ainda 60× abaixo do
# statement_timeout. Sai em ~1 a cada 10s por instância (5% do mix), então é uma
# demonstração de query cara — não um teste de carga.
_HEAVY_QUERY_ROWS = 20_000

# Fração do alvo de conexões que a frota demo mantém em repouso — a carga-base
# contínua que deixa o dashboard vivo desde o primeiro login (conexões, queries/s,
# latência e crescimento de disco sempre com sinal real, medido). O backfill de 24h
# do seed usa a MESMA fração (ver seed/history), para o histórico emendar com a
# medição ao vivo sem degrau. Tunável: subir deixa a frota em repouso mais
# movimentada, ao custo de mais conexões abertas por instância.
BASELINE_INTENSITY = 0.3

# Fração das conexões do pool que dispara uma query a cada ciclo de _drive. Cada
# query roda em autocommit (= 1 transação = 1 xact_commit), então esta fração é o
# que converte "conexões abertas" em "commits por ciclo" — a base do queries/s.
# Nomeada porque `target_queries_per_second` precisa do MESMO valor que _drive usa
# para modelar a taxa que o poller vai medir.
_ACTIVE_FRACTION = 0.45

# Quantas queries LEVES cada conexão ativa dispara por ciclo. É o que dá um
# queries/s vivo (~6-12/s em prod, ~3-6/s em staging) em vez de ~0.1/s, que o card
# arredondava para "0". São leituras pontuais indexadas (microssegundos), então o
# volume é barato — a query PESADA fica de fora da rajada (_HEAVY_QUERY_PROB), para
# tráfego não virar teste de carga. Tunável: sobe/desce o queries/s proporcional.
_QUERIES_PER_ACTIVE_CONN = 100

# Probabilidade de uma conexão ativa disparar UMA query pesada no ciclo — a cauda
# que popula a tela de queries lentas. Rara de propósito (fora da rajada leve): é
# a mesma cadência esparsa de antes, agora independente do volume de leitura.
_HEAVY_QUERY_PROB = 0.05


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Curva de tráfego (compartilhada com o backfill histórico do seed)
# --------------------------------------------------------------------------- #
def _instance_phase_hours(name: str) -> float:
    """Defasagem estável (±2h) do pico por instância — evita frota em uníssono."""
    return random.Random(f"workload-phase::{name}").uniform(-2.0, 2.0)


def _jitter(name: str, at: datetime) -> float:
    """Ruído determinístico por instância e bucket de 5 min, em [-1, 1]."""
    bucket = int(at.timestamp()) // 300
    return random.Random(f"workload-jitter::{name}::{bucket}").uniform(-1.0, 1.0)


def traffic_factor(name: str, at: datetime) -> float:
    """
    Intensidade do tráfego em [0, 1] para uma instância num instante.

    Cosseno de período 24h (1.0 no pico, piso em _TROUGH_FACTOR), defasado por
    instância, amortecido no fim de semana. Determinístico: o mesmo (name, at)
    devolve sempre o mesmo valor, o que torna a curva testável e faz o
    histórico semeado bater com a carga ao vivo.
    """
    hour = at.hour + at.minute / 60.0 + _instance_phase_hours(name)
    daily = 0.5 + 0.5 * cos(2 * pi * (hour - _PEAK_HOUR_UTC) / 24.0)
    factor = _TROUGH_FACTOR + (1.0 - _TROUGH_FACTOR) * daily
    if at.weekday() >= 5:
        factor *= _WEEKEND_FACTOR
    return min(1.0, max(0.0, factor))


def target_connections(
    name: str,
    environment: Environment | None,
    at: datetime,
    cap: int | None = None,
    intensity: float = 1.0,
) -> int:
    """
    Quantas conexões esta instância deve manter abertas em `at`.

    Produção usa a faixa inteira até o teto; staging fica em ~metade dela —
    a diferença de porte entre os ambientes é o que faz a frota parecer real
    no dashboard, não só cada card isolado.

    `intensity` é o multiplicador da carga (`BASELINE_INTENSITY` ao vivo; 1.0 no
    pico da curva usado pelo backfill para dimensionar a latência).
    """
    cap = cap or settings.DEMO_WORKLOAD_MAX_CONNECTIONS
    if environment == Environment.PRODUCTION:
        low, high = max(1, cap // 5), cap
    else:
        low, high = 1, max(2, cap // 2)
    value = low + (high - low) * traffic_factor(name, at) + _jitter(name, at)
    return int(max(1, min(high, round(value * intensity))))


def target_queries_per_second(
    name: str,
    environment: Environment | None,
    at: datetime,
    intensity: float = BASELINE_INTENSITY,
) -> float:
    """
    Commits/s que a carga-base produz nesta instância em `at`.

    Modela o que `_drive` faz de fato: ~`_ACTIVE_FRACTION` das conexões abertas
    dispara uma query — cada uma em autocommit, logo uma transação e um
    `xact_commit` — a cada ciclo de `DEMO_WORKLOAD_INTERVAL_SECONDS`. Deriva do
    MESMO `target_connections` da carga viva, então a taxa modelada bate com a que
    o poller mede. É o que o seed usa para ancorar o par de `xact_commit` no boot
    (ver `seed/history._seed_xact_commit_anchor`), para o card mostrar queries/s
    já no primeiro render em vez de "—" por dois ciclos do poller.
    """
    conns = target_connections(name, environment, at, intensity=intensity)
    return (
        _ACTIVE_FRACTION
        * conns
        * _QUERIES_PER_ACTIVE_CONN
        / settings.DEMO_WORKLOAD_INTERVAL_SECONDS
    )


# --------------------------------------------------------------------------- #
# Pool de conexões por instância
# --------------------------------------------------------------------------- #
class _InstancePool:
    """Conexões vivas de uma instância + o estado que sobrevive entre ciclos."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.conns: list[psycopg.Connection] = []
        # Tabela do dataset semeado, descoberta na primeira conexão (staging
        # não tem dataset — lá o mix roda só sobre workload_events).
        self.dataset_table: str | None = None
        # A tabela de lastro do seed existe? É a única grande o bastante para a
        # query pesada custar tempo mensurável (ver _run_query).
        self.has_ballast = False
        self.prepared = False

    def close_all(self) -> None:
        for conn in self.conns:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 — encerrando, o motivo não importa
                pass
        self.conns = []


# Pools vivos, por instância. Estado de módulo (como o contador de ciclos do
# metrics_poller): o loop é único por processo.
_pools: dict[uuid.UUID, _InstancePool] = {}


def _connect(uri: str) -> psycopg.Connection:
    """
    Conexão do simulador: autocommit (cada query = uma transação, alimentando
    xact_commit, que é a base do KPI de queries/s) e statement_timeout curto
    para nenhuma query sintética prender um backend.
    """
    return psycopg.connect(
        uri,
        connect_timeout=5,
        autocommit=True,
        application_name=APPLICATION_NAME,
        options="-c statement_timeout=10000",
    )


def _prepare(pool: _InstancePool, conn: psycopg.Connection) -> None:
    """Cria a tabela de escrita e descobre a tabela do dataset (uma vez)."""
    conn.execute(
        psql.SQL(
            "CREATE TABLE IF NOT EXISTS {} ("
            "  id         BIGSERIAL PRIMARY KEY,"
            "  kind       TEXT NOT NULL,"
            "  payload    TEXT NOT NULL,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        ).format(psql.Identifier(WORKLOAD_TABLE))
    )
    # A tabela de lastro do seed é a maior do banco de longe, mas é volume
    # morto: escolhê-la como dataset faria o self-join "pesado" do mix rodar
    # sobre centenas de milhares de linhas e travar o backend.
    row = conn.execute(
        "SELECT relname FROM pg_stat_user_tables "
        "WHERE relname <> ALL(%s) ORDER BY n_live_tup DESC LIMIT 1",
        ([WORKLOAD_TABLE, BALLAST_TABLE],),
    ).fetchone()
    pool.dataset_table = row[0] if row else None
    pool.has_ballast = bool(
        conn.execute("SELECT to_regclass(%s) IS NOT NULL", (BALLAST_TABLE,)).fetchone()[0]
    )
    pool.prepared = True


def _resize(pool: _InstancePool, uri: str, target: int) -> None:
    """Aproxima o pool do alvo, no máximo _MAX_POOL_STEP conexões por ciclo."""
    current = len(pool.conns)
    if current < target:
        for _ in range(min(_MAX_POOL_STEP, target - current)):
            conn = _connect(uri)
            if not pool.prepared:
                _prepare(pool, conn)
            pool.conns.append(conn)
    elif current > target:
        for _ in range(min(_MAX_POOL_STEP, current - target)):
            conn = pool.conns.pop()
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def _run_light_query(pool: _InstancePool, conn: psycopg.Connection, rng: random.Random) -> None:
    """
    Uma query LEVE do mix OLTP: leitura pontual (dominante), escrita esporádica ou
    agregação. Cada chamada é uma transação em autocommit (= 1 xact_commit) — é o
    VOLUME destas, disparado em rajada por `_drive`, que dá o queries/s vivo do
    card. Leituras dominam de propósito: são microssegundos e não incham a tabela,
    então o volume alto sai barato. A query PESADA fica fora daqui
    (`_run_heavy_query`), para a rajada não virar teste de carga.
    """
    table = pool.dataset_table
    roll = rng.random()

    if roll < 0.90:  # leitura pontual (domina o mix)
        if table:
            conn.execute(
                psql.SQL("SELECT * FROM {} ORDER BY id LIMIT 20 OFFSET %s").format(
                    psql.Identifier(table)
                ),
                (rng.randint(0, 80),),
            ).fetchall()
        else:  # staging não tem dataset: lê a própria tabela de workload
            conn.execute(
                psql.SQL("SELECT count(*), max(created_at) FROM {}").format(
                    psql.Identifier(WORKLOAD_TABLE)
                )
            ).fetchone()
    elif roll < 0.97:  # escrita esporádica
        conn.execute(
            psql.SQL("INSERT INTO {} (kind, payload) VALUES (%s, %s)").format(
                psql.Identifier(WORKLOAD_TABLE)
            ),
            ("page_view", f"session-{rng.randint(1000, 9999)}"),
        )
        if rng.random() < 0.1:  # poda: mantém a tabela num tamanho estável
            conn.execute(
                psql.SQL(
                    "DELETE FROM {t} WHERE id < "
                    "(SELECT max(id) - %s FROM {t})"
                ).format(t=psql.Identifier(WORKLOAD_TABLE)),
                (_WORKLOAD_TABLE_MAX_ROWS,),
            )
    else:  # agregação
        target = table or WORKLOAD_TABLE
        conn.execute(
            psql.SQL("SELECT count(*) FROM {}").format(psql.Identifier(target))
        ).fetchone()


def _run_heavy_query(pool: _InstancePool, conn: psycopg.Connection, rng: random.Random) -> None:
    """
    A query cara que popula a tela de queries lentas. Chamada raramente por
    `_drive` (`_HEAVY_QUERY_PROB`), fora da rajada leve.
    """
    table = pool.dataset_table
    if pool.has_ballast:  # query pesada: agregação sobre uma fatia grande
        # O dataset semeado tem ~100 linhas: um self-join sobre ele terminava em
        # microssegundos e a tela de queries lentas não tinha nada para
        # investigar. A tabela de lastro tem centenas de milhares de linhas —
        # hashear uma fatia dela custa dezenas de ms e produz uma cauda de p95
        # de verdade. A fatia é LIMITADA de propósito: uma query pesada numa
        # demo tem que ser cara, não perigosa.
        conn.execute(
            psql.SQL(
                "SELECT count(DISTINCT md5(blob)) FROM ("
                "  SELECT blob FROM {} ORDER BY id OFFSET %s LIMIT %s"
                ") s"
            ).format(psql.Identifier(BALLAST_TABLE)),
            (rng.randint(0, 20_000), _HEAVY_QUERY_ROWS),
        ).fetchone()
    elif table:  # sem lastro (instância criada pelo usuário): self-join no dataset
        conn.execute(
            psql.SQL(
                "SELECT count(*) FROM {t} a JOIN {t} b ON a.id <> b.id "
                "WHERE b.id < 40"
            ).format(t=psql.Identifier(table))
        ).fetchone()
    else:
        conn.execute(
            psql.SQL("SELECT count(*), max(created_at) FROM {}").format(
                psql.Identifier(WORKLOAD_TABLE)
            )
        ).fetchone()


def _drive(pool: _InstancePool, rng: random.Random) -> int:
    """Dispara o mix em parte do pool. Conexão que falha é descartada."""
    executed = 0
    for conn in list(pool.conns):
        # Nem toda conexão de um app está executando algo a cada instante —
        # as ociosas contam para numbackends e mantêm a curva de conexões.
        if rng.random() > _ACTIVE_FRACTION:
            continue
        try:
            # Rajada de queries leves: o volume que dá o queries/s vivo do card.
            for _ in range(_QUERIES_PER_ACTIVE_CONN):
                _run_light_query(pool, conn, rng)
                executed += 1
            # Uma pesada de vez em quando, para a tela de queries lentas ter carne.
            if rng.random() < _HEAVY_QUERY_PROB:
                _run_heavy_query(pool, conn, rng)
                executed += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug("Workload: conexão descartada em %s: %s", pool.name, exc)
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            if conn in pool.conns:
                pool.conns.remove(conn)
    return executed


# --------------------------------------------------------------------------- #
# Ciclo e loop
# --------------------------------------------------------------------------- #
def _demo_instances(db) -> list[DatabaseInstance]:
    from src.seed.demo import DEMO_MARKER  # lazy: evita import circular

    return (
        db.query(DatabaseInstance)
        .filter(
            DatabaseInstance.notes == DEMO_MARKER,
            DatabaseInstance.status == InstanceStatus.RUNNING,
            DatabaseInstance.deleted_at.is_(None),
            DatabaseInstance.connection_uri.isnot(None),
        )
        .all()
    )


def simulate_once() -> None:
    """
    Um ciclo: ajusta o pool de cada instância demo ao alvo da carga-base e roda o
    mix de queries. Erro numa instância (container parado, rede) não cancela as
    demais — o pool dela é fechado e recomeça no ciclo seguinte.

    Roda sempre à intensidade da carga-base: o loop só sobe em modo demo (main.py),
    então os pools ficam abertos continuamente enquanto houver instâncias demo, e
    a frota nunca parece morta.
    """
    db = SessionLocal()
    try:
        instances = _demo_instances(db)
        alive = {inst.id for inst in instances}

        # Instância que saiu da frota (parada, removida): devolve as conexões.
        for instance_id in list(_pools):
            if instance_id not in alive:
                _pools.pop(instance_id).close_all()

        # Hora-do-dia real: a curva posiciona o alvo de conexões pelo horário.
        now = _now()
        for inst in instances:
            pool = _pools.setdefault(inst.id, _InstancePool(inst.name))
            try:
                # A URI decriptada vive só dentro deste ciclo — nunca é guardada
                # no pool (mesma disciplina do metrics.get_connection).
                uri = decrypt_value(inst.connection_uri)
                _resize(
                    pool,
                    uri,
                    target_connections(
                        inst.name, inst.environment, now, intensity=BASELINE_INTENSITY
                    ),
                )
                executed = _drive(pool, random.Random())
                logger.debug(
                    "Workload %s: %d conexões, %d queries",
                    inst.name,
                    len(pool.conns),
                    executed,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("Workload: ciclo falhou em %s: %s", inst.name, exc)
                pool.close_all()
    finally:
        db.close()


def shutdown_pools() -> None:
    """Fecha todas as conexões — chamado no shutdown do app."""
    for pool in _pools.values():
        pool.close_all()
    _pools.clear()


async def workload_loop(stop_event: asyncio.Event) -> None:
    """
    Loop async do simulador (mesmo padrão do metrics_polling_loop).

    O intervalo é bem menor que o do poller de métricas: a curva precisa se
    mover entre duas coletas, senão o gráfico de conexões vira uma escada.
    """
    interval = settings.DEMO_WORKLOAD_INTERVAL_SECONDS
    logger.info("Demo workload generator iniciado (intervalo: %ds)", interval)

    while not stop_event.is_set():
        try:
            await asyncio.to_thread(simulate_once)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Erro no ciclo do workload generator: %s", exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue

    await asyncio.to_thread(shutdown_pools)
    logger.info("Demo workload generator encerrado.")
