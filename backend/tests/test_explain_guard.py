"""
Testes do guard SELECT-only de collect_explain (FASE 4).

Este é o mesmo guard que o SQL Console (FRONTEND F7) vai reusar para a execução
read-only de SQL — por isso vale travar o comportamento agora, antes do reuso.

As validações (tamanho, ponto-e-vírgula, startswith select, blacklist DML/DDL)
rodam ANTES de qualquer uso da conexão. Logo, passamos conn=None: nas entradas
inválidas a função levanta ValueError sem nunca tocar no banco. Não há
dependência de Postgres aqui.
"""
import pytest

from src.collectors.pg_stats import _EXPLAIN_MAX_LEN, collect_explain


def test_rejects_query_over_max_length():
    huge = "select " + "a" * (_EXPLAIN_MAX_LEN + 1)
    with pytest.raises(ValueError, match="too long"):
        collect_explain(None, huge)


def test_rejects_semicolon():
    with pytest.raises(ValueError, match="[Ss]emicolon"):
        collect_explain(None, "select 1; drop table users")


@pytest.mark.parametrize(
    "query",
    [
        "delete from users",
        "update users set x = 1",
        "insert into users values (1)",
        "  drop table users  ",
        "with x as (select 1) delete from users",  # não começa com select
    ],
)
def test_rejects_non_select_start(query):
    with pytest.raises(ValueError):
        collect_explain(None, query)


@pytest.mark.parametrize(
    "keyword,query",
    [
        ("delete", "select * from (delete from users returning *) t"),
        ("update", "select * from foo where x in (update bar set y=1 returning id)"),
        ("drop", "select 1 where false union select drop"),
        ("truncate", "select truncate"),
    ],
)
def test_rejects_blocked_keyword_inside_select(keyword, query):
    with pytest.raises(ValueError, match="disallowed keyword"):
        collect_explain(None, query)


def test_case_insensitive_and_whitespace_tolerant():
    # SELECT maiúsculo com espaços à frente passa pela validação e só falha ao
    # tentar usar a conexão None — provando que o guard não barrou a query.
    with pytest.raises(AttributeError):
        collect_explain(None, "   SELECT 1   ")
