/**
 * RendererInstructions — type definitions for the EvidenceInterpreter output.
 *
 * These are the ONLY data structures that DatasetWorkspace consumes.
 * DatasetWorkspace NEVER imports EvidenceReference or EvidenceCollection directly.
 * The EvidenceInterpreter is the single translation seam between evidence and renderer.
 *
 * Architecture invariant:
 *   EvidenceReference → EvidenceInterpreter → RenderInstructionSet → DatasetWorkspace
 *
 * @typedef {Object} HighlightInstruction
 * @property {number[]} rowIndices   - Absolute row indices to highlight
 * @property {string[]} columnNames  - Specific columns to highlight (empty = all columns)
 * @property {string}   color        - CSS color token: 'amber' | 'red' | 'green' | 'blue' | 'purple'
 * @property {number}   opacity      - 0.0–1.0 glow intensity
 * @property {boolean}  pulse        - Play pulse animation on first render
 * @property {string}   label        - Tooltip label for highlighted rows
 * @property {string}   evidenceId   - Source evidence ID for click-through
 *
 * @typedef {Object} NavigationInstruction
 * @property {'scroll_to_row' | 'center_row' | 'none'} action
 * @property {number}  targetRowIndex
 * @property {'instant' | 'smooth'} behavior
 *
 * @typedef {Object} FocusInstruction
 * @property {boolean}  enabled       - If true, non-highlighted rows are faded
 * @property {number}   fadedOpacity  - Opacity for non-highlighted rows (default 0.25)
 *
 * @typedef {Object} AnnotationInstruction
 * @property {number}  rowIndex
 * @property {string}  text          - Tooltip text shown on hover
 * @property {'info' | 'warning' | 'error'} type
 *
 * @typedef {Object} RenderInstructionSet
 * @property {HighlightInstruction[]}   highlights   - Row/column highlights
 * @property {NavigationInstruction}    navigation   - Where to scroll
 * @property {FocusInstruction}         focus        - Whether to fade non-highlighted rows
 * @property {AnnotationInstruction[]}  annotations  - Row-level tooltips
 * @property {string}                   evidenceId   - Source evidence ID
 * @property {'single'|'collection'}    mode         - Rendering mode
 * @property {boolean}                  hasLegend    - Show color legend (for collections)
 * @property {Array<{label:string, color:string, count:number}>} legend - Legend items
 */

/**
 * Create an empty (no-op) RenderInstructionSet.
 * Used to clear highlights without emitting a null.
 * @returns {RenderInstructionSet}
 */
export function emptyRenderInstructions() {
  return {
    highlights: [],
    navigation: { action: 'none', targetRowIndex: -1, behavior: 'instant' },
    focus: { enabled: false, fadedOpacity: 0.25 },
    annotations: [],
    evidenceId: null,
    mode: 'single',
    hasLegend: false,
    legend: [],
  };
}

/**
 * Highlight color palette for evidence types.
 * Matches workspace.css glow classes: .ws-row--highlight-amber, etc.
 */
export const EVIDENCE_COLORS = Object.freeze({
  top_n:       'amber',
  bottom_n:    'red',
  outliers:    'red',
  missing:     'orange',
  duplicates:  'purple',
  filtered:    'blue',
  correlation: 'cyan',
  rows:        'amber',
  columns:     'blue',
  sample:      'green',
  aggregate:   'green',
  group:       'cyan',
  // collection references get colors by index
  _collection: ['amber', 'blue', 'green', 'purple', 'cyan', 'red'],
});
