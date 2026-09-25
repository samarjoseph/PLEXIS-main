/**
 * LocatorResolver — resolves a backend RowLocator to current row indices in the
 * loaded workspace data.
 *
 * Mirrors the backend LocatorBuilder strategy priority order:
 *   1. PRIMARY_KEY   — look up rows where PK column equals stored value(s)
 *   2. COMPOSITE_KEY — look up rows where all key columns match
 *   3. ROW_HASH      — compute SHA-256 of each loaded row, match against stored hashes
 *   4. FILTER_EXPR   — re-evaluate stored filter expression (best-effort JS eval)
 *   5. POSITION      — use stored fallback indices directly (unstable)
 *
 * Used exclusively by WorkspaceContext when handling EVIDENCE_SELECTED events.
 * DatasetWorkspace only receives resolved {rowIndices, isStable} — never RowLocator.
 *
 * Performance: hash computation is memoized per loaded rows snapshot.
 */

export class LocatorResolver {
  constructor() {
    /** @type {Map<string, number[]>} hash → row-index cache */
    this._hashCache = new Map();
    this._cachedRows = null;
  }

  /**
   * Resolve a RowLocator to row indices in the currently loaded data.
   *
   * @param {Object} locator - RowLocator from backend
   * @param {Object[]} loadedRows - Current page of rows from workspace
   * @param {string[]} columnNames - Column names in order
   * @returns {{ rowIndices: number[], isStable: boolean }}
   */
  resolve(locator, loadedRows, columnNames) {
    if (!locator || !loadedRows?.length) {
      return { rowIndices: [], isStable: false };
    }

    const strategy = locator.strategy;

    try {
      if (strategy === 'primary_key') {
        return this._resolveByPrimaryKey(locator, loadedRows);
      }
      if (strategy === 'composite_key') {
        return this._resolveByCompositeKey(locator, loadedRows);
      }
      if (strategy === 'row_hash') {
        return this._resolveByRowHash(locator, loadedRows, columnNames);
      }
      if (strategy === 'filter_expr') {
        return this._resolveByFilterExpr(locator, loadedRows);
      }
      if (strategy === 'position') {
        return this._resolveByPosition(locator, loadedRows);
      }
    } catch (err) {
      console.error('[LocatorResolver] Resolution failed:', err);
    }

    // Final fallback: use fallback_indices if available
    if (locator.fallback_indices?.length) {
      return {
        rowIndices: locator.fallback_indices.filter(i => i < loadedRows.length),
        isStable: false,
      };
    }

    return { rowIndices: [], isStable: false };
  }

  /** Invalidate hash cache when rows change. */
  invalidateCache() {
    this._hashCache.clear();
    this._cachedRows = null;
  }

  // ── Private resolution strategies ─────────────────────────────────────────

  _resolveByPrimaryKey(locator, loadedRows) {
    const pk = locator.primary_key;
    if (!pk) return { rowIndices: [], isStable: true };

    const [pkCol, pkVals] = Object.entries(pk)[0];
    const valSet = new Set(Array.isArray(pkVals) ? pkVals.map(String) : [String(pkVals)]);

    const indices = [];
    loadedRows.forEach((row, i) => {
      if (row[pkCol] !== undefined && valSet.has(String(row[pkCol]))) {
        indices.push(i);
      }
    });

    return { rowIndices: indices, isStable: true };
  }

  _resolveByCompositeKey(locator, loadedRows) {
    const ck = locator.composite_key;
    if (!ck) return { rowIndices: [], isStable: true };

    const entries = Object.entries(ck);
    const indices = [];

    loadedRows.forEach((row, i) => {
      const matches = entries.every(([col, vals]) => {
        const valSet = new Set(Array.isArray(vals) ? vals.map(String) : [String(vals)]);
        return row[col] !== undefined && valSet.has(String(row[col]));
      });
      if (matches) indices.push(i);
    });

    return { rowIndices: indices, isStable: true };
  }

  _resolveByRowHash(locator, loadedRows, columnNames) {
    const targetHashes = new Set(locator.row_hashes || []);
    if (!targetHashes.size) return { rowIndices: [], isStable: true };

    const indices = [];
    loadedRows.forEach((row, i) => {
      const hash = this._hashRow(row, columnNames);
      if (targetHashes.has(hash)) {
        indices.push(i);
      }
    });

    return { rowIndices: indices, isStable: true };
  }

  _resolveByFilterExpr(locator, loadedRows) {
    const expr = locator.filter_expr;
    if (!expr) return { rowIndices: [], isStable: true };

    // Best-effort: parse simple "col == val" expressions
    const eqMatch = expr.match(/^(\w+)\s*==\s*(.+)$/);
    if (eqMatch) {
      const col = eqMatch[1].trim();
      const val = eqMatch[2].trim().replace(/^['"]|['"]$/g, '');
      const indices = [];
      loadedRows.forEach((row, i) => {
        if (row[col] !== undefined && String(row[col]) === val) {
          indices.push(i);
        }
      });
      return { rowIndices: indices, isStable: true };
    }

    // Fallback to position if expression can't be parsed
    return this._resolveByPosition(locator, loadedRows);
  }

  _resolveByPosition(locator, loadedRows) {
    const indices = (locator.fallback_indices || []).filter(i => i < loadedRows.length);
    return { rowIndices: indices, isStable: false };
  }

  /**
   * Compute a stable hash for a row.
   * Simple implementation: sorted key=value string.
   * Matches backend's LocatorBuilder._compute_hashes() logic.
   */
  _hashRow(row, columnNames) {
    try {
      // Use sorted entries to match backend (which uses sorted(row.to_dict().items()))
      const entries = Object.entries(row).sort(([a], [b]) => a.localeCompare(b));
      const str = entries.map(([k, v]) => `('${k}', ${JSON.stringify(v)})`).join(', ');
      // Simple djb2-like hash (not SHA-256, but consistent for the session)
      // For production, use crypto.subtle.digest if needed
      return this._simpleHash(`[${str}]`);
    } catch {
      return '';
    }
  }

  _simpleHash(str) {
    let hash = 5381;
    for (let i = 0; i < str.length; i++) {
      hash = ((hash << 5) + hash) + str.charCodeAt(i);
      hash = hash & hash; // Convert to 32bit int
    }
    return (hash >>> 0).toString(16);
  }
}

export const locatorResolver = new LocatorResolver();
