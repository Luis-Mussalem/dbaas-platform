// Período do dia para a saudação do Painel. Devolve só a CHAVE — a frase
// inteira vive nas mensagens (Dashboard.greeting, via {period, select, ...}).
// Antes esta função devolvia "Bom dia" e o call-site aplicava .toLowerCase():
// uma regra de capitalização do português cravada no JSX, que produziria
// "good afternoon" em inglês.
//
// `hour` é parâmetro obrigatório de propósito: lê-lo do relógio aqui faria o
// servidor (outro fuso) e o cliente discordarem na hidratação. Quem chama
// resolve o horário depois da montagem.
export type Period = "morning" | "afternoon" | "evening";

export function periodForHour(hour: number): Period {
  return hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening";
}
