/**
 * EvidenceRegistry — in-memory store for all EvidenceReference and EvidenceCollection
 * objects received from the backend during the current session.
 *
 * Design:
 *   - Singleton, lives for the browser session
 *   - Keyed by evidence.id (UUID)
 *   - Staleness is determined by dataset_fingerprint comparison
 *   - Emits EventBus events on register and on stale marking
 *   - Components read from registry by ID; they never store evidence directly
 *
 * Integration:
 *   Dashboard.jsx registers evidence after every chat response.
 *   EvidenceCard reads from registry by message.evidence.id.
 *   WorkspaceContext subscribes to EVIDENCE_SELECTED to fetch from registry.
 */
import { EventBus } from '../events/EventBus.js';
import { Events } from '../events/Events.js';

class EvidenceRegistryClass {
  constructor() {
    /** @type {Map<string, Object>} id → evidence */
    this._store = new Map();
    /** @type {string | null} Current dataset fingerprint for staleness detection */
    this._currentFingerprint = null;
  }

  /**
   * Register a new evidence object.
   * If evidence with same id already exists, it is overwritten.
   * @param {Object} evidence - EvidenceReference or EvidenceCollection from API
   */
  register(evidence) {
    if (!evidence?.id) {
      console.warn('[EvidenceRegistry] Attempted to register evidence without an id.');
      return;
    }
    this._store.set(evidence.id, { ...evidence, is_stale: false });
    EventBus.emit(Events.EVIDENCE_CREATED, { evidenceId: evidence.id, evidence });
  }

  /**
   * Get a stored evidence object by ID.
   * @param {string} id
   * @returns {Object | null}
   */
  get(id) {
    return this._store.get(id) ?? null;
  }

  /**
   * Returns all stored evidence objects.
   * @returns {Object[]}
   */
  all() {
    return Array.from(this._store.values());
  }

  /**
   * Mark all evidence with a different dataset_fingerprint as stale.
   * Called when a new dataset is uploaded (new fingerprint).
   * @param {string} newFingerprint - The new dataset's fingerprint
   */
  markStaleByFingerprint(newFingerprint) {
    let staleCount = 0;
    this._store.forEach((evidence, id) => {
      if (evidence.dataset_fingerprint && evidence.dataset_fingerprint !== newFingerprint) {
        this._store.set(id, { ...evidence, is_stale: true });
        staleCount++;
      }
    });
    if (staleCount > 0) {
      this._currentFingerprint = newFingerprint;
      EventBus.emit(Events.EVIDENCE_STALE, {
        newFingerprint,
        staleCount,
      });
    }
  }

  /**
   * Update the current dataset fingerprint (called on DATASET_LOADED).
   * @param {string} fingerprint
   */
  setCurrentFingerprint(fingerprint) {
    if (this._currentFingerprint && this._currentFingerprint !== fingerprint) {
      this.markStaleByFingerprint(fingerprint);
    }
    this._currentFingerprint = fingerprint;
  }

  /**
   * Remove all stored evidence. Called on logout or full reset.
   */
  clear() {
    this._store.clear();
    this._currentFingerprint = null;
  }

  /** Count of stored evidence objects */
  get size() {
    return this._store.size;
  }
}

export const EvidenceRegistry = new EvidenceRegistryClass();
