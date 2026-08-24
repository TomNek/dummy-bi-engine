/**
 * FormulaBar - Power BI-style DAX formula editor
 * 
 * Displays context-sensitive editor for various DAX objects:
 * - Measures
 * - Calculated tables
 * - Calculated columns
 * - Field parameters
 * - What-if parameters
 * - Calculation items
 */

import { useCallback, useEffect } from 'react'
import { useFormulaBarStore } from '@/stores'
import { 
  getMeasure, updateMeasure, 
  getCalcTable, updateCalcTable,
  listCalcColumns, updateCalcColumn,
  getCalculationGroups, updateCalculationGroups,
  getFieldParameters, updateFieldParameters,
  getWhatIfParameters, updateWhatIfParameters,
  type FieldParameterDef, type WhatIfParameterDef,
} from '@/lib/api'
import { useAppStore } from '@/stores'
import { DaxAutocompleteTextarea } from '@/components/ui/dax-autocomplete-textarea'
import { Button } from '@/components/ui/button'

// Parse Power BI field parameter DAX back to spec
// Format: Name = { ("Label", "ColumnRef" | NAMEOF(...), Sort [, SortColumn]), ... }
// SortColumn can be: NAMEOF(...) or "ColumnName"
function parseFieldParamDAX(dax: string): FieldParameterDef | null {
  const daxText = (dax || '').trim()
  if (!daxText) return null
  
  // Match the table literal pattern
  const tableMatch = daxText.match(/^\s*\w+\s*=\s*\{([\s\S]*)\}\s*$/)
  if (!tableMatch) return null
  
  const body = tableMatch[1].trim()
  if (!body) return { items: [] }
  
  // Parse rows: ("Label", Ref, Sort) or ("Label", Ref, Sort, SortColumn)
  // Ref can be: NAMEOF(...), BLANK(), or "StringRef"
  // SortColumn can be: NAMEOF(...) or "StringRef"
  const items: FieldParameterDef['items'] = []
  // Match 3 or 4 element tuples - 4th element can be NAMEOF(...) or "string"
  const rowPattern = /\(\s*"([^"]+)"\s*,\s*(NAMEOF\s*\([^)]+\)|BLANK\s*\(\s*\)|"[^"]*")\s*,\s*(\d+)\s*(?:,\s*(NAMEOF\s*\([^)]+\)|"[^"]*"))?\s*\)/gi
  let match: RegExpExecArray | null
  while ((match = rowPattern.exec(body)) !== null) {
    const label = match[1]
    const refExpr = match[2]
    const sort = parseInt(match[3], 10)
    const sortColExpr = match[4] // optional 4th element - sort column reference
    
    let ref: NonNullable<FieldParameterDef['items']>[0]['ref'] = undefined
    // Parse NAMEOF('Table'[Column]) or NAMEOF([Measure])
    const colMatch = refExpr.match(/NAMEOF\s*\(\s*'([^']+)'\s*\[\s*([^\]]+)\s*\]\s*\)/i)
    const measureMatch = refExpr.match(/NAMEOF\s*\(\s*\[\s*([^\]]+)\s*\]\s*\)/i)
    // Plain string reference (e.g., "Brand" -> column name without table)
    const stringMatch = refExpr.match(/^"([^"]*)"$/)
    
    if (colMatch) {
      ref = { type: 'ColumnRef', table: colMatch[1], column: colMatch[2] }
    } else if (measureMatch) {
      ref = { type: 'MeasureRef', name: measureMatch[1] }
    } else if (stringMatch) {
      // Plain string reference - store as column name (table will need resolution)
      ref = { type: 'ColumnRef', column: stringMatch[1] }
    }
    
    // Parse sort column if present
    let sortColumn: string | undefined
    if (sortColExpr) {
      const sortColMatch = sortColExpr.match(/NAMEOF\s*\(\s*'([^']+)'\s*\[\s*([^\]]+)\s*\]\s*\)/i)
      const sortColString = sortColExpr.match(/^"([^"]*)"$/)
      if (sortColMatch) {
        sortColumn = `${sortColMatch[1]}[${sortColMatch[2]}]`
      } else if (sortColString) {
        sortColumn = sortColString[1]
      }
    }
    
    items.push({ name: label, sort, ref, ...(sortColumn && { sortColumn }) })
  }
  
  return { items }
}

