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
  O schema de negócio semeado (catálogo + tabela-fato payments/sales) é só lido.

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

# Linhas varridas pela query pesada do mix: uma agregação "receita por hora" sobre
# uma FATIA limitada da tabela-fato de negócio (payments/sales). ~20k linhas
# varridas + agregadas custam dezenas de ms contra ~2 ms de uma leitura pontual:
# cauda suficiente para aparecer no p95 e no pg_stat_statements, ainda muito abaixo
# do statement_timeout. Sai em ~1 a cada 10s por instância (5% do mix) — uma query
# de negócio cara, não um teste de carga.
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
# tráfego não virar teste de carga.
#
# Dimensionado JUNTO com DEMO_WORKLOAD_INTERVAL_SECONDS (5s): a taxa-base é
# `_ACTIVE_FRACTION × conns × este / intervalo`, então rajadas menores e mais
# frequentes (5s) dão o MESMO queries/s que 100/15s, porém distribuído — cada
# janela de coleta de 15s cobre ~3 rajadas, o que tira o aliasing do gráfico de
# queries/s (antes, poll e rajada tinham o mesmo período de 15s e batiam mal).
_QUERIES_PER_ACTIVE_CONN = 33

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
        # Maior tabela de negócio (a fato: payments/sales), descoberta na primeira
        # conexão. É o alvo das leituras leves e da query pesada.
        self.dataset_table: str | None = None
        # A tabela-fato tem `amount` + `created_at`? Só então a query pesada roda a
        # agregação "receita por hora"; senão cai para uma contagem barata.
        self.bulk_ready = False
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
    """Cria a tabela de escrita e descobre a tabela-fato (numa conexão nova)."""
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
    _discover(pool, conn)


def _discover(pool: _InstancePool, conn: psycopg.Connection) -> None:
    """
    (Re)descobre a maior tabela de negócio (payments/sales) e se ela serve à query
    pesada. Barato — roda de novo a cada ciclo ENQUANTO ainda não achou a fato, e
    após um erro (ex.: o seed migrou o schema por baixo do pool, dropando a antiga).
    `prepared` só vira True quando há uma fato, então um boot onde a carga sobe antes
    do seed terminar continua tentando até a tabela existir.
    """
    # A maior tabela (excluída a de escrita) é a fato de negócio (payments/sales):
    # é onde a leitura pontual busca e onde a query pesada agrega uma fatia.
    row = conn.execute(
        "SELECT relname FROM pg_stat_user_tables "
        "WHERE relname <> %s ORDER BY n_live_tup DESC LIMIT 1",
        (WORKLOAD_TABLE,),
    ).fetchone()
    pool.dataset_table = row[0] if row else None
    # A query pesada agrega por `amount`/`created_at`; só a rode se a tabela os tem
    # (toda tabela-fato do seed tem — mas uma instância a meio de semear, não).
    pool.bulk_ready = bool(
        pool.dataset_table
        and conn.execute(
            "SELECT count(*) = 2 FROM information_schema.columns "
            "WHERE table_name = %s AND column_name IN ('amount', 'created_at')",
            (pool.dataset_table,),
        ).fetchone()[0]
    )
    pool.prepared = pool.dataset_table is not None


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
        else:  # sem tabela-fato ainda: lê a própria tabela de workload
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
    else:  # agregação LEVE: contagem sobre uma cauda recente, não a tabela inteira
        # (count(*) na fato de milhões de linhas seria um seq scan caro no meio da
        # rajada; aqui a fatia é limitada pela PK e sai em microssegundos).
        target = table or WORKLOAD_TABLE
        conn.execute(
            psql.SQL(
                "SELECT count(*) FROM (SELECT id FROM {} ORDER BY id DESC LIMIT 200) s"
            ).format(psql.Identifier(target))
        ).fetchone()


def _run_heavy_query(pool: _InstancePool, conn: psycopg.Connection, rng: random.Random) -> None:
    """
    A query cara que popula a tela de queries lentas. Chamada raramente por
    `_drive` (`_HEAVY_QUERY_PROB`), fora da rajada leve.
    """
    table = pool.dataset_table
    if pool.bulk_ready and table:
        # Relatório "receita por hora" sobre uma FATIA limitada da tabela-fato:
        # varre ~_HEAVY_QUERY_ROWS linhas e agrega por hora — dezenas de ms, uma
        # cauda de p95 de verdade e uma query que faz sentido de negócio na tela de
        # slow queries. A fatia é LIMITADA de propósito: cara, não perigosa.
        conn.execute(
            psql.SQL(
                "SELECT date_trunc('hour', created_at) AS bucket, count(*), "
                "round(sum(amount), 2) FROM ("
                "  SELECT amount, created_at FROM {} ORDER BY id OFFSET %s LIMIT %s"
                ") s GROUP BY bucket ORDER BY bucket DESC"
            ).format(psql.Identifier(table)),
            (rng.randint(0, 20_000), _HEAVY_QUERY_ROWS),
        ).fetchall()
    else:  # tabela-fato ainda não pronta: contagem barata no buffer de escrita
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
            # O schema pode ter mudado sob o pool (o seed migrou a tabela-fato):
            # força a redescoberta no próximo ciclo, contra o schema atual.
            pool.prepared = False
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
                # A fato pode surgir DEPOIS de o pool já estar no alvo (o seed ainda
                # semeando no boot): enquanto não a achamos, redescobre a cada ciclo
                # numa conexão existente, sem esperar o pool crescer.
                if not pool.prepared and pool.conns:
                    _discover(pool, pool.conns[0])
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
