/**
 * Main Application Controller for HHGoa Analyst Command Center
 */
document.addEventListener('DOMContentLoaded', async () => {
  let activeCaseId = null;
  let activeCaseData = null;
  let graphRenderer = new GraphRenderer('graphCanvas');

  // DOM Elements
  const caseSelect = document.getElementById('caseSelect');
  const btnInvestigate = document.getElementById('btnInvestigate');
  const tgStatusDot = document.getElementById('tgStatusDot');
  const tgStatusText = document.getElementById('tgStatusText');
  const dbStatusDot = document.getElementById('dbStatusDot');
  const dbStatusText = document.getElementById('dbStatusText');

  // Trigger & Meta Elements
  const triggerTypeBadge = document.getElementById('triggerTypeBadge');
  const triggerText = document.getElementById('triggerText');
  const metaTxnId = document.getElementById('metaTxnId');
  const metaCardId = document.getElementById('metaCardId');
  const metaCustId = document.getElementById('metaCustId');
  const metaRiskScore = document.getElementById('metaRiskScore');

  // Assessment Elements
  const verdictBadge = document.getElementById('verdictBadge');
  const probBar = document.getElementById('probBar');
  const probVal = document.getElementById('probVal');
  const patternVal = document.getElementById('patternVal');
  const exposureVal = document.getElementById('exposureVal');

  // Tab Panes & Counts
  const evCount = document.getElementById('evCount');
  const uncCount = document.getElementById('uncCount');
  const aprCount = document.getElementById('aprCount');
  const evidenceList = document.getElementById('evidenceList');
  const uncertaintyList = document.getElementById('uncertaintyList');
  const addEvidenceList = document.getElementById('addEvidenceList');
  const nbaDiffContent = document.getElementById('nbaDiffContent');
  const approvalsList = document.getElementById('approvalsList');
  const persistenceContent = document.getElementById('persistenceContent');

  // Initialize System Health
  async function checkHealth() {
    try {
      const h = await API.getHealth();
      const tgHealthy = h.graph && (h.graph.tigergraph === 'healthy' || h.graph.local === 'healthy');
      tgStatusDot.className = 'status-dot ' + (tgHealthy ? 'healthy' : 'degraded');
      tgStatusText.textContent = h.graph.tigergraph ? `TG: ${h.graph.tigergraph}` : 'TG: active';

      dbStatusDot.className = 'status-dot ' + (h.app_db === 'healthy' ? 'healthy' : 'degraded');
      dbStatusText.textContent = `DB: ${h.app_db}`;
    } catch (e) {
      console.warn('Health check failed:', e);
      tgStatusDot.className = 'status-dot degraded';
      dbStatusDot.className = 'status-dot degraded';
    }
  }

  // Load Case Pack Triggers
  async function loadCasePack() {
    try {
      const cases = await API.getCases();
      caseSelect.innerHTML = '';
      cases.forEach(c => {
        const opt = document.createElement('option');
        opt.value = c.case_id;
        opt.textContent = `${c.case_id} — ${c.trigger_type} (${c.flagged_txn_id})`;
        opt.dataset.case = JSON.stringify(c);
        caseSelect.appendChild(opt);
      });

      if (cases.length > 0) {
        selectCase(cases[0].case_id);
      }
    } catch (e) {
      console.error('Failed to load case pack:', e);
    }
  }

  // Handle Case Selection
  async function selectCase(caseId) {
    activeCaseId = caseId;
    caseSelect.value = caseId;

    const opt = caseSelect.selectedOptions[0];
    const triggerData = opt ? JSON.parse(opt.dataset.case || '{}') : {};

    // Populate Trigger Card
    triggerTypeBadge.textContent = triggerData.trigger_type || 'TRIGGER';
    triggerText.textContent = triggerData.trigger_text || 'No trigger alert text provided.';
    metaTxnId.textContent = triggerData.flagged_txn_id || '—';
    metaCardId.textContent = triggerData.card_id || '—';
    metaCustId.textContent = triggerData.customer_id || '—';
    metaRiskScore.textContent = triggerData.risk_score != null ? Number(triggerData.risk_score).toFixed(2) : '—';

    resetTimeline();
    resetAssessment();

    // Fetch existing investigation & graph
    const [fullData, graphData] = await Promise.all([
      API.getInvestigationFull(caseId).catch(() => null),
      API.getInvestigationGraph(caseId).catch(() => null)
    ]);

    if (fullData) {
      renderInvestigation(fullData);
    } else {
      renderEmptyState();
    }

    if (graphData) {
      graphRenderer.setData(graphData);
    } else {
      graphRenderer.setData({ nodes: [], links: [] });
    }
  }

  caseSelect.addEventListener('change', () => {
    selectCase(caseSelect.value);
  });

  // Timeline Stepper Helper
  function setTimelineStep(stepIndex, status = 'active') {
    const steps = document.querySelectorAll('.step-item');
    steps.forEach((s, idx) => {
      s.classList.remove('active', 'completed');
      if (idx < stepIndex) {
        s.classList.add('completed');
      } else if (idx === stepIndex) {
        s.classList.add(status);
      }
    });
  }

  function resetTimeline() {
    document.querySelectorAll('.step-item').forEach(s => s.classList.remove('active', 'completed'));
    setTimelineStep(0, 'active');
  }

  function resetAssessment() {
    verdictBadge.textContent = 'PENDING';
    verdictBadge.className = 'verdict-badge';
    probBar.style.width = '0%';
    probBar.style.backgroundColor = 'var(--text-muted)';
    probVal.textContent = '0.00';
    patternVal.textContent = '—';
    exposureVal.textContent = '$0.00';
  }

  function renderEmptyState() {
    resetAssessment();
    evidenceList.innerHTML = '<div class="empty-state"><p>Case not yet investigated.<br>Click <strong>"Start Live Investigation"</strong> to run agent workflow.</p></div>';
    uncertaintyList.innerHTML = '<div class="empty-state"><p>No uncertainty items recorded.</p></div>';
    addEvidenceList.innerHTML = '<div class="empty-state"><p>No additional evidence requested.</p></div>';
    nbaDiffContent.innerHTML = '<div class="empty-state"><p>NBA recommendations will appear after assessment.</p></div>';
    approvalsList.innerHTML = '<div class="empty-state"><p>No pending human approvals.</p></div>';
    persistenceContent.innerHTML = '<div class="empty-state"><p>Not yet written to graph case memory.</p></div>';
    evCount.textContent = '0';
    uncCount.textContent = '0';
    aprCount.textContent = '0';
  }

  // Render Completed Investigation
  function renderInvestigation(caseData) {
    activeCaseData = caseData;
    const c = caseData;

    // Timeline: all completed
    setTimelineStep(8, 'completed');

    // Threat Assessment Banner
    const verdict = (c.verdict || 'uncertain').toLowerCase();
    verdictBadge.textContent = verdict.toUpperCase();
    verdictBadge.className = `verdict-badge verdict-${verdict}`;

    const prob = Number(c.fraud_probability || 0);
    probBar.style.width = `${Math.round(prob * 100)}%`;
    probVal.textContent = prob.toFixed(3);
    if (prob >= 0.85) {
      probBar.style.backgroundColor = 'var(--accent-rose)';
    } else if (prob >= 0.3) {
      probBar.style.backgroundColor = 'var(--accent-amber)';
    } else {
      probBar.style.backgroundColor = 'var(--accent-emerald)';
    }

    patternVal.textContent = c.pattern || 'none';
    exposureVal.textContent = `$${Number(c.exposure_usd || 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}`;

    // Evidence Tab
    const evidence = c.evidence || [];
    evCount.textContent = evidence.length;
    if (evidence.length === 0) {
      evidenceList.innerHTML = '<div class="empty-state"><p>No evidence items gathered.</p></div>';
    } else {
      evidenceList.innerHTML = evidence.map(ev => `
        <div class="evidence-card">
          <div class="ev-card-header">
            <span class="ev-source-badge ev-source-${ev.source || 'graph'}">${ev.source || 'GRAPH'}</span>
            <span style="font-size:0.68rem; color:var(--text-muted); font-weight:600;">Conf: ${(Number(ev.confidence || 0.7)*100).toFixed(0)}%</span>
          </div>
          <div class="ev-claim">${escapeHtml(ev.claim)}</div>
          <div class="ev-provenance">Ref: ${escapeHtml(ev.ref || '—')}</div>
        </div>
      `).join('');
    }

    // Uncertainty Tab
    const uncertainty = c.uncertainty || [];
    uncCount.textContent = uncertainty.length;
    if (uncertainty.length === 0) {
      uncertaintyList.innerHTML = '<div class="empty-state"><p>No remaining uncertainty items.</p></div>';
    } else {
      uncertaintyList.innerHTML = uncertainty.map(u => `
        <div class="uncertainty-card">
          <div class="unc-question">${escapeHtml(u.question || 'Unspecified ambiguity')}</div>
          <div class="unc-impact">Impact: ${escapeHtml(u.impact || 'Influences fraud probability')}</div>
          <div class="unc-resolution">Resolution: ${escapeHtml(u.resolution_method || 'Customer validation')}</div>
        </div>
      `).join('');
    }

    // Additional Evidence Tab
    const requests = c.evidence_requests || [];
    if (requests.length === 0) {
      addEvidenceList.innerHTML = '<div class="empty-state"><p>No additional evidence requested during this investigation.</p></div>';
    } else {
      addEvidenceList.innerHTML = requests.map(req => `
        <div class="evidence-card" style="border-left: 3px solid var(--accent-cyan);">
          <div class="ev-card-header">
            <span class="ev-source-badge ev-source-customer">REQUEST: ${req.type || 'CUSTOMER_VALIDATION'}</span>
            <span style="font-size:0.68rem; color:var(--text-muted); font-weight:600;">Step ${req.asked_after_step}</span>
          </div>
          <div class="ev-claim" style="font-weight:600;">Rationale: ${escapeHtml(req.rationale || 'Address ambiguity')}</div>
          <div class="ev-provenance" style="color:var(--accent-emerald);">Response: ${escapeHtml(req.assumed_response || 'Pending reply')}</div>
        </div>
      `).join('');
    }

    // NBA Diff Component
    const initialNba = c.nba_initial || [];
    const finalNba = c.nba_final || [];
    const whatChanged = c.nba_what_changed || 'nothing';

    nbaDiffContent.innerHTML = `
      <div class="nba-diff-container">
        <div class="nba-what-changed">
          <strong>Reassessment Delta:</strong> ${escapeHtml(whatChanged)}
        </div>
        <div class="nba-diff-box">
          <div class="nba-diff-header">
            <span>Initial NBA (Before Evidence)</span>
            <span>${initialNba.length} actions</span>
          </div>
          ${initialNba.map(a => renderActionRow(a)).join('') || '<div style="font-size:0.75rem; color:var(--text-muted);">No initial actions.</div>'}
        </div>
        <div class="nba-diff-box">
          <div class="nba-diff-header" style="color:var(--accent-emerald);">
            <span>Final NBA (After Evidence)</span>
            <span>${finalNba.length} actions</span>
          </div>
          ${finalNba.map(a => renderActionRow(a)).join('') || '<div style="font-size:0.75rem; color:var(--text-muted);">No final actions.</div>'}
        </div>
      </div>
    `;

    // Approvals Console Tab
    const approvals = c.approvals || [];
    const pendingApprovals = approvals.filter(a => a.status === 'pending');
    aprCount.textContent = pendingApprovals.length;

    if (approvals.length === 0) {
      approvalsList.innerHTML = '<div class="empty-state"><p>No actions require human approval (all actions auto-executed under policy).</p></div>';
    } else {
      approvalsList.innerHTML = approvals.map(apr => `
        <div class="approval-card ${apr.status}">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <span style="font-weight:700; color:var(--text-primary);">${apr.action}</span>
            <span class="route-pill route-${(apr.required_route || 'l1').toLowerCase()}">${apr.required_route || 'L1'} APPROVAL</span>
          </div>
          <div class="action-reason">${escapeHtml(apr.reason || '')}</div>
          <div style="margin-top:6px; font-size:0.7rem; color:var(--text-muted);">Status: <strong style="color:${apr.status === 'approved' ? 'var(--accent-emerald)' : apr.status === 'rejected' ? 'var(--accent-rose)' : 'var(--accent-amber)'}">${apr.status.toUpperCase()}</strong></div>
          ${apr.status === 'pending' ? `
            <div class="approval-actions">
              <button class="btn-approve" onclick="handleApprovalDecision('${c.case_id}', '${apr.approval_id}', 'approved')">Approve Action</button>
              <button class="btn-reject" onclick="handleApprovalDecision('${c.case_id}', '${apr.approval_id}', 'rejected')">Reject Action</button>
            </div>
          ` : ''}
        </div>
      `).join('');
    }

    // Persistence & Case Memory Tab
    const sar = c.sar || {};
    persistenceContent.innerHTML = `
      <div class="persistence-box">
        <div class="persistence-header">
          <span style="font-weight:700; font-size:0.8rem;">Live TigerGraph Persistence</span>
          <span class="route-pill route-auto">${c.written_to_graph ? 'WRITTEN TO GRAPH' : 'LOCAL CACHE'}</span>
        </div>
        <div style="font-family:var(--font-mono); font-size:0.75rem; color:var(--accent-cyan); margin-bottom:6px;">
          Vertex ID: ${escapeHtml(c.graph_case_id || `CASE-2016-${c.case_id}`)}
        </div>
        <div style="font-size:0.75rem; color:var(--text-secondary); margin-bottom:12px;">
          Summary: ${escapeHtml(c.summary || 'Investigation completed successfully.')}
        </div>
      </div>

      <div class="persistence-box">
        <div class="persistence-header">
          <span style="font-weight:700; font-size:0.8rem;">FinCEN Suspicious Activity Report (SAR)</span>
          <span class="route-pill ${sar.file ? 'route-l2' : 'route-auto'}">${sar.file ? 'SAR FILED' : 'NO SAR REQUIRED'}</span>
        </div>
        ${sar.file ? `
          <div style="font-size:0.75rem; color:var(--text-secondary); margin-bottom:8px;">
            <strong>Reason:</strong> ${escapeHtml(sar.reason || 'Policy §4 threshold')}
          </div>
          <div class="sar-narrative-box">${escapeHtml(sar.narrative || 'No narrative provided.')}</div>
        ` : `
          <div style="font-size:0.75rem; color:var(--text-muted);">
            Threshold for FinCEN reporting not met (exposure &lt; $2,000 without cross-entity syndication).
          </div>
        `}
      </div>
    `;
  }

  function renderActionRow(a) {
    const route = (a.route || 'auto').toLowerCase();
    return `
      <div class="action-row">
        <div>
          <div class="action-name">${a.action}</div>
          <div class="action-reason">${escapeHtml(a.reason || '')}</div>
        </div>
        <span class="route-pill route-${route}">${route.toUpperCase()}</span>
      </div>
    `;
  }

  // Handle Live Investigation Execution
  btnInvestigate.addEventListener('click', async () => {
    if (!activeCaseId) return;

    btnInvestigate.disabled = true;
    btnInvestigate.innerHTML = '<div class="spinner" style="width:16px; height:16px; border-width:2px; margin:0;"></div> Investigating...';

    try {
      // Simulate visual progression through stages
      setTimelineStep(1, 'active');
      await sleep(350);
      setTimelineStep(2, 'active');
      await sleep(350);
      setTimelineStep(3, 'active');

      // Call real backend orchestrator
      const answer = await API.runInvestigation(activeCaseId);

      setTimelineStep(5, 'active');
      await sleep(250);
      setTimelineStep(6, 'active');
      await sleep(250);
      setTimelineStep(7, 'active');

      // Reload rich full model & graph
      const [fullData, graphData] = await Promise.all([
        API.getInvestigationFull(activeCaseId),
        API.getInvestigationGraph(activeCaseId)
      ]);

      renderInvestigation(fullData);
      if (graphData) {
        graphRenderer.setData(graphData);
      }
    } catch (err) {
      console.error('Investigation error:', err);
      alert(`Investigation failed: ${err.message}`);
    } finally {
      btnInvestigate.disabled = false;
      btnInvestigate.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
        Start Live Investigation
      `;
    }
  });

  // Global handler for approval decision buttons
  window.handleApprovalDecision = async (caseId, approvalId, decision) => {
    try {
      await API.decideApproval(caseId, approvalId, decision, 'Analyst-Judge-01');
      // Refresh case data
      const fullData = await API.getInvestigationFull(caseId);
      if (fullData) renderInvestigation(fullData);
    } catch (e) {
      alert(`Approval error: ${e.message}`);
    }
  };

  // Tab Navigation Handling
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

      btn.classList.add('active');
      const targetId = btn.dataset.tab;
      const targetPane = document.getElementById(targetId);
      if (targetPane) targetPane.classList.add('active');
    });
  });

  // Graph Controls
  document.getElementById('btnZoomIn')?.addEventListener('click', () => graphRenderer.zoomIn());
  document.getElementById('btnZoomOut')?.addEventListener('click', () => graphRenderer.zoomOut());
  document.getElementById('btnResetView')?.addEventListener('click', () => graphRenderer.resetView());

  function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Initial Boot
  await checkHealth();
  await loadCasePack();
});