// Parse What-If parameter DAX back to spec
// Format: Name = GENERATESERIES(min, max, step)
function parseWhatIfDAX(dax: string): WhatIfParameterDef | null {
  const daxText = (dax || '').trim()
  if (!daxText) return null
  
  // Match GENERATESERIES pattern
  const genMatch = daxText.match(/GENERATESERIES\s*\(\s*([^,]+)\s*,\s*([^,]+)\s*,\s*([^)]+)\s*\)/i)
  if (!genMatch) return null
  
  const min = parseFloat(genMatch[1])
  const max = parseFloat(genMatch[2])
  const step = parseFloat(genMatch[3])
  
  if (isNaN(min) || isNaN(max) || isNaN(step)) return null
  
  // Extract format from comment (-- or // style)
  const formatMatch = daxText.match(/(?:--|\/)\s*Format:\s*(.+)/i)
  const format = formatMatch ? formatMatch[1].trim() : undefined
  
  // Extract default from comment (-- or // style)
  const defaultMatch = daxText.match(/(?:--|\/)\s*Default:\s*([0-9.+-]+)/i)
  const defaultVal = defaultMatch ? parseFloat(defaultMatch[1]) : min
  
  return { min, max, step, default: isNaN(defaultVal) ? min : defaultVal, format }
}

