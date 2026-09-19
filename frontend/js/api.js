/**
 * API Client for HHGoa Fraud Investigation Backend
 */
const API = {
  baseUrl: '',

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
    const res = await fetch(`${this.baseUrl}/investigations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ case_id: caseId })
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      throw new Error(errBody.detail || `Investigation run failed: ${res.statusText}`);
    }
    return await res.json();
  }
};

window.API = API;
