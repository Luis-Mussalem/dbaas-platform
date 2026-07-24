// Teto comum (base zero) para os sparklines de queries/s dos cards. Com uma régua
// COMPARTILHADA a altura da linha passa a codificar magnitude — um card de 12 q/s
// fica visivelmente mais alto que um de 4 — em vez de cada card se auto-escalar e
// todos parecerem igualmente cheios. Parte do maior número da frota, adiciona folga
// para os picos da linha (que oscila acima da média) e arredonda para um valor
// "redondo", para o teto não pular a cada atualização.
export function qpsScaleMax(values: (number | null | undefined)[]): number {
  const peak = Math.max(0, ...values.map((v) => v ?? 0)) * 1.5;
  if (peak <= 0) return 1;
  const mag = 10 ** Math.floor(Math.log10(peak));
  for (const step of [1, 2, 5, 10]) {
    if (peak <= step * mag) return step * mag;
  }
  return 10 * mag;
}
