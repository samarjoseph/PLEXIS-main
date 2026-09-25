/**
 * Plexis EventBus — lightweight, typed pub/sub for cross-component communication.
 *
 * Design principles:
 *   - No external dependency (no Redux, no Zustand, no context hell)
 *   - Typed event catalog (Events.js) prevents magic string errors
 *   - Synchronous dispatch — no async event ordering issues
 *   - Components subscribe in useEffect, unsubscribe on cleanup
 *   - Future plugins integrate by subscribing, never by modifying existing components
 *   - Dev-mode validation: unknown events log an error instead of failing silently
 *
 * Usage:
 *   import { EventBus } from '../events/EventBus';
 *   import { Events } from '../events/Events';
 *
 *   // Subscribe:
 *   const unsub = EventBus.on(Events.EVIDENCE_SELECTED, ({ evidenceId }) => { ... });
 *   // Cleanup:
 *   useEffect(() => { return EventBus.on(Events.EVIDENCE_SELECTED, handler); }, []);
 *
 *   // Emit:
 *   EventBus.emit(Events.EVIDENCE_SELECTED, { evidenceId: '...' });
 */

class EventBusClass {
  constructor() {
    /** @type {Map<string, Set<Function>>} */
    this._listeners = new Map();
    this._knownEvents = null; // Lazy-loaded from Events.js in dev mode
  }

  /**
   * Subscribe to an event.
   * @param {string} eventName - Must be a value from Events.js
   * @param {Function} handler - Called with payload when event fires
   * @returns {Function} Unsubscribe function — call in useEffect cleanup
   */
  on(eventName, handler) {
    if (!this._listeners.has(eventName)) {
      this._listeners.set(eventName, new Set());
    }
    this._listeners.get(eventName).add(handler);
    // Return unsubscribe function
    return () => this.off(eventName, handler);
  }

  /**
   * Unsubscribe a specific handler from an event.
   * @param {string} eventName
   * @param {Function} handler
   */
  off(eventName, handler) {
    this._listeners.get(eventName)?.delete(handler);
  }

  /**
   * Emit an event to all registered handlers.
   * Handler errors are caught individually — one bad handler doesn't stop others.
   * @param {string} eventName
   * @param {Object} payload
   */
  emit(eventName, payload = {}) {
    // Dev-mode validation — check event is in catalog
    if (import.meta.env.DEV) {
      if (this._knownEvents === null) {
        // Lazy-load Events catalog to avoid circular import issues
        import('./Events.js').then(({ Events }) => {
          this._knownEvents = new Set(Object.values(Events));
        });
      }
      if (this._knownEvents && !this._knownEvents.has(eventName)) {
        console.error(
          `[EventBus] Unknown event: "${eventName}". Add it to Events.js.`
        );
      }
    }

    const handlers = this._listeners.get(eventName);
    if (!handlers || handlers.size === 0) return;

    handlers.forEach((handler) => {
      try {
        handler(payload);
      } catch (err) {
        console.error(`[EventBus] Handler error for "${eventName}":`, err);
      }
    });
  }

  /**
   * Remove ALL listeners for a specific event.
   * Useful for cleanup in tests.
   * @param {string} eventName
   */
  clear(eventName) {
    this._listeners.delete(eventName);
  }

  /** Remove ALL listeners for ALL events. Use only in tests or full resets. */
  clearAll() {
    this._listeners.clear();
  }

  /** Returns the number of active listeners for an event (useful for debugging). */
  listenerCount(eventName) {
    return this._listeners.get(eventName)?.size ?? 0;
  }
}

export const EventBus = new EventBusClass();
