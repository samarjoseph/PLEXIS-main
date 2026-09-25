/**
 * usePlexisStream
 *
 * Generic React hook for consuming a Plexis SSE stream.
 *
 * This is the only file in the streaming layer that touches React state.
 * It wraps StreamController and exposes streaming state to components.
 *
 * Usage:
 *   const {
 *     text,        // accumulated markdown string
 *     isStreaming, // true from first chunk until done
 *     isError,     // true if error event received
 *     errorMessage,
 *     doneData,    // payload from done event (e.g. dataset_info)
 *     startStream, // call with a fetch() Response to begin
 *     reset,       // reset state for reuse
 *   } = usePlexisStream();
 *
 *   // To stream:
 *   const response = await fetch('/api/upload', { method: 'POST', body: formData });
 *   startStream(response);
 */

import { useCallback, useRef, useState } from 'react';
import { StreamController } from './StreamController.js';
import { StreamEvents } from './StreamEvents.js';

/**
 * @returns {{
 *   text: string,
 *   isStreaming: boolean,
 *   isError: boolean,
 *   errorMessage: string,
 *   doneData: object|null,
 *   startStream: (response: Response) => void,
 *   reset: () => void,
 * }}
 */
export function usePlexisStream() {
  const [text, setText] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [isError, setIsError] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [doneData, setDoneData] = useState(null);

  // Store the StreamController in a ref — not state — to avoid re-renders
  const controllerRef = useRef(null);

  const reset = useCallback(() => {
    // Abort any in-flight stream
    controllerRef.current?.abort();
    controllerRef.current = null;
    setText('');
    setIsStreaming(false);
    setIsError(false);
    setErrorMessage('');
    setDoneData(null);
  }, []);

  /**
   * Begin consuming a fetch() Response as an SSE stream.
   * @param {Response} response
   */
  const startStream = useCallback((response) => {
    // Reset state for a fresh stream
    setText('');
    setIsStreaming(true);
    setIsError(false);
    setErrorMessage('');
    setDoneData(null);

    const controller = new StreamController();
    controllerRef.current = controller;

    controller
      .on(StreamEvents.CHUNK, ({ text: chunk }) => {
        if (chunk) {
          // Append-only update — one setState call per chunk to minimise renders
          setText((prev) => prev + chunk);
        }
      })
      .on(StreamEvents.DONE, (data) => {
        setIsStreaming(false);
        setDoneData(data ?? null);
      })
      .on(StreamEvents.ERROR, ({ message }) => {
        setIsStreaming(false);
        setIsError(true);
        setErrorMessage(message || 'An unexpected streaming error occurred.');
      });

    // Kick off the async consumption in the background
    controller.consume(response).catch((err) => {
      setIsStreaming(false);
      setIsError(true);
      setErrorMessage(err.message || 'Stream consumption failed.');
    });
  }, []);

  return {
    text,
    isStreaming,
    isError,
    errorMessage,
    doneData,
    startStream,
    reset,
  };
}
