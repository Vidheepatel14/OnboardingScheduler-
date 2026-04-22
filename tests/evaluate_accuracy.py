import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))

import json
from src.core.agent import chat_with_agent, conversation_history

# Mock the execution to only capture intent
def run_evaluation():
    print("========================================")
    print("🧪 STARTING AGENT EVALUATION")
    print("========================================")

    test_cases = [
        {
            "name": "Intent: RAG Search",
            "input": "What is the policy on vacations?",
            "expected_tool": "search_policy",
            "expected_param": "vacation"
        },
        {
            "name": "Intent: Check Schedule",
            "input": "When can I have a meeting?",
            "expected_tool": "check_calendar",
            "expected_param": None
        },
        {
            "name": "Intent: Update Progress",
            "input": "I finished task 101",
            "expected_tool": "mark_complete",
            "expected_param": "101"
        }
    ]

    score = 0
    
    for test in test_cases:
        print(f"\n🔹 Testing: {test['name']}")
        
        # Reset history for clean test
        conversation_history.clear()
        
        # We assume chat_with_agent prints the decision in debug or we parse the history
        # For this test, we peek into the Agent's internal logic by simulating the prompt:
        
        # (In a real unit test, we would mock the hosted LLM call, but here we run it live)
        response = chat_with_agent(test['input'], "test@user.com")
        
        # Check history to see what the agent *tried* to do
        last_action = None
        for msg in conversation_history:
            if msg['role'] == 'assistant':
                try:
                    data = json.loads(msg['content'])
                    if data.get('action') == 'tool_use':
                        last_action = data
                except: pass
        
        if last_action and last_action['tool_name'] == test['expected_tool']:
            print(f"   ✅ PASS: Selected {test['expected_tool']}")
            score += 1
        else:
            print(f"   ❌ FAIL: Expected {test['expected_tool']}, got {last_action}")

    print("========================================")
    print(f"📊 FINAL SCORE: {score}/{len(test_cases)}")
    print("========================================")

if __name__ == "__main__":
    run_evaluation()
