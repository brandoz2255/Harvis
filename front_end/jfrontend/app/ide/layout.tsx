// Force dynamic rendering for IDE route (no static generation)
export const dynamic = 'force-dynamic'
export const revalidate = 0

export default function IDELayout({
  children,
}: {
  children: React.ReactNode
}) {
  return children
}







