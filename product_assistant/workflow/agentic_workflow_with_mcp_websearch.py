from typing import Annotated, Sequence, TypedDict, Literal
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

from product_assistant.prompt_library.prompts import PROMPT_REGISTRY, PromptType
from product_assistant.retriever.retrieval import Retriever
from product_assistant.utils.model_loader import ModelLoader
from langgraph.checkpoint.memory import MemorySaver
import asyncio
import signal
from product_assistant.evaluation.ragas_eval import evaluate_context_precision, evaluate_response_relevancy
from langchain_mcp_adapters.client import MultiServerMCPClient


class AgenticRAG:
    """Agentic RAG pipeline using LangGraph + MCP (Retriever + WebSearch)."""

    class AgentState(TypedDict):
        messages: Annotated[Sequence[BaseMessage], add_messages]
        retry_count: int

    def __init__(self):
        self.retriever_obj = Retriever()
        self.model_loader = ModelLoader()
        self.llm = self.model_loader.load_llm()
        self.checkpointer = MemorySaver()

        # MCP Client Init with fallback
        self.mcp_tools = []
        self.mcp_enabled = False
        
        try:
            import os
            current_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            server_path = os.path.join(current_dir, "product_assistant", "mcp_servers", "product_search_server.py")
            
            if os.path.exists(server_path):
                self.mcp_client = MultiServerMCPClient({
                    "hybrid_search": {
                        "command": "python",
                        "args": [server_path],  # server with retriever+websearch
                        "transport": "stdio"
                    }
                })
                # Load MCP tools with timeout
                def timeout_handler(signum, frame):
                    raise TimeoutError("MCP initialization timeout")
                
                signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(10)  # 10 second timeout
                
                try:
                    self.mcp_tools = asyncio.run(self.mcp_client.get_tools())
                    self.mcp_enabled = True
                    print("MCP tools loaded successfully")
                except Exception as e:
                    print(f"Warning: MCP tools failed to load: {e}")
                finally:
                    signal.alarm(0)  # Cancel the alarm
            else:
                print(f"MCP server not found at {server_path}")
                
        except Exception as e:
            print(f"Warning: MCP initialization failed: {e}")

        self.workflow = self._build_workflow()
        self.app = self.workflow.compile(checkpointer=self.checkpointer)

    # ---------- Helpers ----------
    def _format_docs(self, docs) -> str:
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
    def _ai_assistant(self, state: AgentState):
        print("--- CALL ASSISTANT ---")
        messages = state["messages"]
        last_message = messages[-1].content

        if any(word in last_message.lower() for word in ["price", "review", "product"]):
            return {"messages": [HumanMessage(content="TOOL: retriever")]}
        else:
            prompt = ChatPromptTemplate.from_template(
                "You are a helpful assistant. Answer the user directly.\n\nQuestion: {question}\nAnswer:"
            )
            chain = prompt | self.llm | StrOutputParser()
            response = chain.invoke({"question": last_message})
            return {"messages": [HumanMessage(content=response)]}



    def _vector_retriever(self, state: AgentState):
        print("--- RETRIEVER (MCP/Fallback) ---")
        query = state["messages"][0].content  # Use original query instead of last message
        
        # Check if MCP tools are available and enabled
        if self.mcp_enabled and self.mcp_tools:
            try:
                # Find the tool by name
                tool = next((t for t in self.mcp_tools if t.name == "get_product_info"), None)
                if tool:
                    # Call the tool (sync wrapper)
                    result = asyncio.run(tool.ainvoke({"query": query}))
                    context = result if result else "No MCP data found"
                    print(f"MCP result: {context[:100]}...")
                    return {"messages": [HumanMessage(content=context)]}
            except Exception as e:
                print(f"MCP tool error: {e}, falling back to regular retrieval")
        
        # Fallback to regular retrieval
        print("Using regular vector retrieval")
        docs = self.retriever_obj.call_retriever(query)
        context = self._format_docs(docs) if hasattr(self, '_format_docs') else str(docs)
        print(f"Retrieved {len(docs) if docs else 0} documents")
        return {"messages": [HumanMessage(content=context)]}

    def _web_search(self, state: AgentState):
        print("--- WEB SEARCH (MCP/Fallback) ---")
        query = state["messages"][0].content  # Use original query instead of last message
        
        # Check if MCP tools are available and enabled
        if self.mcp_enabled and self.mcp_tools:
            try:
                # Find the tool by name
                tool = next((t for t in self.mcp_tools if t.name == "web_search"), None)
                if tool:
                    # Call the tool (sync wrapper)
                    result = asyncio.run(tool.ainvoke({"query": query}))
                    context = result if result else "No web search data found"
                    print(f"Web search result: {context[:100]}...")
                    return {"messages": [HumanMessage(content=context)]}
            except Exception as e:
                print(f"MCP web search error: {e}, using fallback message")
        
        # Fallback message
        print("MCP web search not available")
        context = f"I couldn't perform a web search for '{query}' at the moment. Please try again later or check online manually."
        return {"messages": [HumanMessage(content=context)]}

    def _grade_documents(self, state: AgentState) -> Literal["generator", "rewriter"]:
        print("--- GRADER ---")
        question = state["messages"][0].content
        docs = state["messages"][-1].content
        retry_count = state.get("retry_count", 0)

        # If this is from web search (contains search results), always accept it
        if ("search" in docs.lower() or "iphone" in docs.lower() or 
            "price" in docs.lower() or len(docs.strip()) > 50):
            print("Documents contain useful information, proceeding to generation")
            return "generator"
            
        # If we've already tried rewriting, accept whatever we have
        if retry_count >= 1:
            print("Already tried rewriting, proceeding to generation")
            return "generator"

        # More lenient grading - if we have any substantial content, proceed to generation
        if docs and docs.strip() and "No" not in docs and len(docs.strip()) > 10:
            print("Documents seem relevant, proceeding to generation")
            return "generator"
        
        # Only rewrite if we have truly empty or minimal content and haven't tried before
        print("Documents not sufficient, rewriting query")
        return "rewriter"

    def _generate(self, state: AgentState):
        print("--- GENERATE ---")
        question = state["messages"][0].content
        docs = state["messages"][-1].content
        prompt = ChatPromptTemplate.from_template(
            PROMPT_REGISTRY[PromptType.PRODUCT_BOT].template
        )
        chain = prompt | self.llm | StrOutputParser()
        response = chain.invoke({"context": docs, "question": question})
        return {"messages": [HumanMessage(content=response)]}

    def _rewrite(self, state: AgentState):
        print("--- REWRITE ---")
        retry_count = state.get("retry_count", 0)
        
        # Prevent infinite loops - max 2 rewrites
        if retry_count >= 2:
            print("Max rewrites reached, using original query")
            return {"messages": [HumanMessage(content=state["messages"][0].content)]}
        
        question = state["messages"][0].content
        prompt = ChatPromptTemplate.from_template(
            "Rewrite this user query to make it more clear and specific for a search engine. "
            "Do NOT answer the query. Only rewrite it.\n\nQuery: {question}\nRewritten Query:"
        )
        chain = prompt | self.llm | StrOutputParser()
        new_q = chain.invoke({"question": question})
        return {"messages": [HumanMessage(content=new_q.strip())], "retry_count": retry_count + 1}


    # ---------- Build Workflow ----------
    def _build_workflow(self):
        workflow = StateGraph(self.AgentState)
        workflow.add_node("Assistant", self._ai_assistant)
        workflow.add_node("Retriever", self._vector_retriever)
        workflow.add_node("Generator", self._generate)
        workflow.add_node("Rewriter", self._rewrite)
        workflow.add_node("WebSearch", self._web_search)

        workflow.add_edge(START, "Assistant")
        workflow.add_conditional_edges(
            "Assistant",
            lambda state: "Retriever" if "TOOL" in state["messages"][-1].content else END,
            {"Retriever": "Retriever", END: END},
        )
        workflow.add_conditional_edges(
            "Retriever",
            self._grade_documents,
            {"generator": "Generator", "rewriter": "Rewriter"},
        )
        workflow.add_edge("Generator", END)

        # Fixed path: Rewriter → WebSearch → Generator → END
        workflow.add_edge("Rewriter", "WebSearch")
        workflow.add_edge("WebSearch", "Generator")  # Always generate after web search
        
        return workflow

    # ---------- Public Run ----------
    def run(self, query: str, thread_id: str = "default_thread") -> str:
        """Run the workflow for a given query and return the final answer."""
        result = self.app.invoke(
            {"messages": [HumanMessage(content=query)], "retry_count": 0},
            config={"configurable": {"thread_id": thread_id}}
        )
        return result["messages"][-1].content


if __name__ == "__main__":
    rag_agent = AgenticRAG()
    answer = rag_agent.run("What is the price of iPhone 15?")
    print("\nFinal Answer:\n", answer)
