const API_URL = 'http://localhost:8000';

export const uploadCircular = async (file) => {
    const formData = new FormData();
    formData.append('file', file);
    
    const response = await fetch(`${API_URL}/upload`, {
        method: 'POST',
        body: formData,
    });
    if (!response.ok) throw new Error('Failed to upload circular');
    return response.json();
};

export const importObligationsCsv = async (file) => {
    const formData = new FormData();
    formData.append('file', file);
    
    const response = await fetch(`${API_URL}/import/obligations`, {
        method: 'POST',
        body: formData,
    });
    if (!response.ok) throw new Error('Failed to import CSV obligations');
    return response.json();
};

export const getObligations = async () => {
    const response = await fetch(`${API_URL}/obligations`);
    if (!response.ok) throw new Error('Failed to fetch obligations');
    return response.json();
};

export const getReadiness = async () => {
    try {
        const response = await fetch(`${API_URL}/readiness`);
        if (!response.ok) return { has_regulatory_obligations: false, has_company_obligations: false, gap_analysis_available: false };
        return response.json();
    } catch {
        return { has_regulatory_obligations: false, has_company_obligations: false, gap_analysis_available: false };
    }
};

export const getGaps = async () => {
    const response = await fetch(`${API_URL}/gaps`);
    if (response.status === 400) {
        // No company obligations uploaded yet
        const body = await response.json().catch(() => ({}));
        return { __no_company_data: true, detail: body.detail || "Company obligations not uploaded." };
    }
    if (!response.ok) throw new Error('Failed to fetch gaps');
    return response.json();
};

export const getGapAnalysis = async () => {
    const response = await fetch(`${API_URL}/gaps`);
    if (response.status === 400) {
        const body = await response.json().catch(() => ({}));
        return { __no_company_data: true, detail: body.detail || "Company obligations not uploaded." };
    }
    if (!response.ok) throw new Error('Failed to fetch gap analysis');
    return response.json();
};

export const getCompanyObligations = async () => {
    const response = await fetch(`${API_URL}/company-obligations`);
    if (!response.ok) throw new Error('Failed to fetch company obligations');
    return response.json();
};

export const getEvidence = async () => {
    const response = await fetch(`${API_URL}/evidence`);
    if (!response.ok) throw new Error('Failed to fetch evidence');
    return response.json();
};

export const addEvidence = async (obligationId, description) => {
    const response = await fetch(`${API_URL}/evidence`, {
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
    const response = await fetch(`${API_URL}/audit_log`);
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
    const url = `${API_URL}/review/${encodeURIComponent(threadId)}/decision?decision=${encodeURIComponent(decision)}&actor=${encodeURIComponent(actor)}`;
    const response = await fetch(url, {
        method: 'POST',
    });
    if (!response.ok) throw new Error('Failed to submit review decision');
    return response.json();
};

export const getReviewQueue = async () => {
    const response = await fetch(`${API_URL}/review/queue`);
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
    const response = await fetch(`${API_URL}/review/${encodeURIComponent(threadId)}/submit`, {
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
