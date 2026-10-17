const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const API_KEY = import.meta.env.VITE_API_KEY || '';

/** fetch() against the API: prefixes the base URL and adds the X-API-Key header. */
const apiFetch = (path, options = {}) => {
    const headers = { ...(options.headers || {}) };
    if (API_KEY) headers['X-API-Key'] = API_KEY;
    return fetch(`${API_URL}${path}`, { ...options, headers });
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const JOB_POLL_INTERVAL_MS = 1500;
const JOB_TIMEOUT_MS = 30 * 60 * 1000;

const errorDetail = async (response, fallback) => {
    const body = await response.json().catch(() => ({}));
    return typeof body.detail === 'string' ? body.detail : fallback;
};

/**
 * Upload a circular. The server parses the PDF immediately, then processes clauses in a
 * background job; this polls that job and resolves with the same summary the old
 * synchronous endpoint returned ({ circular_id, results, ... }).
 * @param {File} file
 * @param {(progress: {done: number, total: number}) => void} [onProgress]
 */
export const uploadCircular = async (file, onProgress) => {
    const formData = new FormData();
    formData.append('file', file);

    const response = await apiFetch('/upload', { method: 'POST', body: formData });
    if (!response.ok) throw new Error(await errorDetail(response, 'Failed to upload circular'));
    const accepted = await response.json();
    if (response.status !== 202) return accepted; // nothing to process (e.g. 0 clauses)

    const deadline = Date.now() + JOB_TIMEOUT_MS;
    while (Date.now() < deadline) {
        await sleep(JOB_POLL_INTERVAL_MS);
        const poll = await apiFetch(`/jobs/${encodeURIComponent(accepted.job_id)}`);
        if (!poll.ok) throw new Error(await errorDetail(poll, 'Failed to check upload progress'));
        const job = await poll.json();
        if (onProgress) onProgress({ done: job.clauses_done, total: job.clauses_total });
        if (job.status === 'completed') return job.result;
        if (job.status === 'failed') throw new Error(job.error || 'Circular processing failed');
    }
    throw new Error('Timed out waiting for the circular to finish processing');
};

export const importObligationsCsv = async (file) => {
    const formData = new FormData();
    formData.append('file', file);
    
    const response = await apiFetch(`/import/obligations`, {
        method: 'POST',
        body: formData,
    });
    if (!response.ok) throw new Error('Failed to import CSV obligations');
    return response.json();
};

export const getObligations = async () => {
    const response = await apiFetch(`/obligations`);
    if (!response.ok) throw new Error('Failed to fetch obligations');
    return response.json();
};

export const getReadiness = async () => {
    try {
        const response = await apiFetch(`/readiness`);
        if (!response.ok) return { has_regulatory_obligations: false, has_company_obligations: false, gap_analysis_available: false };
        return response.json();
    } catch {
        return { has_regulatory_obligations: false, has_company_obligations: false, gap_analysis_available: false };
    }
};

export const getWorkflowState = async () => {
    try {
        const response = await apiFetch(`/workflow-state`);
        if (!response.ok) return { state: 'IDLE', can_upload: true };
        return response.json();
    } catch {
        return { state: 'IDLE', can_upload: true };
    }
};

export const finishWorkflow = async () => {
    const response = await apiFetch(`/workflow/finish`, { method: 'POST' });
    if (!response.ok) throw new Error('Failed to complete workflow');
    return response.json();
};

export const startComplianceWorkflow = async () => {
    const response = await apiFetch(`/workflow/start-compliance`, { method: 'POST' });
    if (!response.ok) throw new Error('Failed to start compliance workflow');
    return response.json();
};

export const getGaps = async () => {
    const response = await apiFetch(`/gaps`);
    if (response.status === 400) {
        // No company obligations uploaded yet
        const body = await response.json().catch(() => ({}));
        return { __no_company_data: true, detail: body.detail || "Company obligations not uploaded." };
    }
    if (!response.ok) throw new Error('Failed to fetch gaps');
    return response.json();
};

export const getGapAnalysis = async () => {
    const response = await apiFetch(`/gaps`);
    if (response.status === 400) {
        const body = await response.json().catch(() => ({}));
        return { __no_company_data: true, detail: body.detail || "Company obligations not uploaded." };
    }
    if (!response.ok) throw new Error('Failed to fetch gap analysis');
    return response.json();
};

export const getCompanyObligations = async () => {
    const response = await apiFetch(`/company-obligations`);
    if (!response.ok) throw new Error('Failed to fetch company obligations');
    return response.json();
};

export const getEvidence = async () => {
    const response = await apiFetch(`/evidence`);
    if (!response.ok) throw new Error('Failed to fetch evidence');
    return response.json();
};

export const addEvidence = async (obligationId, description) => {
    const response = await apiFetch(`/evidence`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            obligation_id: obligationId,
            description: description,
        }),
    });
    if (!response.ok) throw new Error('Failed to add evidence');
    return response.json();
};

export const getAuditLog = async () => {
    const response = await apiFetch(`/audit_log`);
    if (!response.ok) throw new Error('Failed to fetch audit log');
    return response.json();
};

/**
 * @param {string} threadId - Unique thread identifier (e.g. "circular_id:clause_id")
 * @param {string} decision - Review decision ("approve", "reject", "amend:...")
 * @param {string} [actor="reviewer"]
 */
export const submitReviewDecision = async (threadId, decision, actor = "reviewer") => {
    if (!threadId || typeof threadId !== "string" || threadId.trim() === "" || threadId === "undefined") {
        console.error("Invalid threadId provided to submitReviewDecision:", threadId);
        throw new Error("Missing or invalid review thread identifier (threadId)");
    }
    const url = `/review/${encodeURIComponent(threadId)}/decision?decision=${encodeURIComponent(decision)}&actor=${encodeURIComponent(actor)}`;
    const response = await apiFetch(url, {
        method: 'POST',
    });
    if (!response.ok) throw new Error('Failed to submit review decision');
    return response.json();
};

export const getReviewQueue = async () => {
    const response = await apiFetch(`/review/queue`);
    if (!response.ok) throw new Error('Failed to fetch review queue');
    return response.json();
};

/**
 * @param {string} threadId - Unique thread identifier (e.g. "circular_id:clause_id")
 * @param {string} action - Action type ("approve", "reject", "edit")
 * @param {Object} [obligationData=null]
 */
export const submitReviewAction = async (threadId, action, obligationData = null) => {
    if (!threadId || typeof threadId !== "string" || threadId.trim() === "" || threadId === "undefined") {
        console.error("Invalid threadId provided to submitReviewAction:", threadId);
        throw new Error("Missing or invalid review thread identifier (threadId)");
    }
    const response = await apiFetch(`/review/${encodeURIComponent(threadId)}/submit`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            action: action,
            obligation_data: obligationData,
        }),
    });
    if (!response.ok) throw new Error('Failed to submit review action');
    return response.json();
};
