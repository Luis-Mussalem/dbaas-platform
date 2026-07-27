import { NextRequest, NextResponse } from "next/server";

const PUBLIC_ROUTES = ["/login"];

// Next.js 16 renamed the `middleware` convention to `proxy` (same runtime/edge,
// same `config.matcher`); the exported function is now called `proxy`.
// The access_token cookie is HttpOnly (written by the backend) — invisible to client-side
// JS, but the proxy runs on the server and reads it from the request normally.
export function proxy(request: NextRequest) {
  const token = request.cookies.get("access_token")?.value;
  const { pathname } = request.nextUrl;
  const isPublic = PUBLIC_ROUTES.includes(pathname);

  if (!token && !isPublic) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  // No /login → / redirect when a cookie is present: JS can't clear an HttpOnly
  // cookie, so a dead token (refresh failed) would create an infinite
  // login ↔ dashboard loop. A logged-in user visiting /login just sees the form — harmless.
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
