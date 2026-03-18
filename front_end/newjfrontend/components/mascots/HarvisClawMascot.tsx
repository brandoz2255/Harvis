"use client"

import { useState, useEffect, useCallback } from "react"

type MascotState = "idle" | "lookLeft" | "lookRight" | "wave" | "working" | "angry"

interface HarvisClawMascotProps {
  state?: MascotState
  size?: number
  className?: string
  interactive?: boolean
}

export function HarvisClawMascot({ state = "idle", size = 60, className = "", interactive = false }: HarvisClawMascotProps) {
  const [currentState, setCurrentState] = useState<MascotState>(state)
  const [eyeOffset, setEyeOffset] = useState(0)
  const [clawOpenLeft, setClawOpenLeft] = useState(0)
  const [clawOpenRight, setClawOpenRight] = useState(0)
  const [bobOffset, setBobOffset] = useState(0)
  const [antennaWiggle, setAntennaWiggle] = useState(0)
  const [clickCount, setClickCount] = useState(0)
  const [isAngry, setIsAngry] = useState(false)
  const [isStartled, setIsStartled] = useState(false)
  const [clickTimer, setClickTimer] = useState<NodeJS.Timeout | null>(null)

  const handleClick = useCallback(() => {
    if (!interactive) return

    setClickCount(prev => {
      const newCount = prev + 1
      if (newCount >= 4) {
        setIsAngry(true)
        setIsStartled(false)
        setTimeout(() => {
          setIsAngry(false)
          setClickCount(0)
        }, 1000)
        return 0
      } else {
        setIsStartled(true)
        setTimeout(() => setIsStartled(false), 300)
      }
      return newCount
    })

    if (clickTimer) clearTimeout(clickTimer)
    const timer = setTimeout(() => setClickCount(0), 2000)
    setClickTimer(timer)
  }, [interactive, clickTimer])

  useEffect(() => {
    return () => {
      if (clickTimer) clearTimeout(clickTimer)
    }
  }, [clickTimer])

  useEffect(() => {
    if (isAngry) {
      setCurrentState("angry")
      return
    }

    if (state !== "idle") {
      setCurrentState(state)
      return
    }

    const sequence = ["idle", "lookLeft", "idle", "lookRight", "idle", "wave"] as MascotState[]
    let index = 0

    const interval = setInterval(() => {
      index = (index + 1) % sequence.length
      setCurrentState(sequence[index])
    }, 2000)

    return () => clearInterval(interval)
  }, [state, isAngry])

  useEffect(() => {
    switch (currentState) {
      case "lookLeft":
        setEyeOffset(-4)
        break
      case "lookRight":
        setEyeOffset(4)
        break
      default:
        setEyeOffset(0)
    }
  }, [currentState])

  useEffect(() => {
    if (currentState !== "wave" && currentState !== "working") {
      setClawOpenLeft(0)
      setClawOpenRight(0)
      return
    }

    let frame = 0
    const animate = () => {
      frame++
      setClawOpenLeft(Math.sin(frame * 0.4) * 15)
      setClawOpenRight(Math.sin(frame * 0.4 + Math.PI) * 15)
      if (frame < 60) {
        requestAnimationFrame(animate)
      } else {
        setClawOpenLeft(0)
        setClawOpenRight(0)
      }
    }
    animate()
  }, [currentState])

  useEffect(() => {
    if (state !== "working") return

    let frame = 0
    let animationId: number
    const animate = () => {
      frame++
      setClawOpenLeft(Math.sin(frame * 0.2) * 12)
      setClawOpenRight(Math.sin(frame * 0.2 + Math.PI) * 12)
      animationId = requestAnimationFrame(animate)
    }
    animationId = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(animationId)
  }, [state])

  useEffect(() => {
    let frame = 0
    let animationId: number
    const animate = () => {
      frame++
      setBobOffset(Math.sin(frame * 0.05) * 2)
      setAntennaWiggle(Math.sin(frame * 0.08) * 3)
      animationId = requestAnimationFrame(animate)
    }
    animationId = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(animationId)
  }, [])

  const isLooking = currentState === "lookLeft" || currentState === "lookRight"
  const isSmiling = currentState === "idle" || currentState === "wave"

  const jumpOffset = isStartled ? -8 : 0
  const startleScale = isStartled ? 1.1 : 1

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 80 75"
      className={`${className} ${interactive ? "cursor-pointer" : ""}`}
      style={{ 
        transform: `translateY(${bobOffset + jumpOffset}px) scale(${startleScale})`,
        transition: isStartled ? "transform 0.1s ease-out" : "transform 0.3s ease"
      }}
      onClick={handleClick}
    >
      <defs>
        <filter id="clawGlow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="1.5" result="coloredBlur" />
          <feMerge>
            <feMergeNode in="coloredBlur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <linearGradient id="clawHeadGradient" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="#4FD1C5" />
          <stop offset="100%" stopColor="#319795" />
        </linearGradient>
        <linearGradient id="clawScreenGradient" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="#1A365D" />
          <stop offset="100%" stopColor="#0D1B2A" />
        </linearGradient>
        <linearGradient id="clawGradient" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="#FC8181" />
          <stop offset="100%" stopColor="#C53030" />
        </linearGradient>
        <linearGradient id="clawBodyGradient" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="#E53E3E" />
          <stop offset="100%" stopColor="#9B2C2C" />
        </linearGradient>
        <linearGradient id="clawAngryGradient" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="#FC8181" />
          <stop offset="100%" stopColor="#E53E3E" />
        </linearGradient>
      </defs>

      <g style={{ transformOrigin: "30px 8px", transform: `rotate(${antennaWiggle}deg)` }}>
        <line x1="30" y1="8" x2="26" y2="0" stroke={isAngry ? "#E53E3E" : "#4FD1C5"} strokeWidth="2" strokeLinecap="round" />
        <circle cx="26" cy="2" r="3" fill={isAngry ? "#E53E3E" : "#4FD1C5"} filter="url(#clawGlow)" />
      </g>

      <g style={{ transformOrigin: "50px 8px", transform: `rotate(${-antennaWiggle}deg)` }}>
        <line x1="50" y1="8" x2="54" y2="0" stroke={isAngry ? "#E53E3E" : "#4FD1C5"} strokeWidth="2" strokeLinecap="round" />
        <circle cx="54" cy="2" r="3" fill={isAngry ? "#E53E3E" : "#4FD1C5"} filter="url(#clawGlow)" />
      </g>

      <rect x="22" y="8" width="36" height="30" rx="6" fill={isAngry ? "url(#clawAngryGradient)" : "url(#clawHeadGradient)"} />
      <rect x="26" y="12" width="28" height="22" rx="3" fill="url(#clawScreenGradient)" />

      <g style={{ transform: `translateX(${eyeOffset}px)`, transition: "transform 0.3s ease" }}>
        {isAngry ? (
          <>
            <line x1="29" y1="15" x2="38" y2="18" stroke="#E53E3E" strokeWidth="2.5" strokeLinecap="round" />
            <line x1="51" y1="15" x2="42" y2="18" stroke="#E53E3E" strokeWidth="2.5" strokeLinecap="round" />
            <ellipse cx="34" cy="22" rx="4" ry="2" fill="#E53E3E" />
            <ellipse cx="34" cy="22" rx="2" ry="1" fill="#FED7D7" />
            <ellipse cx="46" cy="22" rx="4" ry="2" fill="#E53E3E" />
            <ellipse cx="46" cy="22" rx="2" ry="1" fill="#FED7D7" />
          </>
        ) : isStartled ? (
          <>
            <circle cx="34" cy="20" r="5" fill="#4FD1C5" filter="url(#clawGlow)" />
            <circle cx="34" cy="20" r="2.5" fill="#E6FFFA" />
            <circle cx="34" cy="19" r="1" fill="#ffffff" />
            <circle cx="46" cy="20" r="5" fill="#4FD1C5" filter="url(#clawGlow)" />
            <circle cx="46" cy="20" r="2.5" fill="#E6FFFA" />
            <circle cx="46" cy="19" r="1" fill="#ffffff" />
          </>
        ) : isSmiling ? (
          <>
            <path d="M31 21 Q34 17 37 21" stroke="#4FD1C5" strokeWidth="2.5" strokeLinecap="round" fill="none" filter="url(#clawGlow)" />
            <path d="M43 21 Q46 17 49 21" stroke="#4FD1C5" strokeWidth="2.5" strokeLinecap="round" fill="none" filter="url(#clawGlow)" />
          </>
        ) : (
          <>
            <ellipse cx="34" cy="20" rx="3" ry="4" fill="#4FD1C5" filter="url(#clawGlow)" />
            <ellipse cx="34" cy="20" rx="1.5" ry="2" fill="#E6FFFA" />
            <ellipse cx="46" cy="20" rx="3" ry="4" fill="#4FD1C5" filter="url(#clawGlow)" />
            <ellipse cx="46" cy="20" rx="1.5" ry="2" fill="#E6FFFA" />
          </>
        )}
      </g>

      {isAngry ? (
        <path d="M34 30 Q40 26 46 30" stroke="#E53E3E" strokeWidth="2" strokeLinecap="round" fill="none" />
      ) : (isSmiling && !isStartled) && (
        <path d="M34 28 Q40 33 46 28" stroke="#4FD1C5" strokeWidth="2" strokeLinecap="round" fill="none" filter="url(#clawGlow)" />
      )}

      <rect x="24" y="38" width="10" height="24" rx="3" fill="url(#clawBodyGradient)" />
      <rect x="46" y="38" width="10" height="24" rx="3" fill="url(#clawBodyGradient)" />
      <rect x="24" y="46" width="32" height="10" rx="2" fill="url(#clawBodyGradient)" />
      <text x="40" y="55" textAnchor="middle" fontSize="10" fontWeight="bold" fill="#FED7D7">H</text>

      <g style={{ transformOrigin: "16px 45px" }}>
        <ellipse cx="12" cy="42" rx="8" ry="6" fill="url(#clawGradient)" />
        <g style={{ transformOrigin: "8px 50px" }}>
          <path d={`M3 ${44 - clawOpenLeft * 0.3} Q8 ${40 - clawOpenLeft * 0.3} 10 ${46 - clawOpenLeft * 0.2}`} fill="url(#clawGradient)" stroke="#9B2C2C" strokeWidth="1" />
          <ellipse cx="3" cy={44 - clawOpenLeft * 0.3} rx="4" ry="5" fill="url(#clawGradient)" />
          <path d={`M3 ${52 + clawOpenLeft * 0.3} Q8 ${56 + clawOpenLeft * 0.3} 10 ${50 + clawOpenLeft * 0.2}`} fill="url(#clawGradient)" stroke="#9B2C2C" strokeWidth="1" />
          <ellipse cx="3" cy={52 + clawOpenLeft * 0.3} rx="4" ry="5" fill="url(#clawGradient)" />
        </g>
      </g>

      <g style={{ transformOrigin: "64px 45px" }}>
        <ellipse cx="68" cy="42" rx="8" ry="6" fill="url(#clawGradient)" />
        <g style={{ transformOrigin: "72px 50px" }}>
          <path d={`M77 ${44 - clawOpenRight * 0.3} Q72 ${40 - clawOpenRight * 0.3} 70 ${46 - clawOpenRight * 0.2}`} fill="url(#clawGradient)" stroke="#9B2C2C" strokeWidth="1" />
          <ellipse cx="77" cy={44 - clawOpenRight * 0.3} rx="4" ry="5" fill="url(#clawGradient)" />
          <path d={`M77 ${52 + clawOpenRight * 0.3} Q72 ${56 + clawOpenRight * 0.3} 70 ${50 + clawOpenRight * 0.2}`} fill="url(#clawGradient)" stroke="#9B2C2C" strokeWidth="1" />
          <ellipse cx="77" cy={52 + clawOpenRight * 0.3} rx="4" ry="5" fill="url(#clawGradient)" />
        </g>
      </g>
    </svg>
  )
}
