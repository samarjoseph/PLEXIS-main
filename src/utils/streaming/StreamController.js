/**
 * StreamController
 *
 * Handles the raw SSE stream mechanics over a fetch() ReadableStream.
 * Parses typed SSE events and dispatches to registered handlers.
 *
 * No React dependency — reusable in any context.
 *
 * Usage:
 *   const controller = new StreamController();
 *   controller.on('chunk', ({ text }) => accumulate(text));
 *   controller.on('done',  (data)       => finalize(data));
 *   controller.on('error', ({ message }) => handleError(message));
 *   await controller.consume(fetchResponse);
 */

import { StreamEvents } from './StreamEvents.js';

export class StreamController {
  constructor() {
    /** @type {Record<string, Function>} */
    this._handlers = {};
    this._reader = null;
    this._aborted = false;
  }

  /**
   * Register a handler for a specific SSE event type.
   * Returns `this` for method chaining.
   * @param {string} eventType
   * @param {Function} handler
   */
  on(eventType, handler) {
    this._handlers[eventType] = handler;
    return this;
  }

  /**
   * Consume a fetch() Response that contains an SSE stream.
   * Reads the stream, parses SSE events, and dispatches to registered handlers.
   *
   * @param {Response} response - The raw fetch Response
   */
  async consume(response) {
    if (!response.ok) {
      this._dispatch(StreamEvents.ERROR, {
        message: `Server returned ${response.status}: ${response.statusText}`,
      });
      return;
    }

    if (!response.body) {
      this._dispatch(StreamEvents.ERROR, { message: 'Response body is empty' });
      return;
    }

    this._reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    try {
      while (!this._aborted) {
        const { done, value } = await this._reader.read();
        if (done) break;

        // Decode the incoming chunk and append to the line buffer
        buffer += decoder.decode(value, { stream: true });

        // SSE messages are separated by double newlines
        const messages = buffer.split('\n\n');
        // The last element may be an incomplete message — keep it in the buffer
        buffer = messages.pop() ?? '';

        for (const rawMessage of messages) {
          if (!rawMessage.trim()) continue;
          this._parseAndDispatch(rawMessage);
        }
      }

      // Flush any remaining buffer content
      if (buffer.trim()) {
        this._parseAndDispatch(buffer);
      }
    } catch (err) {
      if (!this._aborted) {
        this._dispatch(StreamEvents.ERROR, { message: err.message || 'Stream read error' });
      }
    } finally {
      try { this._reader?.releaseLock(); } catch (_) { /* ignore */ }
    }
  }

  /**
   * Abort the current stream read.
   * Useful for stop-generation feature in the future.
   */
  abort() {
    this._aborted = true;
    try { this._reader?.cancel(); } catch (_) { /* ignore */ }
  }

  // ---------------------------------------------------------------------------
  // Private helpers
  // ---------------------------------------------------------------------------

  /**
   * Parse a raw SSE message block and dispatch based on event type.
   * Handles the `event:` and `data:` SSE line format.
   *
   * @param {string} rawMessage
   */
  _parseAndDispatch(rawMessage) {
    let eventType = StreamEvents.CHUNK; // default to chunk if no event: line
    let dataLine = '';

    for (const line of rawMessage.split('\n')) {
      if (line.startsWith('event:')) {
        eventType = line.slice(6).trim();
      } else if (line.startsWith('data:')) {
        dataLine = line.slice(5).trim();
      }
    }

    if (!dataLine) return;

    let parsed;
    try {
      parsed = JSON.parse(dataLine);
    } catch {
      // Plain text chunk (shouldn't happen with our backend, but handle gracefully)
      parsed = { text: dataLine };
    }

    this._dispatch(eventType, parsed);
  }

  /**
   * Dispatch a parsed event to its registered handler (if any).
   * Unknown event types are silently ignored — future-safe by design.
   *
   * @param {string} eventType
   * @param {any} data
   */
  _dispatch(eventType, data) {
    const handler = this._handlers[eventType];
    if (typeof handler === 'function') {
      try {
        handler(data);
      } catch (err) {
        console.error(`[StreamController] Handler error for '${eventType}':`, err);
      }
    }
  }
}
