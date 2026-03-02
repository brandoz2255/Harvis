/**
 * Structured Result Types for Harvis AI
 * 
 * These types define the shape of structured data that can be returned
 * by the AI for various result types (locations, weather, calculations, etc.)
 */

// ═══════════════════════════════════════════════════════════════════════════════
// Base Result Types
// ═══════════════════════════════════════════════════════════════════════════════

export type ResultType = 
  | 'location' 
  | 'weather' 
  | 'stock' 
  | 'calculation' 
  | 'definition'
  | 'translation'
  | 'time'
  | 'currency'
  | 'code'
  | 'table'
  | 'list'
  | 'link'
  | 'image'
  | 'video'
  | 'generic';

export interface BaseStructuredResult {
  type: ResultType;
  title?: string;
  description?: string;
  source?: string;
  timestamp?: string;
}

// ═══════════════════════════════════════════════════════════════════════════════
// Location Result Types
// ═══════════════════════════════════════════════════════════════════════════════

export interface LocationResult extends BaseStructuredResult {
  type: 'location';
  placeId: string;
  name: string;
  address: string;
  latitude: number;
  longitude: number;
  rating?: number;
  totalRatings?: number;
  priceLevel?: 1 | 2 | 3 | 4;
  openNow?: boolean;
  phoneNumber?: string;
  website?: string;
  url?: string;  // Google Maps URL
  photoUrl?: string;
  vicinity?: string;
  types?: string[];  // e.g., ["restaurant", "food", "point_of_interest"]
  distance?: {
    value: number;
    text: string;
  };
  duration?: {
    value: number;
    text: string;
  };
}

export interface LocationSearchResult extends BaseStructuredResult {
  type: 'location';
  query: string;
  results: LocationResult[];
  totalResults: number;
  nextPageToken?: string;
}

// ═══════════════════════════════════════════════════════════════════════════════
// Weather Result Types
// ═══════════════════════════════════════════════════════════════════════════════

export interface WeatherCondition {
  description: string;
  icon: string;
  temperature: number;
  feelsLike?: number;
  humidity?: number;
  windSpeed?: number;
  windDirection?: string;
  pressure?: number;
  visibility?: number;
  uvIndex?: number;
}

export interface WeatherForecast {
  date: string;
  high: number;
  low: number;
  condition: string;
  icon: string;
  precipitationChance?: number;
}

export interface WeatherResult extends BaseStructuredResult {
  type: 'weather';
  location: string;
  current: WeatherCondition;
  forecast?: WeatherForecast[];
  unit: 'celsius' | 'fahrenheit';
}

// ═══════════════════════════════════════════════════════════════════════════════
// Stock/Finance Result Types
// ═══════════════════════════════════════════════════════════════════════════════

export interface StockResult extends BaseStructuredResult {
  type: 'stock';
  symbol: string;
  name: string;
  price: number;
  change: number;
  changePercent: number;
  currency: string;
  market: string;
  volume?: number;
  marketCap?: number;
  dayHigh?: number;
  dayLow?: number;
  yearHigh?: number;
  yearLow?: number;
  peRatio?: number;
  dividend?: number;
  lastUpdated: string;
}

// ═══════════════════════════════════════════════════════════════════════════════
// Calculation Result Type
// ═══════════════════════════════════════════════════════════════════════════════

export interface CalculationResult extends BaseStructuredResult {
  type: 'calculation';
  expression: string;
  result: number | string;
  steps?: string[];
}

// ═══════════════════════════════════════════════════════════════════════════════
// Definition/Translation Result Types
// ═══════════════════════════════════════════════════════════════════════════════

export interface Definition {
  partOfSpeech: string;
  definition: string;
  example?: string;
  synonyms?: string[];
}

export interface DefinitionResult extends BaseStructuredResult {
  type: 'definition';
  word: string;
  pronunciation?: string;
  audioUrl?: string;
  definitions: Definition[];
  etymology?: string;
}

export interface TranslationResult extends BaseStructuredResult {
  type: 'translation';
  originalText: string;
  translatedText: string;
  fromLanguage: string;
  toLanguage: string;
  pronunciation?: string;
}

// ═══════════════════════════════════════════════════════════════════════════════
// Time Result Type
// ═══════════════════════════════════════════════════════════════════════════════

export interface TimeResult extends BaseStructuredResult {
  type: 'time';
  location: string;
  timezone: string;
  currentTime: string;
  date: string;
  dayOfWeek: string;
  isDST: boolean;
  utcOffset: string;
}

// ═══════════════════════════════════════════════════════════════════════════════
// Currency Result Type
// ═══════════════════════════════════════════════════════════════════════════════

export interface CurrencyResult extends BaseStructuredResult {
  type: 'currency';
  from: {
    amount: number;
    currency: string;
    symbol: string;
  };
  to: {
    amount: number;
    currency: string;
    symbol: string;
  };
  rate: number;
  inverseRate: number;
  lastUpdated: string;
}

// ═══════════════════════════════════════════════════════════════════════════════
// Code Result Type
// ═══════════════════════════════════════════════════════════════════════════════

export interface CodeResult extends BaseStructuredResult {
  type: 'code';
  language: string;
  code: string;
  explanation?: string;
  output?: string;
}

// ═══════════════════════════════════════════════════════════════════════════════
// Table Result Type
// ═══════════════════════════════════════════════════════════════════════════════

