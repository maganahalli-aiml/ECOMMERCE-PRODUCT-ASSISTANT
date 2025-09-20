from typing import Annotated, Sequence, TypedDict, Literal
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.runnables import RunnablePassthrough

from product_assistant.prompt_library.prompts import PROMPT_REGISTRY, PromptType
from product_assistant.retriever.retrieval import Retriever
from product_assistant.utils.model_loader import ModelLoader
from product_assistant.evaluation.ragas_eval import evaluate_context_precision, evaluate_response_relevancy

retriever_obj = Retriever()
model_loader = ModelLoader()
llm = model_loader.load_llm()


# ---------- State Definition ----------
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]


# ---------- Helper for formatting ----------
def format_docs(docs) -> str:
    if not docs:
        return "No relevant documents found."
    formatted_chunks = []
    for d in docs:
        meta = d.metadata or {}
        formatted = (
            f"Title: {meta.get('product_title', 'N/A')}\n"
            f"Price: {meta.get('price', 'N/A')}\n"
            f"Rating: {meta.get('rating', 'N/A')}\n"
            f"Reviews:\n{d.page_content.strip()}"
        )
        formatted_chunks.append(formatted)
    return "\n\n---\n\n".join(formatted_chunks)


# ---------- Nodes ----------
def ai_assistant(state: AgentState):
    """Decide whether to call retriever or just answer directly."""
    print("--- CALL ASSISTANT ---")
    messages = state["messages"]
    last_message = messages[-1].content

    # Simple routing: if query mentions product → go retriever
    if any(word in last_message.lower() for word in ["price", "review", "product"]):
        return {"messages": [HumanMessage(content="TOOL: retriever")]}
    else:
        # direct answer without retriever
        prompt = ChatPromptTemplate.from_template(
            "You are a helpful assistant. Answer the user directly.\n\nQuestion: {question}\nAnswer:"
        )
        chain = prompt | llm | StrOutputParser()
        response = chain.invoke({"question": last_message})
        return {"messages": [HumanMessage(content=response)]}


def vector_retriever(state: AgentState):
    """Fetch product info from vector DB."""
    print("--- RETRIEVER ---")
    query = state["messages"][-1].content
    retriever = retriever_obj.load_retriever()
    docs = retriever.invoke(query)
    context = format_docs(docs)
    return {"messages": [HumanMessage(content=context)]}


def grade_documents(state: AgentState) -> Literal["generator", "rewriter"]:
    """Grade docs relevance."""
    print("--- GRADER ---")
    question = state["messages"][0].content
    docs = state["messages"][-1].content

    prompt = PromptTemplate(
        template="""You are a grader. Question: {question}\nDocs: {docs}\n
        Are docs relevant to the question? Answer yes or no.""",
        input_variables=["question", "docs"],
    )
    chain = prompt | llm | StrOutputParser()
    score = chain.invoke({"question": question, "docs": docs})
    return "generator" if "yes" in score.lower() else "rewriter"


def generate(state: AgentState):
    """Generate final answer with docs."""
    print("--- GENERATE ---")
    question = state["messages"][0].content
    docs = state["messages"][-1].content
    prompt = ChatPromptTemplate.from_template(
        PROMPT_REGISTRY[PromptType.PRODUCT_BOT].template
    )
    chain = prompt | llm | StrOutputParser()
    response = chain.invoke({"context": docs, "question": question})
    return {"messages": [HumanMessage(content=response)]}


def rewrite(state: AgentState):
    """Rewrite bad query."""
    print("--- REWRITE ---")
    question = state["messages"][0].content
    new_q = llm.invoke(
        [HumanMessage(content=f"Rewrite the query to be clearer: {question}")]
    )
    return {"messages": [HumanMessage(content=new_q.content)]}


# ---------- Build Workflow ----------
workflow = StateGraph(AgentState)
workflow.add_node("Assistant", ai_assistant)
workflow.add_node("Retriever", vector_retriever)
workflow.add_node("Generator", generate)
workflow.add_node("Rewriter", rewrite)

# edges
workflow.add_edge(START, "Assistant")
workflow.add_conditional_edges(
    "Assistant",
    lambda state: "Retriever" if "TOOL" in state["messages"][-1].content else END,
    {"Retriever": "Retriever", END: END},
)
workflow.add_conditional_edges(
    "Retriever",
    grade_documents,
    {"generator": "Generator", "rewriter": "Rewriter"},
)
workflow.add_edge("Generator", END)
workflow.add_edge("Rewriter", "Assistant")

app = workflow.compile()


def build_chain(query):
    """Build the RAG pipeline chain with retriever, prompt, LLM, and parser."""
    retriever = retriever_obj.load_retriever()
    retrieved_docs = retriever.invoke(query)

    # Format all docs together for context evaluation
    retrieved_contexts = [format_docs(retrieved_docs)] if retrieved_docs else ["No relevant documents found."]

    llm = model_loader.load_llm()
    prompt = ChatPromptTemplate.from_template(
        PROMPT_REGISTRY[PromptType.PRODUCT_BOT].template
    )

    chain = (
        {"context": retriever | format_docs, "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )
    return chain, retrieved_contexts



def invoke_chain(query: str, debug: bool = False):
    """Run the chain with a user query."""
    try:
        chain, retrieved_contexts = build_chain(query)

        if debug:
            # For debugging: show docs retrieved before passing to LLM
            docs = retriever_obj.load_retriever().invoke(query)
            print("\nRetrieved Documents:")
            print(format_docs(docs))
            print("\n---\n")

        response = chain.invoke(query)
        return retrieved_contexts, response
    except Exception as e:
        print(f"Error during invoke_chain: {e}")
        return ["Error: could not retrieve contexts."], f"Error: {e}"

# ---------- Run ----------
if __name__ == "__main__":
    # Evaluate with RAGAS
    user_query = "Can you suggest good budget iPhone under 1,00,000 INR?"
    try:
        retrieved_contexts, response = invoke_chain(user_query)
        context_score = evaluate_context_precision(user_query, response, retrieved_contexts)
        relevancy_score = evaluate_response_relevancy(user_query, response, retrieved_contexts)
        print(f"Context Precision Score: {context_score}")
        print(f"Relevancy Score: {relevancy_score}")
    except Exception as e:
        print(f"Error in main block: {e}")