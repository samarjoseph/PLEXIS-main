import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import './EarlyAccessPage.css';
import { ArrowRight, Database, TrendingUp, Search, BarChart2, CheckCircle2, Shield, Eye, Settings, MessageSquare, Zap } from 'lucide-react';
import PlexisLogo from '../brand/PlexisLogo';


const fadeUp = {
  hidden: { opacity: 0, y: 30 },
  visible: (i = 0) => ({
    opacity: 1,
    y: 0,
    transition: { duration: 0.8, delay: i * 0.15, ease: [0.16, 1, 0.3, 1] },
  }),
};

export default function EarlyAccessPage() {
  const [feedbackOptions, setFeedbackOptions] = useState([]);
  const [feedbackText, setFeedbackText] = useState('');
  const [email, setEmail] = useState('');
  const [emailError, setEmailError] = useState('');
  const [role, setRole] = useState('');
  const [isSubmitted, setIsSubmitted] = useState(false);
  const [showNotification, setShowNotification] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const toggleOption = (opt) => {
    setFeedbackOptions((prev) =>
      prev.includes(opt) ? prev.filter((o) => o !== opt) : [...prev, opt]
    );
  };

  const validateEmail = (email) => {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
  };

  const handleSignup = async (e) => {
    e.preventDefault();
    if (!email) {
      setEmailError('Please enter your email address.');
      return;
    }
    if (!validateEmail(email)) {
      setEmailError('Please enter a valid email address.');
      return;
    }
    setEmailError('');
    setIsSubmitting(true);
    
    try {
      const response = await fetch(`${import.meta.env.VITE_API_BASE_URL || ''}/api/early-access`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email,
          role,
          idea: feedbackText,
          selected_features: feedbackOptions
        })
      });
      
      const data = await response.json();
      
      if (!response.ok) {
        throw new Error(data.error || 'Submission failed');
      }
      
      setIsSubmitted(true);
      setShowNotification(true);
      setTimeout(() => setShowNotification(false), 5000);
      
    } catch (err) {
      setEmailError('We couldn\'t submit your request. Please try again.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const scrollToSection = (id) => {
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: 'smooth' });
  };

  const featureOptions = [
    'Clean messy datasets',
    'Find patterns',
    'Detect outliers',
    'Generate visualizations',
    'Explain statistics',
    'Ask questions about data',
    'Review data changes',
    'Generate reports',
    'Something else'
  ];

  const roleOptions = [
    'Student',
    'Developer',
    'Data Analyst',
    'Founder',
    'Researcher',
    'Other'
  ];

  return (
    <div className="ea-page">
      <AnimatePresence>
        {showNotification && (
          <motion.div
            className="ea-notification"
            initial={{ opacity: 0, y: -50, x: '-50%' }}
            animate={{ opacity: 1, y: 0, x: '-50%' }}
            exit={{ opacity: 0, y: -50, x: '-50%' }}
            role="status"
            aria-live="polite"
          >
            <div className="ea-notification-content">
              <CheckCircle2 className="ea-notification-icon" />
              <div>
                <strong>✓ You're on the Plexis early-access list!</strong>
                <p>We'll let you know when early access is available.</p>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <nav className="ea-nav">
        <motion.div 
          className="ea-logo"
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.5 }}
        >
          <PlexisLogo width={28} height={28} />
          Plexis
        </motion.div>
      </nav>

      <main>
        {/* 1. Hero Section */}
        <section className="ea-hero">
          <motion.div 
            className="ea-hero-badge"
            variants={fadeUp}
            initial="hidden"
            animate="visible"
            custom={0}
          >
            Plexis Early Access
          </motion.div>
          <motion.h1 
            className="ea-headline"
            variants={fadeUp}
            initial="hidden"
            animate="visible"
            custom={1}
          >
            Your data. The evidence behind every answer.
          </motion.h1>
          <motion.p 
            className="ea-subheadline"
            variants={fadeUp}
            initial="hidden"
            animate="visible"
            custom={2}
          >
            Plexis turns messy datasets into analysis you can actually verify. Explore the numbers, understand where insights come from, review changes before they're applied, and stay in control of your data from start to finish.
          </motion.p>
          <motion.div 
            className="ea-hero-actions"
            variants={fadeUp}
            initial="hidden"
            animate="visible"
            custom={3}
          >
            <motion.button 
              className="ea-btn ea-btn-primary" 
              onClick={() => scrollToSection('signup')}
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
            >
              Get Early Access <ArrowRight size={18} />
            </motion.button>
            <motion.button 
              className="ea-btn ea-btn-secondary" 
              onClick={() => scrollToSection('feedback')}
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
            >
              Tell us what you need
            </motion.button>
          </motion.div>
        </section>

        {/* 2. Hero Product Visual */}
        <motion.section 
          className="ea-visual-section"
          initial={{ opacity: 0, y: 40 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-50px" }}
          transition={{ duration: 0.8 }}
        >
          <div className="ea-mockup-wrapper">
            <div className="ea-mockup-chat">
              <div className="ea-mockup-msg user">
                Which category had the highest average revenue?
              </div>
              <div className="ea-mockup-msg ai">
                <strong>Category A</strong> had the highest average revenue at $1,245.50.
                
                <div className="ea-mockup-evidence">
                  <div className="ea-evidence-header">
                    <Shield size={14} /> Evidence
                  </div>
                  <div className="ea-evidence-grid">
                    <div><span className="label">Rows analyzed:</span> 12,450</div>
                    <div><span className="label">Column:</span> revenue</div>
                    <div><span className="label">Calculation:</span> mean() group by category</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </motion.section>

        {/* 3. The Differentiator */}
        <motion.section 
          className="ea-statement-section"
          initial={{ opacity: 0, scale: 0.95 }}
          whileInView={{ opacity: 1, scale: 1 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.7 }}
        >
          <h2>AI shouldn't get to make up what your data says.</h2>
          <p>
            Plexis separates reasoning from computation. Your data is analyzed using deterministic tools, while AI helps you understand the results, navigate the analysis, and ask better questions.
          </p>
        </motion.section>

        {/* 4. Evidence Layer */}
        <motion.section 
          className="ea-feature-section"
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.7 }}
        >
          <div className="ea-feature-content">
            <div className="ea-tag"><Shield size={16} /> Evidence Layer</div>
            <h2>Don't just get an answer. See why it's true.</h2>
            <p>
              Plexis connects important insights back to the evidence behind them — calculations, fields, records, and statistical results — so you can inspect the reasoning instead of blindly trusting a generated response.
            </p>
          </div>
          <div className="ea-feature-visual">
            <div className="ea-mockup-msg ai">
              Several unusually high values were detected in the revenue column.
              <div className="ea-mockup-evidence interactive">
                <div className="ea-evidence-header">
                  <Search size={14} /> Evidence
                </div>
                <div className="ea-evidence-grid">
                  <div><span className="label">Column:</span> revenue</div>
                  <div><span className="label">Detection method:</span> statistical outlier analysis (Z-score &gt; 3)</div>
                  <div><span className="label">Outliers detected:</span> 17 out of 1,000 rows</div>
                </div>
                <button className="ea-micro-btn">View Evidence Details</button>
              </div>
            </div>
          </div>
        </motion.section>

        {/* 5. Review Changes */}
        <motion.section 
          className="ea-feature-section reverse"
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.7 }}
        >
          <div className="ea-feature-content">
            <div className="ea-tag"><Eye size={16} /> Data Integrity</div>
            <h2>Review changes before they change your data.</h2>
            <p>
              Data cleaning shouldn't be a leap of faith. Plexis lets you inspect proposed transformations before applying them.
            </p>
          </div>
          <div className="ea-feature-visual">
            <div className="ea-review-card">
              <div className="ea-review-header">Proposed Transformation</div>
              <div className="ea-review-body">
                <div className="ea-diff-row">
                  <div className="ea-diff-before">Age: "twenty three"</div>
                  <div className="ea-diff-arrow">→</div>
                  <div className="ea-diff-after">23</div>
                </div>
              </div>
              <div className="ea-review-actions">
                <button className="ea-micro-btn danger">Reject</button>
                <button className="ea-micro-btn success">Apply Change</button>
              </div>
            </div>
          </div>
        </motion.section>

        {/* 6. Deterministic Analysis */}
        <motion.section 
          className="ea-feature-section centered"
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.7 }}
        >
          <div className="ea-tag"><Settings size={16} /> Deterministic</div>
          <h2>Let the data do the math.</h2>
          <p>
            Statistics should come from the dataset itself — not from an LLM guessing what the answer might be.
          </p>
          
          <div className="ea-math-visual">
            <div className="ea-math-tags">
              <span>Mean</span><span>Median</span><span>Missing values</span>
              <span>Distributions</span><span>Outliers</span><span>Correlations</span>
            </div>
            <div className="ea-math-flow">
              <div className="ea-flow-node">Dataset</div>
              <ArrowRight className="ea-flow-arr" size={16} />
              <div className="ea-flow-node highlight">Computation</div>
              <ArrowRight className="ea-flow-arr" size={16} />
              <div className="ea-flow-node">Result</div>
              <ArrowRight className="ea-flow-arr" size={16} />
              <div className="ea-flow-node">Explanation</div>
            </div>
            <p className="ea-math-quote">"AI explains the result. The data produces it."</p>
          </div>
        </motion.section>

        {/* 7. Ask Your Data */}
        <motion.section 
          className="ea-feature-section"
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.7 }}
        >
          <div className="ea-feature-content">
            <div className="ea-tag"><MessageSquare size={16} /> Conversational Interface</div>
            <h2>Ask questions naturally. Go deeper when you need to.</h2>
            <p>
              Ask Plexis questions in plain English, then move from the explanation to the underlying analysis and evidence. Conversation is the interface — not the source of truth.
            </p>
          </div>
          <div className="ea-feature-visual">
             <div className="ea-mockup-chat small">
              <div className="ea-mockup-msg user">
                Which product category is performing best?
              </div>
              <div className="ea-mockup-msg ai">
                Category A has the highest average revenue.
                <button className="ea-micro-btn outline" style={{marginTop: '0.75rem'}}>View analysis →</button>
              </div>
            </div>
          </div>
        </motion.section>
        
        {/* 8. Visualization */}
        <motion.section 
          className="ea-feature-section reverse"
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.7 }}
        >
          <div className="ea-feature-content">
            <div className="ea-tag"><BarChart2 size={16} /> Reporting</div>
            <h2>From numbers to something you can see.</h2>
            <p>
              Turn analysis into clear visualizations and reports without manually rebuilding every result.
            </p>
          </div>
          <div className="ea-feature-visual">
            <div className="ea-chart-mockup">
              <div className="ea-chart-bar" style={{height: '60%'}}></div>
              <div className="ea-chart-bar" style={{height: '100%', background: 'var(--accent)'}}></div>
              <div className="ea-chart-bar" style={{height: '40%'}}></div>
              <div className="ea-chart-bar" style={{height: '80%'}}></div>
            </div>
          </div>
        </motion.section>

        {/* 9. Plexis Workflow */}
        <motion.section 
          className="ea-workflow-section"
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.7 }}
        >
          <h2>One workspace. From raw data to verified insight.</h2>
          <div className="ea-workflow-grid">
            <div className="ea-workflow-step">
              <span className="num">01</span>
              <h4>Upload</h4>
              <p>Bring in your dataset.</p>
            </div>
            <div className="ea-workflow-step">
              <span className="num">02</span>
              <h4>Understand</h4>
              <p>Plexis profiles structure, fields, and data quality.</p>
            </div>
            <div className="ea-workflow-step">
              <span className="num">03</span>
              <h4>Analyze</h4>
              <p>Deterministic analytics calculate the actual results.</p>
            </div>
            <div className="ea-workflow-step">
              <span className="num">04</span>
              <h4>Explain</h4>
              <p>AI translates the analysis into understandable language.</p>
            </div>
            <div className="ea-workflow-step">
              <span className="num">05</span>
              <h4>Verify</h4>
              <p>Inspect the evidence behind important conclusions.</p>
            </div>
            <div className="ea-workflow-step">
              <span className="num">06</span>
              <h4>Review</h4>
              <p>Approve or reject proposed data changes.</p>
            </div>
          </div>
        </motion.section>

        {/* 10, 11, 12. Feedback / Signup Flow */}
        <motion.section 
          className="ea-feedback" id="feedback"
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.7 }}
        >
          <div className="ea-cta-header">
            <h2>Help shape Plexis before everyone else gets access.</h2>
            <p>We're building Plexis with early users. Tell us what you want it to solve, what you struggle with when working with data, and what would make you trust an AI data-analysis tool.</p>
          </div>

          <div className="ea-onboarding-card">
            <div className="ea-onboarding-step">
              <div className="ea-step-header">
                <h2>What would make Plexis indispensable to you?</h2>
                <AnimatePresence>
                  {feedbackOptions.length > 0 && (
                    <motion.span 
                      className="ea-counter-badge"
                      initial={{ opacity: 0, scale: 0.8 }}
                      animate={{ opacity: 1, scale: 1 }}
                      exit={{ opacity: 0, scale: 0.8 }}
                    >
                      {feedbackOptions.length} selected
                    </motion.span>
                  )}
                </AnimatePresence>
              </div>
              <div className="ea-options">
                {featureOptions.map((opt) => (
                  <motion.button
                    key={opt}
                    className={`ea-option ${feedbackOptions.includes(opt) ? 'selected' : ''}`}
                    onClick={() => toggleOption(opt)}
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.95 }}
                  >
                    {opt}
                  </motion.button>
                ))}
              </div>
            </div>

            <AnimatePresence>
              {feedbackOptions.length > 0 && (
                <motion.div 
                  className="ea-onboarding-step"
                  initial={{ opacity: 0, height: 0, marginTop: 0 }}
                  animate={{ opacity: 1, height: 'auto', marginTop: '2rem' }}
                  exit={{ opacity: 0, height: 0, marginTop: 0 }}
                  transition={{ duration: 0.4 }}
                >
                  <div className="ea-step-header">
                    <h2>Tell us what you're trying to solve.</h2>
                  </div>
                  <div className="ea-textarea-container">
                    <textarea
                      className="ea-textarea"
                      placeholder="What do you wish you could do with your data in a few clicks?"
                      value={feedbackText}
                      maxLength={1000}
                      onChange={(e) => setFeedbackText(e.target.value)}
                    />
                    <div className="ea-char-counter">
                      {feedbackText.length}/1000
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            <AnimatePresence>
              {(feedbackOptions.length > 0 && feedbackText.length > 0) && (
                <motion.div 
                  className="ea-onboarding-step"
                  initial={{ opacity: 0, height: 0, marginTop: 0 }}
                  animate={{ opacity: 1, height: 'auto', marginTop: '2rem' }}
                  exit={{ opacity: 0, height: 0, marginTop: 0 }}
                  transition={{ duration: 0.4 }}
                >
                  <div className="ea-step-header">
                    <h2>What best describes you?</h2>
                  </div>
                  <div className="ea-options">
                    {roleOptions.map((r) => (
                      <motion.button
                        key={r}
                        className={`ea-option ${role === r ? 'selected' : ''}`}
                        onClick={() => { setRole(r); setTimeout(() => scrollToSection('signup'), 400); }}
                        whileHover={{ scale: 1.05 }}
                        whileTap={{ scale: 0.95 }}
                      >
                        {r}
                      </motion.button>
                    ))}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </motion.section>

        {/* Signup / Offer Screen */}
        <motion.section 
          className="ea-signup" id="signup"
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.7 }}
        >
          <div className="ea-signup-container">
            <AnimatePresence mode="wait">
              {isSubmitted ? (
                <motion.div 
                  key="success"
                  className="ea-offer-screen"
                  initial={{ opacity: 0, scale: 0.95 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ duration: 0.5 }}
                >
                  <h2>You're in. 🚀</h2>
                  <p className="ea-offer-success-msg">You're now on the Plexis early-access list.</p>
                  
                  <div className="ea-offer-card">
                    <h3>Your first month is on us.</h3>
                    <p className="ea-offer-text">
                      When your beta access is activated, early-access users will get the best available Plexis features free for their first month.
                    </p>
                  </div>
                  <div className="ea-hero-actions" style={{ marginTop: '2rem' }}>
                    <button className="ea-btn ea-btn-primary full-width" disabled>
                      Stay tuned for beta access
                    </button>
                  </div>
                </motion.div>
              ) : (
                <motion.div key="signup-form" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                  <form className="ea-form" onSubmit={handleSignup} noValidate>
                    <div className="ea-form-group">
                      <label>Email *</label>
                      <input
                        type="email"
                        required
                        placeholder="you@company.com"
                        value={email}
                        onChange={(e) => {
                          setEmail(e.target.value);
                          if (emailError) setEmailError('');
                        }}
                        className={emailError ? 'has-error' : ''}
                      />
                      <AnimatePresence>
                        {emailError && (
                          <motion.div 
                            className="ea-error-msg"
                            initial={{ opacity: 0, height: 0 }}
                            animate={{ opacity: 1, height: 'auto' }}
                            exit={{ opacity: 0, height: 0 }}
                          >
                            {emailError}
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </div>
                    <motion.button 
                      type="submit" 
                      className="ea-btn ea-btn-primary full-width"
                      whileHover={{ scale: 1.02 }}
                      whileTap={{ scale: 0.98 }}
                      disabled={isSubmitting}
                    >
                      {isSubmitting ? 'Joining...' : 'Get Early Access →'}
                    </motion.button>
                  </form>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </motion.section>

      </main>

      {/* Footer */}
      <footer className="ea-footer">
        <div className="ea-logo"><PlexisLogo width={16} height={16} style={{marginRight: '8px'}} /> Plexis</div>
        <p>Your data. The evidence behind every answer.</p>
      </footer>
    </div>
  );
}
