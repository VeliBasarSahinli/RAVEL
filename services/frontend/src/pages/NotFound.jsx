import { Link } from "react-router-dom"

export default function NotFound() {
  return (
    <div className="grid min-h-screen place-items-center bg-ravel-bg text-ravel-text">
      <div className="text-center">
        <p className="font-display text-7xl text-aurora">404</p>
        <p className="mt-4 text-ravel-muted">Aradığın sayfa burada yok.</p>
        <Link
          to="/"
          className="mt-8 inline-block rounded-xl bg-ravel-blue/90 px-6 py-3 font-medium hover:bg-ravel-blue"
        >
          Anasayfaya dön
        </Link>
      </div>
    </div>
  )
}
