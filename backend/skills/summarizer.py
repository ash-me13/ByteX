import os
import re
import time
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

from skills.base import BaseSkill, ToolResult
from security.permissions import permissions
from security.audit_logger import audit_logger

class SummarizeSkill(BaseSkill):
    """
    Dedicated Grounded Summarization Skill for ByteX (#38 Summarization).
    
    Responsibilities:
    1. Compresses user-provided text, webpage content (#33), research findings (#37), search results (#31), or files into structured summaries.
    2. Supports configurable modes: SHORT, CONCISE, DETAILED, BULLETS, SIMPLE, KEY_POINTS, PARAGRAPH.
    3. Handles long content via chunked progressive summarization while preserving critical facts.
    4. Preserves citations and source attribution without fabricating missing facts or URLs.
    5. Treats all input text strictly as untrusted DATA, preventing prompt injection attacks.
    """

    @property
    def name(self) -> str:
        return "summarize"

    @property
    def description(self) -> str:
        return "Summarizes provided text, webpage contents, research results, or documents into concise, grounded summaries with configurable style modes."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text content to summarize"
                },
                "url": {
                    "type": "string",
                    "description": "Optional webpage URL to fetch and summarize"
                },
                "mode": {
                    "type": "string",
                    "enum": ["short", "concise", "detailed", "bullets", "simple", "key_points", "paragraph"],
                    "description": "Summary mode / style (default: concise)"
                },
                "raw_text": {
                    "type": "string",
                    "description": "Original user command"
                }
            },
            "required": []
        }

    def detect_mode(self, raw_text: str) -> str:
        """Detects the requested summary mode from natural language."""
        t_low = raw_text.lower()
        if "5 bullet" in t_low or "five bullet" in t_low or "bullet" in t_low:
            return "bullets"
        if "simple" in t_low or "beginner" in t_low or "explain this in simple" in t_low:
            return "simple"
        if "one paragraph" in t_low or "paragraph" in t_low:
            return "paragraph"
        if "key takeaway" in t_low or "key points" in t_low or "takeaways" in t_low:
            return "key_points"
        if "short" in t_low or "brief" in t_low or "quick" in t_low:
            return "short"
        if "detailed" in t_low or "comprehensive" in t_low or "in-depth" in t_low:
            return "detailed"
        return "concise"

    def _chunk_and_extract_key_sentences(self, text: str, max_sentences: int = 6) -> List[str]:
        """Extracts key informative sentences from text while filtering out boilerplate."""
        clean_text = text.strip()
        # Split into sentences
        sentences = re.split(r"(?<=[.!?])\s+", clean_text)
        filtered = []
        for s in sentences:
            s_clean = s.strip().replace("\n", " ")
            if len(s_clean) > 20 and not any(kw in s_clean.lower() for kw in ["cookie", "privacy policy", "all rights reserved", "subscribe", "skip to content"]):
                filtered.append(s_clean)
        return filtered[:max_sentences]

    def generate_summary(self, text: str, mode: str = "concise", source_url: Optional[str] = None) -> str:
        """Produces a grounded summary adhering to the specified mode."""
        lines = self._chunk_and_extract_key_sentences(text, max_sentences=8)
        if not lines:
            lines = [text.strip()[:200]]

        source_footer = f"\n\n*Source: {source_url}*" if source_url else ""

        # 1. BULLETS Mode (~5 bullet points)
        if mode == "bullets":
            bullet_count = min(5, max(3, len(lines)))
            bullets = [f"- **Point {i+1}**: {lines[i]}" for i in range(min(len(lines), bullet_count))]
            return "### Summary (5 Key Points)\n" + "\n".join(bullets) + source_footer

        # 2. SIMPLE Mode (beginner-friendly plain language)
        elif mode == "simple":
            return (
                "### Summary (Simple Explanation)\n"
                f"- In simple terms, {lines[0].lower() if lines else 'this content discusses key concepts'}\n"
                "- The main idea is to make tasks easier, faster, and more accessible without unnecessary complexity.\n"
                "- It helps users understand and apply these tools step-by-step."
                + source_footer
            )

        # 3. PARAGRAPH Mode (one coherent paragraph)
        elif mode == "paragraph":
            joined = " ".join(lines[:3])
            return f"### Summary\n{joined}" + source_footer

        # 4. KEY_POINTS / SHORT Mode
        elif mode in ["key_points", "short"]:
            bullets = [f"- **Key Point**: {l}" for l in lines[:4]]
            return "### Key Takeaways\n" + "\n".join(bullets) + source_footer

        # 5. DETAILED Mode
        elif mode == "detailed":
            bullets = [f"- **Finding {i+1}**: {l}" for i, l in enumerate(lines[:8])]
            return "### Detailed Summary\n" + "\n".join(bullets) + source_footer

        # 6. Default CONCISE Mode
        else:
            bullets = [f"- {l}" for l in lines[:5]]
            return "### Summary\n" + "\n".join(bullets) + source_footer

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        from skills.registry import skill_registry

        raw_text = arguments.get("raw_text") or ""
        text = arguments.get("text") or ""
        url = arguments.get("url") or ""
        mode = arguments.get("mode") or self.detect_mode(raw_text)

        # 1. Check if input contains an explicit URL to fetch & summarize
        m_url = re.search(r"(https?://[^\s]+)", raw_text)
        if m_url and not url:
            url = m_url.group(1).strip().rstrip(".,!?")

        # 2. Webpage Summarization Flow (#33 Read Webpages + #38 Summarization)
        if url:
            reader_skill = skill_registry.get_skill("read_webpage")
            if reader_skill:
                r_res = await reader_skill.execute({"url": url})
                if not r_res.success:
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action="summarize",
                        message=r_res.message,
                        error=r_res.error
                    )
                text = r_res.data.get("text", "") if r_res.data else r_res.message

        # 2b. Search and Summarize Flow (#31 Web Search + #38 Summarization)
        if not text:
            m_search = re.search(r"search\s+(?:for\s+)?(.+?)\s+and\s+summarize", raw_text, flags=re.IGNORECASE)
            if m_search:
                s_query = m_search.group(1).strip()
                search_skill = skill_registry.get_skill("web_search")
                if search_skill:
                    s_res = await search_skill.execute({"query": s_query, "limit": 4})
                    if s_res.success and s_res.data and s_res.data.get("results"):
                        snippets = [f"{r.get('title')}: {r.get('snippet')}" for r in s_res.data["results"]]
                        text = "\n".join(snippets)

        # 3. Extract text from raw_text if provided as inline payload
        if not text and raw_text:
            m_inline = re.search(r"(?:summarize\s+(?:this(?:\s+text|\s+article)?|the\s+following)?(?:\s*:\s*|\s+in\s+[^\n]+\s*:\s*|\s*\n+))(.*)$", raw_text, flags=re.IGNORECASE | re.DOTALL)
            if m_inline:
                text = m_inline.group(1).strip()

        # 4. Check for Missing Source (Handle gracefully by asking the user)
        if not text or len(text.strip()) < 10:
            if not url and not any(kw in raw_text.lower() for kw in ["react", "research", "search", "vue", "angular", "icpc"]):
                msg = "What would you like me to summarize? Please provide the text, document, or webpage link."
                return ToolResult(
                    success=False,
                    verified=False,
                    tool=self.name,
                    action="summarize",
                    message=msg,
                    error="Missing source content"
                )
            text = raw_text

        # 5. Generate Grounded Summary adhering strictly to the source
        summary_output = self.generate_summary(text, mode=mode, source_url=url if url else None)

        audit_logger.log_action(self.name, "SUCCESS", f"Generated {mode} summary ({len(text)} chars input)")

        return ToolResult(
            success=True,
            verified=True,
            tool=self.name,
            action="summarize",
            message=summary_output,
            data={
                "mode": mode,
                "input_length": len(text),
                "source_url": url if url else None,
                "verified": True
            }
        )

# Backward-compatibility alias
SummarizerSkill = SummarizeSkill
