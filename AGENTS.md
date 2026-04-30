# PalmTreeDB — Agent Instructions

> Documento central de orientação para o GitHub Copilot neste projeto.
> Atualizar sempre que houver mudança de convenções, stack ou cronograma.

> ⚠️ **REGRA DE SEGURANÇA — NUNCA IGNORAR**
>
> As informações abaixo **jamais devem ir ao GitHub**, em nenhuma circunstância:
> - Senhas (banco, pgAdmin, APIs externas)
> - Chaves secretas JWT (`JWT_SECRET_KEY`)
> - Tokens de API (Stripe, AWS, SendGrid, etc.)
> - Strings de conexão com credenciais reais
> - Qualquer arquivo `.env` com valores reais de produção ou staging
>
> O arquivo `.env` está no `.gitignore` justamente por isso.
> O `.env.example` existe para documentar **quais variáveis existem**, mas com
> valores fictícios/placeholder — nunca com valores reais.
>
> Antes de qualquer `git add`, verificar: **nenhum dado sensível está sendo commitado.**
> Em caso de dúvida, usar `git diff --staged` para revisar o que está na área de stage.

> 🖥️ **ENCERRAMENTO DO DIA — SEMPRE EXECUTAR ANTES DE FECHAR**
>
> Este é um PC pessoal usado para tarefas pesadas. Nada deve ficar rodando
> desnecessariamente em background. Ao finalizar o dia:
>
> ```bash
> # 1. Parar a API (Ctrl+C no terminal do uvicorn, ou:)
> kill $(lsof -t -i :8001)
>
> # 2. Parar os containers Docker
> sudo docker compose down
>
> # 3. Confirmar que nada ficou rodando
> sudo docker compose ps
> ```
>
> Para retomar no próximo dia:
>
> ```bash
> sudo docker compose up -d
> source .venv/bin/activate
> uvicorn src.main:app --reload --port 8001
> ```

---

## 1. Contexto do Projeto

**PalmTreeDB** — plataforma de gerenciamento de bancos de dados PostgreSQL,
focada em **provisionar, monitorar, automatizar e tornar inquebráveis** os bancos
de dados de cada cliente.

**Visão de produto:** Serviço de DBA para PMEs (pequenas e médias empresas),
inicialmente no Brasil, com potencial de expansão futura. Muitas startups e
empresas menores rodam PostgreSQL sem DBA dedicado — PalmTreeDB é a ferramenta
que permite a um operador solo gerenciar múltiplos bancos de clientes com
monitoramento, backup, manutenção automatizada e alertas proativos. O projeto
é simultaneamente o produto e um instrumento de aprendizado profundo em
engenharia de banco de dados.

O repositório é **público** (portfólio para recrutadores), portanto apenas a
arquitetura genérica e reutilizável deve ser commitada. Configurações específicas
de clientes e integrações proprietárias ficam em repositórios privados separados.

**Operação:** Single-operator — o próprio desenvolvedor gerencia toda a plataforma.
Não há necessidade de sistema multi-usuário ou multi-tenant por enquanto. A
autenticação existente (FASE 1) serve como admin access para proteger a API.

**Pilares do produto:**
- **Monitoramento** — Visibilidade profunda sobre cada banco gerenciado (queries, locks, bloat, índices)
- **Backup & Recovery** — Garantia de segurança dos dados, essencial para confiança dos clientes
- **Manutenção Automatizada** — VACUUM, REINDEX, tuning, gestão de conexões
- **Alertas Proativos** — Detecção de problemas antes que impactem o cliente

**Princípios:**
- Dominar a engenharia de banco de dados na prática (provisioning, monitoring, backup, maintenance)
- Código limpo e bem estruturado que demonstra competência técnica
- Cada bloco funciona de forma independente e incremental
- Bancos dos clientes devem ser recuperáveis, monitorados e automatizados

---

## 2. Stack do Projeto

