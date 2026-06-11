"""SENA NDIS Assistant — entry point.

Run with: python index.py

Handles authentication (login or paste-JWT) and runs the interactive REPL.
All real work is delegated to router.process_query.

Module layout:
    config.py         — env vars, AWS clients, guardrails, constants
    state.py          — shared mutable state (user_context, conversation_history,
                        STAFF_APIS / CLIENT_APIS / COMMON_APIS / AVAILABLE_APIS)
    auth.py           — login, JWT decode, jwt_token, get_auth_headers
    guardrails.py     — Bedrock Guardrails helpers + persistence scrubbing
    bedrock_client.py — call_bedrock + streaming variant
    memory.py         — AgentCore + DDB audit + in-memory history + memory-first gate
    api_router.py     — intent detection, API selection, URL construction, access check
    handlers.py       — META / CHAT / API mode handlers
    router.py         — process_query (top-level orchestrator)
    index.py          — this file (auth + REPL)
"""
from state import user_context, STAFF_APIS, CLIENT_APIS, COMMON_APIS
from auth import login_user, authenticate_user, authenticate_with_jwt
from memory import _handle_memory_command
from router import process_query


def main():
    print("\n" + "="*70)
    print("SENA Assistant (Bedrock Model API)")
    print("="*70)
    print(
        f"Loaded {len(STAFF_APIS)} staff + {len(CLIENT_APIS)} client + "
        f"{len(COMMON_APIS)} common APIs\n"
    )

    auth_choice = input("Choose auth method (1=Login, 2=JWT Token): ").strip()

    if auth_choice == "2":
        jwt_token_input = input("Paste JWT token: ").strip()
        if not authenticate_with_jwt(jwt_token_input):
            print("JWT authentication failed. Exiting.")
            exit(1)
    else:
        email = input("Email: ").strip()
        password = input("Password: ").strip()

        if not login_user(email, password):
            print("Login failed. Exiting.")
            exit(1)

        if not authenticate_user():
            print("User info fetch failed. Exiting.")
            exit(1)

    print("\nAuthentication successful!")
    print(f"Welcome {user_context['email']}!")
    print("You can ask normal questions or work-related queries")
    print("Type 'quit' to exit\n")

    while True:
        try:
            user_input = input("\nYou: ").strip()

            if user_input.lower() in ['quit', 'exit', 'q']:
                print("Goodbye!")
                break

            if not user_input:
                print("Please enter a question")
                continue

            if user_input.lower().startswith("/memory"):
                _handle_memory_command(user_input)
                continue

            result = process_query(user_input)
            # process_normal_chat / process_api_call already stream output live and print
            # their fallbacks. Only echo the non-streamed early-return errors here.
            if isinstance(result, str) and result.startswith((
                "You don't appear",     # access check failed
                "I couldn't find",      # no suitable data route
                "I couldn't work",      # incomplete route
            )):
                print(f"\nSena: {result}")

        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")
            continue


if __name__ == "__main__":
    main()
