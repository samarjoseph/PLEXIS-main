/**
 * Plexis Universal Streaming Event Protocol
 *
 * All SSE streaming endpoints in Plexis use these typed event names.
 * The frontend dispatches on event type rather than assuming every
 * payload is plain text — making the streaming system reusable across
 * any future AI workflow.
 *
 * Currently active:
 *   CHUNK   — LLM text token arriving
 *   DONE    — Generation complete (payload may contain dataset_info, etc.)
 *   ERROR   — Fatal stream error
 *
 * Reserved for future use (not yet active — no implementation needed):
 *   THINKING  — Pre-generation reasoning step
 *   PLANNER   — Planner execution step
 *   PROGRESS  — Generic progress update
 *   TOOL      — Tool execution result
 *   CHART     — Chart data ready
 *   REPORT    — Report generation step
 *   WARNING   — Non-fatal warning
 */
export const StreamEvents = {
  // Active
  CHUNK:        'chunk',
  DONE:         'done',
  ERROR:        'error',

  // RFC-002 module-aware upload pipeline
  ANALYZING:    'analyzing',     // status update during intelligence phases
  MODULE_READY: 'module_ready',  // one module build complete

  // Reserved — extend without breaking changes when needed
  THINKING: 'thinking',
  PLANNER:  'planner',
  PROGRESS: 'progress',
  TOOL:     'tool',
  CHART:    'chart',
  REPORT:   'report',
  WARNING:  'warning',
};
