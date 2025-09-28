#!/usr/bin/env python3
"""
Simple test script to verify the workflow is working without infinite loops
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from product_assistant.workflow.agentic_workflow_with_mcp_websearch import AgenticRAG

def test_workflow():
    try:
        print("Initializing AgenticRAG...")
        rag_agent = AgenticRAG()
        
        print("Testing with iPhone 15 price query...")
        
        # Set a timeout to prevent infinite loops
        import signal
        
        def timeout_handler(signum, frame):
            raise TimeoutError("Workflow timeout - likely infinite loop")
        
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(60)  # 60 second timeout
        
        try:
            answer = rag_agent.run("What is the price of iPhone 15?")
            signal.alarm(0)  # Cancel timeout
            
            print("\n" + "="*50)
            print("SUCCESS! Final Answer:")
            print("="*50)
            print(answer)
            print("="*50)
            
        except TimeoutError:
            print("ERROR: Workflow timed out - likely stuck in infinite loop")
            return False
        finally:
            signal.alarm(0)
            
    except Exception as e:
        print(f"ERROR: {e}")
        return False
    
    return True

if __name__ == "__main__":
    success = test_workflow()
    if success:
        print("\n✅ Workflow completed successfully!")
    else:
        print("\n❌ Workflow failed or timed out")