| Camada     | Tecnologia                                           |
|------------|------------------------------------------------------|
| Framework  | FastAPI 0.115.0 (Python 3.12)                        |
| ORM        | SQLAlchemy 2.0.44 — **SYNC sempre** (Session + psycopg) |
| Migrations | Alembic 1.17.2                                       |
| Database   | PostgreSQL 16 Alpine                                  |
| DB Admin   | pgAdmin                                              |
| Ambiente   | WSL2 Ubuntu 24.04, venv em `.venv/`                  |

---

## 3. Instruções de Resposta

1. **Contexto primeiro** — Antes de qualquer ação, consultar o estado atual do
   projeto (arquitetura, erros pendentes, fase do cronograma).
2. **Ordem cronológica** — Respostas seguem a sequência: o que muda → por que
   muda → como muda. Sem saltos nem antecipações.
3. **Explicações detalhadas** — Este é um projeto de estudo. Toda resposta deve
   explicar **o que** cada arquivo/função/conceito faz, **por que** é necessário
   neste momento, e **como se relaciona** com o restante do projeto. Incluir:
   - Para que serve cada pasta, arquivo ou módulo envolvido
   - Como os arquivos conversam entre si (quem importa quem, fluxo de dados)
   - Conceitos novos explicados em linguagem direta com exemplos quando útil
   - O papel de cada dependência/ferramenta utilizada
4. **Objetivo e preciso** — Detalhado, mas sem retrabalho. Cada resposta deve
   avançar o projeto sem criar necessidade de voltar atrás.
5. **Mudanças explicadas** — Toda alteração de código/config vem com explicação
   clara do que faz e por que é necessária neste momento.
6. **Consciência de erros** — Consultar a seção 5 (Histórico de Erros) antes de
   propor soluções para não repetir falhas já registradas.
7. **Commits separados** — Cada grande mudança deve gerar um commit único no GitHub (sempre em inglês)
   desta forma o versionamento fica mais rastreável.

### 3.1 Formato Padrão de Resposta

O usuário cria todos os arquivos manualmente. **Sempre evitar** usar ferramentas de
edição automática (create_file, replace_string_in_file, etc.) para código do
projeto — a não ser quando seja explicitamente solicitado pelo usuário.

Cada resposta de implementação deve seguir este template:

```
### [Título do que está sendo criado]

**O que muda:** descrição curta
**Por que muda:** justificativa técnica

**Arquivo:** `caminho/relativo/do/arquivo.ext` (criar novo | editar existente)

\`\`\`linguagem
[código completo do arquivo — nunca parcial, nunca com "..." ou "# resto do código"]
\`\`\`

> Se for edição de arquivo existente: indicar exatamente ONDE inserir/alterar
> com linhas de contexto antes e depois.

**Commit:**
\`\`\`bash
git add caminho/do/arquivo.ext
git commit -m "tipo: descrição objetiva da mudança"
\`\`\`
```

**Regras:**
- Código sempre **completo** — o usuário faz copy-paste direto
- Indicar **caminho exato** do arquivo relativo à raiz do projeto
- Se o arquivo é novo, dizer "criar novo"; se existe, dizer "editar existente"
- Sempre fechar com o **comando de commit** com mensagem descritiva
- Convenção de commit: `feat:`, `fix:`, `chore:`, `refactor:`, `docs:`

---

## 4. Cronograma do Projeto

> Roadmap orientado ao objetivo central: dominar a engenharia de banco de dados.
> Cada fase entrega uma capacidade real de gerenciamento de bancos PostgreSQL.
> Fases são sequenciais — cada uma depende das anteriores.

### FASE 0 — Fundação `[x]`

> Esqueleto do projeto. Tudo se constrói sobre isso.

