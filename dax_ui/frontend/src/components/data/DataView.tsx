/**
 * DataView — Main container for the Data View tab.
 * Three-panel layout: table list | data grid + footer | column profile
 */
import { useDataView } from '@/hooks/useDataView'
import { DataTableList } from './DataTableList'
import { DataGrid } from './DataGrid'
import { DataColumnProfile } from './DataColumnProfile'
import { DataFooter } from './DataFooter'

export function DataView() {
  const dv = useDataView()

  return (
    <div className="flex flex-1 overflow-hidden" data-testid="data-view">
      {/* Left: table list */}
      <DataTableList
        tables={dv.tables}
        loading={dv.tablesLoading}
        error={dv.tablesError}
        selectedTable={dv.selectedTable}
        onSelectTable={dv.setSelectedTable}
      />

      {/* Center: grid + footer */}
      <div className="flex flex-col flex-1 overflow-hidden">
        {dv.selectedTable ? (
          <>
            <DataGrid
              columns={dv.columns}
              rows={dv.rows}
              loading={dv.rowsLoading}
              error={dv.rowsError}
              sortColumn={dv.sortColumn}
              sortDir={dv.sortDir}
              onToggleSort={dv.toggleSort}
              filters={dv.filters}
              onSetFilter={dv.setColumnFilter}
              selectedColumn={dv.selectedColumn}
              onSelectColumn={dv.setSelectedColumn}
              profile={dv.profile}
              filterValues={dv.filterValues}
              filterValuesLoading={dv.filterValuesLoading}
              onLoadFilterValues={dv.loadFilterValues}
              page={dv.page}
              pageSize={dv.pageSize}
              sortByMap={dv.sortByMap}
              allTableColumns={dv.allTableColumns}
              onSetSortByColumn={dv.handleSetSortByColumn}
            />
            <DataFooter
              totalRows={dv.totalRows}
              totalColumns={dv.columns.length}
              filterCount={Object.keys(dv.filters).length}
              page={dv.page}
              pageSize={dv.pageSize}
              totalPages={dv.totalPages}
              onSetPage={dv.setPage}
              onSetPageSize={dv.setPageSize}
              onClearFilters={dv.clearAllFilters}
            />
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-muted-foreground" data-testid="data-view-placeholder">
            <p className="text-sm">Select a table to view its data</p>
          </div>
        )}
      </div>

      {/* Right: column profile */}
      {dv.selectedColumn && dv.selectedColumnProfile && (
        <DataColumnProfile
          column={dv.selectedColumnProfile}
          onClose={() => dv.setSelectedColumn(null)}
        />
      )}
    </div>
  )
}
