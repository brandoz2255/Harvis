'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

// Redirect root /open-notebook to /open-notebook/notebooks
export default function OpenNotebookPage() {
  const router = useRouter()

  useEffect(() => {
    router.replace('/open-notebook/notebooks')
  }, [router])

  return null
}
