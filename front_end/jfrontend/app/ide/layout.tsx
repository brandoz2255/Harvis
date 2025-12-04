// Force dynamic rendering for IDE route (no static generation)
export const dynamic = 'force-dynamic'
export const revalidate = 0

export default function IDELayout({
  children,
}: {
  children: React.ReactNode
}) {
  // The IDE needs to break out of the container constraints from the root layout
  // Shift left (~4 inches = ~384px = 96 in tailwind units)
  // -ml-96 = 384px left shift for approximately 4 inches
  return (
    <div className="ide-layout-wrapper -mx-4 -ml-96 -my-8 -mt-16 w-[calc(100%+24rem)] min-h-screen">
      {children}
    </div>
  )
}
