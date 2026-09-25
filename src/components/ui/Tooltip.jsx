import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

export default function Tooltip({ children, label, shortcut, side = 'right', disabled = false, fullWidth = false }) {
  const [show, setShow] = useState(false);

  let pos = {};
  if (side === 'right') {
    pos = { left: '100%', top: '50%', transform: 'translateY(-50%)', marginLeft: 10 };
  } else if (side === 'top') {
    pos = { bottom: '100%', left: '50%', transform: 'translateX(-50%)', marginBottom: 8 };
  } else if (side === 'bottom') {
    pos = { top: '100%', left: '50%', transform: 'translateX(-50%)', marginTop: 8 };
  } else if (side === 'left') {
    pos = { right: '100%', top: '50%', transform: 'translateY(-50%)', marginRight: 10 };
  }

  return (
    <div
      className="v2-tip-wrap"
      onMouseEnter={() => !disabled && setShow(true)}
      onMouseLeave={() => setShow(false)}
      style={{ position: 'relative', display: fullWidth ? 'flex' : 'inline-flex', width: fullWidth ? '100%' : 'auto' }}
    >
      {children}
      <AnimatePresence>
        {show && !disabled && window.innerWidth >= 1024 && (
          <motion.div
            className="v2-tooltip"
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 4 }}
            transition={{ duration: 0.15, ease: 'easeOut' }}
            style={{ ...pos, position: 'absolute', zIndex: 9999, whiteSpace: 'nowrap' }}
          >
            <span className="v2-tooltip-label">{label}</span>
            {shortcut && <span className="v2-tooltip-shortcut">{shortcut}</span>}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
