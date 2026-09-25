import React from 'react';
import { motion } from 'framer-motion';

export default function HeroIllustration() {
  return (
    <div className="hero-illustration-container" style={{ width: '100%', height: '500px', position: 'relative', background: '#0a0c14', overflow: 'hidden' }}>
      
      {/* Abstract Connections */}
      <svg width="100%" height="100%" style={{ position: 'absolute', inset: 0, opacity: 0.3 }}>
        <defs>
          <linearGradient id="lineGrad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#6366f1" />
            <stop offset="100%" stopColor="#a855f7" />
          </linearGradient>
        </defs>
        <path d="M 100 400 Q 300 200 500 300 T 900 100" fill="none" stroke="url(#lineGrad)" strokeWidth="2" strokeDasharray="5,5" />
        <path d="M 200 100 Q 400 300 700 150 T 1100 400" fill="none" stroke="url(#lineGrad)" strokeWidth="1.5" strokeDasharray="3,6" opacity="0.5" />
      </svg>

      {/* Main Central Processing Node */}
      <motion.div
        animate={{ y: [0, -10, 0] }}
        transition={{ repeat: Infinity, duration: 4, ease: "easeInOut" }}
        style={{
          position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)',
          width: '120px', height: '120px', background: 'rgba(99, 102, 241, 0.1)',
          border: '1px solid rgba(99, 102, 241, 0.4)', borderRadius: '24px',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          boxShadow: '0 0 40px rgba(99, 102, 241, 0.2)'
        }}
      >
        <div style={{
          width: '60px', height: '60px', background: 'linear-gradient(135deg, #6366f1, #a855f7)',
          borderRadius: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center',
          boxShadow: '0 10px 20px rgba(0,0,0,0.5)'
        }}>
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2">
            <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
          </svg>
        </div>
      </motion.div>

      {/* Floating Data Nodes */}
      <motion.div
        animate={{ y: [0, 15, 0], opacity: [0.5, 1, 0.5] }}
        transition={{ repeat: Infinity, duration: 5, ease: "easeInOut" }}
        style={{
          position: 'absolute', top: '20%', left: '15%', padding: '12px 16px',
          background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.1)',
          borderRadius: '12px', display: 'flex', alignItems: 'center', gap: '8px'
        }}
      >
        <div style={{ width: '12px', height: '12px', borderRadius: '50%', background: '#34d399' }}></div>
        <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>Ingesting CSV...</span>
      </motion.div>

      <motion.div
        animate={{ y: [0, -15, 0], opacity: [0.5, 1, 0.5] }}
        transition={{ repeat: Infinity, duration: 6, ease: "easeInOut", delay: 1 }}
        style={{
          position: 'absolute', bottom: '25%', right: '15%', padding: '16px',
          background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.1)',
          borderRadius: '12px', display: 'flex', flexDirection: 'column', gap: '6px'
        }}
      >
        <span style={{ fontSize: '0.75rem', color: '#a855f7', fontWeight: 600 }}>AI Insight</span>
        <span style={{ fontSize: '0.8rem', color: '#e2e8f0' }}>Correlation detected in Q3 sales</span>
        <div style={{ display: 'flex', gap: '4px', marginTop: '4px' }}>
          {[40, 70, 45, 90, 65].map((h, i) => (
            <div key={i} style={{ width: '4px', height: `${h}px`, background: '#a855f7', borderRadius: '2px' }}></div>
          ))}
        </div>
      </motion.div>

      <motion.div
        animate={{ scale: [0.95, 1.05, 0.95] }}
        transition={{ repeat: Infinity, duration: 3, ease: "easeInOut" }}
        style={{
          position: 'absolute', top: '30%', right: '25%', padding: '12px',
          background: 'rgba(99, 102, 241, 0.1)', border: '1px solid rgba(99, 102, 241, 0.3)',
          borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center'
        }}
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#6366f1" strokeWidth="2">
          <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8" />
          <path d="M21 3v5h-5" />
        </svg>
      </motion.div>

      <motion.div
        animate={{ scale: [0.95, 1.05, 0.95] }}
        transition={{ repeat: Infinity, duration: 4, ease: "easeInOut", delay: 1.5 }}
        style={{
          position: 'absolute', bottom: '20%', left: '25%', padding: '12px',
          background: 'rgba(236, 72, 153, 0.1)', border: '1px solid rgba(236, 72, 153, 0.3)',
          borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center'
        }}
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#ec4899" strokeWidth="2">
          <circle cx="12" cy="12" r="10" />
          <path d="M12 16v-4" />
          <path d="M12 8h.01" />
        </svg>
      </motion.div>
    </div>
  );
}