| Entrega | Descrição |
|---------|-----------|
| Estrutura de pastas | `src/` com layout de pacotes (models, schemas, routers, services, core) |
| Docker Compose | PostgreSQL 16 Alpine + pgAdmin — ambiente local completo |
| Configuração | `.env.example` + `pydantic-settings` para gerenciar variáveis |
| FastAPI app | Aplicação inicializada com CORS e tratamento de exceções padronizado |
| SQLAlchemy | Engine sync + `SessionLocal` factory com `psycopg` |
| Alembic | Inicializado, configurado para ler a URL do `.env` |
| Health check | `GET /health` retorna status da API e conectividade com o banco |
| Dependências | `requirements.txt` com versões pinadas |
| .gitignore | Ignora `.venv/`, `.env`, `__pycache__/`, etc. |

**Critério de conclusão:** `docker compose up` sobe Postgres + pgAdmin.
`GET /health` retorna `200 OK`. Alembic conecta ao banco.

---

### FASE 1 — Autenticação (Admin Access) `[x]`

> Protege a API contra acesso externo. Single-operator: apenas o admin
> (desenvolvedor) acessa a plataforma. Não é sistema multi-usuário.

| Entrega | Descrição |
|---------|-----------|
| Model `User` | id, email, hashed_password, is_active, is_superuser, created_at, updated_at |
| Migration | Alembic: tabela `users` |
| Schemas | `UserCreate`, `UserRead`, `UserUpdate` (Pydantic v2) |
| Security | bcrypt para hash de senha, JWT (access token + refresh token) |
| Router `/auth` | `POST /auth/register`, `POST /auth/login`, `GET /auth/me` |
| Dependency | `get_current_user` — extrai JWT do header → retorna User |
| Router `/users` | `GET /users/{id}`, `PATCH /users/{id}` (self-service) |

**Critério de conclusão:** Admin registra, loga, recebe JWT, acessa rotas protegidas.

---

### FASE 1.5 — Banco Mock E-Commerce (Aprendizado) `[x]`

> Banco de dados simulando um cliente real do PalmTreeDB.
> Serve como instrumento de estudo das ferramentas e como demonstração do produto.
> Esta fase é essencialmente prática: aprender SQL, relacionamentos, e como
> bancos reais se comportam antes de construir a plataforma que os gerencia.

| Entrega | Descrição |
|---------|-----------|
| Banco `ecommerce_mock` | Segundo banco no mesmo PostgreSQL — isolado do banco da plataforma |
| 5 tabelas relacionais | `categories`, `products`, `customers`, `orders`, `order_items` |
| Script de seed | `scripts/seed_ecommerce.py` — insere ~100 registros mock realistas |
| Exercícios SQL | Queries no pgAdmin: JOIN, GROUP BY, agregações, filtros |
| Script CRUD | `scripts/explore_ecommerce.py` — demonstra CRUD via SQLAlchemy |

**Critério de conclusão:** Banco `ecommerce_mock` populado. Queries SQL rodando no pgAdmin.
CRUD via SQLAlchemy funcionando. Entendimento claro de relacionamentos e joins.

> 📁 Os scripts ficam em `scripts/` — pasta local, listada no `.gitignore`.
> Não fazem parte da API. São ferramentas de estudo e demonstração.

---

### FASE 2 — Modelo de Instâncias de Banco `[x]`

> O objeto de domínio central da plataforma: representar cada banco de dados
> gerenciado como uma entidade com ciclo de vida completo.

| Entrega | Descrição |
|---------|-----------|
| Model `DatabaseInstance` | id, name, engine_version, status, host, port, db_name, db_user, connection_uri (encriptada), cpu, memory, storage, notes, created_at, updated_at, deleted_at (soft delete) |
| Enum `InstanceStatus` | PENDING → PROVISIONING → RUNNING ↔ STOPPED → DELETING → DELETED / FAILED |
| Migration | Alembic: tabela `database_instances` |
| Schemas | `InstanceCreate`, `InstanceRead`, `InstanceUpdate` |
| Router `/instances` | `POST`, `GET` (list/detail), `PATCH`, `DELETE` — rotas protegidas por JWT |
| Service layer | Máquina de estados de status, validação de transições |

**Critério de conclusão:** CRUD completo de instâncias com máquina de estados de status.
Cada instância representa um banco de um cliente que será gerenciado pela plataforma.

