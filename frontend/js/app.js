/**
 * Main Application Controller for HHGoa Analyst Command Center
 * Phase D.6: Prototype Polish & Competitive Hardening
 */
document.addEventListener('DOMContentLoaded', async () => {
  let activeCaseId = null;
  let activeCaseData = null;
  let activeGraphData = null;
  let activeEntityFilter = null;
  let isBreakdownOpen = false;

  const graphRenderer = new GraphRenderer('graphCanvas');

  // DOM Elements
  const caseSelect = document.getElementById('caseSelect');
  const btnInvestigate = document.getElementById('btnInvestigate');
  const tgStatusDot = document.getElementById('tgStatusDot');
  const tgStatusText = document.getElementById('tgStatusText');
  const dbStatusDot = document.getElementById('dbStatusDot');
  const dbStatusText = document.getElementById('dbStatusText');
  const btnTgStatus = document.getElementById('btnTgStatus');
  const btnDbStatus = document.getElementById('btnDbStatus');

  // Trigger & Meta Elements
  const triggerTypeBadge = document.getElementById('triggerTypeBadge');
  const triggerChannelBadge = document.getElementById('triggerChannelBadge');
  const triggerText = document.getElementById('triggerText');
  const metaTxnId = document.getElementById('metaTxnId');
  const metaCardId = document.getElementById('metaCardId');
  const metaCustId = document.getElementById('metaCustId');
  const metaRiskScore = document.getElementById('metaRiskScore');

  // Assessment Banner Elements
  const verdictBadge = document.getElementById('verdictBadge');
  const probBar = document.getElementById('probBar');
  const probVal = document.getElementById('probVal');
  const patternVal = document.getElementById('patternVal');
  const patternSecondaryVal = document.getElementById('patternSecondaryVal');
  const exposureVal = document.getElementById('exposureVal');
  const exposureSub = document.getElementById('exposureSub');
  const btnDecomposeScore = document.getElementById('btnDecomposeScore');

  // Tab Panes & Counts
  const evCount = document.getElementById('evCount');
  const uncCount = document.getElementById('uncCount');
  const aprCount = document.getElementById('aprCount');
  const evidenceList = document.getElementById('evidenceList');
  const scoreBreakdownCard = document.getElementById('scoreBreakdownCard');
  const toggleBreakdown = document.getElementById('toggleBreakdown');
  const breakdownContent = document.getElementById('breakdownContent');
  const breakdownTableBody = document.getElementById('breakdownTableBody');
  const evFilterBar = document.getElementById('evFilterBar');
  const filterEntityName = document.getElementById('filterEntityName');
  const btnClearEvFilter = document.getElementById('btnClearEvFilter');
  const uncertaintyCycleContent = document.getElementById('uncertaintyCycleContent');
  const nbaGovernanceContent = document.getElementById('nbaGovernanceContent');
  const persistenceContent = document.getElementById('persistenceContent');

  // Graph Inspector Elements
  const graphInspector = document.getElementById('graphInspector');
  const inspNodeType = document.getElementById('inspNodeType');
  const inspNodeId = document.getElementById('inspNodeId');
  const inspNodeRelevance = document.getElementById('inspNodeRelevance');
  const inspNodeMeta = document.getElementById('inspNodeMeta');
  const btnCloseInspector = document.getElementById('btnCloseInspector');
  const btnFilterEvidence = document.getElementById('btnFilterEvidence');

  // Toast Container & Health Modal
  const toastContainer = document.getElementById('toastContainer');
  const healthModal = document.getElementById('healthModal');
  const btnCloseHealthModal = document.getElementById('btnCloseHealthModal');

  // ── Non-Blocking Toast System ─────────────────────────────────────────────
  function showToast(message, type = 'info', duration = 4000) {
    if (!toastContainer) return;
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
      <div class="toast-msg">${escapeHtml(message)}</div>
      <button class="toast-close" title="Dismiss">&times;</button>
    `;

    toast.querySelector('.toast-close').addEventListener('click', () => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(20px)';
      setTimeout(() => toast.remove(), 200);
    });

    toastContainer.appendChild(toast);

    setTimeout(() => {
      if (toast.parentElement) {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(20px)';
        setTimeout(() => toast.remove(), 200);
      }
    }, duration);
  }

  // ── Health Diagnostics ────────────────────────────────────────────────────
  let lastHealthData = null;
  async function checkHealth() {
    try {
      const h = await API.getHealth();
      lastHealthData = h;
      const isTgHealthy = h.graph && (h.graph.tigergraph === 'healthy' || h.graph.local === 'healthy');
      tgStatusDot.className = 'status-dot ' + (isTgHealthy ? 'healthy' : 'degraded');
      tgStatusText.textContent = h.graph.tigergraph ? `TG: ${h.graph.tigergraph}` : 'TG: active';

      const isDbHealthy = h.app_db === 'healthy';
      dbStatusDot.className = 'status-dot ' + (isDbHealthy ? 'healthy' : 'degraded');
      dbStatusText.textContent = `DB: ${h.app_db}`;
    } catch (e) {
      console.warn('Health check failed:', e);
      tgStatusDot.className = 'status-dot degraded';
      dbStatusDot.className = 'status-dot degraded';
      tgStatusText.textContent = 'TG: unreachable';
      dbStatusText.textContent = 'DB: check failed';
    }
  }

  function openHealthModal() {
    if (!healthModal) return;
    const h = lastHealthData || {};
    const tgStatus = document.getElementById('diagTgStatus');
    const dbStatus = document.getElementById('diagDbStatus');
    const llmProvider = document.getElementById('diagLlmProvider');

    if (tgStatus) tgStatus.textContent = h.graph ? (h.graph.tigergraph || h.graph.local || 'Unknown') : 'Checking...';
    if (dbStatus) dbStatus.textContent = h.app_db || 'Healthy';
    if (llmProvider) {
      if (h.llm_provider === 'groq') {
        llmProvider.textContent = 'Groq Cloud (OpenAI GPT-OSS / Llama)';
      } else {
        llmProvider.textContent = h.llm_provider || 'Deterministic Fallback (Audit Safe)';
      }
    }

    healthModal.style.display = 'flex';
  }

  btnTgStatus?.addEventListener('click', openHealthModal);
  btnDbStatus?.addEventListener('click', openHealthModal);
  btnCloseHealthModal?.addEventListener('click', () => {
    if (healthModal) healthModal.style.display = 'none';
  });
  healthModal?.addEventListener('click', e => {
    if (e.target === healthModal) healthModal.style.display = 'none';
  });

  // ── Load Benchmark Case Pack ──────────────────────────────────────────────
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
        const defaultCase = cases.find(c => c.case_id === 'HHG-014') || cases[0];
        selectCase(defaultCase.case_id);
      }
    } catch (e) {
      console.error('Failed to load case pack:', e);
      showToast('Could not load case pack triggers from API.', 'error');
    }
  }

  // ── Case Selection ────────────────────────────────────────────────────────
  async function selectCase(caseId) {
    activeCaseId = caseId;
    activeCaseData = null;
    activeGraphData = null;
    activeEntityFilter = null;
    caseSelect.value = caseId;

    if (evFilterBar) evFilterBar.style.display = 'none';
    if (graphInspector) graphInspector.style.display = 'none';
    if (graphRenderer) {
      graphRenderer.selectedNode = null;
      graphRenderer.setData({ nodes: [], links: [] });
    }

    const opt = caseSelect.selectedOptions[0];
    const triggerData = opt ? JSON.parse(opt.dataset.case || '{}') : {};

    // Populate Trigger Card
    triggerTypeBadge.textContent = triggerData.trigger_type || 'RISK SCORE';
    triggerText.textContent = triggerData.trigger_text || 'No trigger alert text provided.';
    metaTxnId.textContent = triggerData.flagged_txn_id || '—';
    metaCardId.textContent = triggerData.card_id || '—';
    metaCustId.textContent = triggerData.customer_id || '—';
    metaRiskScore.textContent = triggerData.risk_score != null ? Number(triggerData.risk_score).toFixed(2) : '—';

    // Reset investigation state
    resetTimeline();
    resetAssessment();

    // Render empty state (passive selection; wait for user to click Start Live Investigation)
    renderEmptyState(triggerData);
  }

  caseSelect.addEventListener('change', () => {
    selectCase(caseSelect.value);
  });

  // ── Investigation Story Stepper ───────────────────────────────────────────
  function setTimelineStep(stepIndex, status = 'active') {
    const steps = document.querySelectorAll('.step-item');
    steps.forEach((s, idx) => {
      s.classList.remove('active', 'completed', 'focused');
      if (idx < stepIndex) {
        s.classList.add('completed');
      } else if (idx === stepIndex) {
        s.classList.add(status);
      }
    });
  }

  function resetTimeline() {
    document.querySelectorAll('.step-item').forEach(s => s.classList.remove('active', 'completed', 'focused'));
    setTimelineStep(0, 'active');
  }

  // Allow clicking on story steps to focus relevant views
  document.querySelectorAll('.step-item').forEach((stepEl, idx) => {
    stepEl.addEventListener('click', () => {
      document.querySelectorAll('.step-item').forEach(s => s.classList.remove('focused'));
      stepEl.classList.add('focused');

      const stepKey = stepEl.dataset.step;
      if (stepKey === 'evidence' || stepKey === 'traversal') {
        switchTab('tabEvidence');
      } else if (stepKey === 'risk') {
        switchTab('tabEvidence');
        openScoreBreakdown(true);
      } else if (stepKey === 'uncertainty' || stepKey === 'request' || stepKey === 'reassessment') {
        switchTab('tabUncertainty');
      } else if (stepKey === 'nba') {
        switchTab('tabNba');
      } else if (stepKey === 'persistence') {
        switchTab('tabPersistence');
      }
    });
  });

  function switchTab(tabId) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    const targetBtn = document.querySelector(`[data-tab="${tabId}"]`);
    const targetPane = document.getElementById(tabId);
    if (targetBtn) targetBtn.classList.add('active');
    if (targetPane) targetPane.classList.add('active');
  }

  function resetAssessment() {
    verdictBadge.textContent = 'READY';
    verdictBadge.className = 'verdict-badge verdict-ready';
    probBar.style.width = '0%';
    probBar.style.backgroundColor = 'var(--text-muted)';
    probVal.textContent = '0.000';
    patternVal.textContent = '—';
    if (patternSecondaryVal) patternSecondaryVal.textContent = 'Secondary: none';
    exposureVal.textContent = '$0.00';
    if (exposureSub) exposureSub.textContent = '1 Flagged Transaction';
  }

  function renderEmptyState(triggerData) {
    resetAssessment();
    openScoreBreakdown(false);
    if (btnInvestigate) {
      btnInvestigate.disabled = false;
      btnInvestigate.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polygon points="5 3 19 12 5 21 5 3"></polygon>
        </svg>
        <span>Start Live Investigation</span>
      `;
    }
    evidenceList.innerHTML = `
      <div class="empty-state">
        <p>Case not yet investigated.<br>Click <strong>"Start Live Investigation"</strong> to execute live TigerGraph queries and agent assessment.</p>
      </div>
    `;
    uncertaintyCycleContent.innerHTML = `
      <div class="empty-state">
        <p>Uncertainty analysis and reassessment cycle will appear once investigation is initiated.</p>
      </div>
    `;
    nbaGovernanceContent.innerHTML = `
      <div class="empty-state">
        <p>Governed NBA recommendations and approval workflows will render after risk assessment.</p>
      </div>
    `;
    persistenceContent.innerHTML = `
      <div class="empty-state">
        <p>Investigation case not yet persisted to TigerGraph memory.</p>
      </div>
    `;
    evCount.textContent = '0';
    uncCount.textContent = '0';
    aprCount.textContent = '0';
    if (breakdownTableBody) breakdownTableBody.innerHTML = '';
  }

  // ── Render Completed Investigation ────────────────────────────────────────
  function renderInvestigation(caseData) {
    activeCaseData = caseData;
    const c = caseData;

    // Timeline: audit-driven progression.  Stage completion reflects what the
    // backend actually did (evidence count, requests, NBA, persistence).
    const hasPending = (c.evidence_requests || []).some(r => r.status === 'pending');
    if (hasPending) {
      setTimelineStep(7, 'active');   // paused at evidence request stage
    } else if ((c.approvals || []).some(a => a.status === 'pending')) {
      setTimelineStep(10, 'active');  // paused at approval stage
    } else {
      setTimelineStep(11, 'completed');
    }

    // 1. Assessment Banner
    const verdict = (c.verdict || 'uncertain').toLowerCase();
    verdictBadge.textContent = hasPending ? 'AWAITING EVIDENCE' : verdict.toUpperCase();
    verdictBadge.className = hasPending ? 'verdict-badge verdict-ready' : `verdict-badge verdict-${verdict}`;

    const prob = Number(c.fraud_probability || 0);
    probBar.style.width = `${Math.round(prob * 100)}%`;
    probVal.textContent = prob.toFixed(3);
    if (prob >= 0.75) {
      probBar.style.backgroundColor = 'var(--accent-rose)';
    } else if (prob >= 0.35) {
      probBar.style.backgroundColor = 'var(--accent-amber)';
    } else {
      probBar.style.backgroundColor = 'var(--accent-emerald)';
    }

    patternVal.textContent = c.pattern || 'none';
    if (patternSecondaryVal) {
      patternSecondaryVal.textContent = c.pattern_secondary
        ? `Secondary: ${c.pattern_secondary}`
        : 'Secondary: none';
    }

    exposureVal.textContent = `$${Number(c.exposure_usd || 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
    if (exposureSub) {
      const txnCount = (c.affected_txn_ids || []).length || 1;
      exposureSub.textContent = `${txnCount} Affected Transaction${txnCount > 1 ? 's' : ''}`;
    }

    // 2. Score Breakdown (Noisy-OR Table)
    const breakdown = (c.risk_assessment && c.risk_assessment.score_breakdown) ||
                      (c.risk_before && c.risk_before.score_breakdown) || [];
    renderScoreBreakdown(breakdown, prob);

    // 3. Evidence Tab
    renderEvidenceList(c.evidence || []);

    // 4. Uncertainty & Reassessment Lifecycle (P0)
    renderUncertaintyCycle(c);

    // 5. Governed NBA & Policy Tab (P1)
    renderNbaGovernance(c);

    // 6. Case Memory & SAR
    renderPersistence(c);
  }

  // ── Render Noisy-OR Score Breakdown ───────────────────────────────────────
  function renderScoreBreakdown(breakdown, finalProb) {
    if (!breakdownTableBody) return;

    if (breakdown.length === 0) {
      breakdownTableBody.innerHTML = `
        <tr>
          <td colspan="4" style="text-align:center; color:var(--text-muted); padding:10px;">
            Baseline trigger score only (no pattern signals triggered).
          </td>
        </tr>
      `;
      return;
    }

    breakdownTableBody.innerHTML = breakdown.map(item => {
      const type = item.type || 'fraud_signal';
      const weightClass = type === 'fraud_signal' ? 'fraud' : type === 'clearing_signal' ? 'clearing' : 'total';
      const typeBadge = type === 'fraud_signal'
        ? '<span class="claim-type-badge claim-type-model_score">RISK</span>'
        : type === 'clearing_signal'
        ? '<span class="claim-type-badge claim-type-observed_fact">CLEARING</span>'
        : '<span class="claim-type-badge claim-type-derived_inference">TOTAL</span>';

      const weightStr = type === 'clearing_signal'
        ? `&times;${Number(item.contribution).toFixed(2)}`
        : type === 'total'
        ? `${Number(item.contribution).toFixed(3)}`
        : `+${Number(item.contribution).toFixed(2)}`;

      return `
        <tr>
          <td><strong style="color:var(--text-primary); font-family:var(--font-mono);">${escapeHtml(item.channel)}</strong></td>
          <td>${typeBadge}</td>
          <td><span class="channel-weight ${weightClass}">${weightStr}</span></td>
          <td style="color:var(--text-secondary);">${escapeHtml(item.label || item.reason || '')}</td>
        </tr>
      `;
    }).join('');
  }

  function openScoreBreakdown(forceOpen = null) {
    isBreakdownOpen = forceOpen !== null ? forceOpen : !isBreakdownOpen;
    if (breakdownContent) {
      breakdownContent.style.display = isBreakdownOpen ? 'block' : 'none';
    }
    const arrow = document.querySelector('.breakdown-arrow');
    if (arrow) arrow.innerHTML = isBreakdownOpen ? '&#9652;' : '&#9662;';
  }

  toggleBreakdown?.addEventListener('click', () => openScoreBreakdown());
  btnDecomposeScore?.addEventListener('click', () => {
    switchTab('tabEvidence');
    openScoreBreakdown(true);
  });

  // ── Render Evidence List with Claim Types & Provenance ────────────────────
  function renderEvidenceList(evidence) {
    evCount.textContent = evidence.length;

    let filtered = evidence;
    if (activeEntityFilter) {
      filtered = evidence.filter(ev =>
        (ev.entity_ids || []).some(id => String(id).toLowerCase() === activeEntityFilter.toLowerCase())
      );
    }

    if (filtered.length === 0) {
      evidenceList.innerHTML = `
        <div class="empty-state">
          <p>${activeEntityFilter ? `No evidence items reference entity "${activeEntityFilter}".` : 'No evidence items recorded.'}</p>
        </div>
      `;
      return;
    }

    evidenceList.innerHTML = filtered.map(ev => {
      const prov = ev.provenance || {};
      const claimType = prov.claim_type || (ev.source === 'graph' ? 'observed_fact' : ev.source === 'external' ? 'model_score' : 'derived_inference');
      const claimTypeClass = `claim-type-${claimType}`;
      const claimTypeLabel = claimType.replace('_', ' ').toUpperCase();
      const severityClass = `ev-severity-${(ev.severity || 'medium').toLowerCase()}`;

      const entityChips = (ev.entity_ids || []).map(ent => `
        <span class="entity-chip" title="Click to highlight on graph" onclick="handleEntityClick('${escapeHtml(ent)}')">${escapeHtml(ent)}</span>
      `).join('');

      return `
        <div class="evidence-card ${severityClass}" id="evCard-${ev.evidence_id || ''}">
          <div class="ev-header-row">
            <div class="ev-badge-group">
              <span class="ev-id-badge">${escapeHtml(ev.evidence_id || 'EV-ITEM')}</span>
              <span class="claim-type-badge ${claimTypeClass}">${claimTypeLabel}</span>
              <span class="ev-source-badge ev-source-${(ev.source || 'graph').toLowerCase()}">${(ev.source || 'GRAPH').toUpperCase()}</span>
            </div>
            <span style="font-size:0.68rem; color:var(--text-muted); font-family:var(--font-mono); font-weight:600;">
              Conf: ${(Number(ev.confidence || 0.7) * 100).toFixed(0)}%
            </span>
          </div>

          <div class="ev-claim">${escapeHtml(ev.claim)}</div>

          <div class="ev-provenance" style="margin-top:6px;">
            <strong style="color:var(--text-muted);">Query/Ref:</strong> ${escapeHtml(ev.ref || '—')}
          </div>

          ${entityChips ? `
            <div class="ev-entities-row">
              <span style="font-size:0.65rem; color:var(--text-muted); line-height:20px;">Entities:</span>
              ${entityChips}
            </div>
          ` : ''}
        </div>
      `;
    }).join('');
  }

  // Global handler for clicking entity tags inside evidence cards
  window.handleEntityClick = (entityId) => {
    graphRenderer.highlightEntity(entityId);
  };

  btnClearEvFilter?.addEventListener('click', () => {
    activeEntityFilter = null;
    if (evFilterBar) evFilterBar.style.display = 'none';
    if (activeCaseData) renderEvidenceList(activeCaseData.evidence || []);
  });

  // ── P0: Uncertainty & Reassessment Lifecycle View ─────────────────────────
  function renderUncertaintyCycle(c) {
    const uncertainties = c.uncertainty || [];
    const requests = c.evidence_requests || [];
    uncCount.textContent = uncertainties.length;
    const pendingReq = requests.find(r => r.status === 'pending');

    const probBefore = c.risk_before ? Number(c.risk_before.fraud_probability || 0).toFixed(3) : '0.429';
    const probAfter = Number(c.fraud_probability || 0).toFixed(3);
    const initialActions = (c.nba_initial || []).map(a => a.action).join(', ') || 'CREATE_CASE, VERIFY_WITH_CUSTOMER';
    const finalActions = (c.nba_final || []).map(a => a.action).join(', ') || 'None';

    uncertaintyCycleContent.innerHTML = `
      <!-- Cycle Stage 1: The Open Ambiguity -->
      <div class="uncertainty-cycle-card">
        <div class="cycle-step-badge">1. Open Ambiguity & Policy Stopping Boundary</div>
        ${uncertainties.length > 0 ? uncertainties.map(u => `
          <div style="margin-top:6px;">
            <div class="unc-question" style="font-weight:700; color:var(--text-primary); font-size:0.82rem;">
              Q: ${escapeHtml(u.question || '')}
            </div>
            <div class="unc-impact" style="font-size:0.75rem; color:var(--text-secondary); margin-top:2px;">
              <strong>Impact:</strong> ${escapeHtml(u.impact || '')}
            </div>
            <div style="display:flex; justify-content:space-between; align-items:center; margin-top:6px;">
              <span class="claim-type-badge claim-type-model_score">Method: ${escapeHtml(u.resolution_method || 'Customer Validation')}</span>
              <span class="route-pill ${u.status === 'resolved' ? 'route-auto' : 'route-l1'}">
                ${(u.status || 'open').toUpperCase()}
              </span>
            </div>
          </div>
        `).join('') : '<p style="font-size:0.75rem; color:var(--text-muted);">No open ambiguity recorded.</p>'}
      </div>

      <!-- Cycle Stage 2: Targeted Evidence Request -->
      <div class="uncertainty-cycle-card">
        <div class="cycle-step-badge">2. Evidence Request (Selected by Information Value)</div>
        ${requests.length > 0 ? requests.map(req => `
          <div style="margin-top:6px;">
            <div style="display:flex; justify-content:space-between; font-size:0.72rem; margin-bottom:4px;">
              <span style="font-family:var(--font-mono); color:var(--accent-cyan); font-weight:700;">REQUEST TYPE: ${req.type || 'CUSTOMER_VALIDATION'}</span>
              <span class="route-pill ${req.origin === 'human_in_loop' ? 'route-l1' : 'route-auto'}" title="Origin of the response">
                ${(req.origin || 'simulated') === 'human_in_loop' ? 'HUMAN SUPPLIED' : 'SIMULATED'}
              </span>
            </div>
            ${req.info_value != null ? `
            <div style="font-size:0.68rem; color:var(--text-muted); margin-bottom:4px;">
              Information value: <strong style="color:var(--accent-cyan);">${Number(req.info_value).toFixed(2)}</strong>
              ${req.alternatives_considered && req.alternatives_considered.length ? `
                &nbsp;|&nbsp; Alternatives: ${req.alternatives_considered.map(a => `${a.type} (${Number(a.info_value).toFixed(2)})`).join(', ')}` : ''}
            </div>
            <div style="font-size:0.68rem; color:var(--text-secondary); margin-bottom:4px; font-style:italic;">${escapeHtml(req.decision_relevance || '')}</div>` : ''}
            ${req.status === 'pending' ? `
            <div style="background:var(--bg-input); padding:10px; border-radius:6px; border:1px solid var(--accent-amber);">
              <div style="color:var(--accent-amber); font-weight:700; font-size:0.7rem; text-transform:uppercase; margin-bottom:6px;">&#9203; Awaiting evidence — agent paused (MORE_EVIDENCE_REQUIRED)</div>
              <div style="font-size:0.72rem; color:var(--text-secondary); margin-bottom:6px;"><strong>Question:</strong> ${escapeHtml(req.question || 'Did you make this transaction?')}</div>
              <div class="approval-actions" style="display:flex; gap:6px; flex-wrap:wrap;">
                <input id="evResponseInput" type="text" placeholder="Paste the customer / step-up / analyst response…" style="flex:1; min-width:200px; padding:6px 8px; border-radius:6px; border:1px solid var(--border-subtle); background:var(--bg-input); color:var(--text-primary); font-size:0.72rem;">
                <button class="btn-approve" id="btnSubmitEvidence">Submit Response</button>
              </div>
              <div style="margin-top:6px; display:flex; gap:6px; flex-wrap:wrap;">
                <button class="btn-subtle" style="font-size:0.65rem; padding:4px 8px;" onclick="window._quickEvidence('Customer states they did not make these purchases and still has the card in their possession.')">Simulate: denied</button>
                <button class="btn-subtle" style="font-size:0.65rem; padding:4px 8px;" onclick="window._quickEvidence('Customer confirms they made this purchase while traveling.')">Simulate: confirmed</button>
                <button class="btn-subtle" style="font-size:0.65rem; padding:4px 8px;" onclick="window._quickEvidence('No response received within the 24-hour window.')">Simulate: no reply</button>
                <button class="btn-subtle" style="font-size:0.65rem; padding:4px 8px;" onclick="window._quickEvidence('Step-up authentication failed: device not recognized by the cardholder.')">Simulate: step-up failed</button>
              </div>
            </div>` : `
            <div style="background:var(--bg-input); padding:8px 10px; border-radius:6px; font-size:0.75rem; border:1px solid var(--border-subtle);">
              <div style="color:var(--text-muted); font-size:0.68rem; text-transform:uppercase; font-weight:700;">Response Received:</div>
              <div style="color:var(--accent-emerald); font-weight:600; margin-top:2px;">&ldquo;${escapeHtml(req.assumed_response || req.response || '')}&rdquo;</div>
            </div>`}
          </div>
        `).join('') : '<p style="font-size:0.75rem; color:var(--text-muted);">No additional evidence requested: no unrequested evidence would materially change the decision.</p>'}
      </div>

      <!-- Cycle Stage 3: Reassessment Delta & Resolution Impact -->
      <div class="uncertainty-cycle-card">
        <div class="cycle-step-badge">3. Reassessment Delta & Decision Shift</div>
        <div class="reassessment-delta-box">
          <div class="delta-metrics-row">
            <div class="delta-stat">
              <div class="delta-label">Fraud Probability Shift</div>
              <div class="delta-values">
                <span>${probBefore}</span>
                <span class="delta-arrow">&rarr;</span>
                <span style="color:${Number(probAfter) >= 0.75 ? 'var(--accent-rose)' : Number(probAfter) >= 0.35 ? 'var(--accent-amber)' : 'var(--accent-emerald)'};">${probAfter}</span>
              </div>
            </div>
            <div class="delta-stat">
              <div class="delta-label">Policy Governance Verdict</div>
              <div class="delta-values" style="font-size:0.78rem;">
                <span style="text-transform:uppercase;">${c.risk_before ? (c.risk_before.risk_level || 'MEDIUM') : 'MEDIUM'}</span>
                <span class="delta-arrow">&rarr;</span>
                <span style="color:var(--accent-cyan); text-transform:uppercase;">${c.risk_level || 'MEDIUM'}</span>
              </div>
            </div>
          </div>

          <div style="font-size:0.72rem; color:var(--text-secondary); margin-top:8px;">
            <strong style="color:var(--text-primary);">Action Set Delta:</strong>
            <div style="font-family:var(--font-mono); margin-top:2px; color:var(--text-muted); font-size:0.68rem;">Initial: ${escapeHtml(initialActions)}</div>
            <div style="font-family:var(--font-mono); margin-top:1px; color:var(--accent-emerald); font-size:0.68rem;">Final: &nbsp;${escapeHtml(finalActions)}</div>
          </div>

          <div class="resolution-impact-banner">
            <strong>Resolution Impact:</strong> ${escapeHtml(c.nba_what_changed || (uncertainties[0] && uncertainties[0].resolution_impact) || 'Targeted evidence removed ambiguity; adjusted policy constraints.')}
          </div>
        </div>
      </div>
    `;
  }

  // ── P1: Governed NBA & Policy Matrix Console ──────────────────────────────
  function renderNbaGovernance(c) {
    const finalNba = c.nba_final || [];
    const approvals = c.approvals || [];
    const pendingApprovals = approvals.filter(a => a.status === 'pending');
    aprCount.textContent = pendingApprovals.length;

    if (finalNba.length === 0) {
      nbaGovernanceContent.innerHTML = `
        <div class="empty-state">
          <p>No actions recommended for this case.</p>
        </div>
      `;
      return;
    }

    nbaGovernanceContent.innerHTML = finalNba.map(act => {
      const route = (act.route || 'auto').toLowerCase();
      const isCritical = act.action === 'BLOCK_CARD' || act.action === 'BLOCK_ALL_CARDS' || act.action === 'FILE_REPORT';
      const isElevated = act.action === 'DECLINE_TRANSACTION' || act.action === 'ESCALATE_TO_ANALYST';
      const cardClass = isCritical ? 'action-critical' : isElevated ? 'action-elevated' : 'action-standard';

      // Find matching approval record if any
      const apr = approvals.find(a => a.action === act.action);

      // Alternatives rejected (counterfactuals)
      const rejectedList = (act.alternatives_rejected || []).map(r => `
        <div class="alt-item">&bull; ${escapeHtml(r)}</div>
      `).join('');

      // Supporting evidence ID chips
      const evChips = (act.evidence_ids || []).map(id => `
        <span class="entity-chip" onclick="handleEvidenceJump('${escapeHtml(id)}')" title="Jump to evidence item">${escapeHtml(id)}</span>
      `).join('');

      return `
        <div class="action-card ${cardClass}">
          <div class="action-header-row">
            <span class="action-name-title">${act.action}</span>
            <span class="route-pill route-${route}">
              ${route === 'auto' ? 'AUTO-EXECUTE' : route === 'l1' ? 'L1 ANALYST' : 'L2 COMPLIANCE'}
            </span>
          </div>

          <div class="action-reason">
            <strong style="color:var(--text-secondary);">Policy Rule:</strong> ${escapeHtml(act.reason || '')}
          </div>

          ${act.expected_impact ? `
            <div class="expected-impact-box">
              <strong>Expected Operational Impact:</strong> ${escapeHtml(act.expected_impact)}
            </div>
          ` : ''}

          ${rejectedList ? `
            <div class="alternatives-box">
              <div class="alternatives-title">Counterfactuals (Alternatives Rejected):</div>
              ${rejectedList}
            </div>
          ` : ''}

          ${evChips ? `
            <div class="evidence-ref-group">
              <span>Supporting Evidence:</span>
              ${evChips}
            </div>
          ` : ''}

          ${apr ? `
            <div style="border-top:1px solid var(--border-subtle); padding-top:8px; margin-top:8px;">
              <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-size:0.7rem; color:var(--text-muted);">
                  Status: <strong style="color:${apr.status === 'approved' ? 'var(--accent-emerald)' : apr.status === 'rejected' ? 'var(--accent-rose)' : 'var(--accent-amber)'}">${apr.status.toUpperCase()}</strong>
                </span>
                ${apr.status === 'pending' ? `
                  <div class="approval-actions" style="margin:0;">
                    <button class="btn-approve" onclick="handleApprovalDecision('${c.case_id}', '${apr.approval_id}', 'approved')">Approve Action</button>
                    <button class="btn-reject" onclick="handleApprovalDecision('${c.case_id}', '${apr.approval_id}', 'rejected')">Reject Action</button>
                  </div>
                ` : `
                  <span style="font-size:0.65rem; color:var(--text-muted); font-family:var(--font-mono);">
                    Decided by: ${apr.decided_by || 'Analyst'}
                  </span>
                `}
              </div>
            </div>
          ` : ''}
        </div>
      `;
    }).join('');
  }

  window.handleEvidenceJump = (evidenceId) => {
    switchTab('tabEvidence');
    const targetEl = document.getElementById(`evCard-${evidenceId}`);
    if (targetEl) {
      targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
      targetEl.classList.add('highlighted');
      setTimeout(() => targetEl.classList.remove('highlighted'), 2500);
    }
  };

  // ── Render Case Memory & SAR ──────────────────────────────────────────────
  function renderPersistence(c) {
    const sar = c.sar || {};
    persistenceContent.innerHTML = `
      <div class="persistence-box">
        <div class="persistence-header">
          <span style="font-weight:700; font-size:0.8rem;">Durable TigerGraph Memory Persistence</span>
          <span class="route-pill ${c.written_to_graph ? 'route-auto' : 'route-l1'}">
            ${c.written_to_graph ? 'WRITTEN TO GRAPH' : 'LOCAL CACHE'}
          </span>
        </div>
        <div style="font-family:var(--font-mono); font-size:0.75rem; color:var(--accent-cyan); margin-bottom:6px;">
          Vertex ID: ${escapeHtml(c.graph_case_id || `CASE-2016-${c.case_id}`)}
        </div>
        <div style="font-size:0.75rem; color:var(--text-secondary); margin-bottom:8px;">
          <strong>Graph State:</strong> Vertex upserted into 'fraud_investigation' graph with IC_ON_CARD, IC_FOR_CUSTOMER, and IC_INVOLVES edges.
        </div>
        <div style="font-size:0.75rem; color:var(--text-secondary); line-height:1.45;">
          <strong>Executive Summary:</strong> ${escapeHtml(c.summary || 'Investigation completed successfully.')}
        </div>
      </div>

      <div class="persistence-box">
        <div class="persistence-header">
          <span style="font-weight:700; font-size:0.8rem;">FinCEN Suspicious Activity Report (SAR)</span>
          <span class="route-pill ${sar.file ? 'route-l2' : 'route-auto'}">
            ${sar.file ? 'SAR FILING REQUIRED' : 'NO SAR REQUIRED'}
          </span>
        </div>
        ${sar.file ? `
          <div style="font-size:0.75rem; color:var(--text-secondary); margin-bottom:8px;">
            <strong>Filing Justification:</strong> ${escapeHtml(sar.reason || 'Policy §4 regulatory disclosure threshold met')}
          </div>
          <div class="sar-narrative-box">${escapeHtml(sar.narrative || 'FinCEN SAR narrative generated.')}</div>
        ` : `
          <div style="font-size:0.75rem; color:var(--text-muted); line-height:1.4;">
            Threshold for FinCEN reporting not met (financial exposure is under $2,000 threshold without cross-entity syndicate indicators).
          </div>
        `}
      </div>
    `;
  }

  // ── P1: Interactive Graph Node Inspector Integration ──────────────────────
  graphRenderer.onNodeSelected = (node) => {
    if (!node) {
      if (graphInspector) graphInspector.style.display = 'none';
      return;
    }

    if (graphInspector) {
      graphInspector.style.display = 'block';
      inspNodeType.textContent = node.type.toUpperCase();
      inspNodeId.textContent = node.id;
      inspNodeRelevance.textContent = (node.metadata && node.metadata.relevance)
        ? node.metadata.relevance
        : `Investigative entity in case graph (${node.type}).`;

      // Build metadata items
      if (inspNodeMeta) {
        const meta = node.metadata || {};
        const items = [];
        if (meta.amount != null) items.push(`Amount: $${Number(meta.amount).toFixed(2)}`);
        if (meta.risk_score != null) items.push(`Score: ${Number(meta.risk_score).toFixed(2)}`);
        if (meta.status) items.push(`Status: ${meta.status}`);
        if (meta.verdict) items.push(`Verdict: ${meta.verdict}`);
        if (meta.role) items.push(`Role: ${meta.role}`);
        inspNodeMeta.innerHTML = items.map(it => `<span class="insp-meta-item">${escapeHtml(it)}</span>`).join('');
      }

      // Filter button
      if (btnFilterEvidence) {
        btnFilterEvidence.onclick = () => {
          activeEntityFilter = node.id;
          if (evFilterBar) {
            evFilterBar.style.display = 'flex';
            filterEntityName.textContent = `${node.type}: ${node.id}`;
          }
          switchTab('tabEvidence');
          if (activeCaseData) renderEvidenceList(activeCaseData.evidence || []);
        };
      }
    }
  };

  btnCloseInspector?.addEventListener('click', () => {
    if (graphInspector) graphInspector.style.display = 'none';
    graphRenderer.selectedNode = null;
    graphRenderer.render();
  });

  // ── Handle Live Investigation Execution ───────────────────────────────────
  btnInvestigate.addEventListener('click', async () => {
    if (!activeCaseId || btnInvestigate.disabled) return;

    btnInvestigate.disabled = true;
    btnInvestigate.innerHTML = '<div class="spinner" style="width:16px; height:16px; border-width:2px; margin:0;"></div> <span>Investigating...</span>';

    try {
      showToast(`Initiating live TigerGraph investigation for ${activeCaseId}...`, 'info');

      // The backend planner is genuinely querying TigerGraph right now —
      // stage display advances only when real data confirms it.
      setTimelineStep(2, 'active');

      // Call backend API (real execution; no scripted timers)
      const answer = await API.runInvestigation(activeCaseId);

      // Reload investigation data after execution completes
      const [fullData, graphData] = await Promise.all([
        API.getInvestigationFull(activeCaseId),
        API.getInvestigationGraph(activeCaseId)
      ]);

      renderInvestigation(fullData);
      activeGraphData = graphData;
      if (graphData) {
        graphRenderer.setData(graphData);
      }

      const pendingReq = (fullData.evidence_requests || []).find(r => r.status === 'pending');
      if (pendingReq) {
        switchTab('tabUncertainty');
        showToast(`Agent PAUSED: requesting ${String(pendingReq.type).replace(/_/g, ' ')} (info value ${Number(pendingReq.info_value || 0).toFixed(2)}). Submit the response in the Uncertainty tab.`, 'info', 9000);
      } else {
        showToast(`Investigation for ${activeCaseId} complete! Verdict: ${(fullData.verdict || 'uncertain').toUpperCase()}`, 'success');
      }
    } catch (err) {
      console.error('Investigation error:', err);
      showToast(`Investigation failed: ${err.message}`, 'error', 6000);
    } finally {
      btnInvestigate.disabled = false;
      btnInvestigate.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
        <span>Start Live Investigation</span>
      `;
    }
  });

  // ── Human-in-the-Loop Evidence Submission ───────────────────────────────
  // Delegated handler: the Uncertainty tab re-renders dynamically, so we bind
  // at document level for the submit button and quick-fill buttons.
  document.addEventListener('click', async (e) => {
    // Quick-fill buttons place a canned response into the input
    if (e.target && e.target.closest && e.target.closest('.btn-subtle[onclick*="_quickEvidence"]')) {
      return; // handled by the inline onclick
    }
    if (e.target && e.target.id === 'btnSubmitEvidence') {
      const input = document.getElementById('evResponseInput');
      if (!input || !input.value.trim()) {
        showToast('Enter (or quick-fill) a response before submitting.', 'error');
        return;
      }
      const btn = e.target;
      btn.disabled = true;
      btn.textContent = 'Submitting…';
      try {
        showToast('Response received — agent resuming (reassessment → NBA → policy)…', 'info');
        await API.submitEvidence(activeCaseId, '', input.value.trim());
        const [fullData, graphData] = await Promise.all([
          API.getInvestigationFull(activeCaseId),
          API.getInvestigationGraph(activeCaseId)
        ]);
        renderInvestigation(fullData);
        if (graphData) graphRenderer.setData(graphData);
        showToast(`Reassessment complete. Verdict: ${(fullData.verdict || 'uncertain').toUpperCase()}, probability ${Number(fullData.fraud_probability || 0).toFixed(3)}`, 'success');
      } catch (err) {
        console.error('Evidence submission error:', err);
        showToast(`Evidence submission failed: ${err.message}`, 'error', 6000);
      } finally {
        btn.disabled = false;
        btn.textContent = 'Submit Response';
      }
    }
  });

  window._quickEvidence = (text) => {
    const input = document.getElementById('evResponseInput');
    if (input) {
      input.value = text;
      input.focus();
    }
  };

  // ── Global Approval Decision Handler ──────────────────────────────────────
  window.handleApprovalDecision = async (caseId, approvalId, decision) => {
    try {
      await API.decideApproval(caseId, approvalId, decision, 'Analyst-Judge-01');
      showToast(`Action ${decision === 'approved' ? 'APPROVED' : 'REJECTED'} successfully under policy audit.`, 'success');

      // Refresh case data
      const fullData = await API.getInvestigationFull(caseId);
      if (fullData) renderInvestigation(fullData);
    } catch (e) {
      console.error('Approval error:', e);
      showToast(`Approval error: ${e.message}`, 'error');
    }
  };

  // ── Tab Navigation Handling ───────────────────────────────────────────────
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

  // ── Graph Controls ────────────────────────────────────────────────────────
  document.getElementById('btnZoomIn')?.addEventListener('click', () => graphRenderer.zoomIn());
  document.getElementById('btnZoomOut')?.addEventListener('click', () => graphRenderer.zoomOut());
  document.getElementById('btnResetView')?.addEventListener('click', () => graphRenderer.resetView());

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // ── Live Benchmark Tab ────────────────────────────────────────────────────
  async function loadBenchmarkTab() {
    const elCompleted = document.getElementById('benchCompleted');
    if (!elCompleted) return;
    try {
      const [report, checkpoints] = await Promise.all([
        API.getBenchmarkReport().catch(() => null),
        API.getBenchmarkCheckpoints().catch(() => null),
      ]);

      if (report) {
        elCompleted.textContent = `${report.completed} / ${report.total_cases}`;
        const elapsed = document.getElementById('benchElapsed');
        if (elapsed) elapsed.textContent = `completed in ${report.elapsed_s}s`;
        const note = document.getElementById('benchRunNote');
        if (note) note.textContent = `Benchmark artifacts loaded live from cases/_benchmark_report.json (${report.completed} cases, ${report.failed} failures).`;

        const table = document.getElementById('benchCaseTable');
        if (table) {
          const rows = (report.results || []).map(r => `
            <tr>
              <td style="padding:3px 6px; font-family:var(--font-mono);">${escapeHtml(r.case_id)}</td>
              <td style="padding:3px 6px; color:${r.verdict === 'fraud' ? 'var(--accent-rose)' : r.verdict === 'legitimate' ? 'var(--accent-emerald)' : 'var(--accent-amber)'};">${escapeHtml(r.verdict)}</td>
              <td style="padding:3px 6px;">${Number(r.fraud_probability).toFixed(2)}</td>
              <td style="padding:3px 6px; font-size:0.65rem;">${escapeHtml(r.pattern)}</td>
              <td style="padding:3px 6px; text-align:center;">${r.evidence_requests ?? '—'}</td>
              <td style="padding:3px 6px; text-align:center;">${r.tool_calls}</td>
              <td style="padding:3px 6px; text-align:center;">${r.sar_filed ? 'SAR' : '—'}</td>
            </tr>`).join('');
          table.innerHTML = `
            <table style="width:100%; border-collapse:collapse; font-size:0.68rem; color:var(--text-secondary);">
              <thead><tr style="color:var(--text-muted); text-transform:uppercase; font-size:0.6rem;">
                <th style="text-align:left; padding:3px 6px;">Case</th><th style="text-align:left; padding:3px 6px;">Verdict</th>
                <th style="text-align:left; padding:3px 6px;">P(fraud)</th><th style="text-align:left; padding:3px 6px;">Pattern</th>
                <th style="padding:3px 6px;">ERs</th><th style="padding:3px 6px;">Tools</th><th style="padding:3px 6px;">SAR</th>
              </tr></thead><tbody>${rows}</tbody></table>`;
        }
      } else if (elCompleted) {
        elCompleted.textContent = '—';
      }

      if (checkpoints) {
        const el = document.getElementById('benchCheckpoints');
        if (el) {
          el.textContent = `${checkpoints.checkpoint_pass} / ${checkpoints.checkpoint_total}`;
        }
      } else {
        const el = document.getElementById('benchCheckpoints');
        if (el) el.textContent = 'run benchmark';
      }
    } catch (e) {
      console.warn('Benchmark tab load failed:', e);
    }
  }

  // ── Initial Boot ──────────────────────────────────────────────────────────
  await checkHealth();
  await loadCasePack();
  loadBenchmarkTab();
});
