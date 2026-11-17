import { cn } from '@/lib/utils'

const assetPath = (path: string) => `${import.meta.env.BASE_URL}${path.replace(/^\/+/, '')}`

// Brand badge: the Harvis screen-face mark, identical in light/dark. The art is
// public/harvis-logo.png (source: harvis-logo.svg); replace it to rebrand.
// Fills the tile; size via className (default size-14).
export function BrandMark({ className, ...props }: React.ComponentProps<'span'>) {
  return (
    <span
      className={cn('inline-flex size-14 shrink-0 items-center justify-center overflow-hidden rounded-md', className)}
      {...props}
    >
      <img alt="" className="size-full object-contain" src={assetPath('harvis-logo.png')} />
    </span>
  )
}
