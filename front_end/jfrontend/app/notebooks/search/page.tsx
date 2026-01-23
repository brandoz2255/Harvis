import { Suspense } from "react"
import SearchClient from "./SearchClient"

export default function NotebookSearchPage() {
  return (
    <Suspense fallback={<div className="p-6 text-gray-400">Loading…</div>}>
      <SearchClient />
    </Suspense>
  )
}