---

### FASE 2.5 — Security Hardening `[x]`

> Hardening prático da API antes de servir clientes reais. As FASES 0–2
> já possuem uma base funcional (bcrypt, JWT, Pydantic, SQLAlchemy
> parameterizado), mas faltam camadas adicionais que tornam o sistema
> robusto para operação: rate limiting, revogação de tokens, encriptação
> at rest, e controle de acesso ao registro.
>
> **Escopo:** Correções práticas de segurança baseadas na auditoria de
> 2026-04-14 (12 vulnerabilidades identificadas). Estudo aprofundado de
> tráfego de rede e criptografia fica para o futuro.

#### Entregas

| # | Entrega | Descrição |
|---|---------|-----------|
| 1 | **Hardening JWT** | Claim `type` (access/refresh), endpoint `POST /auth/refresh`, validação no `get_current_user` |
| 2 | **Revogação de tokens** | Model `TokenBlacklist`, verificação no middleware, endpoint `POST /auth/logout` |
| 3 | **Rate limiting** | Middleware `slowapi`, limites em `/auth/login` e `/auth/register` |
| 4 | **Lockout do registro** | `/auth/register` restrito (first-run setup ou convite admin) |
| 5 | **Validação de senha forte** | Min 12 chars, uppercase, lowercase, digit, special char |
| 6 | **Security headers** | Middleware com `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, etc. |
| 7 | **Encriptação Fernet** | Módulo `encryption.py`, `FERNET_KEY`, encrypt/decrypt para connection URIs |
| 8 | **Hardening Docker & CORS** | Portas restritas a localhost, CORS com methods/headers específicos |
| 9 | **Timing-safe auth** | Executar bcrypt mesmo quando user não existe |

**Critério de conclusão:** Toda rota protegida contra brute force. Tokens JWT
diferenciados e revogáveis. Registro restrito. Senhas validadas. Connection URIs
encriptadas. Security headers em toda resposta. Docker com portas restritas.

> 💡 **Conceito-chave — Defesa em Profundidade:**
> Nenhuma camada de segurança é perfeita sozinha. O princípio é empilhar múltiplas
> barreiras: mesmo que o rate limiting falhe, o bcrypt torna brute force lento;
> mesmo que um token vaze, a blacklist permite revogá-lo; mesmo que alguém acesse
> o banco, as URIs estão encriptadas. Cada camada assume que a anterior pode cair.

---

### FASE 3 — Motor de Provisionamento `[x]`

> Transformar o modelo de dados em bancos reais. Interface abstrata que pode ser
> trocada por ambiente (dev = Docker, prod = servidor dedicado).
> Inclui segurança no nível do banco: cada instância provisionada com roles e
> permissões isoladas — princípio do menor privilégio desde o primeiro dia.

| Entrega | Descrição |
|---------|-----------|
| `ProvisionerBase` (ABC) | Interface: create, delete, start, stop, get_status |
| `DockerProvisioner` | Implementação local — cria containers PostgreSQL via Docker SDK |
| Connection strings | Geração + armazenamento seguro da URI de conexão (Fernet encryption) |
| Database roles | Role dedicada por instância com permissões mínimas (CONNECT, CRUD nas próprias tabelas) |
| Integração | Router chama Service → Service chama Provisioner → atualiza status |
| Status polling | Task que verifica se a instância provisionada está saudável |

**Critério de conclusão:** `POST /instances` cria um container PostgreSQL real acessível.
O banco provisionado aceita conexões com role dedicada. Connection URI encriptada no banco
da plataforma.

---

### FASE 4 — Monitoramento & Observabilidade Profunda `[x]`

> Visibilidade total sobre cada banco gerenciado. Sem monitoramento, não há
> como garantir que um banco é "inquebrável". Esta fase vai além de métricas
> superficiais — mergulha nas views internas do PostgreSQL para entender
> exatamente o que acontece dentro de cada banco.

| Entrega | Descrição |
|---------|-----------|
| Model `Metric` | instance_id, metric_type, value, collected_at |
| Collector `pg_stat_*` | Consultas automáticas às views de estatísticas do PostgreSQL |
| Métricas base | Conexões ativas, transações/s, cache hit ratio, tuplas lidas/escritas, tamanho do banco |
| `pg_stat_statements` | Integração com a extensão para rastrear queries lentas e mais executadas |
| `pg_stat_user_indexes` | Análise de uso de índices — quais são usados, quais são peso morto |
| `pg_locks` | Monitoramento de locks ativos, detecção de deadlocks |
| `EXPLAIN ANALYZE` | Captura e armazenamento de planos de execução para queries lentas |
| Table bloat | Estimativa de espaço desperdiçado por tabelas e índices inchados |
| Health polling | Verifica conectividade e responsividade de cada instância periodicamente |
| Router | `GET /instances/{id}/metrics`, `GET /instances/{id}/health`, `GET /instances/{id}/slow-queries` |

**Critério de conclusão:** Endpoint retorna métricas reais e profundas: conexões, cache hit
ratio, top queries por tempo/execuções, locks ativos, índices não utilizados, estimativa de
bloat. Health check por instância funcional. Capacidade de capturar EXPLAIN de queries.

---

### FASE 5 — Backup, Restore & PITR `[x]`

> Proteção de dados em duas camadas: backups lógicos (pg_dump) para portabilidade
> e backups físicos (pg_basebackup + WAL) para Point-in-Time Recovery.
> Um banco "inquebrável" oferece ambas as estratégias — uma para conveniência,
> outra para quando cada segundo de dados importa.

| Entrega | Descrição |
|---------|-----------|
| Model `Backup` | id, instance_id, type (manual/scheduled), strategy (logical/physical), format, status, file_path, size_bytes, created_at, completed_at |
| Model `BackupSchedule` | instance_id, cron_expression, retention_days, strategy, is_active |
| Service `pg_dump` | Backups lógicos com formatos custom e plain — portáveis entre versões |
| Service `pg_restore` | Restore completo ou seletivo a partir de backups lógicos |
| WAL archiving | Configuração de `archive_command` para arquivar WAL segments continuamente |
| `pg_basebackup` | Backup físico completo como base para PITR |
| Point-in-Time Recovery | Restore até um timestamp específico usando base backup + WAL replay |
| Retenção automática | Limpeza de backups antigos e WAL segments conforme política de retenção |
| Router | `POST /instances/{id}/backups`, `GET` list, `POST /backups/{id}/restore` |

**Critério de conclusão:** Dois caminhos de backup funcionais: (1) pg_dump/pg_restore para
backup lógico, (2) pg_basebackup + WAL para PITR. Capacidade de restaurar um banco a
qualquer ponto no tempo. Backups antigos limpos automaticamente pela retenção.

> 💡 **Conceito-chave — WAL (Write-Ahead Log):**
> O PostgreSQL grava TODA alteração primeiro no WAL antes de aplicar nos dados.
> Arquivando esses logs + um backup base, é possível "rebobinar" o banco para
> qualquer segundo no tempo. Isso é o que bancos de produção reais usam.

---

### FASE 5.5 — Fundação para Crescimento `[x]`

> Duas correções de infraestrutura que precisam ser feitas antes das próximas
> fases adicionarem mais rotas, endpoints e containers. São mudanças pequenas
> hoje; seriam refatorações custosas na FASE 10.

| Entrega | Descrição |
|---------|----------|
| **API versioning** | Prefixo `/api/v1/` em todos os routers (exceto `GET /health` — permanece na raiz para compatibilidade com load balancers e probes de infraestrutura) |
| **Docker resource limits** | `DockerProvisioner.create()` passa `mem_limit` e `nano_cpus` ao `containers.run()` usando os campos `memory_mb` e `cpu` da `DatabaseInstance` — existentes desde a FASE 2, ainda ignorados pelo provisioner |

**Critério de conclusão:** Todas as rotas da API acessíveis via `/api/v1/...`. `GET /health`
continua funcionando na raiz sem prefixo. Containers provisionados respeitam os limites de
CPU e RAM configurados na instância — nenhum banco pode sufocar os outros por consumo excessivo.

> 💡 **Por que agora e não na FASE 10:**
> O projeto tem hoje 26 rotas em 5 routers. Ao final da FASE 9 terá ~40 rotas em 8 routers,
> mais testes acumulados em todas as fases intermediárias. Adicionar o prefixo sobre 26 rotas
> custa 1 mudança em `main.py`; sobre 40 rotas + testes custa refatoração de múltiplos arquivos
> e reescrita de todos os testes que referenciam URLs sem o prefixo.

---

### FASE 6 — Manutenção Automatizada `[x]`

> PostgreSQL exige manutenção regular para manter performance. Esta fase
> automatiza tudo que um DBA faria manualmente: VACUUM, REINDEX, ANALYZE,
> e gerenciamento de conexões.

| Entrega | Descrição |
|---------|-----------|
| Model `MaintenanceTask` | id, instance_id, task_type, status, scheduled_at, started_at, completed_at, result_summary |
| Model `MaintenanceSchedule` | instance_id, task_type, cron_expression, is_active |
| VACUUM automation | `VACUUM ANALYZE` periódico, `VACUUM FULL` quando necessário (bloat detection) |
| REINDEX automation | Detecção de índices inchados + rebuild automático |
| ANALYZE automation | Atualização de estatísticas para o query planner |
| Connection management | Detecção de conexões idle/leaked, kill automático de long-running queries |
| Configuration tuning | Análise e recomendação de parâmetros (`shared_buffers`, `work_mem`, `effective_cache_size`, `maintenance_work_mem`) baseada nos recursos da instância |
| Router | `GET /instances/{id}/maintenance`, `POST /instances/{id}/maintenance/run`, `GET /instances/{id}/config-recommendations` |

**Critério de conclusão:** Manutenção roda automaticamente em schedule configurável.
Conexões problemáticas são detectadas e tratadas. Índices inchados são reconstruídos.
Recomendações de tuning geradas automaticamente baseadas em CPU/memória da instância.

> 💡 **Conceito-chave — Por que VACUUM existe:**
> O PostgreSQL usa MVCC (Multi-Version Concurrency Control) — quando uma linha é
> atualizada ou deletada, a versão antiga NÃO é apagada imediatamente. O VACUUM
> limpa essas "tuplas mortas". Sem ele, o banco cresce indefinidamente.

---

### FASE 7 — Alertas & Notificações `[ ]`

> Detecção proativa de problemas. Em vez de esperar algo quebrar, a plataforma
> avisa antes — transformando reação em prevenção.

| Entrega | Descrição |
|---------|-----------|
| Model `AlertRule` | id, instance_id, metric_type, condition (gt/lt/eq), threshold, severity (info/warning/critical), is_active |
| Model `AlertEvent` | id, rule_id, instance_id, triggered_at, resolved_at, current_value, message |
| Engine de avaliação | Compara métricas coletadas (FASE 4) contra regras de alerta |
| Alertas padrão | Disco > 80%, conexões > 90% do max, cache hit ratio < 95%, long queries, backup com `status=FAILED` (crítico) |
| Notificações | Log + webhook (extensível para email/Telegram/Slack no futuro) |
| Router | `GET /alerts`, `POST /alerts/rules`, `GET /instances/{id}/alerts` |

> **Nota:** "Replication lag" foi movido para a FASE 9 — replicação não existe antes
> dessa fase, portanto o alerta não tem dado para avaliar até lá.

**Critério de conclusão:** Alertas disparam automaticamente quando métricas excedem
thresholds configurados. Backup com falha nas últimas 24h gera alerta crítico.
Histórico de alertas consultável.

---

### FASE 8 — Painel de Administração `[ ]`

> Visão consolidada de toda a plataforma. Um único lugar para ver a saúde
> de todos os bancos gerenciados.

| Entrega | Descrição |
|---------|-----------|
| Dashboard endpoints | Rotas que agregam dados de todas as instâncias |
| Overview da plataforma | Total de instâncias (por status), alertas ativos, backups recentes, próximas manutenções |
| Model `AuditLog` | user_id, action, resource_type, resource_id, details (JSON), ip_address, timestamp |
| Audit trail | Evento emitido automaticamente pelos endpoints — sem anotação manual no código de negócio |
| Eventos auditáveis | **Auth:** `register`, `login`, `logout` · **Instances:** `create`, `status_change`, `delete` · **Backups:** `backup_created`, `restore_initiated`, `schedule_created`, `schedule_deleted` · **Maintenance (F6):** `maintenance_run`, `config_applied` · **Replication (F9):** `replica_created`, `failover_promoted` |
| Router `/admin` | `GET /admin/dashboard`, `GET /admin/audit-log` |

**Critério de conclusão:** Dashboard retorna visão consolidada da saúde de todos os bancos.
Audit log registra todas as ações relevantes da plataforma.

---

### FASE 9 — Replicação & Alta Disponibilidade `[ ]`

> Um banco "inquebrável" não depende de uma única instância. Replicação
> garante que, se o servidor primário cair, existe uma cópia pronta para
> assumir. Esta fase implementa streaming replication do PostgreSQL —
> o mesmo mecanismo usado por empresas em produção.

> **Groundwork já implementado na FASE 5:** O `DockerProvisioner` já configura
> `wal_level=replica`, `archive_mode=on` e executa `ALTER ROLE {user} WITH REPLICATION`
> em cada banco provisionado. Esta fase começa diretamente na configuração de
> `pg_hba.conf` e `primary_conninfo` — sem necessidade de refatorar o provisioner.

| Entrega | Descrição |
|---------|-----------|
| Model `Replica` | id, primary_instance_id, replica_instance_id, replication_state, lag_bytes, lag_seconds, created_at |
| Streaming replication | Configuração de primary (`wal_level=replica`, `max_wal_senders`) + standby (`primary_conninfo`, recovery) |
| Provisioner extension | `DockerProvisioner` ganha capacidade de criar réplicas vinculadas a um primary |
| Replication monitoring | Consulta `pg_stat_replication` no primary e `pg_stat_wal_receiver` no standby |
| Lag tracking | Monitoramento contínuo do atraso entre primary e réplica |
| Promotion | Capacidade de promover uma réplica a primary (failover manual) |
| Router | `POST /instances/{id}/replicas`, `GET /instances/{id}/replicas`, `POST /replicas/{id}/promote` |

**Critério de conclusão:** Instância primary replica dados em tempo real para um standby.
Lag de replicação monitorado. Réplica pode ser promovida a primary via API.

> 💡 **Conceito-chave — Streaming Replication:**
> O primary envia os WAL records para o standby em tempo real via conexão TCP.
> O standby aplica os WAL records continuamente, mantendo uma cópia quase idêntica.
> É diferente de backup: o backup é uma foto, a réplica é um espelho ao vivo.

---

### FASE 10 — Polimento, Testes & Deploy `[ ]`

> Tornar o projeto production-ready e portfolio-ready.

| Entrega | Descrição |
|---------|-----------|
| Testes | pytest + fixtures para cada fase, cobertura mínima 80% |
| Dockerfile | Multi-stage build otimizado |
| CI/CD | GitHub Actions: lint (ruff), test, build |
| OpenAPI | Documentação customizada, tags organizadas por domínio |
| README.md | Profissional, com arquitetura, setup, screenshots |

**Critério de conclusão:** CI verde. README demonstra o projeto para recrutadores.

---

### Mapa de Dependências

```
FASE 0 (Fundação)
  └─→ FASE 1 (Auth — Admin Access)
      └─→ FASE 1.5 (Mock E-Commerce — Aprendizado)
          └─→ FASE 2 (Instâncias — Modelo de Dados)
                └─→ FASE 2.5 (Security Hardening)
                      └─→ FASE 3 (Provisionamento — Bancos Reais)
                            ├─→ FASE 4 (Monitoramento & Observabilidade)
                            │     └─→ FASE 7 (Alertas & Notificações)
                            └─→ FASE 5 (Backup, Restore & PITR)
                                  └─→ FASE 5.5 (Fundação para Crescimento)
                                        └─→ FASE 6 (Manutenção Automatizada)
                                              └─→ FASE 8 (Painel de Administração)
                                                    └─→ FASE 9 (Replicação & Alta Disponibilidade)
                                                          └─→ FASE 10 (Deploy & Polimento)
