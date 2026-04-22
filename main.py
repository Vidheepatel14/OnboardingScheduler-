from src.database.connection import init_db
from src.database.task_repository import assign_initial_tasks
from src.core.agent import AgentSession

USER_EMAIL = "vpatel141100@gmail.com"

def main():
    print("==========================================")
    print("🚀 Onboarding Assistant Online")
    print("   Type 'exit' to quit.")
    print("==========================================")
    
    # 1. Setup Data
    init_db()
    assign_initial_tasks(USER_EMAIL)
    session = AgentSession()
    
    # 2. Chat Loop
    while True:
        try:
            user_text = input(f"\n👤 You: ")
            if user_text.lower() in ["exit", "quit"]:
                print("👋 Goodbye!")
                break
            
            response = session.run(user_text, USER_EMAIL)
            print(f"🤖 Agent: {response}")
            
        except KeyboardInterrupt:
            print("\n👋 Goodbye!")
            break

if __name__ == "__main__":
    main()
