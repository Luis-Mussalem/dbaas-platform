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
};

const W = 100;
const H = 32;

export function Sparkline({
  data,
  color = "var(--brand)",
  fill = true,
  className = "h-9 w-full",
  strokeWidth = 1.5,
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

  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1; // evita divisão por zero quando a série é plana

  // Mapeia cada ponto para coordenadas do viewBox. y é invertido (0 = topo).
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * W;
    const y = H - 2 - ((v - min) / span) * (H - 4);
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
          <defs>
            <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.28" />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
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
