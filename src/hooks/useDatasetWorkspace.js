/**
 * useDatasetWorkspace — thin hook wrapper around useWorkspace.
 * Exposes a simplified public API for components that only need to toggle the workspace.
 *
 * Usage:
 *   const { isOpen, toggle, openForDataset } = useDatasetWorkspace();
 */
import { useWorkspace } from '../context/WorkspaceContext.jsx';

export function useDatasetWorkspace() {
  const {
    isOpen,
    datasetId,
    sessionId,
    totalRows,
    columns,
    isLoading,
    openWorkspace,
    closeWorkspace,
    toggleWorkspace,
    buildWorkspaceSummaryPayload,
  } = useWorkspace();

  return {
    /** Whether the workspace panel is currently open */
    isOpen,
    datasetId,
    sessionId,
    totalRows,
    columns,
    isLoading,
    /** Toggle open/closed */
    toggle: () => toggleWorkspace(datasetId, sessionId),
    /** Open for a specific dataset */
    openForDataset: (did, sid) => openWorkspace(did, sid),
    /** Close the workspace */
    close: closeWorkspace,
    /** Get workspace state snapshot for sending to /api/ask */
    getSnapshot: buildWorkspaceSummaryPayload,
  };
}
