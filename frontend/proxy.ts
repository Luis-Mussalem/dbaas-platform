import { NextRequest, NextResponse } from "next/server";

const PUBLIC_ROUTES = ["/login"];

// Next.js 16 renomeou a convenção `middleware` para `proxy` (mesmo runtime/edge,
// mesmo `config.matcher`); a função exportada passa a se chamar `proxy`.
// O cookie access_token é HttpOnly (gravado pelo backend) — invisível para o JS
// do cliente, mas o proxy roda no servidor e o lê normalmente do request.
export function proxy(request: NextRequest) {
  const token = request.cookies.get("access_token")?.value;
  const { pathname } = request.nextUrl;
  const isPublic = PUBLIC_ROUTES.includes(pathname);

  if (!token && !isPublic) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  // Sem redirect /login → / quando há cookie: JS não consegue apagar cookie
  // HttpOnly, então um token morto (refresh falhou) criaria um loop infinito
  // login ↔ dashboard. Logado que visita /login só vê o formulário — inócuo.
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
