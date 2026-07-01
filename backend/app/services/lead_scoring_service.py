import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.models.icp import ICP
from app.services.grok_service import GrokService

logger = logging.getLogger(__name__)


class LeadScoringService:
    """
    Three-layer lead scoring pipeline, in order:

      1. Hard disqualifiers (rules)     - instant reject conditions (e.g. no
                                           email, wrong region, banned industry)
      2. ICP fit score (rules)          - cheap firmographic match against the
                                           ICP, computed without any API call
      3. BANT + MEDDIC (Grok / AI)      - qualitative scoring layer, only run
                                           if the lead survives step 1

    Final `score` shown in the UI = weighted blend of icp_fit + bant_total +
    meddic_total. This keeps obviously-bad leads cheap to filter (no wasted
    Grok calls) while still giving every surviving lead a rich BANT/MEDDIC
    breakdown for the qualification view.
    """

    # Weights for the final blended 0-100 score
    WEIGHT_ICP_FIT = 0.35
    WEIGHT_BANT = 0.30
    WEIGHT_MEDDIC = 0.35

    @staticmethod
    def check_hard_disqualifiers(
        lead_data: Dict[str, Any],
        icp: ICP,
    ) -> Tuple[bool, List[str]]:
        """
        Rules-based instant-reject layer. Returns (is_disqualified, reasons).
        Runs BEFORE any AI call so obviously bad leads never cost a Grok request.
        """
        reasons: List[str] = []

        # No way to contact them at all
        if not lead_data.get("email") and not lead_data.get("phone") and not lead_data.get("linkedin_url"):
            reasons.append("No contact method available (no email, phone, or LinkedIn)")

        # Geography hard-filter, only enforced if the ICP specifies regions
        target_regions = icp.target_regions or []
        location = (lead_data.get("location") or "").lower()
        if target_regions and location:
            region_match = any(region.lower() in location for region in target_regions)
            if not region_match:
                reasons.append(f"Location '{lead_data.get('location')}' outside target regions {target_regions}")

        # Company size hard-filter, only enforced if both sides have parseable numbers
        size_range = LeadScoringService._parse_size_range(icp.company_size_range)
        lead_size = LeadScoringService._parse_company_size(lead_data.get("company_size"))
        if size_range and lead_size is not None:
            low, high = size_range
            if lead_size < low * 0.5 or lead_size > high * 2:
                # Generous tolerance (0.5x-2x) - this is a hard filter only for
                # wildly-off company sizes, not a strict gate.
                reasons.append(
                    f"Company size {lead_size} far outside ICP range {icp.company_size_range}"
                )

        return (len(reasons) > 0, reasons)

    @staticmethod
    def compute_icp_fit_score(lead_data: Dict[str, Any], icp: ICP) -> int:
        """
        Cheap, deterministic 0-100 score for how well firmographics match
        the ICP. No API calls. This is what lets "Generate from ICP" rank
        a batch of Apollo results before spending Grok calls on all of them.
        """
        points = 0
        max_points = 0

        # Title match against decision_maker_titles (40 pts)
        max_points += 40
        title = (lead_data.get("title") or "").lower()
        decision_titles = [t.lower() for t in (icp.decision_maker_titles or [])]
        if title and decision_titles:
            if any(dt in title or title in dt for dt in decision_titles):
                points += 40
            elif any(word in title for dt in decision_titles for word in dt.split()):
                points += 20

        # Industry match (25 pts)
        max_points += 25
        industry = (lead_data.get("company_industry") or "").lower()
        target_industries = [i.lower() for i in (icp.target_industries or [])]
        if industry and target_industries:
            if any(ti in industry or industry in ti for ti in target_industries):
                points += 25
            elif any(word in industry for ti in target_industries for word in ti.split()):
                points += 10

        # Company size fit (20 pts)
        max_points += 20
        size_range = LeadScoringService._parse_size_range(icp.company_size_range)
        lead_size = LeadScoringService._parse_company_size(lead_data.get("company_size"))
        if size_range and lead_size is not None:
            low, high = size_range
            if low <= lead_size <= high:
                points += 20
            elif low * 0.5 <= lead_size <= high * 2:
                points += 10

        # Region fit (15 pts)
        max_points += 15
        target_regions = [r.lower() for r in (icp.target_regions or [])]
        location = (lead_data.get("location") or "").lower()
        if location and target_regions:
            if any(region in location for region in target_regions):
                points += 15
        elif not target_regions:
            # No region constraint set on the ICP - don't penalize
            points += 15

        if max_points == 0:
            return 50  # neutral default if ICP has no comparable fields set

        return round((points / max_points) * 100)

    @staticmethod
    async def score_lead(
        lead_data: Dict[str, Any],
        icp: ICP,
    ) -> Dict[str, Any]:
        """
        Run the full 3-layer pipeline for one lead and return everything
        needed to populate the Lead model: disqualification, icp_fit_score,
        bant_*, meddic_*, final blended score, and the UI-facing reasoning
        string.
        """
        is_disqualified, dq_reasons = LeadScoringService.check_hard_disqualifiers(lead_data, icp)

        icp_fit_score = LeadScoringService.compute_icp_fit_score(lead_data, icp)

        result: Dict[str, Any] = {
            "is_disqualified": is_disqualified,
            "disqualify_reasons": dq_reasons,
            "icp_fit_score": icp_fit_score,
        }

        if is_disqualified:
            # Don't waste a Grok call on a lead we're rejecting outright.
            result.update({
                "score": max(5, round(icp_fit_score * 0.2)),
                "status": "Discarded",
                "reasoning": "Auto-discarded: " + "; ".join(dq_reasons),
                "bant_budget_score": None,
                "bant_authority_score": None,
                "bant_need_score": None,
                "bant_timeline_score": None,
                "bant_total_score": None,
                "bant_notes": None,
                "meddic_metrics_score": None,
                "meddic_economic_buyer_score": None,
                "meddic_decision_criteria_score": None,
                "meddic_decision_process_score": None,
                "meddic_identify_pain_score": None,
                "meddic_champion_score": None,
                "meddic_total_score": None,
                "meddic_notes": None,
                "grok_scoring_response": None,
            })
            return result

        icp_dict = {
            "target_industries": icp.target_industries,
            "company_size_range": icp.company_size_range,
            "target_revenues": icp.target_revenues,
            "decision_maker_titles": icp.decision_maker_titles,
            "pain_points": icp.pain_points,
            "key_characteristics": icp.key_characteristics,
        }

        try:
            ai_result = await GrokService.score_lead_bant_meddic(lead_data, icp_dict)
        except Exception as e:
            logger.warning("Grok scoring failed for lead %s, falling back to ICP-fit only: %s",
                            lead_data.get("name"), str(e))
            ai_result = {}

        bant_scores = [
            ai_result.get("bant_budget_score"),
            ai_result.get("bant_authority_score"),
            ai_result.get("bant_need_score"),
            ai_result.get("bant_timeline_score"),
        ]
        bant_valid = [s for s in bant_scores if isinstance(s, (int, float))]
        bant_total = round(sum(bant_valid) / len(bant_valid)) if bant_valid else None

        meddic_scores = [
            ai_result.get("meddic_metrics_score"),
            ai_result.get("meddic_economic_buyer_score"),
            ai_result.get("meddic_decision_criteria_score"),
            ai_result.get("meddic_decision_process_score"),
            ai_result.get("meddic_identify_pain_score"),
            ai_result.get("meddic_champion_score"),
        ]
        meddic_valid = [s for s in meddic_scores if isinstance(s, (int, float))]
        meddic_total = round(sum(meddic_valid) / len(meddic_valid)) if meddic_valid else None

        # Blend the three layers. If Grok failed entirely, fall back to ICP fit alone.
        if bant_total is not None and meddic_total is not None:
            final_score = round(
                icp_fit_score * LeadScoringService.WEIGHT_ICP_FIT
                + bant_total * LeadScoringService.WEIGHT_BANT
                + meddic_total * LeadScoringService.WEIGHT_MEDDIC
            )
        else:
            final_score = icp_fit_score

        final_score = max(0, min(100, final_score))

        reasoning = ai_result.get("reasoning") or (
            f"{lead_data.get('company', 'This company')} scores {icp_fit_score}/100 on ICP fit "
            f"based on firmographics; AI qualification unavailable."
        )

        result.update({
            "score": final_score,
            "status": "Analyzed" if final_score >= 65 else "New",
            "reasoning": reasoning,
            "bant_budget_score": ai_result.get("bant_budget_score"),
            "bant_authority_score": ai_result.get("bant_authority_score"),
            "bant_need_score": ai_result.get("bant_need_score"),
            "bant_timeline_score": ai_result.get("bant_timeline_score"),
            "bant_total_score": bant_total,
            "bant_notes": ai_result.get("bant_notes"),
            "meddic_metrics_score": ai_result.get("meddic_metrics_score"),
            "meddic_economic_buyer_score": ai_result.get("meddic_economic_buyer_score"),
            "meddic_decision_criteria_score": ai_result.get("meddic_decision_criteria_score"),
            "meddic_decision_process_score": ai_result.get("meddic_decision_process_score"),
            "meddic_identify_pain_score": ai_result.get("meddic_identify_pain_score"),
            "meddic_champion_score": ai_result.get("meddic_champion_score"),
            "meddic_total_score": meddic_total,
            "meddic_notes": ai_result.get("meddic_notes"),
            "grok_scoring_response": ai_result.get("full_response"),
        })
        return result

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    @staticmethod
    def _parse_company_size(value: Optional[str]) -> Optional[int]:
        """'247' -> 247, '50-200' -> 125 (midpoint), '1,000+' -> 1000, None -> None"""
        if not value:
            return None
        numbers = [int(n) for n in re.findall(r"\d+", value.replace(",", ""))]
        if not numbers:
            return None
        if len(numbers) == 1:
            return numbers[0]
        return round(sum(numbers[:2]) / 2)

    @staticmethod
    def _parse_size_range(value: Optional[str]) -> Optional[Tuple[int, int]]:
        """'10-50' -> (10, 50), '200+' -> (200, 100000), None -> None"""
        if not value:
            return None
        numbers = [int(n) for n in re.findall(r"\d+", value.replace(",", ""))]
        if not numbers:
            return None
        if len(numbers) == 1:
            return (numbers[0], numbers[0] * 100)
        return (min(numbers[:2]), max(numbers[:2]))