import os
from dotenv import load_dotenv
import json
import logging
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
import google.generativeai as genai

load_dotenv()

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
        self.model_name = actual_model_name
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
        execute_func: Any,
        tools: list
    ) -> Dict[str, Any]:
        """Runs the decider-agent loop with validation verification and auto-correction retries."""
        attempts = 0
        max_attempts = 3
        error_context = ""
        decision = None
        api_result = None

        # Build tools list for Gemini GenerativeModel
        gemini_tools = map_mcp_tools_to_gemini(tools)
        
        # Instantiate GenerativeModel with tools
        model = genai.GenerativeModel(
            self.model_name,
            tools=[gemini_tools] if gemini_tools else None
        )

        while attempts < max_attempts:
            attempts += 1
            logger.info("Agent execution loop attempt %d/%d", attempts, max_attempts)
            
            prompt = (
                "You are an enterprise operations decider agent.\n"
                "Analyze the support ticket, decide on the correct action, and call the appropriate tool. "
                "If no tool matches the request, or if no action is needed, respond with text explaining why.\n"
                f"Ticket: {ticket_text}\n"
                f"Order ID (if any): {order_id}\n"
            )
            # FIX: Explicit comparison prevents literal-tracking warning
            if error_context != "":
                prompt += (
                    "\nWARNING: Your previous tool invocation failed with this error:\n"
                    f"{error_context}\n"
                    "Please correct the parameters and try invoking the tool again with the corrected values."
                )
            
            try:
                response = model.generate_content(prompt)
                
                # Check for function call
                action = "No Action"
                parameters = {}
                reasoning = ""
                
                try:
                    candidate = response.candidates[0]
                    part = candidate.content.parts[0]
                    if hasattr(part, "function_call") and part.function_call:
                        function_call = part.function_call
                        action = function_call.name
                        parameters = dict(function_call.args)
                    else:
                        reasoning = part.text or ""
                except Exception as e:
                    logger.warning(f"Error parsing Gemini response content parts: {e}")
                    # FIX: Use getattr to eliminate unconditional object evaluation
                    reasoning = getattr(response, "text", "")
                
                decision = AgentDecision(
                    action=action,
                    reasoning=reasoning,
                    parameters=parameters
                )
            except Exception as e:
                logger.exception("Failed to generate decision content")
                return {
                    "status": "error",
                    "message": f"Decider failure: {str(e)}",
                    "api_result": {"status_code": 500, "data": {"detail": "Internal decider failure"}}
                }

            # If no write action (No Action), return success
            if decision.action == "No Action":
                return {
                    "status": "success",
                    "action": decision.action,
                    "api_result": {"status_code": 200, "data": {"detail": "No action required"}},
                    "attempts": attempts
                }

            # 2. Consensus check (Verifier Gate)
            if verifier:
                is_agreed = await verifier.verify_action(ticket_text, decision.action, decision.parameters)
                if not is_agreed:
                    logger.warning("Verifier gate blocked proposed action. Routing to human queue.")
                    return {
                        "status": "escalated",
                        "action": decision.action,
                        "message": "Escalated: Consensus verification failed",
                        "api_result": {"status_code": 403, "data": {"detail": "Consensus check failed"}}
                    }

            # 3. Invoke tool call
            try:
                api_result = await execute_func(decision.action, decision.parameters)
            except Exception as e:
                logger.exception("Tool execution failed")
                api_result = {"status_code": 500, "data": {"detail": str(e)}}
                
            # Type-guarding avoids passing a wide union type into int()
            raw_status = api_result.get("status_code", 500) if isinstance(api_result, dict) else 500
            status_code = raw_status if isinstance(raw_status, int) else 500
            
            if status_code < 400:
                # Success!
                logger.info("Tool call succeeded on attempt %d", attempts)
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
                    "Tool call returned error %d. Error details: %s. Initiating self-correction.",
                    status_code, error_context
                )

        logger.error("Failed to complete action after %d attempts.", max_attempts)
        return {
            "status": "failed",
            "action": decision.action if decision else "unknown",
            "message": "Failed: Max retry limit reached",
            "api_result": api_result
        }

def clean_schema(schema: dict) -> dict:
    """Recursively converts all JSON schema type strings to uppercase for Gemini."""
    if not isinstance(schema, dict):
        return schema
    
    # FIX: Explicit type hint prevents dictionary type-locking
    cleaned: Dict[str, Any] = {}
    for k, v in schema.items():
        if k == "type" and isinstance(v, str):
            cleaned[k] = v.upper()
        elif isinstance(v, dict):
            cleaned[k] = clean_schema(v)
        elif isinstance(v, list):
            cleaned[k] = [clean_schema(item) if isinstance(item, dict) else item for item in v]
        else:
            cleaned[k] = v
            
    cleaned.pop("$schema", None)
    cleaned.pop("additionalProperties", None)
    return cleaned

def map_mcp_tools_to_gemini(mcp_tools: list) -> Optional[Any]:
    """Maps a list of MCP tools to a google.generativeai.types.Tool object."""
    if not mcp_tools:
        return None
    declarations = []
    for tool in mcp_tools:
        name = getattr(tool, "name", None) or tool.get("name")
        description = getattr(tool, "description", None) or tool.get("description")
        input_schema = getattr(tool, "inputSchema", None) or tool.get("inputSchema")
        
        if not name:
            continue
            
        cleaned_parameters = clean_schema(input_schema)
        fd = genai.types.FunctionDeclaration(
            name=name,
            description=description or "",
            parameters=cleaned_parameters
        )
        declarations.append(fd)
        
    if not declarations:
        return None
    return genai.types.Tool(function_declarations=declarations)

