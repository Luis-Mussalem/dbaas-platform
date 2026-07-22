// Cadência de atualização das telas de dados do dashboard. Antes vinha do
// SimulationProvider (5s enquanto um reel rodava, 30s em repouso); com o reel
// removido, a frota tem uma vida-base estável e um único intervalo basta.
export const DASHBOARD_POLL_MS = 10_000;
