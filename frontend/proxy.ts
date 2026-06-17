import { NextRequest, NextResponse } from "next/server";

const PUBLIC_ROUTES = ["/login"];

// Next.js 16 renomeou a convenção `middleware` para `proxy` (mesmo runtime/edge,
// mesmo `config.matcher`); a função exportada passa a se chamar `proxy`.
export function proxy(request: NextRequest) {
  const token = request.cookies.get("auth_token")?.value;
  const { pathname } = request.nextUrl;
  const isPublic = PUBLIC_ROUTES.includes(pathname);

  if (!token && !isPublic) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  if (token && isPublic) {
    return NextResponse.redirect(new URL("/", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
