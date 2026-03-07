'use client';

import React, { useState, useRef, useEffect } from 'react';
import { Search, X, FileText, Folder, Tag, StickyNote, Link2 } from 'lucide-react';
import { NodeType } from '../../../types/graph';

interface SearchResult {
  id: string;
  label: string;
  type?: NodeType;
}

interface GraphSearchProps {
  query: string;
  onChange: (query: string) => void;
  results: SearchResult[];
  onSelect: (nodeId: string) => void;
  darkMode?: boolean;
}

const typeIcons: Record<NodeType, typeof FileText> = {
  file: FileText,
  folder: Folder,
  tag: Tag,
  note: StickyNote,
  link: Link2,
};

export function GraphSearch({
  query,
  onChange,
  results,
  onSelect,
  darkMode = true,
}: GraphSearchProps) {
  const [isOpen, setIsOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Keyboard shortcut: / to focus search
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === '/' && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        inputRef.current?.focus();
      }
      if (e.key === 'Escape') {
        setIsOpen(false);
        inputRef.current?.blur();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const handleSelect = (id: string) => {
    onSelect(id);
    setIsOpen(false);
    onChange('');
  };

  const showResults = isOpen && query.trim().length > 0 && results.length > 0;

  return (
    <div ref={containerRef} className="relative">
      <div
        className={`
          flex items-center gap-2 px-3 py-2 rounded-lg
          border transition-all duration-200 w-[300px]
          ${
            darkMode
              ? 'bg-[#262626] border-[#333] focus-within:border-blue-500/50'
              : 'bg-white border-gray-200 focus-within:border-blue-400 shadow-sm'
          }
        `}
      >
        <Search className={`w-4 h-4 ${darkMode ? 'text-gray-500' : 'text-gray-400'}`} />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => {
            onChange(e.target.value);
            setIsOpen(true);
          }}
          onFocus={() => setIsOpen(true)}
          placeholder="Search nodes... (press / to focus)"
          className={`
            bg-transparent border-none outline-none text-sm w-full
            ${darkMode ? 'text-gray-200 placeholder-gray-500' : 'text-gray-700 placeholder-gray-400'}
          `}
        />
        {query && (
          <button
            onClick={() => {
              onChange('');
              inputRef.current?.focus();
            }}
            className={`${darkMode ? 'text-gray-500 hover:text-gray-300' : 'text-gray-400 hover:text-gray-600'}`}
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Dropdown results */}
      {showResults && (
        <div
          className={`
            absolute top-full left-0 right-0 mt-2 py-2 rounded-lg
            border shadow-lg max-h-[300px] overflow-y-auto z-50
            ${darkMode ? 'bg-[#262626] border-[#333]' : 'bg-white border-gray-200'}
          `}
        >
          <div
            className={`px-3 py-1.5 text-xs ${darkMode ? 'text-gray-500' : 'text-gray-400'}`}
          >
            {results.length} result{results.length !== 1 ? 's' : ''}
          </div>
          {results.slice(0, 10).map((result) => {
            const Icon = result.type ? typeIcons[result.type] : FileText;
            return (
              <button
                key={result.id}
                onClick={() => handleSelect(result.id)}
                className={`
                  w-full flex items-center gap-3 px-3 py-2 text-left
                  transition-colors
                  ${darkMode ? 'hover:bg-[#333] text-gray-300' : 'hover:bg-gray-50 text-gray-700'}
                `}
              >
                <Icon className="w-4 h-4 text-gray-400" />
                <span className="text-sm truncate">{result.label}</span>
              </button>
            );
          })}
          {results.length > 10 && (
            <div
              className={`px-3 py-1.5 text-xs ${darkMode ? 'text-gray-500' : 'text-gray-400'}`}
            >
              +{results.length - 10} more results...
            </div>
          )}
        </div>
      )}

      {isOpen && query.trim().length > 0 && results.length === 0 && (
        <div
          className={`
            absolute top-full left-0 right-0 mt-2 py-3 rounded-lg
            border shadow-lg text-center z-50
            ${darkMode ? 'bg-[#262626] border-[#333]' : 'bg-white border-gray-200'}
          `}
        >
          <span className={`text-sm ${darkMode ? 'text-gray-500' : 'text-gray-400'}`}>
            No results found
          </span>
        </div>
      )}
    </div>
  );
}
