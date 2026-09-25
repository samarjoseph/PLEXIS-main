/**
 * WorkspaceNavigator — executes navigation commands in the DatasetWorkspace.
 *
 * Subscribes to Events.NAVIGATE_TO_EVIDENCE via EventBus.
 * Receives a NavCommand object and scrolls the workspace virtual list accordingly.
 *
 * The virtual list ref is set by DatasetWorkspace on mount via setListRef().
 * This singleton bridges the EventBus event layer to the DOM scroll layer.
 */
import { EventBus } from '../events/EventBus.js';
import { Events } from '../events/Events.js';
import { EvidenceRegistry } from '../evidence/EvidenceRegistry.js';
import { locatorResolver } from './LocatorResolver.js';

class WorkspaceNavigatorClass {
  constructor() {
    this._listRef = null;
    this._loadedRows = [];
    this._columnNames = [];
    this._scrollToRowFn = null; // (rowIndex: number) => void — set by DatasetWorkspace

    // Subscribe to navigation events
    EventBus.on(Events.NAVIGATE_TO_EVIDENCE, ({ evidenceId }) => {
      this._navigateToEvidence(evidenceId);
    });
    EventBus.on(Events.NAVIGATE_TO_ROW, ({ rowIndex }) => {
      this.scrollToRow(rowIndex);
    });
  }

  /**
   * Set the scroll-to-row callback. Called by DatasetWorkspace on mount.
   * @param {Function} fn - (rowIndex: number) => void
   */
  setScrollCallback(fn) {
    this._scrollToRowFn = fn;
  }

  /**
   * Update the currently loaded rows for locator resolution.
   * Called by WorkspaceContext whenever rows change.
   */
  setContext(loadedRows, columnNames) {
    this._loadedRows = loadedRows;
    this._columnNames = columnNames;
  }

  /**
   * Execute a NavCommand.
   * @param {Object} command - NavCommand from NavigationCommands.js
   */
  execute(command) {
    if (!command?.type) return;

    switch (command.type) {
      case 'TO_EVIDENCE':
        this._navigateToEvidence(command.evidenceId);
        break;
      case 'TO_ROW':
        this.scrollToRow(command.rowIndex);
        break;
      case 'TO_TOP':
        this.scrollToRow(0);
        break;
      case 'TO_PROPORTION': {
        const totalRows = this._loadedRows.length;
        const targetRow = Math.floor((command.proportion ?? 0) * totalRows);
        this.scrollToRow(targetRow);
        break;
      }
      default:
        console.warn(`[WorkspaceNavigator] Unknown command type: ${command.type}`);
    }
  }

  /** Scroll to a specific row index. */
  scrollToRow(rowIndex) {
    if (typeof this._scrollToRowFn === 'function') {
      this._scrollToRowFn(rowIndex);
    }
  }

  // ── Private ────────────────────────────────────────────────────────────────

  _navigateToEvidence(evidenceId) {
    if (!evidenceId) return;
    const evidence = EvidenceRegistry.get(evidenceId);
    if (!evidence?.locator) return;

    const { rowIndices } = locatorResolver.resolve(
      evidence.locator,
      this._loadedRows,
      this._columnNames,
    );
    if (rowIndices.length > 0) {
      this.scrollToRow(rowIndices[0]);
    }
  }
}

export const WorkspaceNavigator = new WorkspaceNavigatorClass();
