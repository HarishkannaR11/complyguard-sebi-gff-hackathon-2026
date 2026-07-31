from typing import TypedDict, Literal, Optional, List

class ComplianceState(TypedDict):
    circular_id: str
    clause_id: str
    raw_clause: str
    heading: str
    embedding: Optional[List[float]]
    extracted_obligation: Optional[dict]
    similarity_match: Optional[dict]
    diff_status: Literal["new", "amended", "superseded", "unchanged", None]
    task: Optional[dict]
    evidence_status: Literal["present", "missing", "invalid", None]
    human_decision: Optional[str]
    audit_log: List[dict]
    
    # Structure metadata fields (V2 Upgrade)
    confidence: Optional[float]
    page: Optional[int]
    section: Optional[str]
    clause_num: Optional[str]
    parent_clause: Optional[str]
    block_type: Optional[str]