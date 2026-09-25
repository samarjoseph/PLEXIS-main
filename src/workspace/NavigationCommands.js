/**
 * NavigationCommands — factory functions for workspace navigation commands.
 *
 * Commands are plain objects consumed by WorkspaceNavigator.execute().
 * Using factory functions instead of classes keeps them serializable.
 *
 * Usage:
 *   WorkspaceNavigator.execute(NavCommand.TO_EVIDENCE({ evidenceId: '...' }))
 *   WorkspaceNavigator.execute(NavCommand.TO_ROW({ rowIndex: 42 }))
 */

export const NavCommand = Object.freeze({
  /**
   * Navigate to rows indicated by an EvidenceReference.
   * @param {{ evidenceId: string }} payload
   */
  TO_EVIDENCE: (payload) => ({
    type: 'TO_EVIDENCE',
    ...payload,
  }),

  /**
   * Navigate to a specific absolute row index.
   * @param {{ rowIndex: number }} payload
   */
  TO_ROW: (payload) => ({
    type: 'TO_ROW',
    ...payload,
  }),

  /**
   * Scroll to the very top of the dataset.
   */
  TO_TOP: () => ({
    type: 'TO_TOP',
  }),

  /**
   * Navigate to a bookmarked row (future: stored user bookmarks).
   * @param {{ bookmarkId: string }} payload
   */
  TO_BOOKMARK: (payload) => ({
    type: 'TO_BOOKMARK',
    ...payload,
  }),

  /**
   * Navigate to the Nth search result.
   * @param {{ query: string, resultIndex?: number }} payload
   */
  TO_SEARCH_RESULT: (payload) => ({
    type: 'TO_SEARCH_RESULT',
    resultIndex: 0,
    ...payload,
  }),

  /**
   * Navigate to a proportional position (0.0 = top, 1.0 = bottom).
   * Useful for "go to 25% of the dataset" type navigation.
   * @param {{ proportion: number }} payload
   */
  TO_PROPORTION: (payload) => ({
    type: 'TO_PROPORTION',
    ...payload,
  }),
});
