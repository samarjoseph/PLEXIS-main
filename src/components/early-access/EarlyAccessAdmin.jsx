import React, { useState, useEffect } from 'react';
import './EarlyAccessAdmin.css';
import { Database, Search, User, Filter } from 'lucide-react';
import PlexisLogo from '../brand/PlexisLogo';


export default function EarlyAccessAdmin() {
  const [adminKey, setAdminKey] = useState('');
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [submissions, setSubmissions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');

  const fetchSubmissions = async (key) => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${import.meta.env.VITE_API_BASE_URL || ''}/api/early-access/admin/submissions`, {
        headers: {
          'Authorization': `Bearer ${key}`
        }
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to fetch');
      
      setSubmissions(data.submissions || []);
      setIsAuthenticated(true);
      localStorage.setItem('plexis_ea_admin_key', key);
    } catch (err) {
      setError(err.message);
      setIsAuthenticated(false);
      localStorage.removeItem('plexis_ea_admin_key');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const savedKey = localStorage.getItem('plexis_ea_admin_key');
    if (savedKey) {
      setAdminKey(savedKey);
      fetchSubmissions(savedKey);
    }
  }, []);

  const handleLogin = (e) => {
    e.preventDefault();
    if (adminKey) fetchSubmissions(adminKey);
  };

  const updateStatus = async (id, newStatus) => {
    try {
      const res = await fetch(`${import.meta.env.VITE_API_BASE_URL || ''}/api/early-access/admin/submissions/${id}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${adminKey}`
        },
        body: JSON.stringify({ status: newStatus })
      });
      if (res.ok) {
        setSubmissions(prev => prev.map(sub => sub.id === id ? { ...sub, status: newStatus } : sub));
      }
    } catch (err) {
      console.error('Failed to update status:', err);
      alert('Failed to update status');
    }
  };

  if (!isAuthenticated) {
    return (
      <div className="ea-admin-login-page">
        <div className="ea-admin-login-card">
          <div className="ea-logo" style={{ marginBottom: '2rem', justifyContent: 'center' }}>
            <PlexisLogo width={32} height={32} /> Plexis Admin
          </div>
          <h2>Early Access Dashboard</h2>
          <p>Please enter the admin secret key.</p>
          <form onSubmit={handleLogin}>
            <input 
              type="password" 
              placeholder="ADMIN_SECRET_KEY" 
              value={adminKey}
              onChange={e => setAdminKey(e.target.value)}
              className="ea-admin-input"
            />
            {error && <div className="ea-error-msg">{error}</div>}
            <button type="submit" className="ea-btn ea-btn-primary full-width" style={{ marginTop: '1rem' }} disabled={loading}>
              {loading ? 'Authenticating...' : 'Login'}
            </button>
          </form>
        </div>
      </div>
    );
  }

  const filteredSubmissions = submissions.filter(sub => {
    const matchesSearch = sub.email.toLowerCase().includes(searchTerm.toLowerCase()) || 
                          (sub.idea && sub.idea.toLowerCase().includes(searchTerm.toLowerCase()));
    const matchesFilter = statusFilter === 'all' || sub.status === statusFilter;
    return matchesSearch && matchesFilter;
  });

  const stats = {
    total: submissions.length,
    new: submissions.filter(s => s.status === 'new').length,
    reviewed: submissions.filter(s => s.status === 'reviewed').length,
    contacted: submissions.filter(s => s.status === 'contacted').length,
  };

  return (
    <div className="ea-admin-page">
      <nav className="ea-admin-nav">
        <div className="ea-logo">
          <PlexisLogo width={24} height={24} /> Plexis Admin Dashboard
        </div>
        <button className="ea-btn ea-btn-secondary" onClick={() => { setIsAuthenticated(false); localStorage.removeItem('plexis_ea_admin_key'); }}>
          Logout
        </button>
      </nav>

      <main className="ea-admin-main">
        <div className="ea-admin-stats">
          <div className="ea-stat-card">
            <h4>Total Signups</h4>
            <h2>{stats.total}</h2>
          </div>
          <div className="ea-stat-card">
            <h4>New</h4>
            <h2>{stats.new}</h2>
          </div>
          <div className="ea-stat-card">
            <h4>Reviewed</h4>
            <h2>{stats.reviewed}</h2>
          </div>
          <div className="ea-stat-card">
            <h4>Contacted</h4>
            <h2>{stats.contacted}</h2>
          </div>
        </div>

        <div className="ea-admin-controls">
          <div className="ea-admin-search">
            <Search size={18} />
            <input 
              type="text" 
              placeholder="Search emails or ideas..." 
              value={searchTerm}
              onChange={e => setSearchTerm(e.target.value)}
            />
          </div>
          <div className="ea-admin-filter">
            <Filter size={18} />
            <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
              <option value="all">All Statuses</option>
              <option value="new">New</option>
              <option value="reviewed">Reviewed</option>
              <option value="contacted">Contacted</option>
            </select>
          </div>
        </div>

        <div className="ea-admin-table-container">
          <table className="ea-admin-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Email & Role</th>
                <th>Interested Features</th>
                <th>Feedback / Idea</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {filteredSubmissions.length === 0 ? (
                <tr><td colSpan="5" className="ea-admin-empty">No submissions found.</td></tr>
              ) : (
                filteredSubmissions.map(sub => (
                  <tr key={sub.id}>
                    <td className="ea-td-date">
                      {new Date(sub.created_at).toLocaleDateString()}
                    </td>
                    <td className="ea-td-user">
                      <div className="ea-user-email">{sub.email}</div>
                      {sub.role && <span className="ea-user-role">{sub.role}</span>}
                    </td>
                    <td className="ea-td-features">
                      <div className="ea-feature-tags">
                        {sub.selected_features && sub.selected_features.map(f => (
                          <span key={f} className="ea-feature-tag">{f}</span>
                        ))}
                      </div>
                    </td>
                    <td className="ea-td-idea">
                      <div className="ea-idea-text">{sub.idea || <em style={{color: '#64748b'}}>No feedback provided</em>}</div>
                    </td>
                    <td className="ea-td-actions">
                      <select 
                        className={`ea-status-select status-${sub.status}`}
                        value={sub.status}
                        onChange={(e) => updateStatus(sub.id, e.target.value)}
                      >
                        <option value="new">New</option>
                        <option value="reviewed">Reviewed</option>
                        <option value="contacted">Contacted</option>
                      </select>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </main>
    </div>
  );
}
