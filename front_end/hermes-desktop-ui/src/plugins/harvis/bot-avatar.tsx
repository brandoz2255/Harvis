import { cn, Codicon } from '@hermes/plugin-sdk'

import type { BotAvatar as Avatar } from './bots-api'

const SIZES = {
  sm: 'size-5 text-[0.8rem] rounded-md',
  md: 'size-8 text-lg rounded-lg',
  lg: 'size-14 text-3xl rounded-2xl'
} as const

/** A bot's face: its emoji, its image, or a generic robot when it has neither. */
export function BotAvatar({
  avatar,
  className,
  name,
  size = 'md'
}: {
  avatar: Avatar | undefined
  className?: string
  name: string
  size?: keyof typeof SIZES
}) {
  const box = cn(
    'grid shrink-0 place-items-center overflow-hidden bg-accent/60 leading-none select-none',
    SIZES[size],
    className
  )

  if (avatar?.image) {
    return <img alt={name} className={cn(box, 'object-cover')} src={avatar.image} />
  }

  return (
    <span aria-hidden="true" className={box} title={name}>
      {avatar?.emoji || <Codicon name="hubot" size={size === 'lg' ? '1.6rem' : size === 'md' ? '1rem' : '0.75rem'} />}
    </span>
  )
}