export interface TableColumn {
  key: string;
  header: string;
  type?: 'text' | 'number' | 'date' | 'currency' | 'percent' | 'link';
}

export interface TableResult extends BaseStructuredResult {
  type: 'table';
  columns: TableColumn[];
  rows: Record<string, string | number | boolean | null>[];
  sortable?: boolean;
  filterable?: boolean;
}

// ═══════════════════════════════════════════════════════════════════════════════
// List Result Type
// ═══════════════════════════════════════════════════════════════════════════════

export interface ListItem {
  id: string;
  title: string;
  description?: string;
  icon?: string;
  url?: string;
  metadata?: Record<string, string | number | boolean>;
}

export interface ListResult extends BaseStructuredResult {
  type: 'list';
  items: ListItem[];
  ordered: boolean;
}

// ═══════════════════════════════════════════════════════════════════════════════
// Link Result Type
// ═══════════════════════════════════════════════════════════════════════════════

export interface LinkResult extends BaseStructuredResult {
  type: 'link';
  url: string;
  title: string;
  description?: string;
  favicon?: string;
  image?: string;
  domain?: string;
}

// ═══════════════════════════════════════════════════════════════════════════════
// Image Result Type
// ═══════════════════════════════════════════════════════════════════════════════

export interface ImageResult extends BaseStructuredResult {
  type: 'image';
  url: string;
  thumbnailUrl?: string;
  title?: string;
  description?: string;
  width?: number;
  height?: number;
  source?: string;
}

// ═══════════════════════════════════════════════════════════════════════════════
// Video Result Type
// ═══════════════════════════════════════════════════════════════════════════════

export interface VideoResult extends BaseStructuredResult {
  type: 'video';
  videoId: string;
  title: string;
  description?: string;
  thumbnailUrl?: string;
  duration?: string;
  channel?: string;
  publishedAt?: string;
  viewCount?: number;
  platform: 'youtube' | 'vimeo' | 'other';
}

// ═══════════════════════════════════════════════════════════════════════════════
// Generic/Custom Result Type
// ═══════════════════════════════════════════════════════════════════════════════

export interface GenericResult extends BaseStructuredResult {
  type: 'generic';
  data: Record<string, unknown>;
  displayTemplate?: string;
}

// ═══════════════════════════════════════════════════════════════════════════════
// Union Type for All Results
// ═══════════════════════════════════════════════════════════════════════════════

export type StructuredResult =
  | LocationResult
  | LocationSearchResult
  | WeatherResult
  | StockResult
  | CalculationResult
  | DefinitionResult
  | TranslationResult
  | TimeResult
  | CurrencyResult
  | CodeResult
  | TableResult
  | ListResult
  | LinkResult
  | ImageResult
  | VideoResult
  | GenericResult;

// ═══════════════════════════════════════════════════════════════════════════════
// Result Wrapper Type (for embedding in messages)
// ═══════════════════════════════════════════════════════════════════════════════

export interface StructuredResultWrapper {
  /** The structured result data */
  result: StructuredResult;
  /** Whether this result was generated by the AI or is a placeholder */
  isGenerated: boolean;
  /** Timestamp when the result was generated */
  generatedAt: string;
  /** Optional query that generated this result */
  query?: string;
  /** Optional confidence score (0-1) */
  confidence?: number;
}

// ═══════════════════════════════════════════════════════════════════════════════
// Helper Functions
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Type guard to check if a result is a location result
 */
export function isLocationResult(result: StructuredResult): result is LocationResult {
  return result.type === 'location' && 'placeId' in result;
}

/**
 * Type guard to check if a result is a location search result
 */
export function isLocationSearchResult(result: StructuredResult): result is LocationSearchResult {
  return result.type === 'location' && 'results' in result && Array.isArray((result as LocationSearchResult).results);
}

/**
 * Type guard to check if a result is a weather result
 */
export function isWeatherResult(result: StructuredResult): result is WeatherResult {
  return result.type === 'weather' && 'current' in result;
}

/**
 * Type guard to check if a result is a stock result
 */
export function isStockResult(result: StructuredResult): result is StockResult {
  return result.type === 'stock' && 'symbol' in result;
}

/**
 * Type guard to check if a result is a calculation result
 */
export function isCalculationResult(result: StructuredResult): result is CalculationResult {
  return result.type === 'calculation' && 'expression' in result;
}

/**
 * Attempt to parse a JSON string into a StructuredResult
 */
export function parseStructuredResult(json: string): StructuredResult | null {
  try {
    const parsed = JSON.parse(json);
    if (parsed && typeof parsed === 'object' && 'type' in parsed) {
      return parsed as StructuredResult;
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * Attempt to extract a structured result from AI response content
 * Looks for JSON blocks in markdown code blocks
 */
export function extractStructuredResult(content: string): StructuredResult | null {
  // Look for JSON in code blocks
  const jsonBlockRegex = /```(?:json)?\s*([\s\S]*?)```/g;
  let match;
  
  while ((match = jsonBlockRegex.exec(content)) !== null) {
    const result = parseStructuredResult(match[1].trim());
    if (result) return result;
  }
  
  // Try parsing the entire content if it looks like JSON
  const trimmed = content.trim();
  if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
    return parseStructuredResult(trimmed);
  }
  
  return null;
}
