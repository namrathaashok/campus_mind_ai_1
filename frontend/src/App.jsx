/**
 * CampusMindAi — Campus Operations React Dashboard
 * Connects to the Flask backend API for all data; no hardcoded or mocked records.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  Bell,
  Building2,
  Check,
  ChevronDown,
  CircleAlert,
  Droplets,
  Grid2X2,
  Leaf,
  Loader2,
  Search,
  ShieldCheck,
  X,
  Zap,
} from 'lucide-react';

// ---------------------------------------------------------------------------
// Navigation items
// ---------------------------------------------------------------------------
const navigation = [
  { id: 'overview', label: 'Overview',       icon: Grid2X2   },
  { id: 'reports',  label: 'Issue reports',  icon: CircleAlert },
  { id: 'backend',  label: 'Service status', icon: Activity   },
];

// ---------------------------------------------------------------------------
// Static lookup maps
// ---------------------------------------------------------------------------
const CATEGORY_COLORS = {
  water:          'blue',
  electricity:    'amber',
  waste:          'green',
  greenery:       'green',
  infrastructure: 'indigo',
};

const VALID_CATEGORIES = ['water', 'electricity', 'waste', 'greenery', 'infrastructure'];
const VALID_PRIORITIES  = ['low', 'medium', 'high', 'critical'];

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------
function formatLabel(value = '') {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (l) => l.toUpperCase());
}

function formatDate(value) {
  if (!value) return 'Recently';
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? 'Recently'
    : new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric' }).format(date);
}

// ---------------------------------------------------------------------------
// Centralised API client — all fetch calls go through here
// ---------------------------------------------------------------------------
async function apiFetch(path, { method = 'GET', body, isJson = true } = {}) {
  const headers = { Accept: 'application/json' };
  let fetchBody;

  if (body && isJson) {
    headers['Content-Type'] = 'application/json';
    fetchBody = JSON.stringify(body);
  } else if (body) {
    // FormData — let browser set Content-Type with boundary
    fetchBody = body;
  }

  const response = await fetch(path, { method, headers, body: fetchBody });

  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error(`${path} returned ${response.status} with a non-JSON body`);
  }

  if (!response.ok) {
    throw new Error(data?.message || `${path} returned HTTP ${response.status}`);
  }
  return data;
}

// ---------------------------------------------------------------------------
// Main App
// ---------------------------------------------------------------------------
function App() {
  const [activeView, setActiveView]     = useState('overview');
  const [stats,      setStats]          = useState(null);
  const [issues,     setIssues]         = useState([]);
  const [locations,  setLocations]      = useState([]);
  const [authUser,   setAuthUser]       = useState(null);   // logged-in user or null
  const [service,    setService]        = useState({ state: 'checking', message: 'Checking backend connection' });
  const [loading,    setLoading]        = useState(true);
  const [search,     setSearch]         = useState('');
  const [filter,     setFilter]         = useState('all');
  const [error,      setError]          = useState('');
  const [showModal,  setShowModal]      = useState(false);
  const [submitMsg,  setSubmitMsg]      = useState('');      // success/error from submit

  // ---- Load all dashboard data ----
  const loadDashboard = useCallback(async () => {
    const [statsRes, issuesRes, serviceRes, locRes, authRes] = await Promise.allSettled([
      apiFetch('/api/stats/summary'),
      apiFetch('/api/reports'),
      apiFetch('/api/cat'),
      apiFetch('/api/locations'),
      apiFetch('/api/auth/me'),
    ]);

    if (statsRes.status   === 'fulfilled') setStats(statsRes.value);
    if (issuesRes.status  === 'fulfilled') setIssues(issuesRes.value.reports || []);
    if (locRes.status     === 'fulfilled') setLocations(locRes.value.locations || []);
    if (authRes.status    === 'fulfilled') setAuthUser(authRes.value.user);

    if (serviceRes.status === 'fulfilled') {
      setService({ state: 'online', message: serviceRes.value.message || 'Backend is running' });
    } else {
      setService({ state: 'offline', message: 'Backend connection unavailable' });
    }

    if (statsRes.status === 'rejected' && issuesRes.status === 'rejected') {
      setError('Campus data is temporarily unavailable. Check that the Flask backend is running on port 5000.');
    }

    setLoading(false);
  }, []);

  useEffect(() => {
    let active = true;
    loadDashboard().then(() => { if (!active) return; });
    return () => { active = false; };
  }, [loadDashboard]);

  // ---- Client-side filtering (overview shows first 5; reports view filters) ----
  const filteredIssues = useMemo(() => {
    const q = search.trim().toLowerCase();
    return issues.filter((issue) => {
      const matchesFilter = filter === 'all' || issue.status === filter;
      const matchesQuery  = !q || [issue.title, issue.report_number, issue.category, issue.building_name]
        .some((v) => String(v || '').toLowerCase().includes(q));
      return matchesFilter && matchesQuery;
    });
  }, [filter, issues, search]);

  const visibleIssues = activeView === 'overview' ? issues.slice(0, 5) : filteredIssues;

  // ---- Handle report submission from React modal ----
  async function handleSubmitReport(formData) {
    setSubmitMsg('');
    try {
      const result = await apiFetch('/api/reports', {
        method: 'POST',
        body:   formData,
        isJson: false,         // FormData, not JSON (supports optional photo upload)
      });
      setSubmitMsg(`✅ ${result.message}`);
      setShowModal(false);
      // Reload stats and reports to reflect the new entry
      await loadDashboard();
    } catch (err) {
      setSubmitMsg(`❌ ${err.message}`);
    }
  }

  return (
    <div className="app-shell">
      {/* ---- Sidebar ---- */}
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="CampusMindAi home">
          <img src="/static/img/campusmindai-logo.svg" alt="CampusMindAi" />
          <span>Campus operations</span>
        </a>

        <div className="sidebar-section-label">WORKSPACE</div>
        <nav className="side-nav" aria-label="Main navigation">
          {navigation.map(({ id, label, icon: Icon }) => (
            <button
              className={`side-nav-item ${activeView === id ? 'active' : ''}`}
              key={id}
              onClick={() => setActiveView(id)}
              type="button"
            >
              <Icon size={17} strokeWidth={1.8} />
              <span>{label}</span>
              {id === 'reports' && <span className="nav-count">{stats?.pending_reports ?? '—'}</span>}
            </button>
          ))}
        </nav>

        <div className="sidebar-spacer" />
        <div className={`service-card ${service.state}`}>
          <span className="service-indicator" />
          <div>
            <strong>
              Backend{' '}
              {service.state === 'online' ? 'online' : service.state === 'checking' ? 'checking' : 'offline'}
            </strong>
            <span>{service.message}</span>
          </div>
        </div>
        <a className="sidebar-help" href="/assistant" target="_blank" rel="noreferrer">
          Ask CampusMindAi <ArrowUpRight size={14} />
        </a>
      </aside>

      {/* ---- Main panel ---- */}
      <main className="main-panel">
        <header className="topbar">
          <div className="breadcrumb">
            <span>CampusMindAi</span>
            <span className="breadcrumb-divider">/</span>
            <strong>{navigation.find((n) => n.id === activeView)?.label}</strong>
          </div>
          <div className="topbar-actions">
            <span className="campus-selector">
              <Building2 size={15} /> All campuses <ChevronDown size={14} />
            </span>
            <button className="icon-button" type="button" aria-label="Notifications">
              <Bell size={17} />
            </button>
            <div className="profile-chip">
              <span className="profile-avatar">
                {authUser ? authUser.full_name.slice(0, 2).toUpperCase() : 'DS'}
              </span>
              <span>{authUser ? authUser.full_name : 'Campus team'}</span>
            </div>
          </div>
        </header>

        <div className="page-content">
          <section className="page-heading">
            <div>
              <p className="eyebrow">DAYANANDA SAGAR UNIVERSITY</p>
              <h1>
                {activeView === 'reports'
                  ? 'Issue reports'
                  : activeView === 'backend'
                  ? 'Service status'
                  : 'Campus overview'}
              </h1>
              <p className="page-subtitle">A live view of campus sustainability activity and maintenance.</p>
            </div>

            {/* Report button — uses Flask form for full auth/AI workflow; fallback modal when authenticated via React */}
            <div className="action-group">
              <a className="primary-action" href="/report-issue" target="_blank" rel="noreferrer">
                <CircleAlert size={16} /> Report an issue
              </a>
              {authUser && (
                <button
                  className="primary-action secondary-action"
                  type="button"
                  onClick={() => { setShowModal(true); setSubmitMsg(''); }}
                >
                  Quick report
                </button>
              )}
            </div>
          </section>

          {error    && <div className="notice error"><CircleAlert size={16} />{error}</div>}
          {submitMsg && (
            <div className={`notice ${submitMsg.startsWith('❌') ? 'error' : ''}`}>
              {submitMsg}
            </div>
          )}

          {/* ---- Backend health view ---- */}
          {activeView === 'backend' ? (
            <section className="service-detail panel">
              <div className={`service-large-icon ${service.state}`}>
                {service.state === 'online' ? <Check size={22} /> : <Activity size={22} />}
              </div>
              <div>
                <p className="eyebrow">API HEALTH</p>
                <h2>{service.state === 'online' ? 'Backend is running' : service.message}</h2>
                <p className="page-subtitle">
                  Health check: <code>/api/cat</code>
                </p>
              </div>
              <span className={`status-pill ${service.state}`}>{service.state}</span>
            </section>
          ) : (
            <>
              {/* ---- Metric cards ---- */}
              <section className="metric-grid" aria-label="Campus report metrics">
                <MetricCard label="Total reports"        value={stats?.total_reports}      icon={CircleAlert}  tone="indigo" trend="All submissions"                                                   loading={loading} />
                <MetricCard label="Open reports"         value={stats?.pending_reports}    icon={Activity}     tone="blue"  trend="Awaiting resolution"                                                loading={loading} />
                <MetricCard label="Resolved"             value={stats?.resolved_reports}   icon={ShieldCheck}  tone="teal"  trend={`${stats?.resolution_rate ?? 0}% resolution rate`}                 loading={loading} />
                <MetricCard label="Active resource issues" value={(stats?.active_water_leaks ?? 0) + (stats?.active_elec_waste ?? 0)} icon={Droplets} tone="slate" trend={`${stats?.active_water_leaks ?? 0} water · ${stats?.active_elec_waste ?? 0} energy`} loading={loading} />
              </section>

              {/* ---- Reports panel ---- */}
              <section className="panel reports-panel">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">LIVE CAMPUS FEED</p>
                    <h2>{activeView === 'reports' ? 'All issue reports' : 'Recent issue reports'}</h2>
                  </div>
                  <div className="report-controls">
                    <label className="search-field">
                      <Search size={15} />
                      <input
                        aria-label="Search issues"
                        placeholder="Search reports"
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                      />
                    </label>
                    {activeView === 'reports' && (
                      <select
                        aria-label="Filter by status"
                        value={filter}
                        onChange={(e) => setFilter(e.target.value)}
                      >
                        <option value="all">All statuses</option>
                        <option value="submitted">Submitted</option>
                        <option value="verified">Verified</option>
                        <option value="assigned">Assigned</option>
                        <option value="in_progress">In progress</option>
                        <option value="resolved">Resolved</option>
                      </select>
                    )}
                  </div>
                </div>
                <IssueTable issues={visibleIssues} loading={loading} />
                {activeView === 'overview' && issues.length > 5 && (
                  <button
                    className="text-action"
                    type="button"
                    onClick={() => setActiveView('reports')}
                  >
                    View all reports <ArrowUpRight size={14} />
                  </button>
                )}
              </section>

              {/* ---- Bottom strip ---- */}
              <section className="bottom-strip">
                <div>
                  <Droplets size={18} />
                  <span>Water conservation</span>
                  <strong>{stats?.active_water_leaks ?? '—'} active</strong>
                </div>
                <div>
                  <Zap size={18} />
                  <span>Energy monitoring</span>
                  <strong>{stats?.active_elec_waste ?? '—'} active</strong>
                </div>
                <div>
                  <Leaf size={18} />
                  <span>Campus stewardship</span>
                  <strong>In progress</strong>
                </div>
              </section>
            </>
          )}

          <footer className="page-footer">CampusMindAi <span>•</span> DSU campus operations</footer>
        </div>
      </main>

      {/* ---- Quick-report modal (only visible when user is authenticated) ---- */}
      {showModal && (
        <ReportModal
          locations={locations}
          onClose={() => setShowModal(false)}
          onSubmit={handleSubmitReport}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// MetricCard
// ---------------------------------------------------------------------------
function MetricCard({ label, value, icon: Icon, tone, trend, loading }) {
  return (
    <article className="metric-card">
      <div className={`metric-icon ${tone}`}>
        <Icon size={19} strokeWidth={1.8} />
      </div>
      <div className="metric-copy">
        <span>{label}</span>
        <strong>{loading ? '—' : (value ?? 0)}</strong>
        <small>
          <ArrowDownRight size={13} /> {trend}
        </small>
      </div>
    </article>
  );
}

// ---------------------------------------------------------------------------
// IssueTable
// ---------------------------------------------------------------------------
function IssueTable({ issues, loading }) {
  if (loading) {
    return (
      <div className="empty-state">
        <Loader2 size={20} style={{ display: 'inline', verticalAlign: 'middle', marginRight: 6 }} />
        Loading campus reports…
      </div>
    );
  }
  if (!issues.length) return <div className="empty-state">No reports match this view.</div>;

  return (
    <div className="table-wrap">
      <table className="issue-table">
        <thead>
          <tr>
            <th>Report</th>
            <th>Issue</th>
            <th>Location</th>
            <th>Category</th>
            <th>Priority</th>
            <th>Status</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          {issues.map((issue) => (
            <tr key={issue.id}>
              <td className="report-number">{issue.report_number}</td>
              <td className="issue-title">{issue.title}</td>
              <td>
                {issue.building_name || 'Campus'}
                {issue.floor ? ` · ${issue.floor}` : ''}
              </td>
              <td>
                <span className={`category-tag ${CATEGORY_COLORS[issue.category] || 'indigo'}`}>
                  {formatLabel(issue.category)}
                </span>
              </td>
              <td>
                <span className={`priority-dot ${issue.priority}`} />
                {formatLabel(issue.priority)}
              </td>
              <td>
                <span className={`status-pill ${issue.status}`}>
                  {formatLabel(issue.status)}
                </span>
              </td>
              <td>{formatDate(issue.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Quick-report modal
// ---------------------------------------------------------------------------
function ReportModal({ locations, onClose, onSubmit }) {
  const [submitting, setSubmitting] = useState(false);
  const [localError, setLocalError] = useState('');

  async function handleSubmit(e) {
    e.preventDefault();
    setLocalError('');

    const form    = e.target;
    const fd      = new FormData(form);

    // Client-side validation
    const title       = fd.get('title')?.trim();
    const description = fd.get('description')?.trim();
    const spot        = fd.get('specific_spot')?.trim();

    if (!title)       { setLocalError('Title is required.');            return; }
    if (!description) { setLocalError('Description is required.');      return; }
    if (!spot)        { setLocalError('Specific spot is required.');    return; }

    setSubmitting(true);
    try {
      await onSubmit(fd);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-label="Submit report">
      <div className="modal-panel">
        <div className="modal-header">
          <h3>Quick Report</h3>
          <button className="icon-button" type="button" onClick={onClose} aria-label="Close modal">
            <X size={16} />
          </button>
        </div>

        {localError && <div className="notice error"><CircleAlert size={14} /> {localError}</div>}

        <form className="modal-form" onSubmit={handleSubmit} encType="multipart/form-data">
          <label>
            Title <span className="req">*</span>
            <input name="title" maxLength={200} required placeholder="Brief issue description" />
          </label>

          <label>
            Description <span className="req">*</span>
            <textarea name="description" rows={3} maxLength={3000} required
              placeholder="Describe the campus issue in detail" />
          </label>

          <label>
            Specific spot <span className="req">*</span>
            <input name="specific_spot" required placeholder="e.g. Near main gate, Lab 204" />
          </label>

          <div className="form-row">
            <label>
              Category
              <select name="category">
                <option value="">AI will detect</option>
                {VALID_CATEGORIES.map((c) => (
                  <option key={c} value={c}>{formatLabel(c)}</option>
                ))}
              </select>
            </label>

            <label>
              Priority
              <select name="priority">
                <option value="">AI will detect</option>
                {VALID_PRIORITIES.map((p) => (
                  <option key={p} value={p}>{formatLabel(p)}</option>
                ))}
              </select>
            </label>
          </div>

          <label>
            Campus location
            <select name="location_id">
              <option value="">— Select building (optional) —</option>
              {locations.map((loc) => (
                <option key={loc.id} value={loc.id}>
                  {loc.building_name} · {loc.floor} · {loc.zone_or_wing}
                </option>
              ))}
            </select>
          </label>

          <label>
            Photo (optional)
            <input type="file" name="photo" accept=".png,.jpg,.jpeg,.webp" />
          </label>

          <label className="checkbox-label">
            <input type="checkbox" name="is_anonymous" value="1" />
            Submit anonymously
          </label>

          <div className="modal-actions">
            <button type="button" className="btn-ghost" onClick={onClose} disabled={submitting}>
              Cancel
            </button>
            <button type="submit" className="primary-action" disabled={submitting}>
              {submitting ? (
                <>
                  <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> Submitting…
                </>
              ) : (
                <>
                  <CircleAlert size={14} /> Submit report
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default App;