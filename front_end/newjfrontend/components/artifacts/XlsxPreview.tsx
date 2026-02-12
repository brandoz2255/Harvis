"use client"

import React, { useState, useEffect } from "react"
import * as XLSX from "xlsx"
import { Loader2, AlertCircle, FileSpreadsheet } from "lucide-react"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"

interface XlsxPreviewProps {
  downloadUrl: string
  className?: string
}

interface SheetData {
  name: string
  data: any[][]
  rowCount: number
  colCount: number
}

export function XlsxPreview({ downloadUrl, className = "" }: XlsxPreviewProps) {
  const [sheets, setSheets] = useState<SheetData[]>([])
  const [activeSheet, setActiveSheet] = useState<number>(0)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const loadSpreadsheet = async () => {
      try {
        setIsLoading(true)
        setError(null)

        // Fetch the spreadsheet
        const token = localStorage.getItem("token")
        const response = await fetch(downloadUrl, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        })

        if (!response.ok) {
          throw new Error(`Failed to load spreadsheet: ${response.statusText}`)
        }

        // Get the file as array buffer
        const arrayBuffer = await response.arrayBuffer()

        // Parse with XLSX
        const workbook = XLSX.read(arrayBuffer, { type: "array" })

        // Extract data from all sheets
        const sheetData: SheetData[] = workbook.SheetNames.map((sheetName) => {
          const worksheet = workbook.Sheets[sheetName]
          const jsonData = XLSX.utils.sheet_to_json(worksheet, { 
            header: 1,
            defval: "",
          }) as any[][]

          // Limit to first 100 rows for performance
          const limitedData = jsonData.slice(0, 100)

          return {
            name: sheetName,
            data: limitedData,
            rowCount: jsonData.length,
            colCount: Math.max(...jsonData.map((row) => row?.length || 0), 0),
          }
        })

        setSheets(sheetData)
        setActiveSheet(0)
      } catch (err) {
        console.error("Error loading spreadsheet:", err)
        setError(err instanceof Error ? err.message : "Failed to load spreadsheet")
      } finally {
        setIsLoading(false)
      }
    }

    if (downloadUrl) {
      loadSpreadsheet()
    }
  }, [downloadUrl])

  if (isLoading) {
    return (
      <div className={`flex items-center justify-center h-[400px] bg-slate-900/50 rounded-lg ${className}`}>
        <div className="text-center">
          <Loader2 className="h-8 w-8 animate-spin text-violet-400 mx-auto mb-2" />
          <p className="text-sm text-muted-foreground">Loading spreadsheet...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className={`${className}`}>
        <Alert variant="destructive" className="bg-red-500/10 border-red-500/20">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      </div>
    )
  }

  if (sheets.length === 0) {
    return (
      <div className={`flex items-center justify-center h-[200px] bg-slate-900/50 rounded-lg ${className}`}>
        <p className="text-sm text-muted-foreground">No data found in spreadsheet</p>
      </div>
    )
  }

  const currentSheet = sheets[activeSheet]

  return (
    <div className={`xlsx-preview bg-slate-900 rounded-lg overflow-hidden ${className}`}>
      {/* Sheet Tabs */}
      {sheets.length > 1 && (
        <div className="flex border-b border-slate-700 bg-slate-800/50 overflow-x-auto">
          {sheets.map((sheet, index) => (
            <button
              key={sheet.name}
              onClick={() => setActiveSheet(index)}
              className={`px-4 py-2 text-sm font-medium whitespace-nowrap transition-colors ${
                activeSheet === index
                  ? "bg-slate-700 text-white border-b-2 border-violet-400"
                  : "text-muted-foreground hover:bg-slate-800 hover:text-foreground"
              }`}
            >
              <FileSpreadsheet className="h-3 w-3 inline mr-1.5" />
              {sheet.name}
            </button>
          ))}
        </div>
      )}

      {/* Sheet Info */}
      <div className="px-4 py-2 bg-slate-800/30 border-b border-slate-700 text-xs text-muted-foreground">
        {currentSheet.rowCount > 100 && (
          <span className="text-amber-400">Showing first 100 of {currentSheet.rowCount} rows</span>
        )}
      </div>

      {/* Spreadsheet Table */}
      <div className="overflow-auto max-h-[500px]">
        {currentSheet.data.length > 0 ? (
          <table className="w-full text-sm">
            <thead className="bg-slate-800 sticky top-0">
              <tr>
                {currentSheet.data[0]?.map((cell, colIndex) => (
                  <th
                    key={colIndex}
                    className="px-3 py-2 text-left font-medium text-muted-foreground border-b border-slate-700 bg-slate-800"
                  >
                    {cell?.toString() || ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {currentSheet.data.slice(1).map((row, rowIndex) => (
                <tr
                  key={rowIndex}
                  className={rowIndex % 2 === 0 ? "bg-slate-900/50" : "bg-slate-800/20"}
                >
                  {row?.map((cell, colIndex) => (
                    <td
                      key={colIndex}
                      className="px-3 py-2 text-foreground border-b border-slate-800"
                    >
                      {cell?.toString() || ""}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="flex items-center justify-center h-[200px]">
            <p className="text-sm text-muted-foreground">Empty sheet</p>
          </div>
        )}
      </div>
    </div>
  )
}

export default XlsxPreview