```

### Separação Público / Privado

| Escopo | Fases | Justificativa |
|--------|-------|---------------|
| **Repo público** (portfólio) | 0 → 10 | Arquitetura genérica de gerenciamento de bancos, sem segredos |
| **Repo(s) privado(s)** (operação) | — | Configs de clientes reais, credenciais de produção, scripts específicos de infra |

O repo público contém **toda a engenharia** com implementações genéricas.
O valor proprietário está na **operação com clientes reais**, não no código-base.

---

## 5. Histórico de Erros

> Registrar aqui cada erro relevante encontrado durante o desenvolvimento,
> com causa-raiz e resolução, para evitar reincidência.

| # | Data | Erro | Causa-raiz | Resolução |
|---|------|------|------------|-----------|
| 1 | 2026-04-08 | `pgAdmin` em loop de restart | `dpage/pgadmin4` versão recente rejeita domínios `.local` no email | Trocar `admin@dbaas.local` por `admin@admin.com` (depois `admin@palmtreedb.dev`) |
| 2 | 2026-04-08 | `(trapped) error reading bcrypt version` | `passlib 1.7.4` tenta acessar `bcrypt.__about__` removido na versão 4.x | Remover `passlib`, usar `bcrypt` diretamente via `bcrypt.hashpw` / `bcrypt.checkpw` |
| 3 | 2026-04-08 | `RuntimeError: Form data requires python-multipart` | `OAuth2PasswordRequestForm` depende de `python-multipart` não incluído no `requirements.txt` | Instalar e adicionar `python-multipart==0.0.9` ao `requirements.txt` |
| 4 | 2026-04-14 | pgAdmin `password authentication failed for user "palmtreedb"` | Arquivo `.env` com terminação CRLF (Windows). Copy-paste incluía `\r` invisível na senha (33 chars vs 32 esperados) | `sed -i 's/\r$//' .env` para converter CRLF → LF. Verificar LF no canto inferior do VS Code |
| 5 | 2026-04-30 | `collect_explain` aceitava `SELECT * FROM (DELETE ...)` | Validação apenas com `startswith("select")` — não bloqueava DML embutido em subqueries | Blacklist `_EXPLAIN_BLOCKED`, limite de 8000 chars, proibição de `;` em `src/collectors/pg_stats.py` |
| 6 | 2026-04-30 | `DATABASE_URL` quebrava com senhas contendo `@`, `#`, `/` | f-string sem encode da senha → SQLAlchemy falha ao parsear host da URL | `urllib.parse.quote(password, safe="")` no property `DATABASE_URL` em `src/core/config.py` |
| 7 | 2026-04-30 | `token_blacklist` crescia indefinidamente | Nenhuma tarefa removia tokens já expirados da tabela | `cleanup_expired_tokens()` em `src/services/auth.py` + chamada diária no `status_poller` |
| 8 | 2026-04-30 | Tabela `metrics` crescia indefinidamente | Sem política de retenção — ~864k linhas/dia com 10 instâncias RUNNING | Retenção de 30 dias + limpeza diária em `src/services/metrics_poller.py` |
| 9 | 2026-04-30 | `ExplainRequest.query` sem `max_length` no schema Pydantic | Schema e collector desalinhados — Pydantic aceitava strings arbitrariamente longas | `max_length=8000` adicionado ao campo em `src/schemas/metric.py` |

