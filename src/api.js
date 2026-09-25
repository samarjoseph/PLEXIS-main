/**
 * Plexis API Client v2.0 — RFC-002
 *
 * All routes now use explicit dataset_id (not /active/).
 * New module endpoints support the ModuleGrid UI.
 * v2.1: Chat API + X-User-Email identity header for DB persistence.
 */

const BASE_URL = "http://localhost:5000";

/**
 * Get the current user email from localStorage or default to dev user.
 * Set via: localStorage.setItem('plexis_user_email', 'user@example.com')
 */
export function getPlexisUserEmail() {
  return localStorage.getItem('plexis_user_email') || 'dev@plexis.local';
}

/** Default headers for all API requests. */
function defaultHeaders(extra = {}) {
  return {
    'Content-Type': 'application/json',
    'X-User-Email': getPlexisUserEmail(),
    ...extra,
  };
}

export const PlexisAPI = {
  /**
   * Upload a dataset. Returns raw fetch Response for SSE streaming.
   * SSE events: analyzing | module_ready | chunk | done | error
   * @param {string} [chatId] - Optional chat to associate the dataset with
   */
  async uploadCSVStream(file, optionalQuery = "", chatId = null) {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("message", optionalQuery);
    if (chatId) formData.append("chat_id", chatId);
    return fetch(`${BASE_URL}/api/upload`, {
      method: "POST",
      headers: { 'X-User-Email': getPlexisUserEmail() },
      body: formData,
    });
  },

  /**
   * Ask a question — workspace-aware.
   * @param {string} message
   * @param {string} datasetContextId
   * @param {Object} options
   * @param {Object} [options.workspaceState]  - WorkspaceContext state snapshot
   * @param {Object} [options.workspaceAction] - Explicit workspace action
   * @param {string} [options.sessionId]       - Frontend conversation/session ID
   * @param {string} [options.chatId]          - DB chat ID for persistence
   * @returns {Promise<Object>} { answer, source, evidence, _debug, ... }
   */
  async askQuestion(message, datasetContextId = '', options = {}) {
    const { workspaceState = null, workspaceAction = null, sessionId = null, chatId = null } = options;
    const response = await fetch(`${BASE_URL}/api/ask`, {
      method: 'POST',
      headers: defaultHeaders(),
      body: JSON.stringify({
        message,
        dataset_id: datasetContextId,
        session_id: sessionId,
        workspace_state: workspaceState,
        workspace_action: workspaceAction,
        chat_id: chatId,
      }),
    });
    if (!response.ok) throw new Error(`Query failed: ${response.status}`);
    return response.json();
  },

  // ── Module API ────────────────────────────────────────────────────────────

  /** List all available modules for a dataset (sorted by richness). */
  async listModules(datasetId) {
    const r = await fetch(`${BASE_URL}/api/datasets/${datasetId}/modules`, {
      headers: { 'X-User-Email': getPlexisUserEmail() },
    });
    if (!r.ok) throw new Error(`listModules failed: ${r.status}`);
    return r.json();
  },

  /** Get raw JSON data for a specific module. */
  async getModule(datasetId, moduleId) {
    const r = await fetch(`${BASE_URL}/api/datasets/${datasetId}/modules/${moduleId}`, {
      headers: { 'X-User-Email': getPlexisUserEmail() },
    });
    if (!r.ok) throw new Error(`getModule ${moduleId} failed: ${r.status}`);
    return r.json();
  },

  /**
   * Stream an LLM explanation for a module.
   * Returns raw fetch Response for SSE streaming.
   * SSE events: chunk | done | error
   */
  async explainModuleStream(datasetId, moduleId, options = {}) {
    const { userQuery = null, verbosity = "standard", audience = "technical", previouslyStated = null } = options;
    return fetch(`${BASE_URL}/api/datasets/${datasetId}/modules/${moduleId}/explain`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_query: userQuery,
        verbosity,
        audience,
        previously_stated: previouslyStated,
      }),
    });
  },

  // ── Dataset API ───────────────────────────────────────────────────────────

  async getDataset(datasetId) {
    const r = await fetch(`${BASE_URL}/api/datasets/${datasetId}`, {
      headers: { 'X-User-Email': getPlexisUserEmail() },
    });
    if (!r.ok) throw new Error(`getDataset failed: ${r.status}`);
    return r.json();
  },

  async listDatasets() {
    const r = await fetch(`${BASE_URL}/api/datasets`, {
      headers: { 'X-User-Email': getPlexisUserEmail() },
    });
    if (!r.ok) throw new Error(`listDatasets failed: ${r.status}`);
    return r.json();
  },

  // ── Workspace Data API ────────────────────────────────────────────────────

  /**
   * Fetch a windowed slice of dataset rows for virtual scrolling.
   * @param {string} datasetId
   * @param {number} offset     - Start row (default 0)
   * @param {number} limit      - Rows per page (default 100, max 500)
   * @param {string} [sortCol]  - Column to sort by
   * @param {string} [sortDir]  - 'asc' | 'desc'
   * @param {string} [search]   - Global search string
   * @param {string} [filterCol] - Column to filter
   * @param {string} [filterVal] - Filter value
   * @returns {Promise<{columns, rows, total_rows, offset, limit, dataset_id, filename}>}
   */
  async getDatasetWindow(datasetId, offset = 0, limit = 100, sortCol, sortDir, search, filterCol, filterVal) {
    const params = new URLSearchParams();
    params.set('offset', offset);
    params.set('limit', limit);
    if (sortCol)   params.set('sort_col', sortCol);
    if (sortDir)   params.set('sort_dir', sortDir);
    if (search)    params.set('search', search);
    if (filterCol) params.set('filter_col', filterCol);
    if (filterVal) params.set('filter_val', filterVal);

    const r = await fetch(`${BASE_URL}/api/datasets/${datasetId}/data?${params}`);
    if (!r.ok) throw new Error(`getDatasetWindow failed: ${r.status}`);
    return r.json();
  },

  // ── Spreadsheet AI API ────────────────────────────────────────────────────

  /**
   * Execute a deterministic spreadsheet operation on the backend.
   * Backend performs the dataframe computation; frontend applies the result visually.
   *
   * @param {string} datasetId
   * @param {Object} operation  - { operation, column, n, order, columns, ... }
   * @returns {Promise<{ operation, row_indices, result_count, summary, column_stats, success }>}
   */
  async operateSpreadsheet(datasetId, operation) {
    const r = await fetch(`${BASE_URL}/api/spreadsheet/operate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dataset_id: datasetId, ...operation }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.error || `operateSpreadsheet failed: ${r.status}`);
    }
    return r.json();
  },

  /**
   * Interpret a natural language query about the spreadsheet.
   * Returns a structured operation for the deterministic engine to execute.
   *
   * @param {Object} payload
   * @param {string} payload.dataset_id
   * @param {string} payload.session_id
   * @param {string} payload.query
   * @param {Object} payload.spreadsheet_context
   * @returns {Promise<{ operation: { type, ...params }, explanation, confidence }>}
   */
  async interpretSpreadsheetQuery(payload) {
    const r = await fetch(`${BASE_URL}/api/spreadsheet/interpret`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.error || `interpretSpreadsheetQuery failed: ${r.status}`);
    }
    return r.json();
  },

  // ── Chat API (Phase 12) ───────────────────────────────────────────────────

  /**
   * Create a new chat for the current user.
   * @param {string} [title] - Chat display title
   * @returns {Promise<{chat_id, slug, title}>}
   */
  async createChat(title = 'New Chat') {
    const r = await fetch(`${BASE_URL}/api/chats`, {
      method: 'POST',
      headers: defaultHeaders(),
      body: JSON.stringify({ title }),
    });
    if (!r.ok) throw new Error(`createChat failed: ${r.status}`);
    return r.json();
  },

  /**
   * List all non-archived chats for the current user.
   * @returns {Promise<{chats: Array}>}
   */
  async listChats() {
    const r = await fetch(`${BASE_URL}/api/chats`, {
      headers: { 'X-User-Email': getPlexisUserEmail() },
    });
    if (!r.ok) throw new Error(`listChats failed: ${r.status}`);
    return r.json();
  },

  /**
   * Load a chat by slug (ownership verified).
   * Returns full chat state: chat, messages, analysis_sessions, current_dataset_id.
   * @param {string} slug - Chat URL slug
   * @returns {Promise<{chat, messages, analysis_sessions, current_dataset_id}>}
   */
  async loadChat(slug) {
    const r = await fetch(`${BASE_URL}/api/chats/${slug}`, {
      headers: { 'X-User-Email': getPlexisUserEmail() },
    });
    if (r.status === 404) return null;
    if (!r.ok) throw new Error(`loadChat failed: ${r.status}`);
    return r.json();
  },

  /**
   * Delete a chat (hard delete, cascades to all messages/sessions).
   * @param {string} chatId - Chat UUID
   */
  async deleteChat(chatId) {
    const r = await fetch(`${BASE_URL}/api/chats/${chatId}`, {
      method: 'DELETE',
      headers: { 'X-User-Email': getPlexisUserEmail() },
    });
    if (!r.ok) throw new Error(`deleteChat failed: ${r.status}`);
    return r.json();
  },

  /**
   * Update the currently active dataset for a chat.
   * @param {string} chatId - Chat UUID
   * @param {string} datasetId - Dataset UUID
   */
  async updateChatDataset(chatId, datasetId) {
    const r = await fetch(`${BASE_URL}/api/chats/${chatId}/dataset`, {
      method: 'PATCH',
      headers: defaultHeaders(),
      body: JSON.stringify({ dataset_id: datasetId }),
    });
    if (!r.ok) throw new Error(`updateChatDataset failed: ${r.status}`);
    return r.json();
  },

  // ── Analysis API ─────────────────────────────────────────────────────────

  /**
   * Get locator data for an analytical result.
   * Returns rows with source_row_number for Locate in spreadsheet.
   * @param {string} analysisId
   * @returns {Promise<{rows, row_count, navigate_direct, ...}>}
   */
  async locateAnalysis(analysisId) {
    const r = await fetch(`${BASE_URL}/api/analysis/${analysisId}/locate`, {
      headers: { 'X-User-Email': getPlexisUserEmail() },
    });
    if (!r.ok) throw new Error(`locateAnalysis failed: ${r.status}`);
    return r.json();
  },

  /**
   * Get an LLM explanation for a verified analytical result.
   * @param {string} analysisId
   * @returns {Promise<{explanation, verified_value, column, operation, verified}>}
   */
  async explainAnalysis(analysisId) {
    const r = await fetch(`${BASE_URL}/api/analysis/${analysisId}/explain`, {
      method: 'POST',
      headers: defaultHeaders(),
      body: JSON.stringify({}),
    });
    if (!r.ok) throw new Error(`explainAnalysis failed: ${r.status}`);
    return r.json();
  },

  /**
   * Log a user's row selection from a multi-row locate result.
   * @param {string} analysisId
   * @param {number} selectedSourceRow
   */
  async logLocateSelection(analysisId, selectedSourceRow) {
    const r = await fetch(`${BASE_URL}/api/analysis/${analysisId}/locate_selection`, {
      method: 'POST',
      headers: defaultHeaders(),
      body: JSON.stringify({ selected_source_row: selectedSourceRow }),
    });
    if (!r.ok) throw new Error(`logLocateSelection failed: ${r.status}`);
    return r.json();
  },

  /**
   * Re-run an analytical query and get a fresh result.
   * @param {string} analysisId
   * @returns {Promise<{analysis_id, value, verified, ...}>}
   */
  async retryAnalysis(analysisId) {
    const r = await fetch(`${BASE_URL}/api/analysis/${analysisId}/retry`, {
      method: 'POST',
      headers: defaultHeaders(),
      body: JSON.stringify({}),
    });
    if (!r.ok) throw new Error(`retryAnalysis failed: ${r.status}`);
    return r.json();
  },

  // ── Autonomous Investigation API ──────────────────────────────────────────

  /** Start investigation */
  startInvestigation: async (datasetId) => {
    const response = await fetch(`${BASE_URL}/api/datasets/${datasetId}/investigate`, {
      method: 'POST',
      headers: defaultHeaders(),
    });
    if (!response.ok && response.status !== 409) {
      throw new Error(`startInvestigation failed: ${response.status}`);
    }
    return response.json();
  },

  /** Get completed investigation */
  getInvestigation: async (datasetId) => {
    const response = await fetch(`${BASE_URL}/api/datasets/${datasetId}/investigation`, {
      headers: { 'X-User-Email': getPlexisUserEmail() }
    });
    if (!response.ok && response.status !== 404 && response.status !== 202) {
        throw new Error(`getInvestigation failed: ${response.status}`);
    }
    return response.json();
  },

  /** SSE stream for investigation (returns EventSource URL) */
  getInvestigationStreamUrl: (datasetId) => {
    return `${BASE_URL}/api/datasets/${datasetId}/investigation/stream`;
  },
};