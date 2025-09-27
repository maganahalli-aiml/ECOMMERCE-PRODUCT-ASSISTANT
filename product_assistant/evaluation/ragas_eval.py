import asyncio
from product_assistant.utils.model_loader import ModelLoader
import grpc.experimental.aio as grpc_aio
grpc_aio.init_grpc_aio()

model_loader = ModelLoader()

def evaluate_context_precision(query, response, retrieved_context):
    """
    Simplified context precision evaluation
    Returns a mock score for now to avoid ragas import issues
    """
    try:
        # For now, return a simple relevance score based on context length
        if retrieved_context and len(retrieved_context) > 0:
            return 0.8  # Mock high precision score
        else:
            return 0.2  # Mock low precision score
    except Exception as e:
        print(f"Context precision evaluation error: {e}")
        return 0.5  # Default score

def evaluate_response_relevancy(query, response, retrieved_context):
    """
    Simplified response relevancy evaluation
    Returns a mock score for now to avoid ragas import issues
    """
    try:
        # For now, return a simple relevance score based on response length
        if response and len(response) > 20:
            return 0.85  # Mock high relevancy score
        else:
            return 0.3   # Mock low relevancy score
    except Exception as e:
        print(f"Response relevancy evaluation error: {e}")
        return 0.5  # Default score