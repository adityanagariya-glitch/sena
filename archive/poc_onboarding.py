import json
from typing import Dict, TypedDict, Any
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool

# --- 1. Define the State ---
from langgraph.graph.message import add_messages
from typing import Annotated

class OnboardingState(TypedDict):
    messages: Annotated[list, add_messages]
    form_data: Dict[str, Any]
    missing_fields: list

# --- 2. Mock RAG Knowledge Base (Local instead of Cloud) ---
MOCK_KNOWLEDGE_BASE = {
    "consent": "Under NDIS policies, you must explicitly provide consent before any physical support is provided. Your data is kept strictly confidential.",
    "pricing": "NDIS pricing limits are set by the NDIA. We charge the standard limits for core supports.",
    "isolation": "Your data is only visible to your specific service provider and is not shared with other NGOs."
}

@tool
def search_policy(query: str) -> str:
    """Use this tool to search for NDIS or company policies if the user asks a question."""
    # Simple keyword mock search
    query = query.lower()
    for key, value in MOCK_KNOWLEDGE_BASE.items():
        if key in query:
            return value
    return "I couldn't find a specific policy on that, but let me know if you want me to flag this for a human coordinator."

@tool
def update_form(field_name: str, value: str) -> str:
    """Use this tool to update the onboarding form when the user provides their details.
    Valid fields are: 'full_name', 'dob', 'ndis_number'."""
    return f"SUCCESS: updated {field_name} with '{value}'"

# --- 3. Build the LangGraph Nodes ---
llm = ChatOpenAI(model="gpt-4o", temperature=0)
tools = [search_policy, update_form]
llm_with_tools = llm.bind_tools(tools)

def chatbot_node(state: OnboardingState):
    system_prompt = SystemMessage(content=f"""
    You are a friendly, human-like AI support coordinator for an NDIS service provider.
    Your goal is to help the user complete their onboarding form.
    
    Current Form State: {json.dumps(state['form_data'])}
    Missing Fields: {', '.join(state['missing_fields'])}
    
    Instructions:
    1. If a user provides information for a missing field, use the `update_form` tool to save it.
    2. Then, gently ask them for the NEXT missing field.
    3. If the user asks a policy question, use the `search_policy` tool to answer them, then guide them back to the form.
    4. Keep your answers concise, natural, and warm. Do not sound robotic.
    """)
    
    # Exclude consecutive ToolMessages without a preceding AIMessage with tool_calls
    # to avoid OpenAI API errors. LangGraph state management usually handles this, 
    # but we need to ensure the system prompt is only added at the very beginning conceptually
    # or handle the messages appropriately.
    
    # simpler approach: just prepend system prompt to the existing history.
    messages = [system_prompt] + state["messages"]
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}

def tool_executor_node(state: OnboardingState):
    """Executes the tool and updates the form data in the state."""
    last_message = state["messages"][-1]
    
    new_form_data = state["form_data"].copy()
    missing_fields = state["missing_fields"].copy()
    msgs = []
    
    for tool_call in last_message.tool_calls:
        if tool_call["name"] == "update_form":
            field = tool_call["args"]["field_name"]
            val = tool_call["args"]["value"]
            new_form_data[field] = val
            if field in missing_fields:
                missing_fields.remove(field)
            msgs.append(ToolMessage(content=f"Tool update_form saved {field}={val}", tool_call_id=tool_call["id"]))
            
        elif tool_call["name"] == "search_policy":
            result = search_policy.invoke(tool_call["args"])
            msgs.append(ToolMessage(content=f"Tool search_policy returned: {result}", tool_call_id=tool_call["id"]))

    return {
        "messages": msgs,
        "form_data": new_form_data,
        "missing_fields": missing_fields
    }

def route_actions(state: OnboardingState):
    """Route to tools if the LLM called a tool, otherwise end turn."""
    last_msg = state["messages"][-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    return END

# --- 4. Assemble the Graph ---
workflow = StateGraph(OnboardingState)
workflow.add_node("chatbot", chatbot_node)
workflow.add_node("tools", tool_executor_node)

workflow.set_entry_point("chatbot")
workflow.add_conditional_edges("chatbot", route_actions, {"tools": "tools", END: END})
workflow.add_edge("tools", "chatbot")

app = workflow.compile()

# --- 5. Interactive Terminal Simulation ---
if __name__ == "__main__":
    print("🤖 Starting Sena AI Onboarding POC (Local)...")
    print("Type 'quit' to exit.\n")
    
    # Initialize the state
    state = {
        "messages": [],
        "form_data": {"full_name": None, "dob": None, "ndis_number": None},
        "missing_fields": ["full_name", "dob", "ndis_number"]
    }
    
    while state["missing_fields"]:
        user_input = input("User: ")
        if user_input.lower() == 'quit':
            break
            
        state["messages"].append(HumanMessage(content=user_input))
        
        # Run the graph
        for event in app.stream(state):
            for k, v in event.items():
                if k == "chatbot" and not v["messages"][-1].tool_calls:
                    print(f"\nSena AI: {v['messages'][-1].content}\n")
                
                # Update our local state loop
                if "form_data" in v:
                    state["form_data"] = v["form_data"]
                if "missing_fields" in v:
                    state["missing_fields"] = v["missing_fields"]
                # We don't need to manually extend messages when using Annotated[list, add_messages]
                # LangGraph handles the append internally now.

    if not state["missing_fields"]:
        print("✅ Onboarding complete! Final Form Data:")
        print(json.dumps(state["form_data"], indent=2))
