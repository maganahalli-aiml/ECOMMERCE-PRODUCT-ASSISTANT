import os
from typing import Annotated, Sequence, TypedDict, Literal
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from tavily import TavilyClient
from product_assistant.prompt_library.prompts import PROMPT_REGISTRY, PromptType
from product_assistant.retriever.retrieval import Retriever
from product_assistant.utils.model_loader import ModelLoader
from langgraph.checkpoint.memory import MemorySaver



class AgenticRAG:
    """Agentic RAG pipeline using LangGraph."""

    class AgentState(TypedDict):
        messages: Annotated[Sequence[BaseMessage], add_messages]

    def __init__(self):
        self.retriever_obj = Retriever()
        self.model_loader = ModelLoader()
        self.llm = self.model_loader.load_llm()
        self.checkpointer = MemorySaver()
        self.workflow = self._build_workflow()
        self.app = self.workflow.compile(checkpointer=self.checkpointer)

    # ---------- Helpers ----------
    def _format_docs(self, docs) -> str:
        import logging
        if not docs:
            logging.info("No documents found for query.")
            return "No relevant documents found."
        formatted_chunks = []
        for d in docs:
            meta = d.metadata or {}
            logging.info(f"Full document metadata: {meta}")
            if 'price' in meta:
                logging.info(f"Price field found: {meta['price']}")
            else:
                logging.warning("Price field missing in metadata!")
            formatted = (
                f"Title: {meta.get('product_title', 'N/A')}\n"
                f"Price: {meta.get('price', 'N/A')}\n"
                f"Rating: {meta.get('rating', 'N/A')}\n"
                f"Reviews:\n{d.page_content.strip()}"
            )
            formatted_chunks.append(formatted)
        return "\n\n---\n\n".join(formatted_chunks)
    def web_search(self, query):
        import logging
        TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
        if not TAVILY_API_KEY:
            logging.error("TAVILY_API_KEY environment variable not set.")
            return "Web search failed: API key not set."
        client = TavilyClient(api_key=TAVILY_API_KEY)
        # Refine query for price extraction
        refined_query = f"{query} price in India"
        try:
            response = client.search(refined_query, max_results=10)
            logging.info(f"Raw Tavily web search response: {response}")
        except Exception as e:
            logging.error(f"Tavily API call failed: {e}")
            return f"Web search failed: {e}"
        results = response.get('results', []) if isinstance(response, dict) else []
        if results:
            best_result = None
            for result in results:
                if isinstance(result, dict):
                    content = result.get("content", "")
                    title = result.get("title", "Web Result")
                    url = result.get("url", "")
                    import re
                    price_patterns = [
                        r"\₹[\d,]+",           # ₹64,900
                        r"Rs\.?\s*[\d,]+",   # Rs. 64,900 or Rs 64,900
                        r"INR\s*[\d,]+",      # INR 64,900
                        r"\$[\d,]+"           # $799
                    ]
                    price = None
                    for pat in price_patterns:
                        match = re.search(pat, content)
                        if match:
                            price = match.group(0)
                            break
                    if price:
                        formatted = f"Title: {title}\nPrice: {price}\nDetails: {content}\nSource: {url}"
                        logging.info(f"Formatted web search result: {formatted}")
                        return formatted
                    # If no price, keep the first result for fallback
                    if not best_result:
                        best_result = f"Title: {title}\nDetails: {content}\nSource: {url}"
                else:
                    logging.warning(f"Unexpected result type: {type(result)} - {result}")
                    continue
            # If no price found in any result, return best available info
            if best_result:
                logging.info(f"No price found, returning best available web result: {best_result}")
                return best_result
            else:
                logging.warning("Web search returned results, but none were usable.")
                return ""
        else:
            logging.warning("Web search returned no results.")
            return ""

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
        import logging
        logging.info("Invoking vector DB lookup for query.")
        print("--- RETRIEVER ---")
        # Get the original user query (first message), not the "TOOL: retriever" message
        query = state["messages"][0].content
        retriever = self.retriever_obj.load_retriever()
        docs = retriever.invoke(query)
        # Log all retrieved docs and their metadata
        logging.info(f"All retrieved docs for query '{query}':")
        for d in docs:
            meta = getattr(d, 'metadata', {})
            logging.info(f"Doc metadata: {meta}")
        # Remove strict relevance filtering: treat all returned docs as relevant
        if docs:
            logging.info(f"Vector DB returned {len(docs)} doc(s) for query '{query}'. Using all for response.")
            context = self._format_docs(docs)
            indicator = "[Source: Database]"
            # If context contains apology/fallback phrases, trigger web search
            apology_phrases = [
                "i am sorry",
                "cannot provide",
                "not included",
                "no relevant documents",
                "not found"
            ]
            context_lower = context.lower()
            if any(phrase in context_lower for phrase in apology_phrases):
                logging.info("DB response contains apology/fallback phrase. Triggering web search.")
                return {"messages": [HumanMessage(content="TOOL: websearch"), HumanMessage(content=query)]}
            return {"messages": [HumanMessage(content=f"{indicator}\n{context}")]}
        else:
            logging.info(f"Vector DB returned no results for query '{query}'. Fallback to web search.")
            return {"messages": [HumanMessage(content="TOOL: websearch"), HumanMessage(content=query)]}

    def _grade_documents(self, state: AgentState) -> Literal["generator", "rewriter"]:
        print("--- GRADER ---")
        question = state["messages"][0].content
        docs = state["messages"][-1].content

        prompt = PromptTemplate(
            template="""You are a grader. Question: {question}\nDocs: {docs}\n
            Are docs relevant to the question? Answer yes or no.""",
            input_variables=["question", "docs"],
        )
        chain = prompt | self.llm | StrOutputParser()
        score = chain.invoke({"question": question, "docs": docs})
        return "generator" if "yes" in score.lower() else "rewriter"

    def _generate(self, state: AgentState):
        import logging
        print("--- GENERATE ---")
        question = state["messages"][0].content
        docs = state["messages"][-1].content
        logging.info(f"Context passed to LLM:\n{docs}")
        # Detect source indicator in context
        indicator = ""
        if docs.startswith("[Source: Database]"):
            indicator = "[Source: Database]"
            docs = docs[len(indicator):].lstrip()
        elif docs.startswith("[Source: Web Search]"):
            indicator = "[Source: Web Search]"
            docs = docs[len(indicator):].lstrip()
        prompt = ChatPromptTemplate.from_template(
            PROMPT_REGISTRY[PromptType.PRODUCT_BOT].template
        )
        chain = prompt | self.llm | StrOutputParser()
        response = chain.invoke({"context": docs, "question": question})
        # Prepend indicator to final output
        final_response = f"{indicator}\n{response}" if indicator else response
        # Check for apology/fallback phrases in LLM output
        apology_phrases = [
            "i am sorry",
            "cannot provide",
            "not included",
            "no relevant documents",
            "not found"
        ]
        response_lower = final_response.lower()
        if any(phrase in response_lower for phrase in apology_phrases):
            import logging
            logging.info("LLM response contains apology/fallback phrase. Triggering web search.")
            # Pass the original question to web search
            return {"messages": [HumanMessage(content="TOOL: websearch"), HumanMessage(content=question)]}
        return {"messages": [HumanMessage(content=final_response)]}

    def _rewrite(self, state: AgentState):
        print("--- REWRITE ---")
        question = state["messages"][0].content
        new_q = self.llm.invoke(
            [HumanMessage(content=f"Rewrite the query to be clearer: {question}")]
        )
        return {"messages": [HumanMessage(content=new_q.content)]}
    
    def _web_search_node(self, state: 'AgenticRAG.AgentState'):
        import re
        print("--- WEB SEARCH ---")
        # Get the original user query (first message), not the "TOOL: websearch" message
        query = state["messages"][0].content
        context = self.web_search(query)
        indicator = "[Source: Web Search]"
        # Normalize query and context for comparison
        def normalize(text):
            return re.sub(r'[^a-zA-Z0-9]', '', text).lower().strip()
        query_norm = normalize(query)
        context_norm = normalize(context)
        invalid_context = (
            not context or
            context_norm == query_norm or
            "web search failed" in context.lower() or
            "no web results found" in context.lower() or
            "web search returned results, but none were usable" in context.lower()
        )
        if invalid_context:
            context = f"No price information found online for {query.strip()}."
        return {"messages": [HumanMessage(content=f"{indicator}\n{context}")]}

    # ---------- Build Workflow ----------
    def _build_workflow(self):
        workflow = StateGraph(self.AgentState)
        workflow.add_node("Assistant", self._ai_assistant)
        workflow.add_node("Retriever", self._vector_retriever)
        workflow.add_node("WebSearch", self._web_search_node)
        workflow.add_node("Generator", self._generate)
        workflow.add_node("Rewriter", self._rewrite)

        workflow.add_edge(START, "Assistant")
        workflow.add_conditional_edges(
            "Assistant",
            lambda state: "Retriever" if "TOOL" in state["messages"][-1].content else END,
            {"Retriever": "Retriever", END: END},
        )
        workflow.add_conditional_edges(
            "Retriever",
            lambda state: "WebSearch" if "TOOL: websearch" in [msg.content for msg in state["messages"]] else "generator",
            {"WebSearch": "WebSearch", "generator": "Generator", "rewriter": "Rewriter"},
        )
        workflow.add_edge("WebSearch", END)
        workflow.add_edge("Generator", END)
        workflow.add_edge("Rewriter", "Assistant")
        return workflow

    # ---------- Public Run ----------
    def run(self, query: str, thread_id: str ="default_thread") -> str:
        """Run the workflow for a given query and return the final answer."""
        import re
        result = self.app.invoke({"messages": [HumanMessage(content=query)]},
                                 config= {"configurable":{"thread_id":thread_id}})
        answer = result["messages"][-1].content
        # Normalize query and answer for comparison
        def normalize(text):
            return re.sub(r'[^a-zA-Z0-9]', '', text).lower().strip()
        query_norm = normalize(query)
        answer_norm = normalize(answer)
        if answer_norm == query_norm:
            return f"No price information found online for {query.strip()}."
        return answer


if __name__ == "__main__":
    rag_agent = AgenticRAG()
    answer = rag_agent.run("What is the price of iPhone 15?", thread_id="test_thread")
    print("\nFinal Answer:\n", answer)
