import { NextRequest, NextResponse } from 'next/server'

const PROTECTED = ['/setup', '/today', '/settings']

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl
  const isProtected = PROTECTED.some((p) => pathname.startsWith(p))
  if (!isProtected) return NextResponse.next()

  const session = req.cookies.get('nf_session')?.value
  if (!session) {
    const url = req.nextUrl.clone()
    url.pathname = '/'
    return NextResponse.redirect(url)
  }

  return NextResponse.next()
}

export const config = {
  matcher: ['/setup/:path*', '/today/:path*', '/settings/:path*'],
}
