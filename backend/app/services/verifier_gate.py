import os
import json
import logging
import httpx

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger("syncops.verifier_gate")

OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e4b")

class ConsensusVerifier:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=15.0)

    async def verify_action(self, ticket_text: str, proposed_action: str) -> bool:
        """Asks local Qwen/Gemma model to verify if the proposed action is correct and safe."""
        # Standard updates do not require consensus checks (address updates, inventory queries)
        # Critical writes like refunds (Process Return) or deal status updates require consensus
        if proposed_action not in ["Process Return", "Upgrade Account"]:
            logger.info(f"Action '{proposed_action}' does not require dual consensus check.")
            return True

        url = f"{OLLAMA_API_URL}/api/generate"
        prompt = (
            "You are an operations audit model. A primary agent has proposed executing "
            f"the action: '{proposed_action}' for the following customer request:\n"
            f"Ticket: {ticket_text}\n\n"
            "Decide if you agree that this action is correct and safe to run.\n"
            "Return JSON matching this schema:\n"
            "{\n"
            "  \"action\": \"Your decided action name\",\n"
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
                is_safe = parsed.get("is_safe", False)
                
                # Check for consensus alignment
                if is_safe and local_action.lower() == proposed_action.lower():
                    logger.info("Consensus reached: Local model verified the action.")
                    return True
                else:
                    logger.warning(
                        "Consensus FAILED! Gemini proposed '%s', local model decided '%s' (is_safe: %s)",
                        proposed_action, local_action, is_safe
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
