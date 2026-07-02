// Saudação por horário do dia (lógica real, baseada no relógio local do usuário).
export function greetingForHour(hour = new Date().getHours()): string {
  return hour < 12 ? "Bom dia" : hour < 18 ? "Boa tarde" : "Boa noite";
}
