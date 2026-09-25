/**
 * DatasetWorkspace — thin panel wrapper for the Spreadsheet component.
 *
 * This file is the public API surface used by Dashboard.jsx.
 * It is responsible only for:
 *   1. Reading isOpen from WorkspaceContext
 *   2. Animating the panel in/out (framer-motion)
 *   3. Rendering the Spreadsheet component
 *
 * ALL spreadsheet logic, virtualization, data fetching, selection, and
 * keyboard handling live in Spreadsheet.jsx and its sub-components.
 *
 * Preserves the existing interface:
 *   import DatasetWorkspace from '.../DatasetWorkspace';
 *   <DatasetWorkspace />
 */
import React from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useWorkspace } from '../../context/WorkspaceContext.jsx';
import Spreadsheet from './Spreadsheet.jsx';

export default function DatasetWorkspace({ viewMode, onViewModeChange }) {
  const { isOpen, closeWorkspace } = useWorkspace();

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          key="workspace-panel"
          style={{
            width: '100%',
            height: '100%',
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
          }}
          initial={{ opacity: 0, x: 24 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: 24 }}
          transition={{ duration: 0.22, ease: 'easeOut' }}
        >
          <Spreadsheet
            onClose={closeWorkspace}
            viewMode={viewMode}
            onViewModeChange={onViewModeChange}
          />
        </motion.div>
      )}
    </AnimatePresence>
  );
}
