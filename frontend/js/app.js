/**
 * FraudLens Command Center — Main Application Controller
 * Agentic Fraud Investigation Platform on TigerGraph
 * The model predicts. TigerGraph proves.
 */

document.addEventListener('DOMContentLoaded', async () => {
  // ── Global Application State ─────────────────────────────────────────────
  let activeView = 'queue';
  let activeCaseId = 'CASE-001';
  let casePackList = [];
  let investigationsCache = new Map();
  let activeCaseFullData = null;
  let activeGraphData = null;
  let activeEntityFilter = null;
  let approvalsAll = [];
  let lastHealthData = null;

  // Queue View Filters
  let queueFilterStatus = 'all';
  let queueFilterVerdict = 'all';
  let queueFilterTrigger = 'all';
  let queueSearchQuery = '';

  // Approvals View Filter
  let approvalsFilterStatus = 'pending';

  // Graph Renderers (one for Live view, one for Case File view)
  const liveGraphRenderer = new GraphRenderer('graphCanvas');
  const caseGraphRenderer = new GraphRenderer('caseGraphCanvas');

  // Wire Node Selection Inspector on both graphs
  const setupNodeInspector = (renderer) => {
    renderer.onNodeSelected = (node) => {
      const inspector = document.getElementById('graphInspector');
      if (!inspector) return;

      if (!node) {
        inspector.style.display = 'none';
        return;
      }

      inspector.style.display = 'block';
      const typePill = document.getElementById('inspNodeType');
      const idText = document.getElementById('inspNodeId');
      const relevanceDesc = document.getElementById('inspNodeRelevance');
      const metaGrid = document.getElementById('inspNodeMeta');

      const parts = renderer.getNodeDisplayParts(node);
      if (typePill) typePill.textContent = parts.typeName;
      if (idText) idText.textContent = parts.idName;
      if (relevanceDesc) {
        relevanceDesc.textContent = node.metadata?.relevance || `${node.type} entity participating in investigation context.`;
      }

      if (metaGrid) {
        metaGrid.innerHTML = '';
        const meta = node.metadata || {};
        const entries = Object.entries(meta).filter(([k]) => !['role', 'relevance', 'evidence_ids'].includes(k));
        if (entries.length === 0) {
          metaGrid.innerHTML = `<div class="insp-meta-cell" style="grid-column: span 2;"><span class="insp-meta-k">Entity Type</span><div class="insp-meta-v">${escapeHtml(node.type)}</div></div>`;
        } else {
          entries.slice(0, 6).forEach(([k, v]) => {
            const cell = document.createElement('div');
            cell.className = 'insp-meta-cell';
            const displayVal = typeof v === 'object' ? JSON.stringify(v) : String(v);
            cell.innerHTML = `
              <span class="insp-meta-k">${escapeHtml(k.replace(/_/g, ' '))}</span>
              <div class="insp-meta-v" title="${escapeHtml(displayVal)}">${escapeHtml(displayVal)}</div>
            `;
            metaGrid.appendChild(cell);
          });
        }
      }

      const btnFilter = document.getElementById('btnFilterEvidence');
      if (btnFilter) {
        btnFilter.onclick = () => {
          filterEvidenceByEntity(node.id, parts.idName);
          switchView('case');
          switchCaseTab('casetabEvidence');
        };
      }
    };
  };

  setupNodeInspector(liveGraphRenderer);
  setupNodeInspector(caseGraphRenderer);

  // Inspector Close
  document.getElementById('btnCloseInspector')?.addEventListener('click', () => {
    const insp = document.getElementById('graphInspector');
    if (insp) insp.style.display = 'none';
    liveGraphRenderer.selectedNode = null;
    caseGraphRenderer.selectedNode = null;
    liveGraphRenderer.render();
    caseGraphRenderer.render();
  });

  // ── Nav Rail & View Switching ─────────────────────────────────────────────
  function switchView(viewName) {
    activeView = viewName;

    // Update Nav Rail buttons
    document.querySelectorAll('.nav-rail-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.view === viewName);
    });

    // Update View Containers
    document.querySelectorAll('.app-view').forEach(view => {
      view.classList.remove('active');
    });

    const targetView = document.getElementById(`view${viewName.charAt(0).toUpperCase() + viewName.slice(1)}`);
    if (targetView) {
      targetView.classList.add('active');
    }

    // View-specific initialization
    if (viewName === 'queue') {
      renderQueueTable();
    } else if (viewName === 'live') {
      liveGraphRenderer.resize();
    } else if (viewName === 'case') {
      caseGraphRenderer.resize();
    } else if (viewName === 'approvals') {
      loadApprovalsInbox();
    } else if (viewName === 'insights') {
      loadInsights();
    }

    // Keep hash updated
    try {
      history.replaceState(null, '', `#${viewName}`);
    } catch {}
  }
  window.switchView = switchView;

  document.querySelectorAll('.nav-rail-btn').forEach(btn => {
    btn.addEventListener('click', () => switchView(btn.dataset.view));
  });

  document.getElementById('navBrandLogo')?.addEventListener('click', () => switchView('queue'));

  // ── Case File Sub-Navigation Tabs ─────────────────────────────────────────
  function switchCaseTab(tabId) {
    document.querySelectorAll('.case-subnav-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.casetab === tabId);
      b.setAttribute('aria-selected', b.dataset.casetab === tabId ? 'true' : 'false');
    });

    document.querySelectorAll('.case-tab-pane').forEach(p => {
      p.classList.toggle('active', p.id === tabId);
    });

    if (tabId === 'casetabGraph') {
      setTimeout(() => caseGraphRenderer.resize(), 50);
    }
  }
  window.switchCaseTab = switchCaseTab;

  document.querySelectorAll('.case-subnav-btn').forEach(btn => {
    btn.addEventListener('click', () => switchCaseTab(btn.dataset.casetab));
  });

  // Backwards compatibility alias for tests & scripts
  window.switchTabTo = function(legacyTabId) {
    switchView('case');
    const mapping = {
      'tabEvidence': 'casetabEvidence',
      'tabUncertainty': 'casetabUncertainty',
      'tabNba': 'casetabNba',
      'tabPersistence': 'casetabSar',
      'tabBenchmark': 'casetabOverview'
    };
    switchCaseTab(mapping[legacyTabId] || 'casetabOverview');
  };

  // ── Toast Notification System ─────────────────────────────────────────────
  function showToast(message, type = 'info', duration = 3500) {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
      <span>${escapeHtml(message)}</span>
      <button class="toast-close" title="Dismiss">&times;</button>
    `;

    toast.querySelector('.toast-close').addEventListener('click', () => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(10px)';
      setTimeout(() => toast.remove(), 180);
    });

    container.appendChild(toast);
    setTimeout(() => {
      if (toast.parentElement) {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
        setTimeout(() => toast.remove(), 180);
      }
    }, duration);
  }
  window.showToast = showToast;

  // ── System Health Diagnostics ─────────────────────────────────────────────
  async function checkHealth() {
    try {
      const h = await API.getHealth();
      lastHealthData = h;
      const isTgHealthy = h.graph && (h.graph.tigergraph === 'healthy' || h.graph.local === 'healthy');
      const dot = document.getElementById('tgStatusDot');
      const text = document.getElementById('tgStatusText');

      if (dot) dot.className = 'status-dot ' + (isTgHealthy ? 'healthy' : 'degraded');
      if (text) {
        if (h.graph?.tigergraph === 'healthy') {
          text.textContent = 'TigerGraph Savanna (MCP)';
        } else {
          text.textContent = 'TigerGraph Local Mirror';
        }
      }
    } catch (e) {
      const dot = document.getElementById('tgStatusDot');
      const text = document.getElementById('tgStatusText');
      if (dot) dot.className = 'status-dot degraded';
      if (text) text.textContent = 'TigerGraph Mirror';
    }
  }

  function openHealthModal() {
    const modal = document.getElementById('healthModal');
    if (!modal) return;
    const h = lastHealthData || {};
    const tgStatus = document.getElementById('diagTgStatus');
    const dbStatus = document.getElementById('diagDbStatus');
    const llmProvider = document.getElementById('diagLlmProvider');

    if (tgStatus) tgStatus.textContent = h.graph ? (h.graph.tigergraph || h.graph.local || 'Savanna Cloud / Local GSQL') : 'Active';
    if (dbStatus) dbStatus.textContent = h.app_db || 'healthy';
    if (llmProvider) llmProvider.textContent = h.llm_provider || 'Deterministic / Claude';

    modal.style.display = 'flex';
  }

  document.getElementById('btnTgStatus')?.addEventListener('click', openHealthModal);
  document.getElementById('btnDbStatus')?.addEventListener('click', openHealthModal);
  document.getElementById('btnCloseHealthModal')?.addEventListener('click', () => {
    const modal = document.getElementById('healthModal');
    if (modal) modal.style.display = 'none';
  });
  document.getElementById('healthModal')?.addEventListener('click', e => {
    if (e.target.id === 'healthModal') e.target.style.display = 'none';
  });

  // ── Load All Cases & Initial Data ─────────────────────────────────────────
  async function loadInitialData() {
    try {
      const cases = await API.getCases();
      casePackList = cases || [];

      // Populate Case Select Dropdown in Command Bar
      const caseSelect = document.getElementById('caseSelect');
      if (caseSelect) {
        caseSelect.innerHTML = '';
        casePackList.forEach(c => {
          const opt = document.createElement('option');
          opt.value = c.case_id;
          opt.textContent = `${c.case_id} — ${formatTitle(c.trigger_type)} (${c.flagged_txn_id})`;
          opt.dataset.case = JSON.stringify(c);
          caseSelect.appendChild(opt);
        });

        caseSelect.addEventListener('change', () => {
          selectCase(caseSelect.value);
        });
      }

      // Pre-fetch investigations to populate table & counts
      await refreshAllInvestigations();

      // Check URL hash for initial view
      const hash = window.location.hash.replace(/^#/, '');
      if (['queue', 'live', 'case', 'approvals', 'insights'].includes(hash)) {
        switchView(hash);
      } else {
        switchView('queue');
      }

      // Load initial active case
      if (casePackList.length > 0) {
        await selectCase(casePackList[0].case_id);
      }
    } catch (err) {
      console.error('Failed to load initial data:', err);
      showToast('Could not load case pack triggers from API.', 'error');
    }
  }

  async function refreshAllInvestigations() {
    try {
      const list = await API.getInvestigations?.(100, 0) || [];
      investigationsCache.clear();
      for (const item of list) {
        investigationsCache.set(item.case_id, item);
      }
    } catch {
      // Fallback: investigations loaded on demand
    }
    await updateApprovalsCount();
    renderQueueTable();
  }

  async function updateApprovalsCount() {
    try {
      const approvals = await API.getAllApprovals?.() || [];
      approvalsAll = approvals;
      const pendingCount = approvals.filter(a => a.status === 'pending').length;

      const badge = document.getElementById('navApprovalsBadge');
      if (badge) {
        if (pendingCount > 0) {
          badge.textContent = pendingCount;
          badge.style.display = 'block';
        } else {
          badge.style.display = 'none';
        }
      }

      const queuePendingVal = document.getElementById('queuePendingApprovalsVal');
      if (queuePendingVal) queuePendingVal.textContent = pendingCount;

      const countAprPending = document.getElementById('countAprPending');
      if (countAprPending) countAprPending.textContent = pendingCount;
    } catch (e) {
      console.warn('Approvals refresh notice:', e);
    }
  }

  // ── Case Selection & Loading ──────────────────────────────────────────────
  async function selectCase(caseId) {
    activeCaseId = caseId;
    activeEntityFilter = null;

    const caseSelect = document.getElementById('caseSelect');
    if (caseSelect) caseSelect.value = caseId;

    // Load trigger meta from case pack
    const triggerData = casePackList.find(c => c.case_id === caseId) || {};

    // Update Live View Trigger Context Card
    const triggerTypeBadge = document.getElementById('triggerTypeBadge');
    if (triggerTypeBadge) triggerTypeBadge.textContent = formatTitle(triggerData.trigger_type || 'Risk Score');
    const triggerText = document.getElementById('triggerText');
    if (triggerText) triggerText.textContent = triggerData.trigger_text || 'No trigger alert text provided.';

    const metaTxnId = document.getElementById('metaTxnId');
    if (metaTxnId) metaTxnId.textContent = triggerData.flagged_txn_id || '—';
    const metaCardId = document.getElementById('metaCardId');
    if (metaCardId) metaCardId.textContent = triggerData.card_id || '—';
    const metaCustId = document.getElementById('metaCustId');
    if (metaCustId) metaCustId.textContent = triggerData.customer_id || '—';
    const metaRiskScore = document.getElementById('metaRiskScore');
    if (metaRiskScore) metaRiskScore.textContent = triggerData.risk_score != null ? Number(triggerData.risk_score).toFixed(2) : '—';

    // Update Case File Hero Elements
    const caseHeroId = document.getElementById('caseHeroId');
    if (caseHeroId) caseHeroId.textContent = caseId;
    const caseHeroTime = document.getElementById('caseHeroTime');
    if (caseHeroTime) caseHeroTime.textContent = triggerData.opened_at ? `Opened ${triggerData.opened_at}` : 'Opened recently';
    const caseHeroTriggerType = document.getElementById('caseHeroTriggerType');
    if (caseHeroTriggerType) caseHeroTriggerType.textContent = formatTitle(triggerData.trigger_type || 'Risk Score');
    const caseHeroNarrative = document.getElementById('caseHeroNarrative');
    if (caseHeroNarrative) caseHeroNarrative.textContent = triggerData.trigger_text || 'No trigger narrative.';

    // Fetch Full Investigation and Subgraph
    try {
      const [fullData, graphData] = await Promise.all([
        API.getInvestigationFull(caseId).catch(() => null),
        API.getInvestigationGraph(caseId).catch(() => null)
      ]);

      if (fullData) {
        activeCaseFullData = fullData;
        investigationsCache.set(caseId, fullData);
        renderInvestigationDossier(fullData);
      } else {
        renderUninvestigatedState(triggerData);
      }

      if (graphData) {
        activeGraphData = graphData;
        liveGraphRenderer.setData(graphData);
        caseGraphRenderer.setData(graphData);
      } else {
        liveGraphRenderer.setData({ nodes: [], links: [] });
        caseGraphRenderer.setData({ nodes: [], links: [] });
      }
    } catch (err) {
      console.warn('Error loading case data:', err);
    }
  }
  window.selectCase = selectCase;

  // ── Render Investigation Dossier (Case File & Live Views) ─────────────────
  function renderInvestigationDossier(data) {
    const c = data;
    const hasPendingEvidence = (c.evidence_requests || []).some(r => r.status === 'pending');
    const verdict = (c.verdict || 'uncertain').toLowerCase();

    // 1. Threat Header & Verdict
    const verdictBadges = [document.getElementById('verdictBadge'), document.getElementById('caseHeroVerdict')];
    verdictBadges.forEach(b => {
      if (!b) return;
      b.textContent = hasPendingEvidence ? 'AWAITING EVIDENCE' : verdict.toUpperCase();
      b.className = `verdict-badge verdict-${verdict} ${b.id === 'caseHeroVerdict' ? 'size-lg' : ''}`;
    });

    const statusBadge = document.getElementById('caseHeroStatus');
    if (statusBadge) {
      statusBadge.textContent = formatTitle(c.status || 'closed');
      statusBadge.className = `badge badge-status-${(c.status || 'closed').toLowerCase()}`;
    }

    // 2. Probability Meter
    const prob = Number(c.fraud_probability || 0);
    const probColor = prob >= 0.85 ? 'var(--fraud)' : prob >= 0.15 ? 'var(--unsure)' : 'var(--legit)';

    const probVal = document.getElementById('probVal');
    if (probVal) {
      probVal.textContent = prob.toFixed(3);
      probVal.style.color = probColor;
    }
    const caseHeroProb = document.getElementById('caseHeroProb');
    if (caseHeroProb) {
      caseHeroProb.textContent = prob.toFixed(3);
      caseHeroProb.style.color = probColor;
    }
    const probBar = document.getElementById('probBar');
    if (probBar) {
      probBar.style.width = `${Math.min(100, Math.max(2, prob * 100))}%`;
      probBar.style.backgroundColor = probColor;
    }

    // 3. Typology & Pattern
    const patternStr = formatTitle(c.pattern || 'Undocumented');
    const patternVal = document.getElementById('patternVal');
    if (patternVal) patternVal.textContent = patternStr;
    const caseHeroPattern = document.getElementById('caseHeroPattern');
    if (caseHeroPattern) caseHeroPattern.textContent = patternStr;

    // 4. Exposure
    const exposureAmt = Number(c.exposure_usd || 0);
    const exposureFormatted = formatMoney(exposureAmt);
    const exposureVal = document.getElementById('exposureVal');
    if (exposureVal) exposureVal.textContent = exposureFormatted;
    const caseHeroExposure = document.getElementById('caseHeroExposure');
    if (caseHeroExposure) caseHeroExposure.textContent = exposureFormatted;

    // 5. SAR Filing Status
    const sarData = c.sar || {};
    const sarStatusText = sarData.file ? 'File with FinCEN' : 'Not Required';
    const caseHeroSar = document.getElementById('caseHeroSar');
    if (caseHeroSar) {
      caseHeroSar.textContent = sarStatusText;
      caseHeroSar.style.color = sarData.file ? 'var(--tg-300)' : 'var(--ink-400)';
    }

    // 6. TigerGraph Case Memory
    const caseHeroGraphMemory = document.getElementById('caseHeroGraphMemory');
    if (caseHeroGraphMemory) {
      if (c.written_to_graph && c.graph_case_id) {
        caseHeroGraphMemory.innerHTML = `&check; ${escapeHtml(c.graph_case_id)}`;
        caseHeroGraphMemory.style.color = 'var(--legit)';
      } else {
        caseHeroGraphMemory.textContent = 'Not written to graph';
        caseHeroGraphMemory.style.color = 'var(--ink-400)';
      }
    }

    // 7. Case Summary & Stop Reason
    const caseSummaryText = document.getElementById('caseSummaryText');
    if (caseSummaryText) caseSummaryText.textContent = c.summary || 'Investigation concluded.';
    const caseStopReason = document.getElementById('caseStopReason');
    if (caseStopReason) caseStopReason.textContent = c.stop_reason ? `Stop: ${c.stop_reason}` : 'Stop: Defensible conclusion reached';

    const casePatternTitle = document.getElementById('casePatternTitle');
    if (casePatternTitle) casePatternTitle.textContent = `${patternStr} Typology`;
    const casePatternDesc = document.getElementById('casePatternDesc');
    if (casePatternDesc) casePatternDesc.textContent = c.pattern_description || 'Pattern identified through graph neighbor clustering and transaction sequence analysis.';

    // 8. Render Evidence Dossier
    renderEvidenceList(c.evidence || []);

    // 9. Render Noisy-OR Risk Channels
    renderRiskChannels(c);

    // 10. Render Decision Uncertainty & Evidence Gaps
    renderUncertaintyCycle(c);

    // 11. Render Governed NBAs
    renderNbaGovernance(c);

    // 12. Render SAR Document
    renderSarDocument(c);

    // 13. Render Audit Timeline
    renderAuditTimeline(c.case_id);

    // Update Stepper Progress
    setTimelineStep(hasPendingEvidence ? 7 : 11, 'completed');
  }

  function renderUninvestigatedState(triggerData) {
    const verdictBadges = [document.getElementById('verdictBadge'), document.getElementById('caseHeroVerdict')];
    verdictBadges.forEach(b => {
      if (!b) return;
      b.textContent = 'READY';
      b.className = 'verdict-badge verdict-ready size-lg';
    });

    const probVal = document.getElementById('probVal');
    if (probVal) probVal.textContent = '0.000';
    const caseHeroProb = document.getElementById('caseHeroProb');
    if (caseHeroProb) caseHeroProb.textContent = '0.000';
    const probBar = document.getElementById('probBar');
    if (probBar) probBar.style.width = '0%';

    const patternVal = document.getElementById('patternVal');
    if (patternVal) patternVal.textContent = '—';
    const caseHeroPattern = document.getElementById('caseHeroPattern');
    if (caseHeroPattern) caseHeroPattern.textContent = '—';

    const exposureVal = document.getElementById('exposureVal');
    if (exposureVal) exposureVal.textContent = '$0.00';
    const caseHeroExposure = document.getElementById('caseHeroExposure');
    if (caseHeroExposure) caseHeroExposure.textContent = '$0.00';

    const caseHeroSar = document.getElementById('caseHeroSar');
    if (caseHeroSar) caseHeroSar.textContent = 'Pending';
    const caseHeroGraphMemory = document.getElementById('caseHeroGraphMemory');
    if (caseHeroGraphMemory) caseHeroGraphMemory.textContent = 'Not yet investigated';

    const caseSummaryText = document.getElementById('caseSummaryText');
    if (caseSummaryText) caseSummaryText.textContent = 'Case not yet investigated. Click "Run Investigation" to trigger live TigerGraph agents.';

    renderEvidenceList([]);
    setTimelineStep(0, 'active');
  }

  // ── Render Evidence List with Re-prove & Entity Chips ─────────────────────
  function renderEvidenceList(evidenceItems) {
    const listEl = document.getElementById('evidenceList');
    const statsEl = document.getElementById('evHeaderStats');
    const evCountBadge = document.getElementById('evCount');

    if (evCountBadge) evCountBadge.textContent = evidenceItems.length;
    if (statsEl) {
      const reprovableCount = evidenceItems.filter(e => (e.ref || '').startsWith('query:')).length;
      statsEl.textContent = `${evidenceItems.length} claims • ${reprovableCount} re-provable on TigerGraph`;
    }

    if (!listEl) return;
    listEl.innerHTML = '';

    const filteredItems = activeEntityFilter
      ? evidenceItems.filter(e => (e.entity_ids || []).map(x => String(x).toLowerCase()).includes(activeEntityFilter.toLowerCase()))
      : evidenceItems;

    if (filteredItems.length === 0) {
      listEl.innerHTML = `
        <li style="padding: 24px; text-align: center; color: var(--ink-400);">
          ${activeEntityFilter ? `No evidence citing entity "${escapeHtml(activeEntityFilter)}".` : 'No evidence recorded yet.'}
        </li>
      `;
      return;
    }

    filteredItems.forEach((ev, idx) => {
      const li = document.createElement('li');
      li.className = 'evidence-row';

      const sourceClass = `source-${(ev.source || 'external').toLowerCase()}`;
      const sourceLabel = formatTitle(ev.source || 'external');

      // Check if reprovable
      const isReprovable = (ev.ref || '').startsWith('query:');

      // Build Entity Chips
      const entityChips = (ev.entity_ids || []).map(eid => `
        <span class="id-chip" data-entity-id="${escapeHtml(eid)}" title="Focus in graph">
          ${escapeHtml(eid)}
        </span>
      `).join('');

      li.innerHTML = `
        <div class="evidence-main">
          <div class="evidence-claim-line">
            <span class="source-chip ${sourceClass}">${escapeHtml(sourceLabel)}</span>
            <div class="evidence-claim-text">${escapeHtml(ev.claim || 'Evidence record')}</div>
          </div>
          ${ev.ref ? `
            <div class="evidence-meta-line">
              <span class="query-ref-box">${escapeHtml(ev.ref)}</span>
            </div>
          ` : ''}
          ${entityChips ? `
            <div class="evidence-entities-wrap">
              ${entityChips}
            </div>
          ` : ''}
        </div>
        <div>
          ${isReprovable ? `
            <button class="btn-reprove" data-ref="${escapeHtml(ev.ref)}" title="Re-run GSQL query on TigerGraph">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M10 2v7.527a2 2 0 0 1-.211.896L4.72 20.55a1 1 0 0 0 .9 1.45h12.76a1 1 0 0 0 .9-1.45l-5.069-10.127A2 2 0 0 1 14 9.527V2"></path><path d="M8.5 2h7"></path><path d="M7 16h10"></path></svg>
              <span>Re-prove</span>
            </button>
          ` : ''}
        </div>
      `;

      // Wire entity chips to graph highlight
      li.querySelectorAll('.id-chip').forEach(chip => {
        chip.addEventListener('click', () => {
          const eid = chip.dataset.entityId;
          caseGraphRenderer.highlightEntity(eid);
          liveGraphRenderer.highlightEntity(eid);
          switchCaseTab('casetabGraph');
        });
      });

      // Wire Re-prove button
      li.querySelector('.btn-reprove')?.addEventListener('click', (e) => {
        const refStr = e.currentTarget.dataset.ref;
        executeReprove(refStr);
      });

      listEl.appendChild(li);
    });
  }

  function filterEvidenceByEntity(entityId, displayName) {
    activeEntityFilter = entityId;
    const filterBar = document.getElementById('evFilterBar');
    const nameEl = document.getElementById('filterEntityName');
    if (filterBar) filterBar.style.display = 'flex';
    if (nameEl) nameEl.textContent = displayName || entityId;

    if (activeCaseFullData) {
      renderEvidenceList(activeCaseFullData.evidence || []);
    }
  }

  document.getElementById('btnClearEvFilter')?.addEventListener('click', () => {
    activeEntityFilter = null;
    const filterBar = document.getElementById('evFilterBar');
    if (filterBar) filterBar.style.display = 'none';
    if (activeCaseFullData) {
      renderEvidenceList(activeCaseFullData.evidence || []);
    }
  });

  // ── Re-prove Interactive Query Modal Execution ────────────────────────────
  async function executeReprove(refStr) {
    const modal = document.getElementById('reproveModal');
    if (!modal) return;

    modal.style.display = 'flex';
    const queryNameEl = document.getElementById('reproveQueryName');
    const latencyEl = document.getElementById('reproveLatency');
    const rowsEl = document.getElementById('reproveRows');
    const viaBadge = document.getElementById('reproveViaBadge');
    const noteEl = document.getElementById('reproveNoteText');
    const thead = document.getElementById('reproveTableHeadRow');
    const tbody = document.getElementById('reproveTableBody');

    if (queryNameEl) queryNameEl.textContent = refStr;
    if (latencyEl) latencyEl.innerHTML = `...<span style="font-size:11px; font-weight:400; color:var(--ink-400);"> ms</span>`;
    if (rowsEl) rowsEl.textContent = '...';
    if (thead) thead.innerHTML = '';
    if (tbody) tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:12px;">Executing graph query...</td></tr>`;

    try {
      const res = await API.reproveQuery(refStr);
      if (latencyEl) latencyEl.innerHTML = `${res.ms}<span style="font-size:11px; font-weight:400; color:var(--ink-400);"> ms</span>`;
      if (rowsEl) rowsEl.textContent = res.rows;
      if (viaBadge) viaBadge.textContent = res.via === 'mcp' ? 'via MCP' : 'via Local GSQL';
      if (noteEl) noteEl.textContent = res.note || 'Query verified reproducible on graph engine.';

      if (tbody) tbody.innerHTML = '';
      if (res.sample && res.sample.length > 0) {
        const cols = Object.keys(res.sample[0]).slice(0, 5);
        if (thead) {
          thead.innerHTML = cols.map(c => `<th>${escapeHtml(c)}</th>`).join('');
        }
        res.sample.slice(0, 8).forEach(row => {
          const tr = document.createElement('tr');
          tr.innerHTML = cols.map(c => {
            const v = row[c];
            const text = typeof v === 'object' ? JSON.stringify(v) : String(v ?? '');
            return `<td title="${escapeHtml(text)}">${escapeHtml(text)}</td>`;
          }).join('');
          tbody.appendChild(tr);
        });
      } else {
        if (tbody) tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:12px;">Query completed with 0 rows.</td></tr>`;
      }
    } catch (err) {
      if (noteEl) noteEl.textContent = `Error executing query: ${err.message}`;
      if (tbody) tbody.innerHTML = `<tr><td colspan="4" style="color:var(--fraud); padding:12px;">Failed to re-prove: ${escapeHtml(err.message)}</td></tr>`;
    }
  }

  document.getElementById('btnCloseReproveModal')?.addEventListener('click', () => {
    const modal = document.getElementById('reproveModal');
    if (modal) modal.style.display = 'none';
  });
  document.getElementById('reproveModal')?.addEventListener('click', e => {
    if (e.target.id === 'reproveModal') e.target.style.display = 'none';
  });

  // ── Render Noisy-OR Risk Channels (real engine output via /risk endpoint) ──
  async function renderRiskChannels(data) {
    const tbody = document.getElementById('breakdownTableBody');
    const priorScoreEl = document.getElementById('riskPriorScore');
    const posteriorScoreEl = document.getElementById('riskPosteriorScore');
    const cardAside = document.getElementById('riskAnalysisAside');
    const trajList = document.getElementById('riskTrajectoryList');
    const provList = document.getElementById('riskProvenanceSummary');
    const methText = document.getElementById('riskMethodologyText');

    const caseId = data.case_id;
    // Race guard: never let a stale case fetch overwrite a later selection.
    const isCurrent = () => activeCaseId === caseId;

    // Header values come straight from the investigation record.
    const trigger = data.trigger || {};
    const prior = trigger.risk_score != null ? Number(trigger.risk_score).toFixed(2) : '—';
    const posterior = Number(data.fraud_probability || 0).toFixed(3);
    if (priorScoreEl) priorScoreEl.textContent = prior;
    if (posteriorScoreEl) posteriorScoreEl.textContent = posterior;
    if (cardAside) cardAside.textContent = 'Engine output • Noisy-OR (D7)';

    const emptyRow = (msg) => {
      if (tbody) tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:18px; color:var(--ink-400);">${escapeHtml(msg)}</td></tr>`;
    };

    let riskData;
    if (data.risk_assessment?.noisy_or_channels?.length) {
      // Legacy in-payload channel breakdown (older stored cases).
      riskData = {
        current: {
          fraud_probability: data.fraud_probability,
          score_breakdown: data.risk_assessment.noisy_or_channels.map(ch => ({
            channel: ch.channel, contribution: Number(ch.weight) || 0, label: ch.reason || '', type: 'fraud_signal'
          }))
        },
        trajectory: null, evidence_type_counts: null, methodology: null
      };
    } else {
      try {
        riskData = await API.getRiskAnalysis(caseId);
      } catch (err) {
        console.warn('Risk analysis fetch failed:', err);
      }
      if (!isCurrent()) return;
    }

    if (!riskData) {
      if (!isCurrent()) return;
      emptyRow('No explainable risk breakdown recorded for this case.');
      if (trajList) trajList.innerHTML = '';
      if (provList) provList.innerHTML = '';
      if (methText) methText.textContent = '';
      return;
    }

    if (!isCurrent()) return;

    // Real Noisy-OR channel decomposition from the risk engine.
    const channels = riskData.current?.score_breakdown || [];
    if (channels.length === 0) {
      emptyRow('No channel decomposition available for this case.');
    } else {
      tbody.innerHTML = '';
      const typeLabel = { fraud_signal: 'Fraud Signal', clearing_signal: 'Clearing Signal', total: 'Combined' };
      const typeClass = { fraud_signal: 'source-graph', clearing_signal: 'source-legitimate', total: 'source-external' };
      channels.forEach(ch => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td style="font-weight:600; color:var(--ink-100);">${escapeHtml(ch.channel || '—')}</td>
          <td><span class="source-chip ${typeClass[ch.type] || 'source-document'}">${escapeHtml(typeLabel[ch.type] || formatTitle(ch.type || 'Rule'))}</span></td>
          <td class="risk-weight-val" style="color:${ch.type === 'clearing_signal' ? 'var(--legit)' : 'var(--tg-300)'}; font-family:var(--font-mono);">${escapeHtml(String(ch.contribution))}</td>
          <td style="color:var(--ink-300); font-size:12px;">${escapeHtml(ch.label || '')}</td>
        `;
        tbody.appendChild(tr);
      });
    }

    // Probability trajectory (bank prior → graph evidence rounds → HITL reassessments → final).
    const originLabel = { bank_model: 'Bank Model', graph_evidence: 'Graph Evidence', evidence_response: 'HITL Response' };
    const originClass = { bank_model: 'source-external', graph_evidence: 'source-graph', evidence_response: 'source-document' };
    if (trajList) {
      const traj = riskData.trajectory || [];
      trajList.innerHTML = (traj.length === 0)
        ? `<div style="color:var(--ink-400); text-align:center; padding:12px;">No probability trajectory recorded.</div>`
        : traj.map(pt => `
          <div class="risk-traj-step">
            <span class="risk-traj-index">${pt.step}</span>
            <span class="source-chip ${originClass[pt.origin] || 'source-document'}">${escapeHtml(originLabel[pt.origin] || pt.origin)}</span>
            <span class="risk-traj-label">${escapeHtml(pt.label)}</span>
            <span class="risk-traj-prob">${Number(pt.probability).toFixed(4)}</span>
          </div>
        `).join('');
    }

    // Evidence provenance summary (real claim-type counts).
    if (provList) {
      const counts = riskData.evidence_type_counts;
      provList.innerHTML = counts
        ? `
          <span class="id-chip">Observed Facts: <strong>${counts.observed_fact}</strong></span>
          <span class="id-chip">Derived Inferences: <strong>${counts.derived_inference}</strong></span>
          <span class="id-chip">Model Scores: <strong>${counts.model_score}</strong></span>
          <span class="id-chip">Total Evidence: <strong>${counts.total}</strong></span>
        `
        : '';
    }

    // Documented methodology note (from the endpoint, never invented in UI).
    if (methText) {
      methText.textContent = riskData.methodology || '';
    }
  }

  // ── Render Decision Uncertainty & Evidence Inquiry (HITL) ─────────────────
  function renderUncertaintyCycle(data) {
    const container = document.getElementById('uncertaintyCycleContent');
    const uncCount = document.getElementById('uncCount');
    if (!container) return;

    const reqs = data.evidence_requests || [];
    if (uncCount) uncCount.textContent = reqs.length;

    if (reqs.length === 0) {
      container.innerHTML = `
        <div style="padding:24px; text-align:center; color:var(--ink-400);">
          No open uncertainty inquiries. Decision threshold is confident and resolved.
        </div>
      `;
      return;
    }

    container.innerHTML = '';
    reqs.forEach((er, idx) => {
      const card = document.createElement('div');
      card.className = 'inquiry-card';

      const isPending = er.status === 'pending';
      card.innerHTML = `
        <div class="inquiry-top">
          <div style="display:flex; align-items:center; gap:8px;">
            <span class="source-chip ${isPending ? 'source-graph' : 'source-document'}">${escapeHtml(formatTitle(er.type || 'Inquiry'))}</span>
            <span class="inquiry-title">${escapeHtml(er.type || 'Verification Inquiry')}</span>
          </div>
          <span class="badge ${isPending ? 'badge-status-open' : 'badge-status-closed'}">${escapeHtml(er.status || 'pending')}</span>
        </div>
        <p class="inquiry-desc" title="Why this inquiry matters for the decision">${escapeHtml(er.decision_relevance || 'Decision relevance not documented for this inquiry.')}</p>

        ${isPending ? `
          <div class="simulation-buttons-row">
            <span style="font-size:11px; text-transform:uppercase; color:var(--ink-400); align-self:center; margin-right:4px;">Simulate Reply:</span>
            <button class="btn-sim sim-confirmed" data-type="${escapeHtml(er.type)}" data-reply="Customer confirmed valid purchase">
              &check; Customer Confirmed
            </button>
            <button class="btn-sim sim-denied" data-type="${escapeHtml(er.type)}" data-reply="Customer denied making this transaction">
              &cross; Customer Denied
            </button>
            <button class="btn-sim" data-type="${escapeHtml(er.type)}" data-reply="No response from customer within 24h">
              No Reply (Timeout)
            </button>
          </div>
          <div class="custom-reply-row">
            <input type="text" placeholder="Type custom human-in-the-loop response..." id="customReplyInput-${idx}">
            <button class="btn-primary" style="height:32px;" id="btnSubmitCustomReply-${idx}">Submit Evidence</button>
          </div>
        ` : `
          <div style="margin-top:10px; padding:8px 12px; border-radius:6px; background-color:var(--ink-900); border:1px solid var(--ink-750); font-size:12px;">
            <span style="color:var(--ink-400);">Received response:</span> <strong style="color:var(--ink-100);">${escapeHtml(er.assumed_response || 'Recorded')}</strong>
          </div>
        `}
      `;

      // Wire quick simulation buttons
      card.querySelectorAll('.btn-sim').forEach(btn => {
        btn.addEventListener('click', async () => {
          const reply = btn.dataset.reply;
          const type = btn.dataset.type;
          await submitEvidenceResponse(data.case_id, type, reply);
        });
      });

      // Wire custom reply submission
      const btnCustom = card.querySelector(`#btnSubmitCustomReply-${idx}`);
      const inputCustom = card.querySelector(`#customReplyInput-${idx}`);
      btnCustom?.addEventListener('click', async () => {
        const text = (inputCustom?.value || '').trim();
        if (!text) return;
        await submitEvidenceResponse(data.case_id, er.type, text);
      });

      container.appendChild(card);
    });
  }

  async function submitEvidenceResponse(caseId, type, responseText) {
    try {
      showToast(`Submitting evidence for ${caseId}...`, 'info');
      const updated = await API.submitEvidence(caseId, type, responseText);
      showToast(`Evidence ingested. Reassessment calculated!`, 'success');
      await selectCase(caseId);
      await refreshAllInvestigations();
    } catch (err) {
      showToast(`Evidence submission failed: ${err.message}`, 'error');
    }
  }

  // ── Render Governed Next Best Actions (Policy Matrix) ────────────────────
  function renderNbaGovernance(data) {
    const container = document.getElementById('nbaGovernanceContent');
    const aprCountBadge = document.getElementById('aprCount');
    if (!container) return;

    const nba = data.next_best_actions || {};
    const finalActions = nba.final || [];
    const initialActions = nba.initial || [];

    if (aprCountBadge) aprCountBadge.textContent = finalActions.length;

    if (finalActions.length === 0) {
      container.innerHTML = `
        <div style="padding:24px; text-align:center; color:var(--ink-400);">
          No actions required for this case.
        </div>
      `;
      return;
    }

    // Compute diff: kept, added, removed
    const initialNames = new Set(initialActions.map(a => a.action));
    const tableRows = finalActions.map((item, idx) => {
      const isNew = !initialNames.has(item.action);
      const route = (item.route || 'auto').toLowerCase();
      const routeClass = route === 'l2' ? 'route-l2' : route === 'l1' ? 'route-l1' : 'route-auto';
      const routeLabel = route === 'l2' ? 'L2 Compliance' : route === 'l1' ? 'L1 Analyst' : 'Auto Executed';

      const needsDecision = route === 'l1' || route === 'l2';
      return `
        <tr>
          <td>
            <div style="display:flex; align-items:center; gap:8px;">
              <span class="action-name">${escapeHtml(item.action)}</span>
              <span class="diff-badge ${isNew ? 'added' : 'kept'}">${isNew ? 'ADDED' : 'KEPT'}</span>
            </div>
          </td>
          <td><span class="route-pill ${routeClass}">${escapeHtml(routeLabel)}</span></td>
          <td style="color:var(--ink-200); font-size:12px; line-height:1.5;">${escapeHtml(item.reason || 'Policy execution')}</td>
          <td style="text-align:right;">
            ${needsDecision ? `
              <button class="btn-approve-inline" data-case="${escapeHtml(data.case_id)}" data-action="${escapeHtml(item.action)}" data-idx="${idx}">Approve</button>
              <button class="btn-reject-inline" data-case="${escapeHtml(data.case_id)}" data-action="${escapeHtml(item.action)}" data-idx="${idx}">Reject</button>
            ` : `
              <span style="font-size:11px; color:var(--legit); font-weight:600;">&check; Executed</span>
            `}
          </td>
        </tr>
      `;
    }).join('');

    container.innerHTML = `
      <table class="nba-table">
        <thead>
          <tr>
            <th style="width:28%;">Institutional Action</th>
            <th style="width:18%;">Approval Route</th>
            <th style="width:38%;">Governed Policy Justification</th>
            <th style="width:16%; text-align:right;">Authority</th>
          </tr>
        </thead>
        <tbody>
          ${tableRows}
        </tbody>
      </table>
    `;

    // Wire inline approve/reject buttons
    container.querySelectorAll('.btn-approve-inline').forEach(btn => {
      btn.addEventListener('click', async () => {
        const caseId = btn.dataset.case;
        const action = btn.dataset.action;
        await decideCaseApproval(caseId, action, 'approved');
      });
    });

    container.querySelectorAll('.btn-reject-inline').forEach(btn => {
      btn.addEventListener('click', async () => {
        const caseId = btn.dataset.case;
        const action = btn.dataset.action;
        await decideCaseApproval(caseId, action, 'rejected');
      });
    });
  }

  async function decideCaseApproval(caseId, action, decision) {
    try {
      showToast(`Recording ${decision} for ${action}...`, 'info');
      // Look up the exact approval record for this action — never fall back to
      // a different approval (that would attach the decision to the wrong action).
      const approvals = await API.getApprovals(caseId);
      const target = approvals.find(a => a.action === action && a.status === 'pending');

      if (!target) {
        const alreadyDecided = approvals.some(a => a.action === action);
        showToast(
          alreadyDecided
            ? `${action} was already decided for ${caseId}. Refreshing case.`
            : `No pending approval record found for ${action} — decision not recorded.`,
          alreadyDecided ? 'info' : 'error'
        );
        await selectCase(caseId);
        await updateApprovalsCount();
        return;
      }

      await API.decideApproval(caseId, target.approval_id, decision, 'FraudAnalyst-L1');
      showToast(`Action ${action} ${decision} successfully.`, 'success');
      await selectCase(caseId);
      await updateApprovalsCount();
    } catch (err) {
      showToast(`Decision failed: ${err.message}`, 'error');
    }
  }

  // ── Render FinCEN SAR Document ────────────────────────────────────────────
  function renderSarDocument(data) {
    const container = document.getElementById('persistenceContent');
    if (!container) return;

    const sar = data.sar || {};
    const subjects = sar.subjects || [data.customer_id, data.card_id].filter(Boolean);

    container.innerHTML = `
      <article class="sar-doc">
        <header class="sar-header">
          <div>
            <div class="sar-tag">Regulatory Filing &bull; FinCEN Form 111 Compliance</div>
            <h3 class="sar-title">Suspicious Activity Report</h3>
            <p class="sar-subtitle">Prepared by FraudLens autonomous agent team. Requires Fraud Manager (L2) sign-off.</p>
          </div>
          <div class="sar-right-meta">
            <div>Case: <strong>${escapeHtml(data.case_id)}</strong></div>
            ${data.graph_case_id ? `<div>Graph Case: ${escapeHtml(data.graph_case_id)}</div>` : ''}
            <div>Filing Status: ${sar.file ? 'Initial Filing Recommended' : 'Exempt'}</div>
          </div>
        </header>

        <section class="sar-section">
          <div class="sar-section-title">Part I. Subjects & Connected Entities</div>
          <table class="sar-table">
            <thead>
              <tr>
                <th style="width:8%;">#</th>
                <th style="width:25%;">Entity Role</th>
                <th>Identifier / Key</th>
              </tr>
            </thead>
            <tbody>
              ${subjects.map((sub, i) => `
                <tr>
                  <td style="font-family:var(--font-mono); color:#5B6068;">${i + 1}</td>
                  <td>${escapeHtml(sub.startsWith('C') && sub.includes('-') ? 'Payment Card' : sub.startsWith('C') ? 'Customer Account' : sub.startsWith('DEV-') ? 'Device Hardware Fingerprint' : 'Transaction')}</td>
                  <td style="font-family:var(--font-mono); font-weight:600;">${escapeHtml(sub)}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </section>

        <section class="sar-section">
          <div class="sar-section-title">Part II. Suspicious Activity Narrative</div>
          <p class="sar-narrative-text" id="sarNarrativeText">
            ${escapeHtml(sar.narrative || data.summary || 'Suspicious financial activity identified across knowledge graph topology.')}
          </p>
        </section>

        <section class="sar-section">
          <div class="sar-section-title">Part III. Statutory Basis for Filing</div>
          <p class="sar-narrative-text">
            ${escapeHtml(sar.reason || 'Activity meets the regulatory threshold for suspicious transaction reporting under 31 CFR § 1020.320.')}
          </p>
        </section>

        <footer class="sar-footer">
          <div>
            <div class="signature-line"></div>
            <div class="signature-caption">Tier 2 Compliance Officer / Fraud Manager Signature</div>
          </div>
          <div>
            <div class="signature-line"></div>
            <div class="signature-caption">Date of Approval & Filing</div>
          </div>
        </footer>
      </article>
    `;

    document.getElementById('btnPrintSar')?.addEventListener('click', () => {
      window.print();
    });

    document.getElementById('btnCopySar')?.addEventListener('click', () => {
      const text = document.getElementById('sarNarrativeText')?.innerText || '';
      navigator.clipboard?.writeText(text);
      showToast('SAR narrative copied to clipboard.', 'success');
    });
  }

  // ── Render Audit Timeline ─────────────────────────────────────────────────
  async function renderAuditTimeline(caseId) {
    const listEl = document.getElementById('timelineEventsList');
    if (!listEl) return;

    try {
      const trail = await API.getTimeline(caseId);
      if (!trail || trail.length === 0) {
        listEl.innerHTML = `<div style="color:var(--ink-400); text-align:center; padding:16px;">No audit trail recorded.</div>`;
        return;
      }

      listEl.innerHTML = trail.map(evt => `
        <div style="display:flex; align-items:flex-start; gap:12px; margin-bottom:12px; padding-bottom:12px; border-bottom:1px solid var(--ink-750);">
          <div style="width:7px; height:7px; border-radius:50%; background-color:var(--tg-500); margin-top:6px; flex-shrink:0;"></div>
          <div style="flex:1;">
            <div style="display:flex; justify-content:space-between; font-size:12px;">
              <strong style="color:var(--ink-100);">${escapeHtml(evt.event_type || 'Event')}</strong>
              <span style="font-family:var(--font-mono); font-size:11px; color:var(--ink-400);">${escapeHtml(evt.timestamp ? evt.timestamp.slice(0, 19).replace('T', ' ') : '—')}</span>
            </div>
            <div style="font-size:12px; color:var(--ink-300); margin-top:2px;">
              ${evt.state_from ? `<span style="color:var(--ink-500);">${escapeHtml(evt.state_from)} &rarr;</span> ` : ''}
              <span style="color:var(--tg-300); font-weight:500;">${escapeHtml(evt.state_to || '')}</span>
              &bull; Actor: <span style="font-family:var(--font-mono); color:var(--ink-200);">${escapeHtml(evt.actor || 'system')}</span>
            </div>
          </div>
        </div>
      `).join('');
    } catch {
      listEl.innerHTML = `<div style="color:var(--ink-400); text-align:center; padding:16px;">Audit trail unavailable.</div>`;
    }
  }

  // ── Render Alert Queue Table & Filters ────────────────────────────────────
  function renderQueueTable() {
    const tbody = document.getElementById('queueTableBody');
    if (!tbody) return;

    let totalExposure = 0;
    let highRiskCount = 0;

    // Filter items
    const filtered = casePackList.filter(c => {
      const inv = investigationsCache.get(c.case_id) || {};
      const status = (inv.status || 'new').toLowerCase();
      const verdict = (inv.verdict || '').toLowerCase();
      const trigger = (c.trigger_type || '').toLowerCase();

      // Status filter
      if (queueFilterStatus !== 'all') {
        if (queueFilterStatus === 'closed' && !status.startsWith('closed')) return false;
        if (queueFilterStatus !== 'closed' && status !== queueFilterStatus) return false;
      }

      // Verdict filter
      if (queueFilterVerdict !== 'all') {
        if (queueFilterVerdict === 'fraud' && verdict !== 'fraud') return false;
        if (queueFilterVerdict === 'legitimate' && verdict !== 'legitimate') return false;
        if (queueFilterVerdict === 'uncertain' && verdict !== 'uncertain') return false;
      }

      // Trigger filter
      if (queueFilterTrigger !== 'all' && trigger !== queueFilterTrigger) {
        return false;
      }

      // Search query
      if (queueSearchQuery) {
        const q = queueSearchQuery.toLowerCase();
        const textToMatch = [c.case_id, c.card_id, c.customer_id, c.flagged_txn_id, c.trigger_text].join(' ').toLowerCase();
        if (!textToMatch.includes(q)) return false;
      }

      return true;
    });

    // Compute stats
    casePackList.forEach(c => {
      const inv = investigationsCache.get(c.case_id) || {};
      const verdict = (inv.verdict || '').toLowerCase();
      const exposure = Number(inv.exposure_usd || 0);
      if (verdict === 'fraud') totalExposure += exposure;
      if (Number(inv.fraud_probability || 0) >= 0.85 || Number(c.risk_score || 0) >= 0.85) highRiskCount++;
    });

    const queueExposureVal = document.getElementById('queueExposureVal');
    if (queueExposureVal) queueExposureVal.textContent = formatMoney(totalExposure);
    const queueHighRiskVal = document.getElementById('queueHighRiskVal');
    if (queueHighRiskVal) queueHighRiskVal.textContent = highRiskCount;

    tbody.innerHTML = '';
    if (filtered.length === 0) {
      tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; padding:32px; color:var(--ink-400);">No cases match the selected filters.</td></tr>`;
      return;
    }

    filtered.forEach(c => {
      const inv = investigationsCache.get(c.case_id) || {};
      const verdict = (inv.verdict || '').toLowerCase();
      const status = (inv.status || 'closed').toLowerCase();
      const scoreNum = c.risk_score != null ? Number(c.risk_score) : null;
      const exposureNum = Number(inv.exposure_usd || 0);

      const tr = document.createElement('tr');
      if (verdict === 'fraud') tr.className = 'verdict-border-fraud';
      else if (verdict === 'legitimate') tr.className = 'verdict-border-legit';
      else if (verdict === 'uncertain') tr.className = 'verdict-border-unsure';

      tr.innerHTML = `
        <td>
          <div class="case-id-cell">
            <span class="case-id-primary">${escapeHtml(c.case_id)}</span>
            <span class="case-sub-meta">txn #${escapeHtml(c.flagged_txn_id)}</span>
            <span class="case-sub-meta">${escapeHtml(c.card_id || '')}</span>
          </div>
          <div class="case-trigger-blurb" title="${escapeHtml(c.trigger_text || '')}">
            ${escapeHtml(c.trigger_text || '')}
          </div>
        </td>
        <td style="font-family:var(--font-mono); font-size:11.5px; color:var(--ink-400);">
          ${escapeHtml(c.opened_at ? c.opened_at.slice(0, 10) : '—')}
          <div style="font-size:10.5px; color:var(--ink-500);">${escapeHtml(c.opened_at ? c.opened_at.slice(11, 16) : '')}</div>
        </td>
        <td>
          <span class="source-chip source-external">${escapeHtml(formatTitle(c.trigger_type))}</span>
        </td>
        <td>
          ${scoreNum != null ? `
            <div class="score-cell">
              <span class="score-val" style="color:${scoreNum >= 0.85 ? 'var(--fraud)' : scoreNum >= 0.5 ? 'var(--unsure)' : 'var(--ink-300)'};">${scoreNum.toFixed(2)}</span>
              <div class="score-track">
                <div class="score-fill" style="width:${scoreNum * 100}%; background-color:${scoreNum >= 0.85 ? 'var(--fraud)' : scoreNum >= 0.5 ? 'var(--unsure)' : 'var(--ink-400)'};"></div>
              </div>
            </div>
          ` : '<span style="color:var(--ink-500); font-size:11.5px;">No score</span>'}
        </td>
        <td>
          <span class="badge badge-status-${status}">${escapeHtml(formatTitle(status))}</span>
        </td>
        <td>
          ${verdict ? `
            <span class="verdict-badge verdict-${verdict}">${escapeHtml(verdict.toUpperCase())}</span>
          ` : '<span style="color:var(--ink-500); font-size:11.5px;">Ready</span>'}
        </td>
        <td style="font-size:12px; color:var(--ink-200);">
          ${escapeHtml(formatTitle(inv.pattern || '—'))}
        </td>
        <td style="font-family:var(--font-mono); font-size:12.5px; text-align:right; font-weight:600; color:var(--ink-100);">
          ${formatMoney(exposureNum)}
        </td>
        <td style="text-align:center;">
          ${inv.sar?.file ? `<span title="SAR Required" style="color:var(--tg-300); font-weight:700;">&check;</span>` : '<span style="color:var(--ink-600);">&minus;</span>'}
        </td>
      `;

      tr.addEventListener('click', () => {
        selectCase(c.case_id);
        switchView('case');
      });

      tbody.appendChild(tr);
    });
  }

  // Queue Filter Event Wiring
  document.querySelectorAll('#filterStatusGroup .segmented-item').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#filterStatusGroup .segmented-item').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      queueFilterStatus = btn.dataset.filter;
      renderQueueTable();
    });
  });

  document.querySelectorAll('#filterVerdictGroup .segmented-item').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#filterVerdictGroup .segmented-item').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      queueFilterVerdict = btn.dataset.filter;
      renderQueueTable();
    });
  });

  document.querySelectorAll('#filterTriggerGroup .segmented-item').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#filterTriggerGroup .segmented-item').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      queueFilterTrigger = btn.dataset.filter;
      renderQueueTable();
    });
  });

  document.getElementById('queueSearchInput')?.addEventListener('input', e => {
    queueSearchQuery = e.target.value;
    renderQueueTable();
  });

  // ── Render Approval Inbox View ────────────────────────────────────────────
  async function loadApprovalsInbox() {
    const tbody = document.getElementById('approvalsInboxTableBody');
    if (!tbody) return;

    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:20px; color:var(--ink-400);">Loading approval inbox...</td></tr>`;

    try {
      const approvals = await API.getAllApprovals?.() || [];
      approvalsAll = approvals;

      const filtered = approvalsFilterStatus === 'all'
        ? approvals
        : approvals.filter(a => a.status === approvalsFilterStatus);

      if (filtered.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:32px; color:var(--ink-400);">No ${escapeHtml(approvalsFilterStatus)} approvals in queue.</td></tr>`;
        return;
      }

      tbody.innerHTML = filtered.map(item => {
        const route = (item.required_route || item.route || 'l1').toLowerCase();
        const routeClass = route === 'l2' ? 'route-l2' : route === 'l1' ? 'route-l1' : 'route-auto';
        const routeLabel = route === 'l2' ? 'L2 Compliance' : route === 'l1' ? 'L1 Analyst' : 'Auto';
        const isPending = item.status === 'pending';

        return `
          <tr>
            <td>
              <span class="id-chip" style="font-weight:700; color:var(--ink-100);">${escapeHtml(item.case_id)}</span>
            </td>
            <td>
              <span class="action-name">${escapeHtml(item.action)}</span>
            </td>
            <td>
              <span class="route-pill ${routeClass}">${escapeHtml(routeLabel)}</span>
            </td>
            <td style="color:var(--ink-200); font-size:12px; line-height:1.5;">
              ${escapeHtml(item.reason || 'Policy execution')}
              ${item.rule_id ? `<div style="font-size:11px; color:var(--tg-300); margin-top:2px;">Governed under Rule ${escapeHtml(item.rule_id)}</div>` : ''}
            </td>
            <td>
              <span class="badge ${isPending ? 'badge-status-open' : item.status === 'approved' ? 'badge-status-closed' : 'badge-status-escalated'}">
                ${escapeHtml(formatTitle(item.status))}
              </span>
            </td>
            <td style="text-align:right;">
              ${isPending ? `
                <button class="btn-approve-inline" data-case="${escapeHtml(item.case_id)}" data-aprid="${escapeHtml(item.approval_id || '')}" data-action="${escapeHtml(item.action)}">Approve</button>
                <button class="btn-reject-inline" data-case="${escapeHtml(item.case_id)}" data-aprid="${escapeHtml(item.approval_id || '')}" data-action="${escapeHtml(item.action)}">Reject</button>
              ` : `
                <span style="font-size:11px; color:var(--ink-400);">Decided by ${escapeHtml(item.approver || 'system')}</span>
              `}
            </td>
          </tr>
        `;
      }).join('');

      tbody.querySelectorAll('.btn-approve-inline').forEach(btn => {
        btn.addEventListener('click', async () => {
          const caseId = btn.dataset.case;
          const aprId = btn.dataset.aprid;
          await decideInboxApproval(caseId, aprId, 'approved');
        });
      });

      tbody.querySelectorAll('.btn-reject-inline').forEach(btn => {
        btn.addEventListener('click', async () => {
          const caseId = btn.dataset.case;
          const aprId = btn.dataset.aprid;
          await decideInboxApproval(caseId, aprId, 'rejected');
        });
      });
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:20px; color:var(--fraud);">Failed to load approvals: ${escapeHtml(err.message)}</td></tr>`;
    }
  }

  async function decideInboxApproval(caseId, aprId, decision) {
    try {
      showToast(`Submitting ${decision} decision...`, 'info');
      await API.decideApproval(caseId, aprId, decision, 'FraudAnalyst-L1');
      showToast(`Approval ${decision} successfully.`, 'success');
      await updateApprovalsCount();
      await loadApprovalsInbox();
    } catch (err) {
      showToast(`Decision failed: ${err.message}`, 'error');
    }
  }

  document.querySelectorAll('#filterApprovalStatusGroup .segmented-item').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#filterApprovalStatusGroup .segmented-item').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      approvalsFilterStatus = btn.dataset.appfilter;
      loadApprovalsInbox();
    });
  });

  // ── Render Insights / Benchmark Validation View ───────────────────────────
  async function loadInsights() {
    const container = document.getElementById('caseRunsTableContainer');
    if (!container) return;

    container.innerHTML = `<div style="padding:16px; text-align:center; color:var(--ink-400);">Loading benchmark runs...</div>`;

    try {
      const rep = await API.getBenchmarkReport().catch(() => null);

      if (rep?.cases?.length) {
        container.innerHTML = `
          <table class="nba-table">
            <thead>
              <tr>
                <th style="width:14%;">Case Dossier</th>
                <th style="width:14%;">Verdict</th>
                <th style="width:14%;">Posterior Prob</th>
                <th style="width:26%;">Detected Typology</th>
                <th style="width:16%;">NBA Count</th>
                <th style="width:16%; text-align:right;">Contract Status</th>
              </tr>
            </thead>
            <tbody>
              ${rep.cases.map(r => `
                <tr style="cursor:pointer;" onclick="window.selectCase('${escapeHtml(r.case_id)}'); window.switchView('case');">
                  <td><strong style="color:var(--ink-100); font-family:var(--font-mono);">${escapeHtml(r.case_id)}</strong></td>
                  <td><span class="verdict-badge verdict-${escapeHtml(String(r.verdict || '').toLowerCase())}">${escapeHtml(String(r.verdict || '').toUpperCase())}</span></td>
                  <td style="font-family:var(--font-mono); color:var(--tg-300);">${Number(r.fraud_probability || 0).toFixed(3)}</td>
                  <td style="color:var(--ink-200);">${escapeHtml(formatTitle(r.pattern || '—'))}</td>
                  <td><span class="id-chip">${r.actions_count || 1} Actions</span></td>
                  <td style="text-align:right;"><span style="color:var(--legit); font-weight:600;">&check; VERIFIED</span></td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        `;
        return;
      }

      // No benchmark report: show only real stored investigations (or an honest
      // empty state). Never synthesize verdicts or probabilities.
      const runs = [...investigationsCache.values()].filter(inv => inv.verdict) || [];

      if (runs.length === 0) {
        container.innerHTML = `
          <div style="padding:28px; text-align:center; color:var(--ink-400);">
            <p style="margin-bottom:8px;">No benchmark report found.</p>
            <p style="font-size:12px;">Run <span style="font-family:var(--font-mono); color:var(--tg-300);">POST /benchmark/run</span> (or the button below) to generate the 20-case validation report. Investigations appear here with verified contract status once the benchmark has executed.</p>
          </div>
        `;
        return;
      }

      container.innerHTML = `
        <div style="padding:8px 16px; border-bottom:1px solid var(--ink-750); font-size:12px; color:var(--ink-400);">
          No benchmark report found — showing <strong style="color:var(--ink-200);">${runs.length}</strong> stored investigation${runs.length === 1 ? '' : 's'} (unverified by benchmark contract).
        </div>
        <table class="nba-table">
          <thead>
            <tr>
              <th style="width:16%;">Case Dossier</th>
              <th style="width:16%;">Verdict</th>
              <th style="width:18%;">Posterior Prob</th>
              <th style="width:28%;">Detected Typology</th>
              <th style="width:10%;">NBA Count</th>
              <th style="width:12%; text-align:right;">Contract Status</th>
            </tr>
          </thead>
          <tbody>
            ${runs.map(r => `
              <tr style="cursor:pointer;" onclick="window.selectCase('${escapeHtml(r.case_id)}'); window.switchView('case');">
                <td><strong style="color:var(--ink-100); font-family:var(--font-mono);">${escapeHtml(r.case_id)}</strong></td>
                <td><span class="verdict-badge verdict-${escapeHtml(String(r.verdict || '').toLowerCase())}">${escapeHtml(String(r.verdict || '').toUpperCase())}</span></td>
                <td style="font-family:var(--font-mono); color:var(--tg-300);">${Number(r.fraud_probability || 0).toFixed(3)}</td>
                <td style="color:var(--ink-200);">${escapeHtml(formatTitle(r.pattern || '—'))}</td>
                <td><span class="id-chip">${(r.next_best_actions?.final?.length || 0)} Actions</span></td>
                <td style="text-align:right;"><span style="color:var(--ink-400);">Unverified</span></td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
    } catch {
      container.innerHTML = `<div style="padding:16px; text-align:center; color:var(--ink-400);">Benchmark data loading.</div>`;
    }
  }

  document.getElementById('btnRunBenchmarkSuite')?.addEventListener('click', async () => {
    const btn = document.getElementById('btnRunBenchmarkSuite');
    if (btn) btn.disabled = true;
    showToast('Executing full 20-case benchmark pipeline (may take several minutes)...', 'info', 8000);
    try {
      const res = await API.runBenchmark();
      const passed = Number(res?.passed ?? res?.summary?.passed);
      const total = Number(res?.total ?? res?.cases?.length ?? 0);
      const msg = Number.isFinite(passed) && Number.isFinite(total)
        ? `Benchmark completed: ${passed}/${total} cases met the contract.`
        : 'Benchmark run completed.';
      showToast(msg, 'success');
      await refreshAllInvestigations();
      await loadInsights();
    } catch (err) {
      showToast(`Benchmark run failed: ${err.message}`, 'error');
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  // ── Run Investigation Button (Header & Live View) ─────────────────────────
  async function triggerLiveInvestigation() {
    if (!activeCaseId) return;
    const btn = document.getElementById('btnInvestigate');
    if (btn) btn.disabled = true;

    showToast(`Launching multi-agent investigation for ${activeCaseId}...`, 'info');
    switchView('live');

    // Simulate multi-step live traversal on graph canvas
    liveGraphRenderer.setTraversalLoading(true, { progress: '1/4', step: 1, stepText: 'Querying transaction history & bursts...', elapsed: 0.1 });

    const timer = setInterval(() => {
      const elapsed = (Number(liveGraphRenderer.traversalState?.elapsed || 0) + 0.3);
      let step = 1;
      let text = 'Querying transaction history & bursts...';
      let prog = '1/4';

      if (elapsed >= 0.9) { step = 2; text = 'Traversing shared device neighbors...'; prog = '2/4'; }
      if (elapsed >= 1.8) { step = 3; text = 'Retrieving similar historical closed cases...'; prog = '3/4'; }
      if (elapsed >= 2.6) { step = 4; text = 'Evaluating policy rules & graph rings...'; prog = '4/4'; }

      liveGraphRenderer.updateTraversalState({ elapsed, step, stepText: text, progress: prog });
    }, 300);

    try {
      const res = await API.runInvestigation(activeCaseId);
      clearInterval(timer);
      liveGraphRenderer.setTraversalLoading(false);

      showToast(`Investigation for ${activeCaseId} completed. Verdict: ${res.case?.verdict?.toUpperCase()}`, 'success');
      await selectCase(activeCaseId);
      await refreshAllInvestigations();
    } catch (err) {
      clearInterval(timer);
      liveGraphRenderer.setTraversalLoading(false);
      showToast(`Investigation error: ${err.message}`, 'error');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  document.getElementById('btnInvestigate')?.addEventListener('click', triggerLiveInvestigation);
  document.getElementById('btnLiveRunTrigger')?.addEventListener('click', triggerLiveInvestigation);
  document.getElementById('btnCaseReplay')?.addEventListener('click', triggerLiveInvestigation);

  // Download Answer JSON
  document.getElementById('btnDownloadJson')?.addEventListener('click', () => {
    if (!activeCaseFullData) return;
    const blob = new Blob([JSON.stringify(activeCaseFullData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${activeCaseId}.json`;
    a.click();
    URL.revokeObjectURL(url);
    showToast(`Downloaded ${activeCaseId}.json`, 'success');
  });

  // Graph Zoom / Reset Event Handlers
  document.getElementById('btnZoomIn')?.addEventListener('click', () => {
    liveGraphRenderer.zoomIn();
    caseGraphRenderer.zoomIn();
  });
  document.getElementById('btnZoomOut')?.addEventListener('click', () => {
    liveGraphRenderer.zoomOut();
    caseGraphRenderer.zoomOut();
  });
  document.getElementById('btnResetView')?.addEventListener('click', () => {
    liveGraphRenderer.resetView();
    caseGraphRenderer.resetView();
  });

  // Stepper Step Click
  function setTimelineStep(stepIndex, status = 'active') {
    const steps = document.querySelectorAll('.step-item');
    steps.forEach((s, idx) => {
      s.classList.remove('active', 'completed');
      if (idx < stepIndex) s.classList.add('completed');
      else if (idx === stepIndex) s.classList.add(status);
    });
  }

  document.querySelectorAll('.step-item').forEach((item, idx) => {
    item.addEventListener('click', () => {
      setTimelineStep(idx, 'active');
      const stepKey = item.dataset.step;
      switchView('case');
      if (['trigger', 'memory', 'pattern'].includes(stepKey)) switchCaseTab('casetabOverview');
      else if (['traversal', 'evidence'].includes(stepKey)) switchCaseTab('casetabEvidence');
      else if (stepKey === 'risk') switchCaseTab('casetabRisk');
      else if (['uncertainty', 'request', 'reassessment'].includes(stepKey)) switchCaseTab('casetabUncertainty');
      else if (stepKey === 'nba') switchCaseTab('casetabNba');
      else if (stepKey === 'persistence') switchCaseTab('casetabSar');
    });
  });

  // ── Format Helpers ────────────────────────────────────────────────────────
  function formatMoney(n) {
    return '$' + Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function formatTitle(str) {
    if (!str) return '';
    return String(str).replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  }

  function escapeHtml(str) {
    if (str == null) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // Initial Boot
  await checkHealth();
  await loadInitialData();
});
