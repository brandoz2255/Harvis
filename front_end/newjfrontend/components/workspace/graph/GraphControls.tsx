'use client';

import React from 'react';
import {
  ZoomIn,
  ZoomOut,
  Maximize,
  Orbit,
  Snowflake,
  Grid3X3,
} from 'lucide-react';

interface GraphControlsProps {
  physicsEnabled: boolean;
  onTogglePhysics: () => void;
  onFitView: () => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
  darkMode?: boolean;
}

export function GraphControls({
  physicsEnabled,
  onTogglePhysics,
  onFitView,
  onZoomIn,
  onZoomOut,
  darkMode = true,
}: GraphControlsProps) {
  const buttonClass = `
    p-2 rounded-md transition-all duration-200
    ${
      darkMode
        ? 'bg-[#262626] border border-[#333] text-gray-400 hover:text-white hover:bg-[#333]'
        : 'bg-white border border-gray-200 text-gray-600 hover:text-gray-900 hover:bg-gray-50 shadow-sm'
    }
  `;

  const activeButtonClass = `
    p-2 rounded-md transition-all duration-200
    ${
      darkMode
        ? 'bg-blue-500/20 border border-blue-500/50 text-blue-400'
        : 'bg-blue-50 border border-blue-200 text-blue-600'
    }
  `;

  return (
    <div
      className={`
        flex items-center gap-1.5 p-1.5 rounded-lg
        ${darkMode ? 'bg-[#1a1a1a]/90' : 'bg-white/90'}
        backdrop-blur-sm border
        ${darkMode ? 'border-[#333]' : 'border-gray-200'}
        shadow-lg
      `}
    >
      {/* Physics toggle */}
      <button
        onClick={onTogglePhysics}
        className={physicsEnabled ? activeButtonClass : buttonClass}
        title={physicsEnabled ? 'Pause physics simulation' : 'Start physics simulation'}
      >
        {physicsEnabled ? (
          <Orbit className="w-4 h-4 animate-spin" style={{ animationDuration: '3s' }} />
        ) : (
          <Snowflake className="w-4 h-4" />
        )}
      </button>

      <div
        className={`w-px h-5 mx-1 ${darkMode ? 'bg-[#333]' : 'bg-gray-200'}`}
      />

      {/* Zoom controls */}
      <button onClick={onZoomIn} className={buttonClass} title="Zoom in">
        <ZoomIn className="w-4 h-4" />
      </button>
      <button onClick={onZoomOut} className={buttonClass} title="Zoom out">
        <ZoomOut className="w-4 h-4" />
      </button>
      <button onClick={onFitView} className={buttonClass} title="Fit to screen">
        <Maximize className="w-4 h-4" />
      </button>

      <div
        className={`w-px h-5 mx-1 ${darkMode ? 'bg-[#333]' : 'bg-gray-200'}`}
      />

      {/* Layout button (placeholder for future) */}
      <button className={buttonClass} title="Change layout">
        <Grid3X3 className="w-4 h-4" />
      </button>
    </div>
  );
}
