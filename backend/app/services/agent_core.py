import os
from dotenv import load_dotenv
load_dotenv()
import json
import logging
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
import google.generativeai as genai

logger = logging.getLogger("syncops.agent_core")

# Configure Gemini
api_key = os.getenv("GEMINI_API_KEY", "mock_key")
genai.configure(api_key=api_key)

class AgentDecision(BaseModel):
    action: str = Field(..., description="Action: 'Update Address', 'Check Inventory', 'Process Return', 'Upgrade Account', or 'No Action'")
    reasoning: str = Field(..., description="Internal step-by-step reasoning for this decision")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Extracted parameters needed for the API call")

class GeminiDecider:
    def __init__(self, model_name: Optional[str] = None):
        actual_model_name = model_name or os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
        self.model = genai.GenerativeModel(
            actual_model_name,
            generation_config={"response_mime_type": "application/json"}
        )

    async def make_decision(self, ticket_text: str, order_id: Optional[str] = None) -> AgentDecision:
        """Invokes Gemini to decide on the required course of action."""
        prompt = (
            "You are an enterprise operations decider agent.\n"
            "Analyze the support ticket, decide on the correct action, and extract parameters.\n"
            f"Ticket: {ticket_text}\n"
            f"Order ID (if any): {order_id}\n\n"
            "Output JSON matching this schema:\n"
            "{\n"
            "  \"action\": \"Action Name\",\n"
            "  \"reasoning\": \"Step-by-step reasoning\",\n"
            "  \"parameters\": {\"param_key\": \"value\"}\n"
            "}"
        )
        try:
            # Wrap the API call in an executor block if using a blocking SDK
            response = self.model.generate_content(prompt)
            data = json.loads(response.text)
            return AgentDecision(**data)
        except Exception as e:
            logger.exception("Gemini API call failed")
            # Return safe default fallback
            return AgentDecision(
                action="No Action",
                reasoning=f"Error in Gemini Decider: {str(e)}",
                parameters={}
            )

    async def execute_agent_loop(
        self,
        ticket_text: str,
        order_id: Optional[str],
        verifier: Optional[Any],
        execute_func: Any
    ) -> Dict[str, Any]:
        """Runs the decider-agent loop with validation verification and auto-correction retries."""
        attempts = 0
        max_attempts = 3
        error_context = ""
        decision = None
        api_result = None

        while attempts < max_attempts:
            attempts += 1
            logger.info("Agent execution loop attempt %d/%d", attempts, max_attempts)
            
            # 1. Ask Gemini Decider for action plan
            prompt = (
                "You are an enterprise operations agent.\n"
                "Decide the correct action and extract parameters.\n"
                f"Ticket: {ticket_text}\n"
                f"Order ID (if any): {order_id}\n"
            )
            if error_context:
                prompt += (
                    "\nWARNING: Your previous attempt failed with this error:\n"
                    f"{error_context}\n"
                    "Correct the parameters based on this error."
                )
            
            try:
                response = self.model.generate_content(prompt)
                data = json.loads(response.text)
                decision = AgentDecision(**data)
            except Exception as e:
                logger.exception("Failed to generate decision content")
                return {
                    "status": "error",
                    "message": f"Decider failure: {str(e)}",
                    "api_result": {"status_code": 500, "data": {"detail": "Internal decider failure"}}
                }

            # If no write action, execute read tool and return
            if decision.action == "No Action" or decision.action == "Check Inventory":
                api_result = await execute_func(decision)
                return {
                    "status": "success",
                    "action": decision.action,
                    "api_result": api_result,
                    "attempts": attempts
                }

            # 2. Consensus check (Verifier Gate)
            if verifier:
                is_agreed = await verifier.verify_action(ticket_text, decision.action)
                if not is_agreed:
                    logger.warning("Verifier gate blocked proposed action. Routing to human queue.")
                    return {
                        "status": "escalated",
                        "action": decision.action,
                        "message": "Escalated: Consensus verification failed",
                        "api_result": {"status_code": 403, "data": {"detail": "Consensus check failed"}}
                    }

            # 3. Invoke tool call
            api_result = await execute_func(decision)
            status_code = api_result.get("status_code", 500)
            
            if status_code < 400:
                # Success!
                logger.info("API call succeeded on attempt %d", attempts)
                return {
                    "status": "success",
                    "action": decision.action,
                    "api_result": api_result,
                    "attempts": attempts
                }
            else:
                # Failure! Extract validation details for correction context
                error_data = api_result.get("data", {})
                error_context = json.dumps(error_data)
                logger.warning(
                    "API call returned error %d. Error details: %s. Initiating self-correction.",
                    status_code, error_context
                )

        logger.error("Failed to complete action after %d attempts.", max_attempts)
        return {
            "status": "failed",
            "action": decision.action if decision else "unknown",
            "message": "Failed: Max retry limit reached",
            "api_result": api_result
        }
