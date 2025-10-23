"use client"

import React, { useState, useEffect, useRef, useCallback } from 'react'

interface ResizablePanelProps {
  children: React.ReactNode
  width?: number
  height?: number
  onResize: (size: number) => void
  minWidth?: number
  maxWidth?: number
  minHeight?: number
  maxHeight?: number
  direction?: 'horizontal' | 'vertical'
  className?: string
  handlePosition?: 'right' | 'left' | 'top' | 'bottom'
}

/**
 * ResizablePanel Component
 * 
 * A flexible panel component that supports both horizontal and vertical resizing.
 * Features:
 * - Drag handle with hover effect
 * - Min/max constraints enforcement
 * - Smooth resizing with visual feedback
 * - Persists sizes via onResize callback (parent can save to user preferences)
 */
export default function ResizablePanel({
  children,
  width,
  height,
  onResize,
  minWidth = 200,
  maxWidth = 800,
  minHeight = 100,
  maxHeight = 600,
  direction = 'horizontal',
  className = '',
  handlePosition = direction === 'horizontal' ? 'right' : 'bottom'
}: ResizablePanelProps) {
  const [isDragging, setIsDragging] = useState(false)
  const [isHovering, setIsHovering] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)
  const startPosRef = useRef<{ x: number; y: number; size: number }>({ x: 0, y: 0, size: 0 })

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    setIsDragging(true)
    
    startPosRef.current = {
      x: e.clientX,
      y: e.clientY,
      size: direction === 'horizontal' ? (width || 0) : (height || 0)
    }
  }, [direction, width, height])

  useEffect(() => {
    if (!isDragging) return

    const handleMouseMove = (e: MouseEvent) => {
      e.preventDefault()
      
      if (direction === 'horizontal') {
        // Calculate new width based on handle position
        let delta = 0
        if (handlePosition === 'right') {
          delta = e.clientX - startPosRef.current.x
        } else if (handlePosition === 'left') {
          delta = startPosRef.current.x - e.clientX
        }
        
        const newWidth = Math.max(
          minWidth,
          Math.min(maxWidth, startPosRef.current.size + delta)
        )
        onResize(newWidth)
      } else {
        // Calculate new height based on handle position
        let delta = 0
        if (handlePosition === 'bottom') {
          delta = e.clientY - startPosRef.current.y
        } else if (handlePosition === 'top') {
          delta = startPosRef.current.y - e.clientY
        }
        
        const newHeight = Math.max(
          minHeight,
          Math.min(maxHeight, startPosRef.current.size + delta)
        )
        onResize(newHeight)
      }
    }

    const handleMouseUp = () => {
      setIsDragging(false)
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)

    // Add cursor style to body while dragging
    if (direction === 'horizontal') {
      document.body.style.cursor = 'col-resize'
    } else {
      document.body.style.cursor = 'row-resize'
    }

    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
      document.body.style.cursor = ''
    }
  }, [isDragging, direction, minWidth, maxWidth, minHeight, maxHeight, onResize, handlePosition])

  const handleStyle: React.CSSProperties = {}
  const containerStyle: React.CSSProperties = {}

  if (direction === 'horizontal') {
    containerStyle.width = width ? `${width}px` : undefined
    
    if (handlePosition === 'right') {
      handleStyle.position = 'absolute'
      handleStyle.right = '-4px'
      handleStyle.top = '0'
      handleStyle.bottom = '0'
      handleStyle.width = '8px'
      handleStyle.cursor = 'col-resize'
    } else if (handlePosition === 'left') {
      handleStyle.position = 'absolute'
      handleStyle.left = '-4px'
      handleStyle.top = '0'
      handleStyle.bottom = '0'
      handleStyle.width = '8px'
      handleStyle.cursor = 'col-resize'
    }
  } else {
    containerStyle.height = height ? `${height}px` : undefined
    
    if (handlePosition === 'bottom') {
      handleStyle.position = 'absolute'
      handleStyle.bottom = '-4px'
      handleStyle.left = '0'
      handleStyle.right = '0'
      handleStyle.height = '8px'
      handleStyle.cursor = 'row-resize'
    } else if (handlePosition === 'top') {
      handleStyle.position = 'absolute'
      handleStyle.top = '-4px'
      handleStyle.left = '0'
      handleStyle.right = '0'
      handleStyle.height = '8px'
      handleStyle.cursor = 'row-resize'
    }
  }

  return (
    <div
      ref={panelRef}
      className={`relative ${className}`}
      style={containerStyle}
    >
      {children}
      
      {/* Drag Handle */}
      <div
        style={handleStyle}
        onMouseDown={handleMouseDown}
        onMouseEnter={() => setIsHovering(true)}
        onMouseLeave={() => setIsHovering(false)}
        className={`
          z-50 transition-colors duration-150
          ${isDragging ? 'bg-purple-500' : isHovering ? 'bg-purple-400/50' : 'bg-transparent hover:bg-purple-400/30'}
        `}
      >
        {/* Visual indicator on hover/drag */}
        {(isHovering || isDragging) && (
          <div
            className={`
              absolute inset-0 flex items-center justify-center
              ${direction === 'horizontal' ? 'flex-col' : 'flex-row'}
            `}
          >
            <div
              className={`
                bg-purple-500 rounded-full
                ${direction === 'horizontal' ? 'w-1 h-8' : 'w-8 h-1'}
              `}
            />
          </div>
        )}
      </div>
    </div>
  )
}
