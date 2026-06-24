import os
import json
import logging
import httpx
from typing import Optional, Dict, Any

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger("syncops.verifier_gate")

OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e4b")

class ConsensusVerifier:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=15.0)

    async def verify_action(self, ticket_text: str, proposed_action: str, parameters: Optional[Dict[str, Any]] = None) -> bool:
        """Asks local Gemma model to verify if the proposed action and parameters are correct and safe."""
        if parameters is None:
            parameters = {}
            
        # Standard updates do not require consensus checks (address updates, inventory queries)
        # Critical writes like refunds (process_return) or deal status updates (upgrade_customer_tier) require consensus
        if proposed_action not in ["process_return", "upgrade_customer_tier", "Process Return", "Upgrade Account"]:
            logger.info(f"Action '{proposed_action}' does not require dual consensus check.")
            return True

        url = f"{OLLAMA_API_URL}/api/generate"
        prompt = (
            "You are an operations audit model. A primary agent has proposed executing "
            f"the action: '{proposed_action}' with parameters: {json.dumps(parameters)} "
            f"for the following customer request:\n"
            f"Ticket: {ticket_text}\n\n"
            "Decide if you agree that this action and its parameters are correct and safe to run.\n"
            "Return JSON matching this schema:\n"
            "{\n"
            "  \"action\": \"Your decided action name\",\n"
            "  \"parameters\": {\"param_key\": \"value\"},\n"
            "  \"is_safe\": true/false\n"
            "}"
        )
        
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.0}
        }
        
        try:
            logger.info("Verifying critical action '%s' with local consensus model '%s'...", proposed_action, OLLAMA_MODEL)
            response = await self.client.post(url, json=payload)
            if response.status_code == 200:
                result = response.json()
                content = result["response"]
                parsed = json.loads(content)
                
                local_action = parsed.get("action", "")
                local_params = parsed.get("parameters", {})
                is_safe = parsed.get("is_safe", False)
                
                # Compare parameters
                params_match = True
                for k, v in parameters.items():
                    local_val = local_params.get(k)
                    if str(local_val).strip() != str(v).strip():
                        params_match = False
                        break
                
                # Check for consensus alignment
                proposed_normalized = proposed_action.replace("_", " ").lower()
                local_normalized = local_action.replace("_", " ").lower()
                if is_safe and proposed_normalized == local_normalized and params_match:
                    logger.info("Consensus reached: Local model verified the action and parameters.")
                    return True
                else:
                    logger.warning(
                        "Consensus FAILED! Gemini proposed '%s' with %s, local model decided '%s' with %s (is_safe: %s)",
                        proposed_action, parameters, local_action, local_params, is_safe
                    )
                    return False
            else:
                logger.error("Consensus model returned status %s", response.status_code)
        except Exception as e:
            logger.error("Consensus verifier connection failure: %s. Defaulting to safe reject.", e)
            
        # Fail open or fail closed? For critical writes, fail closed (escalate to human)
        return False

    async def close(self):
        await self.client.aclose()

