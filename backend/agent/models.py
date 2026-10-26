import time
import uuid
from enum import Enum
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

class StepState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_CONFIRMATION = "waiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class PlanState(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    WAITING_CONFIRMATION = "waiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class AgentDecision(str, Enum):
    CONTINUE = "CONTINUE"
    STOP_SUCCESS = "STOP_SUCCESS"
    STOP_FAILURE = "STOP_FAILURE"
    RECOVER = "RECOVER"
    REPLAN = "REPLAN"

class GoalStatus(str, Enum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    FAILED = "FAILED"

class GoalEvaluation(BaseModel):
    status: GoalStatus
    reason: str
    remaining_requirements: List[str] = Field(default_factory=list)
    completed_step_ids: List[int] = Field(default_factory=list)
    failed_step_ids: List[int] = Field(default_factory=list)
    timestamp: float = Field(default_factory=time.time)

class SkillSelection(BaseModel):
    goal: str
    selected_skills: List[str] = Field(default_factory=list)
    unsupported_intents: List[str] = Field(default_factory=list)
    timestamp: float = Field(default_factory=time.time)

class WorkState(str, Enum):
    COMPLETED = "COMPLETED"
    IN_PROGRESS = "IN_PROGRESS"
    INTERRUPTED = "INTERRUPTED"
    FAILED = "FAILED"
    PAUSED = "PAUSED"
    RECOVERABLE = "RECOVERABLE"
    NOT_RESUMABLE = "NOT_RESUMABLE"

class RecoveryTimelineEventType(str, Enum):
    TASK_STARTED = "TASK_STARTED"
    ACTION_FAILED = "ACTION_FAILED"
    FAILURE_CLASSIFIED = "FAILURE_CLASSIFIED"
    RECOVERY_STARTED = "RECOVERY_STARTED"
    RECOVERY_STRATEGY_SELECTED = "RECOVERY_STRATEGY_SELECTED"
    RETRY_ATTEMPTED = "RETRY_ATTEMPTED"
    RECOVERY_SUCCEEDED = "RECOVERY_SUCCEEDED"
    TASK_RESUMED = "TASK_RESUMED"
    TASK_FAILED = "TASK_FAILED"
    # Feature #42 Timeline Events
    WORK_CONTEXT_FOUND = "WORK_CONTEXT_FOUND"
    RESUME_ANALYSIS_STARTED = "RESUME_ANALYSIS_STARTED"
    RESUME_CANDIDATE_SELECTED = "RESUME_CANDIDATE_SELECTED"
    RESUME_STATE_VERIFIED = "RESUME_STATE_VERIFIED"
    RESUME_CONFIRMATION_REQUIRED = "RESUME_CONFIRMATION_REQUIRED"
    RESUME_STATE_MISMATCH = "RESUME_STATE_MISMATCH"
    RESUME_FAILED = "RESUME_FAILED"
    RESUME_COMPLETED = "RESUME_COMPLETED"
    # Feature #43 Research Timeline Events
    RESEARCH_STARTED = "RESEARCH_STARTED"
    RESEARCH_PLAN_CREATED = "RESEARCH_PLAN_CREATED"
    SEARCH_STARTED = "SEARCH_STARTED"
    SEARCH_COMPLETED = "SEARCH_COMPLETED"
    SOURCE_SELECTED = "SOURCE_SELECTED"
    SOURCE_READ = "SOURCE_READ"
    CLAIM_EXTRACTED = "CLAIM_EXTRACTED"
    CONFLICT_DETECTED = "CONFLICT_DETECTED"
    SOURCE_REJECTED = "SOURCE_REJECTED"
    RESEARCH_RECOVERY_STARTED = "RESEARCH_RECOVERY_STARTED"
    RESEARCH_RESUMED = "RESEARCH_RESUMED"
    RESEARCH_COMPLETED = "RESEARCH_COMPLETED"
    RESEARCH_FAILED = "RESEARCH_FAILED"

class SourceQuality(str, Enum):
    PRIMARY = "PRIMARY"
    OFFICIAL = "OFFICIAL"
    REPUTABLE_SECONDARY = "REPUTABLE_SECONDARY"
    COMMUNITY = "COMMUNITY"
    UNKNOWN = "UNKNOWN"

class ClaimType(str, Enum):
    FACT = "FACT"
    INFERENCE = "INFERENCE"
    UNCERTAIN = "UNCERTAIN"

class ResearchSourceItem(BaseModel):
    title: str
    url: str
    snippet: str
    source_domain: str
    quality: SourceQuality = SourceQuality.UNKNOWN
    content_text: Optional[str] = None
    publication_date: Optional[str] = None
    is_read: bool = False
    relevance_score: float = 1.0

class ResearchClaimItem(BaseModel):
    claim_text: str
    claim_type: ClaimType = ClaimType.FACT
    supporting_urls: List[str] = Field(default_factory=list)
    extracted_snippet: str = ""
    confidence: str = "HIGH"  # HIGH, MEDIUM, LOW

class ResearchConflictItem(BaseModel):
    topic: str
    source_a_claim: str
    source_a_url: str
    source_b_claim: str
    source_b_url: str
    explanation: str

class ResearchTaskContext(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    objective: str
    depth: str = "standard"  # quick, standard, deep
    search_queries: List[str] = Field(default_factory=list)
    sources_discovered: List[ResearchSourceItem] = Field(default_factory=list)
    sources_read: List[ResearchSourceItem] = Field(default_factory=list)
    claims: List[ResearchClaimItem] = Field(default_factory=list)
    conflicts: List[ResearchConflictItem] = Field(default_factory=list)
    status: str = "IN_PROGRESS"  # IN_PROGRESS, COMPLETED, INTERRUPTED, FAILED
    confidence: str = "HIGH"
    timestamp: float = Field(default_factory=time.time)

class WorkContext(BaseModel):
    task_id: str
    task_objective: str
    project: Optional[str] = None
    application: Optional[str] = None
    active_window: Optional[str] = None
    task_status: str
    work_state: WorkState = WorkState.IN_PROGRESS
    completed_steps: List[Dict[str, Any]] = Field(default_factory=list)
    failed_step: Optional[Dict[str, Any]] = None
    remaining_steps: List[Dict[str, Any]] = Field(default_factory=list)
    last_successful_action: Optional[str] = None
    last_failure: Optional[str] = None
    recovery_state: Optional[str] = None
    relevant_project_context: Optional[Dict[str, Any]] = None
    timestamp: float = Field(default_factory=time.time)
    resumability: str = "RESUMABLE"  # "RESUMABLE", "NOT_RESUMABLE", "REQUIRES_CONFIRMATION", "AMBIGUOUS"
    resumable_step_index: int = 1
    reason: str = ""

class RecoveryTimelineEvent(BaseModel):
    event_type: RecoveryTimelineEventType
    task_id: str
    step_id: Optional[int] = None
    action: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)

class FailureRecord(BaseModel):
    error_type: str
    original_error: str
    failed_action: str
    task_id: str = ""
    step_id: int = 1
    timestamp: float = Field(default_factory=time.time)
    retry_count: int = 0
    is_recoverable: bool = True
    suggested_recovery_strategies: List[str] = Field(default_factory=list)

class ExecutionLogEntry(BaseModel):
    step_id: int
    skill: str
    status: StepState
    message: str
    error: Optional[str] = None
    timestamp: float = Field(default_factory=time.time)

class PlanStep(BaseModel):
    step_id: int
    description: str
    suggested_skill: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    requires_confirmation: bool = False
    status: StepState = StepState.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    replan_count: int = 0
    max_replans: int = 3

class StepObservation(BaseModel):
    step_id: int
    execution_status: StepState
    verification_status: str  # "passed" | "failed"
    observation: str
    decision: AgentDecision
    replan_count: int = 0
    suggested_replanned_step: Optional[PlanStep] = None
    recovery_strategy: Optional[str] = None
    timestamp: float = Field(default_factory=time.time)

class RecoveryAttemptRecord(BaseModel):
    step_id: int
    original_action: str
    failure: str
    recovery: str
    attempt: int
    result: str
    timestamp: float = Field(default_factory=time.time)

class AgentPlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    goal: str
    status: PlanState = PlanState.PENDING
    steps: List[PlanStep] = Field(default_factory=list)
    execution_log: List[ExecutionLogEntry] = Field(default_factory=list)
    observations: List[StepObservation] = Field(default_factory=list)
    evaluations: List[GoalEvaluation] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)

class AgentContext(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    goal: str
    status: StepState = StepState.RUNNING
    current_step: int = 1
    steps: List[PlanStep] = Field(default_factory=list)
    completed_steps: List[int] = Field(default_factory=list)
    failed_steps: List[int] = Field(default_factory=list)
    observations: List[str] = Field(default_factory=list)
    recovery_history: List[RecoveryAttemptRecord] = Field(default_factory=list)
    pending_confirmation: Optional[Dict[str, Any]] = None
    replan_count: int = 0
    relevant_memory: List[str] = Field(default_factory=list)
    active_window: Optional[Dict[str, Any]] = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
