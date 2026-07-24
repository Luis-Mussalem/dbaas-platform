// Sparkline — mini gráfico de linha (com preenchimento opcional em gradiente)
// desenhado em SVG puro, sem dependência externa. Escala os valores para caber
// no viewBox e estica para 100% da largura do contêiner.
//
// Conceito novo: SVG responsivo. O viewBox define um sistema de coordenadas
// fixo (W×H); preserveAspectRatio="none" deixa o SVG esticar livremente para o
// tamanho real do elemento, então o desenho acompanha qualquer largura do card.

type SparklineProps = {
  data: number[];
  // Cor da linha/preenchimento — aceita um token CSS (ex.: "var(--brand)").
  color?: string;
  fill?: boolean;
  className?: string;
  strokeWidth?: number;
  // Domínio Y explícito. Sem ele, cada sparkline se auto-escala à própria faixa
  // (bom para ver a FORMA de uma série isolada). Com ele — tipicamente [0, teto da
  // frota] — a régua vira COMPARTILHADA entre cards e a altura passa a codificar
  // MAGNITUDE: um card de 12 q/s fica mais alto que um de 4. Valores fora do
  // domínio são grampeados (um pico raro encosta no topo em vez de estourar).
  domainMin?: number;
  domainMax?: number;
};

const W = 100;
const H = 32;

export function Sparkline({
  data,
  color = "var(--brand)",
  fill = true,
  className = "h-9 w-full",
  strokeWidth = 1.5,
  domainMin,
  domainMax,
}: SparklineProps) {
  // Sem dados suficientes: desenha uma linha de base sutil (placeholder honesto,
  // em vez de inventar uma curva). Mantém o card visualmente completo.
  if (!data || data.length < 2) {
    return (
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className={className}
        aria-hidden
      >
        <line
          x1="0"
          y1={H - 1}
          x2={W}
          y2={H - 1}
          stroke="var(--border-strong)"
          strokeWidth={strokeWidth}
        />
      </svg>
    );
  }

  // Domínio explícito (escala compartilhada entre cards) tem prioridade sobre o
  // auto-escalonamento por série.
  const min = domainMin ?? Math.min(...data);
  const max = domainMax ?? Math.max(...data);
  const span = max - min || 1; // evita divisão por zero quando a série é plana

  // Mapeia cada ponto para coordenadas do viewBox. y é invertido (0 = topo). O
  // clamp mantém a linha dentro do quadro quando o domínio é compartilhado.
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * W;
    const norm = Math.min(1, Math.max(0, (v - min) / span));
    const y = H - 2 - norm * (H - 4);
    return [x, y] as const;
  });

  const line = pts.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  // Área fechada para o preenchimento: linha + descida até a base + volta.
  const area = `${line} L${W},${H} L0,${H} Z`;
  const gradId = `spark-${Math.abs(hash(data))}`;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className={className}
      aria-hidden
    >
      {fill && (
        <>
          {/* Gradiente ancorado na BASE: mais sólido embaixo (o zero, numa régua
              compartilhada) e suave junto à linha. Assim o preenchimento lê como
              uma COLUNA de nível a partir do zero — uma série de 10 q/s enche
              visivelmente o dobro de uma de 5 — em vez de uma faixinha sob a linha. */}
          <defs>
            <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.12" />
              <stop offset="100%" stopColor={color} stopOpacity="0.34" />
            </linearGradient>
          </defs>
          <path d={area} fill={`url(#${gradId})`} stroke="none" />
        </>
      )}
      <path
        d={line}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

// Hash simples só para gerar um id de gradiente estável por série (evita que
// dois sparklines compartilhem o mesmo <linearGradient>).
function hash(data: number[]): number {
  let h = 0;
  for (const v of data) h = (h * 31 + Math.round(v * 100)) | 0;
  return h;
}
