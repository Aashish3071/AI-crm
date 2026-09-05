"""
Verification test for Pipecat Agent + LM Studio Qwen3-4b integration
"""

import asyncio
from pipecat_agent import agent, SCENARIOS

async def run_test():
    print("================================================================")
    print("Testing Pipecat Agent + LM Studio (Qwen3-4b)")
    print(f"Model: {agent.model} | URL: {agent.base_url}")
    print("================================================================")
    
    test_messages = [
        {"role": "assistant", "content": SCENARIOS["motor_renewal"]["initial_greeting"]},
        {"role": "user", "content": "Why did my renewal premium increase compared to last year?"}
    ]
    
    print("\n[User Spoke]: 'Why did my renewal premium increase compared to last year?'")
    print("\n[Streaming from LM Studio via Pipecat] -> ", end="", flush=True)
    
    async for chunk in agent.stream_response(test_messages):
        if chunk["type"] == "token":
            print(chunk["content"], end="", flush=True)
        elif chunk["type"] == "done":
            print("\n")
            print("----------------------------------------------------------------")
            print(f"Time to First Token (TTFT): {chunk['ttft_ms']} ms")
            print(f"Total Tokens Generated:     {chunk['total_tokens']}")
            print(f"Generation Speed:           {chunk['tokens_per_sec']} tokens/sec")
            print(f"Total Response Duration:    {chunk['total_time_s']} s")
            print("----------------------------------------------------------------")
            print("✅ PIPECAT + LM STUDIO PIPELINE VERIFIED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(run_test())
