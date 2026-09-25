/**
 * EvidenceInterpreter — the single translation seam between evidence and renderer.
 *
 * Architecture invariant:
 *   EvidenceReference → EvidenceInterpreter → RenderInstructionSet → DatasetWorkspace
 *
 * DatasetWorkspace NEVER imports EvidenceReference. It only receives RenderInstructionSet.
 * This is enforced by convention (and documented as a rule in the codebase).
 *
 * Usage:
 *   const instructions = EvidenceInterpreter.interpret(evidence, loadedRows, columnNames);
 *   // instructions is a RenderInstructionSet — safe to pass to DatasetWorkspace
 */
import { EVIDENCE_COLORS, emptyRenderInstructions } from '../models/RendererInstructions.js';
import { locatorResolver } from '../workspace/LocatorResolver.js';

class EvidenceInterpreterClass {
  /**
   * Interpret an evidence object into a RenderInstructionSet.
   *
   * @param {Object} evidence       - EvidenceReference or EvidenceCollection from API/registry
   * @param {Object[]} loadedRows   - Currently loaded rows in workspace
   * @param {string[]} columnNames  - Column names in order
   * @returns {RenderInstructionSet}
   */
  interpret(evidence, loadedRows, columnNames) {
    if (!evidence) return emptyRenderInstructions();

    try {
      if (evidence.type === 'collection') {
        return this._interpretCollection(evidence, loadedRows, columnNames);
      }
      return this._interpretSingle(evidence, loadedRows, columnNames);
    } catch (err) {
      console.error('[EvidenceInterpreter] Interpretation failed:', err);
      return emptyRenderInstructions();
    }
  }

  // ── Private ────────────────────────────────────────────────────────────────

  _interpretSingle(evidence, loadedRows, columnNames) {
    const color = this._colorForType(evidence.type);

    // Resolve locator to current display indices.
    // In v2 (WindowCache architecture), loadedRows is always empty.
    // We fall through to fallback_indices (absolute dataset row indices) directly.
    let rowIndices = [];
    let isStable = true;

    if (evidence.locator) {
      if (loadedRows?.length) {
        // Legacy path: resolve against loaded rows
        const resolved = locatorResolver.resolve(evidence.locator, loadedRows, columnNames);
        rowIndices = resolved.rowIndices;
        isStable = resolved.isStable;
      } else if (evidence.locator.fallback_indices?.length) {
        // v2 path: use absolute indices directly (backend provides them)
        rowIndices = evidence.locator.fallback_indices;
        isStable = false; // positional indices may drift if dataset changes
      }
    }

    // Choose navigation target — scroll to first highlighted row
    const targetRow = rowIndices[0] ?? -1;

    // Build annotations for highlighted rows
    const annotations = rowIndices.slice(0, 20).map((idx) => ({
      rowIndex: idx,
      text: evidence.description || 'Evidence',
      type: color === 'red' ? 'warning' : 'info',
    }));

    return {
      highlights: rowIndices.length > 0 ? [{
        rowIndices,
        columnNames: evidence.column_names || [],
        color,
        opacity: 0.85,
        pulse: true,
        label: evidence.description || '',
        evidenceId: evidence.id,
        isStable,
      }] : [],
      navigation: {
        action: targetRow >= 0 ? 'scroll_to_row' : 'none',
        targetRowIndex: targetRow,
        behavior: 'smooth',
      },
      focus: {
        enabled: rowIndices.length > 0 && rowIndices.length < 50,
        fadedOpacity: 0.2,
      },
      annotations,
      evidenceId: evidence.id,
      mode: 'single',
      hasLegend: false,
      legend: [],
    };
  }

  _interpretCollection(evidence, loadedRows, columnNames) {
    const palette = EVIDENCE_COLORS._collection;
    const highlights = [];
    const annotations = [];
    const legend = [];

    evidence.references?.forEach((ref, idx) => {
      const color = palette[idx % palette.length];
      let rowIndices = [];

      if (ref.locator) {
        if (loadedRows?.length) {
          const resolved = locatorResolver.resolve(ref.locator, loadedRows, columnNames);
          rowIndices = resolved.rowIndices;
        } else if (ref.locator.fallback_indices?.length) {
          // v2 path: use absolute indices directly
          rowIndices = ref.locator.fallback_indices;
        }
      }

      if (rowIndices.length > 0) {
        highlights.push({
          rowIndices,
          columnNames: ref.column_names || [],
          color,
          opacity: 0.8,
          pulse: idx === 0,
          label: ref.description || `Reference ${idx + 1}`,
          evidenceId: ref.id,
          isStable: true,
        });
        annotations.push(...rowIndices.slice(0, 5).map((ri) => ({
          rowIndex: ri,
          text: ref.description || `Group ${idx + 1}`,
          type: 'info',
        })));
        legend.push({
          label: ref.description || `Group ${idx + 1}`,
          color,
          count: rowIndices.length,
        });
      }
    });

    const firstRowIndex = highlights[0]?.rowIndices[0] ?? -1;

    return {
      highlights,
      navigation: {
        action: firstRowIndex >= 0 ? 'scroll_to_row' : 'none',
        targetRowIndex: firstRowIndex,
        behavior: 'smooth',
      },
      focus: {
        enabled: highlights.length > 0,
        fadedOpacity: 0.15,
      },
      annotations,
      evidenceId: evidence.id,
      mode: 'collection',
      hasLegend: legend.length > 1,
      legend,
    };
  }

  _colorForType(type) {
    return EVIDENCE_COLORS[type] || 'amber';
  }
}

export const EvidenceInterpreter = new EvidenceInterpreterClass();
