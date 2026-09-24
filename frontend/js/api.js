/**
 * API Client for HHGoa Fraud Investigation Backend
 * Supports both origin-relative calls and local port fallback.
 */
const API = {
  baseUrl: (typeof window !== 'undefined' && window.location.protocol === 'file:')
    ? 'http://127.0.0.1:8008'
    : '',

  async getHealth() {
    const res = await fetch(`${this.baseUrl}/health`);
    if (!res.ok) throw new Error(`Health check failed: ${res.statusText}`);
    return await res.json();
  },

  async getCases() {
    const res = await fetch(`${this.baseUrl}/api/cases`);
    if (!res.ok) throw new Error(`Failed to load cases: ${res.statusText}`);
    return await res.json();
  },

  async getInvestigationFull(caseId) {
    const res = await fetch(`${this.baseUrl}/api/investigations/${encodeURIComponent(caseId)}/full`);
    if (!res.ok) {
      if (res.status === 404) return null;
      throw new Error(`Failed to load investigation: ${res.statusText}`);
    }
    return await res.json();
  },

  async getInvestigationGraph(caseId) {
    const res = await fetch(`${this.baseUrl}/api/investigations/${encodeURIComponent(caseId)}/graph`);
    if (!res.ok) {
      if (res.status === 404) return null;
      throw new Error(`Failed to load graph: ${res.statusText}`);
    }
    return await res.json();
  },

  async getTimeline(caseId) {
    const res = await fetch(`${this.baseUrl}/investigations/${encodeURIComponent(caseId)}/timeline`);
    if (!res.ok) {
      if (res.status === 404) return [];
      throw new Error(`Failed to load timeline: ${res.statusText}`);
    }
    return await res.json();
  },

  async getApprovals(caseId) {
    const res = await fetch(`${this.baseUrl}/investigations/${encodeURIComponent(caseId)}/approvals`);
    if (!res.ok) return [];
    return await res.json();
  },

  async decideApproval(caseId, approvalId, decision, approver = 'FraudAnalyst-L1') {
    const res = await fetch(`${this.baseUrl}/investigations/${encodeURIComponent(caseId)}/approvals/${encodeURIComponent(approvalId)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision, approver })
    });
    if (!res.ok) throw new Error(`Approval decision failed: ${res.statusText}`);
    return await res.json();
  },

  async runInvestigation(caseId) {
    // force=true: the demo button executes a fresh investigation
    const res = await fetch(`${this.baseUrl}/investigations/${encodeURIComponent(caseId)}/run?force=true`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      throw new Error(errBody.detail || `Investigation run failed: ${res.statusText}`);
    }
    return await res.json();
  },

  async submitEvidence(caseId, type, response) {
    const res = await fetch(`${this.baseUrl}/investigations/${encodeURIComponent(caseId)}/evidence`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: type || '', response, origin: 'human_in_loop' })
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      throw new Error(errBody.detail || `Evidence submission failed: ${res.statusText}`);
    }
    return await res.json();
  },

  async getBenchmarkReport() {
    const res = await fetch(`${this.baseUrl}/benchmark/report`);
    if (!res.ok) throw new Error(`Benchmark report unavailable: ${res.statusText}`);
    return await res.json();
  },

  async getBenchmarkCheckpoints() {
    const res = await fetch(`${this.baseUrl}/benchmark/checkpoints`);
    if (!res.ok) throw new Error(`Checkpoint report unavailable: ${res.statusText}`);
    return await res.json();
  }
};

window.API = API;