export function FormulaBar() {
  const selection = useFormulaBarStore(s => s.selection)
  const dax = useFormulaBarStore(s => s.dax)
  const error = useFormulaBarStore(s => s.error)
  const loading = useFormulaBarStore(s => s.loading)
  const isDirty = useFormulaBarStore(s => s.isDirty)
  const setDax = useFormulaBarStore(s => s.setDax)
  const setOriginalDax = useFormulaBarStore(s => s.setOriginalDax)
  const setError = useFormulaBarStore(s => s.setError)
  const setLoading = useFormulaBarStore(s => s.setLoading)
  
  const projectPath = useAppStore(s => s.projectPath)

  // Load DAX when selection changes
  useEffect(() => {
    if (!selection) return

    const loadDax = async () => {
      setLoading(true)
      setError(null)
      
      try {
        switch (selection.kind) {
          case 'measure': {
            if (!selection.name) break
            const result = await getMeasure(selection.name, projectPath || undefined)
            if (result.data?.measure) {
              setOriginalDax(result.data.measure.dax || '')
            } else if (result.error) {
              setError(result.error)
            }
            break
          }
          case 'calc_table': {
            if (!selection.name) break
            const result = await getCalcTable(selection.name, projectPath || undefined)
            if (result.data?.calculated_table) {
              setOriginalDax(
                result.data.calculated_table.expression ||
                result.data.calculated_table.dax ||
                ''
              )
            } else if (result.error) {
              setError(result.error)
            }
            break
          }
          case 'calc_column': {
            if (!selection.table || !selection.column) break
            const result = await listCalcColumns(projectPath || undefined)
            if (result.data?.calculated_columns) {
              const col = result.data.calculated_columns.find(
                c => c.table === selection.table && c.column === selection.column
              )
              if (col) {
                setOriginalDax(col.dax || '')
              } else {
                setError(`Calculated column ${selection.table}[${selection.column}] not found`)
              }
            } else if (result.error) {
              setError(result.error)
            }
            break
          }
          case 'calc_item': {
            if (!selection.group || !selection.item) break
            const result = await getCalculationGroups(projectPath || undefined)
            if (result.data?.calculation_groups) {
              const group = result.data.calculation_groups[selection.group]
              if (group) {
                const item = group.items?.find(i => i.name === selection.item)
                if (item) {
                  setOriginalDax(item.expression || '')
                } else {
                  setError(`Calculation item "${selection.item}" not found in group "${selection.group}"`)
                }
              } else {
                setError(`Calculation group "${selection.group}" not found`)
              }
            } else if (result.error) {
              setError(result.error)
            }
            break
          }
          case 'field_parameter': {
            if (!selection.name) break
            const result = await getFieldParameters(projectPath || undefined)
            if (result.data?.field_parameters_defs) {
              const def = result.data.field_parameters_defs[selection.name]
              if (def) {
                // Generate Power BI-style DAX: ParameterName = { ("Label", NAMEOF('Table'[Column]), sortOrder), ... }
                const items = def.items || []
                if (items.length === 0) {
                  setOriginalDax(`${selection.name} = { }`)
                } else {
                  // Collect custom property keys across all items (preserve first-seen order)
                  const standardKeys = new Set(['name', 'ref', 'sort', 'sortColumn'])
                  const customKeys: string[] = []
                  for (const item of items) {
                    for (const k of Object.keys(item)) {
                      if (!standardKeys.has(k) && !customKeys.includes(k)) {
                        customKeys.push(k)
                      }
                    }
                  }
                  const itemLines = items.map(item => {
                    const label = item.name
                    let ref = ''
                    // Server returns type: 'ColumnRef' or 'MeasureRef'
                    if ((item.ref?.type === 'ColumnRef' || item.ref?.type === 'column') && item.ref.table && item.ref.column) {
                      ref = `NAMEOF('${item.ref.table}'[${item.ref.column}])`
                    } else if ((item.ref?.type === 'MeasureRef' || item.ref?.type === 'measure') && item.ref.name) {
                      ref = `NAMEOF([${item.ref.name}])`
                    } else {
                      // Fallback - unknown ref type or missing
                      ref = `"${label}"`
                    }
                    const sort = item.sort ?? 0
                    const parts = [`"${label}"`, ref, String(sort)]
                    // Append custom property values as quoted strings
                    for (const ck of customKeys) {
                      const val = item[ck]
                      parts.push(`"${val != null ? String(val) : ''}"`)
                    }
                    return `    (${parts.join(', ')})`
                  })
                  setOriginalDax(`${selection.name} = {\n${itemLines.join(',\n')}\n}`)
                }
              } else {
                setError(`Field parameter "${selection.name}" not found`)
              }
            } else if (result.error) {
              setError(result.error)
            }
            break
          }
          case 'what_if_parameter': {
            if (!selection.name) break
            const result = await getWhatIfParameters(projectPath || undefined)
            if (result.data?.what_if_parameters_defs) {
              const def = result.data.what_if_parameters_defs[selection.name]
              if (def) {
                // Generate Power BI-style DAX: ParameterName = GENERATESERIES(min, max, step)
                setOriginalDax(`${selection.name} = GENERATESERIES(${def.min}, ${def.max}, ${def.step})`)
              } else {
                setError(`What-If parameter "${selection.name}" not found`)
              }
            } else if (result.error) {
              setError(result.error)
            }
            break
          }
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
      } finally {
        setLoading(false)
      }
    }

    loadDax()
  }, [selection, projectPath, setOriginalDax, setError, setLoading])

  const handleSave = useCallback(async () => {
    if (!selection || !isDirty) return
    
    setLoading(true)
    setError(null)

    try {
      switch (selection.kind) {
        case 'measure': {
          if (!selection.name) break
          await updateMeasure(selection.name, { dax }, projectPath || undefined)
          setOriginalDax(dax)
          break
        }
        case 'calc_table': {
          if (!selection.name) break
          await updateCalcTable(selection.name, { dax }, projectPath || undefined)
          setOriginalDax(dax)
          break
        }
        case 'calc_column': {
          if (!selection.table || !selection.column) break
          await updateCalcColumn(selection.table, selection.column, { dax }, projectPath || undefined)
          setOriginalDax(dax)
          break
        }
        case 'calc_item': {
          if (!selection.group || !selection.item) break
          // Load current groups, update the specific item, save back
          const result = await getCalculationGroups(projectPath || undefined)
          if (result.data?.calculation_groups) {
            const groups = { ...result.data.calculation_groups }
            const group = groups[selection.group]
            if (group) {
              const updatedItems = (group.items || []).map(i =>
                i.name === selection.item ? { ...i, expression: dax } : i
              )
              groups[selection.group] = { ...group, items: updatedItems }
              await updateCalculationGroups(groups, projectPath || undefined)
              setOriginalDax(dax)
            }
          }
          break
        }
        case 'field_parameter': {
          if (!selection.name) break
          // Parse DAX back to spec and save
          const parsedSpec = parseFieldParamDAX(dax)
          if (!parsedSpec) {
            setError('Invalid field parameter DAX format. Expected: Name = { ("Label", NAMEOF(...), Sort), ... }')
            break
          }
          // Load current defs, update this parameter, save back
          const result = await getFieldParameters(projectPath || undefined)
          if (result.data?.field_parameters_defs) {
            const defs = { ...result.data.field_parameters_defs }
            defs[selection.name] = parsedSpec
            const saveResult = await updateFieldParameters(defs, projectPath || undefined)
            if (saveResult.error) {
              setError(saveResult.error)
              break
            }
            setOriginalDax(dax)
          } else if (result.error) {
            setError(result.error)
          }
          break
        }
        case 'what_if_parameter': {
          if (!selection.name) break
          // Parse DAX back to spec and save
          const parsedSpec = parseWhatIfDAX(dax)
          if (!parsedSpec) {
            setError('Invalid What-If parameter DAX format. Expected: Name = GENERATESERIES(min, max, step)')
            break
          }
          // Load current defs, update this parameter, save back
          const result = await getWhatIfParameters(projectPath || undefined)
          if (result.data?.what_if_parameters_defs) {
            const defs = { ...result.data.what_if_parameters_defs }
            defs[selection.name] = parsedSpec
            await updateWhatIfParameters(defs, projectPath || undefined)
            setOriginalDax(dax)
          }
          break
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [selection, dax, projectPath, isDirty, setOriginalDax, setError, setLoading])

  const getLabel = (): string => {
    if (!selection) return 'Formula'
    
    switch (selection.kind) {
      case 'measure':
        return `Measure [${selection.name || ''}]`
      case 'calc_item':
        return `Calc Item ${selection.group || ''}[${selection.item || ''}]`
      case 'field_parameter':
        return `Field Parameter [${selection.name || ''}]`
      case 'calc_table':
        return `Calculated Table [${selection.name || ''}]`
      case 'calc_column':
        return `Calculated Column ${selection.table || ''}[${selection.column || ''}]`
      case 'what_if_parameter':
        return `What-If Parameter [${selection.name || ''}]`
      default:
        return 'Formula'
    }
  }

  const getHint = (): string => {
    if (!selection) return 'Select an object to edit its DAX definition.'
    
    switch (selection.kind) {
      case 'measure':
        return 'Edit the measure DAX expression and Save.'
      case 'calc_item':
        return 'Edit the calculation item DAX expression and Save.'
      case 'field_parameter':
        return 'Edit the field parameter DAX table definition and Save.'
      case 'calc_table':
        return 'Edit the calculated table DAX expression and Save.'
      case 'calc_column':
        return 'Edit the calculated column DAX expression and Save.'
      case 'what_if_parameter':
        return 'Edit the What-If parameter DAX definition and Save.'
      default:
        return 'Unsupported selection.'
    }
  }

  const getPlaceholder = (): string => {
    if (!selection) return 'Select an object to edit its DAX definition...'
    
    switch (selection.kind) {
      case 'measure':
        return 'Measure DAX expression'
      case 'calc_item':
        return 'Calculation item DAX expression'
      case 'field_parameter':
        return 'Field parameter DAX table definition'
      case 'calc_table':
        return 'Calculated table DAX expression'
      case 'calc_column':
        return 'Calculated column DAX expression'
      case 'what_if_parameter':
        return 'What-If parameter DAX definition'
      default:
        return 'DAX expression'
    }
  }

  const isEnabled = Boolean(selection)

  return (
    <div 
      data-testid="formula-bar"
      className="border-b bg-muted/30 p-2"
    >
      <div className="flex gap-2 items-start">
        {/* Label */}
        <label className="text-muted-foreground text-sm whitespace-nowrap pt-1">
          <span data-testid="formula-bar-label">{getLabel()}</span>:
        </label>
        
        {/* Input area */}
        <div className="flex-1">
          {/* Hint */}
          {!selection && (
            <div 
              data-testid="formula-bar-hint"
              className="text-muted-foreground text-xs mb-1"
            >
              {getHint()}
            </div>
          )}
          
          {/* DAX textarea with autocomplete */}
          <DaxAutocompleteTextarea
            data-testid="formula-bar-dax"
            aria-label="DAX formula editor"
            rows={1}
            className="w-full font-mono text-sm p-2 border rounded resize-y bg-background disabled:opacity-50"
            placeholder={getPlaceholder()}
            value={dax}
            onChange={(v) => setDax(v)}
            disabled={!isEnabled || loading}
          />
        </div>
        
        {/* Save button */}
        <Button
          data-testid="formula-bar-save"
          aria-label="Save formula"
          size="sm"
          disabled={!isEnabled || !isDirty || loading}
          onClick={handleSave}
        >
          {loading ? 'Saving...' : 'Save'}
        </Button>
      </div>
      
      {/* Error display */}
      {error && (
        <div 
          data-testid="formula-bar-error"
          className="mt-2 text-sm text-destructive"
        >
          {error}
        </div>
      )}
    </div>
  )
}
