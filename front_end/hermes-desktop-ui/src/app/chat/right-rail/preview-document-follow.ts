import { useEffect, useLayoutEffect, useRef, useState } from 'react'

/** Keep the live part in view while the document streams, unless the reader scrolled away. */
export function useFollowLive(options: { active: number; enabled: boolean; signature: string }) {
  const { active, enabled, signature } = options
  const scrollRef = useRef<HTMLDivElement>(null)
  const following = useRef(true)
  const [paused, setPaused] = useState(false)

  const liveEl = () => scrollRef.current?.querySelector<HTMLElement>(`[data-part="${active}"]`) ?? null

  const bottomGap = (): number => {
    const root = scrollRef.current
    const el = liveEl()

    if (!root || !el) {
      return 0
    }

    return el.getBoundingClientRect().bottom - root.getBoundingClientRect().bottom
  }

  const toLive = () => {
    const root = scrollRef.current

    const delta = bottomGap() + 24

    if (root && liveEl() && delta > 0) {
      root.scrollTop += delta
    }
  }

  useLayoutEffect(() => {
    if (enabled && following.current) {
      toLive()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, active, signature])

  useEffect(() => {
    if (!enabled) {
      following.current = true
      setPaused(false)
    }
  }, [enabled])

  return {
    jump: () => {
      following.current = true
      setPaused(false)
      toLive()
    },
    onScroll: () => {
      if (!enabled || !liveEl()) {
        return
      }

      const near = bottomGap() < 80

      following.current = near
      setPaused(!near)
    },
    paused: enabled && paused,
    scrollRef,
    scrollToPart: (index: number) => {
      const root = scrollRef.current
      const el = root?.querySelector<HTMLElement>(`[data-part="${index}"]`)

      if (!root || !el) {
        return
      }

      root.scrollTop += el.getBoundingClientRect().top - root.getBoundingClientRect().top - 12

      if (enabled && index !== active) {
        following.current = false
        setPaused(true)
      }
    }
  }
}
